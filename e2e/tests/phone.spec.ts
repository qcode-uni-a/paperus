import { expect, test, type Page } from '@playwright/test';
import { uploadPaper } from './helpers.ts';

/** No sideways scrolling: nothing is wider than the screen. */
async function expectNoHorizontalScroll(page: Page): Promise<void> {
	const widths = await page.evaluate(() => ({
		scroll: document.documentElement.scrollWidth,
		client: document.documentElement.clientWidth
	}));
	expect(widths.scroll).toBeLessThanOrEqual(widths.client);
}

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

		for (const path of ['/collections', '/settings', '/trash']) {
			await page.goto(path);
			await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
			await expectNoHorizontalScroll(page);
		}
	});
});
