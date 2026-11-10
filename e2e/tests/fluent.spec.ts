import { expect, test, type Page } from '@playwright/test';
import { makeLayoutPdf, type Placed } from '../fixtures/pdf.ts';
import { scrollPhone, uploadPaper } from './helpers.ts';

const LINES = 30;

/** Two pages in two columns: a title across the first, a running header
 * with a rule on the second, page numbers at the bottom. */
function twoColumns(title: string, word: string): Buffer {
	const column = (page: number, side: 'Left' | 'Right', x: number): Placed[] =>
		Array.from({ length: LINES }, (_, i) => ({
			x,
			y: 620 - i * 13,
			text: `${side} ${page}.${i} of the ${word} column text`
		}));
	return makeLayoutPdf(
		[
			{
				lines: [
					{ x: 110, y: 700, size: 16, text: title },
					...column(1, 'Left', 72),
					...column(1, 'Right', 330),
					{ x: 300, y: 40, text: '1' }
				]
			},
			{
				lines: [
					{ x: 72, y: 760, size: 8, text: 'Journal of Fluent Tests 7, 2 (2026)' },
					...column(2, 'Left', 72),
					...column(2, 'Right', 330),
					{ x: 300, y: 40, text: '2' }
				],
				rules: [[72, 540, 752]]
			}
		],
		title
	);
}

/** The words of the fluent view's pieces, in their order. */
async function words(page: Page): Promise<string> {
	return page.evaluate(() =>
		[...document.querySelectorAll('.fluent .textLayer')].map((l) => l.textContent).join(' ')
	);
}

test.describe('fluent mode on a phone', () => {
	test.use({ viewport: { width: 390, height: 800 }, isMobile: true, hasTouch: true });

	test('the columns one after another, without the running header', async ({ page }) => {
		test.setTimeout(90_000);
		const paper = await uploadPaper(page, 'Fluent', [], twoColumns);
		const toggle = page.getByRole('button', { name: 'Fluent mode' });
		await expect(toggle).toHaveAttribute('aria-pressed', 'true', { timeout: 20_000 });

		// Drawn as one scrolls through: in reading order, column after column.
		for (let i = 0; i < 12; i++) {
			await scrollPhone(page, 800);
			await page.waitForTimeout(150);
		}
		await expect.poll(() => words(page), { timeout: 20_000 }).toContain('Right 2.29');
		const text = await words(page);
		const order = [
			'Left 1.0 ',
			'Left 1.29 ',
			'Right 1.0 ',
			'Right 1.29 ',
			'Left 2.0 ',
			'Right 2.29 '
		];
		const at = order.map((part) => text.indexOf(part));
		expect(at.every((i) => i >= 0)).toBe(true);
		expect([...at].sort((a, b) => a - b)).toEqual(at);
		expect(text).not.toContain('Journal of Fluent Tests');

		// A highlight over the column break: one, on both columns.
		await page.evaluate(() => {
			const spans = [...document.querySelectorAll('.fluent .textLayer span')];
			const from = spans.find((s) => s.textContent?.startsWith('Left 1.29'))!;
			const to = spans.find((s) => s.textContent?.startsWith('Right 1.0 '))!;
			from.scrollIntoView({ block: 'center' });
			const range = document.createRange();
			range.setStart(from.firstChild!, 0);
			range.setEnd(to.firstChild!, 9);
			const selection = window.getSelection()!;
			selection.removeAllRanges();
			selection.addRange(range);
		});
		await page.getByRole('button', { name: 'Highlight green' }).click();
		const file = (await (await page.request.get(`/api/items/${paper.id}`)).json()).versions[0]
			.files[0].id;
		await expect
			.poll(
				async () =>
					(await (await page.request.get(`/api/files/${file}/annotations`)).json()).annotations
						.length
			)
			.toBe(1);
		const [mark] = (await (await page.request.get(`/api/files/${file}/annotations`)).json())
			.annotations;
		expect(mark.text).toContain('Left 1.29');
		expect(mark.text).toContain('Right 1.0');
		const starts = mark.position.rects.map((r: number[]) => r[0]);
		expect(starts.some((x: number) => x < 100)).toBe(true);
		expect(starts.some((x: number) => x > 300)).toBe(true);

		// Off: the pages as printed; on again.
		await toggle.click();
		await expect(toggle).toHaveAttribute('aria-pressed', 'false');
		await expect(page.locator('#page-1')).toBeVisible();
		await toggle.click();
		await expect(page.locator('.fluent .piece').first()).toBeAttached();
	});
});

