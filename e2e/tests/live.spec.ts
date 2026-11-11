import { expect, test } from '@playwright/test';

// Live signals (#46): a paper added elsewhere (here through the API, as a
// colleague's or the browser extension's) shows in the open list at once,
// without reloading the page.
test('the library list follows changes made elsewhere', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('main')).toBeVisible();
	// Listening (the stream opens with the page).
	await page.waitForTimeout(1000);
	const title = `Added elsewhere ${Date.now()}`;
	const added = await page.request.post('/api/items', { data: { metadata: { title } } });
	expect(added.ok()).toBe(true);
	await expect(page.getByRole('link', { name: title })).toBeVisible({ timeout: 15_000 });
});
