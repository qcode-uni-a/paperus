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

test("a paper's page asks the browser extension for its missing PDF", async ({ page }) => {
	const title = unique('Missing here');
	const doi = `10.5555/${title.toLowerCase().replace(/\W+/g, '-')}`;
	const made = await page.request.post('/api/items', {
		data: { metadata: { title }, identifiers: [{ scheme: 'doi', value: doi }] }
	});
	const item = await made.json();
	await page.addInitScript(() => {
		window.addEventListener('message', (event) => {
			if (event.data?.type === 'paperus:get-pdfs')
				(window as unknown as { asked: unknown }).asked = event.data.papers;
		});
		document.addEventListener('DOMContentLoaded', () => {
			document.documentElement.dataset.paperusExtensionFeatures = 'get-pdfs';
		});
	});
	await page.goto(`/items/${item.id}`);
	const get = page.getByRole('button', { name: 'Get the PDF with the extension' });
	await get.click();
	await expect(page.getByRole('button', { name: 'Getting the PDF…' })).toBeDisabled();
	await expect
		.poll(() => page.evaluate(() => (window as unknown as { asked?: unknown[] }).asked))
		.toEqual([
			{
				item_id: item.id,
				version_id: item.versions[0].id,
				title,
				url: `https://doi.org/${doi}`,
				copies: []
			}
		]);
	// Done (as the extension says): the page as it is now.
	await page.evaluate(() =>
		window.postMessage(
			{ type: 'paperus:getPdfsDone', total: 1, saved: 0, failed: [] },
			location.origin
		)
	);
	await expect(get).toBeEnabled();
});
