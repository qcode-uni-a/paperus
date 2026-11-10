import { expect, test } from '@playwright/test';
import { uploadPaper } from './helpers.ts';

test('a PDF opened again comes from the browser, not downloaded again', async ({ page }) => {
	await uploadPaper(page, 'Kept');
	await expect(page.locator('#page-1 canvas')).toBeVisible({ timeout: 20_000 });
	// Kept once all of it is here.
	await expect
		.poll(() =>
			page.evaluate(
				() =>
					new Promise<number>((done) => {
						const request = indexedDB.open('paperus-pdfs');
						request.onsuccess = () => {
							const count = request.result.transaction('kept').objectStore('kept').count();
							count.onsuccess = () => done(count.result);
						};
					})
			)
		)
		.toBe(1);

	const downloads: string[] = [];
	page.on('request', (request) => {
		if (request.url().includes('/content')) downloads.push(request.url());
	});
	await page.reload();
	await expect(page.locator('#page-1 canvas')).toBeVisible({ timeout: 20_000 });
	await expect(page.locator('#page-1 .textLayer')).toContainText('Abstract. We study');
	expect(downloads).toEqual([]);
});
