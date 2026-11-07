import { expect, test } from '@playwright/test';
import { unique } from './helpers.ts';

test('Back from a paper returns to the same place in the library', async ({ page }) => {
	// More papers than one page of the list (50).
	const word = unique('Place');
	for (let n = 1; n <= 120; n++) {
		const added = await page.request.post('/api/items', {
			data: { metadata: { title: `${word} paper ${n}` } }
		});
		expect(added.status()).toBe(201);
	}
	await page.goto('/');
	// Newest first: paper 30 is on the second page, loaded while scrolling.
	const row = page.getByRole('link', { name: `${word} paper 30`, exact: true });
	for (let tries = 0; tries < 20 && !(await row.isVisible()); tries++) {
		await page.mouse.wheel(0, 2000);
		await page.waitForTimeout(200);
	}
	await row.scrollIntoViewIfNeeded();
	const top = async () => (await row.boundingBox())?.y ?? -1;
	const before = await top();
	expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(1000);

	await row.click();
	await expect(page).toHaveURL(/\/items\//);
	// Papers added meanwhile (at the top) do not move the place.
	for (const n of [121, 122, 123]) {
		const added = await page.request.post('/api/items', {
			data: { metadata: { title: `${word} paper ${n}` } }
		});
		expect(added.status()).toBe(201);
	}
	await page.goBack();
	await expect(row).toBeInViewport();
	expect(Math.abs((await top()) - before)).toBeLessThan(40);

	// The library opened anew (not Back) starts at the top.
	await page.getByRole('link', { name: `${word} paper 30`, exact: true }).click();
	await page.goto('/');
	await expect(page.getByRole('link', { name: `${word} paper 123`, exact: true })).toBeVisible();
	expect(await page.evaluate(() => window.scrollY)).toBe(0);
});
