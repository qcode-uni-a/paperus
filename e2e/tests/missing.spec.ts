import { expect, test } from '@playwright/test';
import { unique } from './helpers.ts';

test('papers missing their PDF go to the browser extension', async ({ page }) => {
	const title = unique('Missing its PDF');
	const doi = `10.5555/${title.toLowerCase().replace(/\W+/g, '-')}`;
	const made = await page.request.post('/api/items', {
		data: { metadata: { title }, identifiers: [{ scheme: 'doi', value: doi }] }
	});
	expect(made.ok()).toBeTruthy();

	// The extension stands in: its page script says it is there, and takes
	// what the page posts (a structured clone, as the browser makes it).
	await page.addInitScript(() => {
		window.addEventListener('message', (event) => {
			if (event.data?.type === 'paperus:get-pdfs')
				(window as unknown as { asked: unknown }).asked = event.data.papers;
		});
		document.addEventListener('DOMContentLoaded', () => {
			document.documentElement.dataset.paperusExtensionFeatures = 'get-pdfs';
		});
	});
	await page.goto('/manage/missing');
	const row = page.locator('li', { hasText: title });
	await row.getByRole('button', { name: 'Get with the extension' }).click();
	const asked = await expect
		.poll(() => page.evaluate(() => (window as unknown as { asked?: unknown[] }).asked))
		.toBeTruthy()
		.then(() =>
			page.evaluate(() => (window as unknown as { asked: { title: string; url: string }[] }).asked)
		);
	expect(asked).toHaveLength(1);
	expect(asked[0].title).toBe(title);
	expect(asked[0].url).toContain(doi);
});