/** What is at the reading line (below the toolbar): in fluent mode the
 * piece ("page-index"), else the page. */
async function atReadingLine(page: Page): Promise<string | null> {
	return page.evaluate(() => {
		const toolbar = document.querySelector<HTMLElement>('.viewer .toolbar');
		const desk = document.querySelector<HTMLElement>('.pages');
		if (!toolbar || !desk) return null; // still opening
		const y = toolbar.getBoundingClientRect().bottom + 20;
		const column = document.querySelector<HTMLElement>('.fluent') ?? desk;
		const node = document.elementFromPoint(column.getBoundingClientRect().left + 120, y);
		const piece = node?.closest('.piece')?.querySelector<HTMLElement>('[data-piece]');
		return piece?.dataset.piece ?? node?.closest<HTMLElement>('.page')?.dataset.page ?? null;
	});
}

test('reading goes on where one stopped, in either view', async ({ page }) => {
	test.setTimeout(90_000);
	const paper = await uploadPaper(page, 'Resumed', [], twoColumns);
	const reading = async () => (await page.request.get(`/api/items/${paper.id}/reading`)).json();
	await expect(page.locator('#page-2')).toBeAttached({ timeout: 20_000 });

	// Normal view: half way down page 2.
	await page.evaluate(() => {
		const sheet = document.getElementById('page-2')!;
		window.scrollTo(0, sheet.getBoundingClientRect().top + window.scrollY + 300);
	});
	await expect.poll(async () => (await reading())?.page, { timeout: 10_000 }).toBe(2);
	expect((await reading()).left).toBeNull();
	await page.reload();
	await expect(page.getByText('Where you left off')).toBeVisible();
	await expect.poll(() => atReadingLine(page), { timeout: 20_000 }).toBe('2');
	// The same place in the fluent view: a piece of page 2.
	await page.evaluate(() => localStorage.setItem('paperus.fluent', 'on'));
	await page.reload();
	await expect.poll(() => atReadingLine(page), { timeout: 20_000 }).toMatch(/^2-/);
	await page.evaluate(() => localStorage.setItem('paperus.fluent', 'off'));

	// Fluent view: a piece of page 1 (the right column), then again.
	await page.evaluate(() => localStorage.setItem('paperus.fluent', 'on'));
	await page.goto(`/items/${paper.id}?page=1`);
	await expect(page.locator('[data-piece^="1-"]').nth(1)).toBeAttached({ timeout: 20_000 });
	await page.evaluate(() => {
		const pieces = document.querySelectorAll('[data-piece^="1-"]');
		const right = pieces[pieces.length - 1].closest('.piece')!;
		window.scrollTo(0, right.getBoundingClientRect().top + window.scrollY - 60);
	});
	await page.mouse.wheel(0, 40);
	await expect.poll(async () => (await reading())?.left, { timeout: 10_000 }).not.toBeNull();
	const there = await atReadingLine(page);
	expect(there).toMatch(/^1-/);
	await page.goto(`/items/${paper.id}`);
	await expect.poll(() => atReadingLine(page), { timeout: 20_000 }).toBe(there);
	// And in the normal view: on page 1.
	await page.evaluate(() => localStorage.setItem('paperus.fluent', 'off'));
	await page.reload();
	await expect.poll(() => atReadingLine(page), { timeout: 20_000 }).toBe('1');
});
