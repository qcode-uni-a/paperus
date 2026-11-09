import { expect, test, type Page } from '@playwright/test';
import { makeLayoutPdf, type Placed } from '../fixtures/pdf.ts';
import { uploadPaper } from './helpers.ts';

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
			await page.mouse.wheel(0, 800);
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
