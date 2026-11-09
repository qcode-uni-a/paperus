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

/** Where the file's (only) annotation is on the screen now (the page may
 * have scrolled), shown whole. */
async function where(page: Page, file: string) {
	const [only] = (await (await page.request.get(`/api/files/${file}/annotations`)).json())
		.annotations;
	const mark = page.locator(`#annotation-${only.id}`);
	await mark.scrollIntoViewIfNeeded();
	return (await mark.boundingBox())!;
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
	await tools.getByRole('button', { name: 'Eraser', exact: true }).click();
	await page.mouse.move(sheet.x + 160, y - 20);
	await page.mouse.down();
	await page.mouse.move(sheet.x + 160, y + 30, { steps: 8 });
	await page.mouse.up();
	await expect.poll(() => count(page, file)).toBe(1);

	// Undo: Ctrl+Z brings the stroke back; the button (saying what it takes
	// back) takes it away again; the comment's change comes next.
	await page.keyboard.press('ControlOrMeta+z');
	await expect.poll(() => count(page, file)).toBe(2);
	await tools.getByRole('button', { name: 'Undo adding the pen stroke' }).click();
	await expect.poll(() => count(page, file)).toBe(1);
	await expect(
		tools.getByRole('button', { name: 'Undo the change to the highlight' })
	).toBeEnabled();
	await tools.getByRole('button', { name: 'Select text' }).click();

	// Delete deletes the open annotation; Ctrl+Z brings it back, comment too.
	const here = await where(page, file);
	await page.mouse.click(here.x + here.width / 2, here.y + here.height / 2);
	await expect(popup).toBeVisible();
	await page.keyboard.press('Delete');
	await expect.poll(() => count(page, file)).toBe(0);
	await page.keyboard.press('ControlOrMeta+z');
	await expect.poll(() => count(page, file)).toBe(1);

	// The eraser takes highlights too (and Ctrl+Z brings it back again).
	await tools.getByRole('button', { name: 'Eraser', exact: true }).click();
	const there = await where(page, file);
	await page.mouse.move(there.x + 2, there.y + there.height / 2);
	await page.mouse.down();
	await page.mouse.move(there.x + there.width / 2, there.y + there.height / 2, { steps: 4 });
	await page.mouse.up();
	await expect.poll(() => count(page, file)).toBe(0);
	await page.keyboard.press('ControlOrMeta+z');
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

test('words on the page without words are discarded', async ({ page }) => {
	const paper = await uploadPaper(page, 'Wordless');
	const pdf = page.locator('#page-1');
	await expect(pdf.locator('.textLayer span').first()).toBeVisible({ timeout: 20_000 });
	const file = (await (await page.request.get(`/api/items/${paper.id}`)).json()).versions[0]
		.files[0].id;
	const tools = page.getByRole('toolbar', { name: 'Annotate' }).first();
	const sheet = (await pdf.boundingBox())!;
	const popup = page.getByRole('dialog', { name: 'Text' });

	// Closed without words: gone, and nothing to undo.
	await tools.getByRole('button', { name: 'Text', exact: true }).click();
	await page.mouse.click(sheet.x + 120, Math.max(sheet.y, 0) + 250);
	await expect(popup).toBeVisible();
	await expect.poll(() => count(page, file)).toBe(1);
	await page.keyboard.press('Escape');
	await expect(popup).toBeHidden();
	await expect.poll(() => count(page, file)).toBe(0);
	await expect(tools.getByRole('button', { name: 'Undo' })).toBeDisabled();

	// With words: kept.
	await page.mouse.click(sheet.x + 120, Math.max(sheet.y, 0) + 250);
	await popup.getByLabel('Text').fill('See section 2');
	await popup.getByRole('button', { name: 'Close' }).click();
	await expect.poll(() => count(page, file)).toBe(1);
});

test.describe('on a phone', () => {
	test.use({ viewport: { width: 390, height: 800 }, isMobile: true, hasTouch: true });

	test('the tools are behind a round button', async ({ page }) => {
		await uploadPaper(page, 'Phone annotated');
		await expect(page.locator('#page-1 .textLayer span').first()).toBeVisible({ timeout: 20_000 });
		const button = page.getByRole('button', { name: 'Annotate' });
		await expect(button).toBeVisible();
		// At the screen's bottom right, also once the page is scrolled.
		await page.mouse.wheel(0, 1500);
		await expect
			.poll(async () => {
				const box = (await button.boundingBox())!;
				return box.y > 800 - 120 && box.x > 390 - 120;
			})
			.toBe(true);
		// Zoomed in by pinching too, at its usual size, whichever way one scrolls.
		const cdp = await page.context().newCDPSession(page);
		await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 2 });
		for (const step of [600, -300]) {
			await page.mouse.wheel(0, step);
			await expect
				.poll(() =>
					page.evaluate(() => {
						const seen = window.visualViewport!;
						const box = document.querySelector('.fab')!.getBoundingClientRect();
						return [
							Math.round((box.x - seen.offsetLeft) * seen.scale),
							Math.round((box.y - seen.offsetTop) * seen.scale),
							Math.round(box.width * seen.scale)
						];
					})
				)
				.toEqual([390 - 16 - 56, 800 - 16 - 56, 56]);
		}
		// The page on screen drawn again that much sharper.
		const canvasWidth = () =>
			page.evaluate(() => document.querySelector<HTMLCanvasElement>('#page-1 canvas')!.width);
		const usual = await page.evaluate(
			() => document.querySelector<HTMLElement>('#page-1 canvas')!.offsetWidth * devicePixelRatio
		);
		await page.mouse.wheel(0, -2000);
		await expect.poll(canvasWidth).toBeGreaterThanOrEqual(Math.floor(usual * 2) - 1);
		await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1 });
		await button.click();
		await expect(page.getByRole('button', { name: 'Pen', exact: true }).last()).toBeVisible();
		const widths = await page.evaluate(() => ({
			scroll: document.documentElement.scrollWidth,
			client: document.documentElement.clientWidth
		}));
		expect(widths.scroll).toBeLessThanOrEqual(widths.client);
	});
});
