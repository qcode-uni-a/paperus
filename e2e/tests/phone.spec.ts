import { expect, test, type Page } from '@playwright/test';
import { uploadPaper } from './helpers.ts';

/** No sideways scrolling: nothing is wider than the screen. */
async function expectNoHorizontalScroll(page: Page): Promise<void> {
	const widths = await page.evaluate(() => ({
		scroll: document.documentElement.scrollWidth,
		client: document.documentElement.clientWidth
	}));
	expect(widths.scroll, page.url()).toBeLessThanOrEqual(widths.client);
}

/** Pages with a heading, wide tables or long forms. */
const PAGES = [
	'/collections',
	'/settings',
	'/trash',
	'/settings?open=import',
	'/notes',
	'/manage/tags',
	'/manage/authors',
	'/manage/collections',
	'/manage/groups',
	'/manage/missing',
	'/admin/users',
	'/admin/settings',
	'/admin/jobs'
];

test.describe('on a phone', () => {
	test.use({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true });

	test('pages fit the screen', async ({ page }) => {
		const paper = await uploadPaper(page, 'Phone');

		await page.goto('/');
		await expect(page.getByRole('heading', { name: /^\d+ items?$/ })).toBeVisible();
		await expect(page.getByRole('link', { name: paper.title })).toBeVisible();
		await expectNoHorizontalScroll(page);

		// The menu is a drawer behind a button.
		const menu = page.getByRole('navigation', { name: 'Menu' });
		await expect(menu).toBeHidden();
		await page.getByRole('button', { name: 'Open menu' }).click();
		await expect(menu).toBeVisible();
		await expectNoHorizontalScroll(page);
		await menu.getByRole('link', { name: 'Collections' }).first().click();
		await expect(page).toHaveURL(/\/collections$/);
		await expect(menu).toBeHidden();

		await page.goto(`/?q=${paper.word}`);
		await expect(page.getByRole('link', { name: paper.title })).toBeVisible();
		await expectNoHorizontalScroll(page);

		await page.goto(`/items/${paper.id}`);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(paper.title);
		await expectNoHorizontalScroll(page);

		for (const path of PAGES) {
			await page.goto(path);
			await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
			await expectNoHorizontalScroll(page);
		}
	});

	test('a long chapter name keeps the PDF toolbar on one line', async ({ page }) => {
		await uploadPaper(page, 'Chapters', [
			['1 A VERY LONG CHAPTER NAME ABOUT DRIVEN QUANTUM SYSTEMS IN MICROWAVE CAVITIES', 'Text.'],
			['2 ANOTHER CHAPTER WITH A NAME FAR TOO LONG FOR A PHONE SCREEN TO HOLD', 'More text.']
		]);
		const toolbar = page.locator('.toolbar');
		const contents = toolbar.locator('[aria-controls="pdf-contents"]');
		await expect(contents).toBeVisible();
		await contents.click();
		await page
			.getByRole('navigation', { name: 'Contents of the PDF' })
			.getByRole('button', { name: /^1 A VERY LONG CHAPTER/ })
			.click();
		await expect(contents).toContainText('A VERY LONG CHAPTER');
		// One line: the name is cut short ("…"), the page number stays beside it.
		const height = (await toolbar.boundingBox())?.height ?? 0;
		expect(height).toBeLessThan(48);
		await expect(toolbar.getByText(/^\d \/ 4$/)).toBeInViewport();
		// Room made: phones zoom by pinching; the file opens from an icon.
		await expect(toolbar.getByRole('button', { name: 'Zoom in' })).toBeHidden();
		await expect(toolbar.getByRole('link', { name: 'Open the PDF in a new tab' })).toBeVisible();
		await expectNoHorizontalScroll(page);

		// In the contents, long names wrap within the panel.
		await contents.click();
		const panel = page.getByRole('navigation', { name: 'Contents of the PDF' });
		const box = await panel.boundingBox();
		for (const entry of await panel.getByRole('button', { name: /CHAPTER/ }).all()) {
			const inner = await entry.evaluate((node) => node.scrollWidth <= node.clientWidth);
			expect(inner).toBe(true);
			const right = await entry.boundingBox();
			expect((right?.x ?? 0) + (right?.width ?? 0)).toBeLessThanOrEqual(
				(box?.x ?? 0) + (box?.width ?? 0)
			);
		}
		await expectNoHorizontalScroll(page);
		await page.screenshot({ path: process.env.TOOLBAR_SHOT ?? 'test-results/toolbar.png' });
	});
});

test.describe('on a tablet held upright', () => {
	test.use({ viewport: { width: 768, height: 1024 }, isMobile: true, hasTouch: true });

	test('the menu is a drawer and pages fit', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('heading', { name: /^\d+ items?$/ })).toBeVisible();
		// The content has the whole width: the menu opens over it.
		await expect(page.getByRole('navigation', { name: 'Menu' })).toBeHidden();
		await expectNoHorizontalScroll(page);
		for (const path of PAGES) {
			await page.goto(path);
			await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
			await expectNoHorizontalScroll(page);
		}
	});
});
