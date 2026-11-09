import { expect, test, type Page } from '@playwright/test';
import { uploadPaper } from './helpers.ts';

/** Select the words of a page's text layer that contain ``text``. */
async function select(page: Page, text: string) {
	await page.evaluate((wanted) => {
		const span = [...document.querySelectorAll('#page-1 .textLayer span')].find((s) =>
			s.textContent?.includes(wanted)
		);
		if (!span?.firstChild) throw new Error(`no "${wanted}" on the page`);
		const range = document.createRange();
		range.selectNodeContents(span);
		const selection = window.getSelection()!;
		selection.removeAllRanges();
		selection.addRange(range);
	}, text);
}

async function count(page: Page, file: string): Promise<number> {
	const listed = await (await page.request.get(`/api/files/${file}/annotations`)).json();
	return listed.annotations.length;
}

test('highlight, comment, draw, erase and gather into a note', async ({ page }) => {
	const paper = await uploadPaper(page, 'Annotated');
	const pdf = page.locator('#page-1');
	await expect(pdf.locator('.textLayer span').first()).toBeVisible({ timeout: 20_000 });
	const file = (await (await page.request.get(`/api/items/${paper.id}`)).json()).versions[0]
		.files[0].id;

	// Selected text: highlighted green from the menu over it.
	await select(page, 'We study the');
	await page.getByRole('button', { name: 'Highlight green' }).click();
	await expect.poll(() => count(page, file)).toBe(1);

	// A click on it opens it; a comment is kept.
	const [highlight] = (await (await page.request.get(`/api/files/${file}/annotations`)).json())
		.annotations;
	const mark = page.locator(`#annotation-${highlight.id}`);
	const box = (await mark.boundingBox())!;
	await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
	const popup = page.getByRole('dialog', { name: 'Highlight' });
	await popup.getByLabel('Comment').fill('The main claim');
	await popup.getByRole('button', { name: 'Close' }).click();
	await expect
		.poll(
			async () =>
				(await (await page.request.get(`/api/files/${file}/annotations`)).json()).annotations[0]
					.comment
		)
		.toBe('The main claim');

	// The pen draws; the eraser takes the stroke away again.
	const tools = page.getByRole('toolbar', { name: 'Annotate' }).first();
	await tools.getByRole('button', { name: 'Pen', exact: true }).click();
	const sheet = (await pdf.boundingBox())!;
	const y = Math.max(sheet.y, 0) + 300;
	await page.mouse.move(sheet.x + 100, y);
	await page.mouse.down();
	for (let i = 1; i <= 10; i++) await page.mouse.move(sheet.x + 100 + i * 15, y + (i % 2) * 10);
	await page.mouse.up();
	await expect.poll(() => count(page, file)).toBe(2);
	await tools.getByRole('button', { name: 'Eraser (pen strokes)' }).click();
	await page.mouse.move(sheet.x + 160, y - 20);
	await page.mouse.down();
	await page.mouse.move(sheet.x + 160, y + 30, { steps: 8 });
	await page.mouse.up();
	await expect.poll(() => count(page, file)).toBe(1);
	await tools.getByRole('button', { name: 'Select text' }).click();

	// Listed; gathered into a note on the paper.
	await page.getByTitle('Annotations', { exact: true }).click();
	const list = page.getByRole('region', { name: 'Annotations' });
	await expect(list).toContainText('The main claim');
	await list.getByRole('button', { name: 'Add note from all' }).click();
	await expect(page).toHaveURL(/\/notes\//);
	await expect(page.getByText(/We study the/)).toBeVisible();
});

test.describe('on a phone', () => {
	test.use({ viewport: { width: 390, height: 800 }, isMobile: true, hasTouch: true });

	test('the tools are behind a round button', async ({ page }) => {
		await uploadPaper(page, 'Phone annotated');
		await expect(page.locator('#page-1 .textLayer span').first()).toBeVisible({ timeout: 20_000 });
		const button = page.getByRole('button', { name: 'Annotate' });
		await expect(button).toBeVisible();
		await button.click();
		await expect(page.getByRole('button', { name: 'Pen', exact: true }).last()).toBeVisible();
		const widths = await page.evaluate(() => ({
			scroll: document.documentElement.scrollWidth,
			client: document.documentElement.clientWidth
		}));
		expect(widths.scroll).toBeLessThanOrEqual(widths.client);
	});
});
