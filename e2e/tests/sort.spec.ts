import { expect, test, type Page } from '@playwright/test';
import { unique } from './helpers.ts';

async function add(page: Page, metadata: Record<string, unknown>): Promise<string> {
	const added = await page.request.post('/api/items', { data: { metadata } });
	expect(added.status()).toBe(201);
	return (await added.json()).id;
}

/** The titles listed with ``word`` in them, top to bottom. */
async function listed(page: Page, word: string): Promise<string[]> {
	return page.getByRole('main').getByRole('link', { name: word }).allInnerTexts();
}

test('the library sorted, by title and by year, either way', async ({ page }) => {
	const family = unique('Sorter');
	const word = unique('sorted');
	const paper = (title: string, year: number, journal: string) =>
		add(page, {
			title: `${title} ${word}`,
			author: [{ family, given: 'Sam' }],
			issued: { 'date-parts': [[year]] },
			'container-title': journal
		});
	const ids = [
		await paper('Beta', 2019, 'Cell'),
		await paper('Alpha', 2024, 'Nature'),
		await paper('Gamma', 2021, 'Annals')
	];

	await page.goto(`/?author=${family}, Sam`);
	// Newest added first.
	await expect
		.poll(() => listed(page, word))
		.toEqual([`Gamma ${word}`, `Alpha ${word}`, `Beta ${word}`]);

	const sort = page.getByRole('group', { name: 'Sort' });
	await sort.getByLabel('Sort by').selectOption('Title');
	await expect(page).toHaveURL(/sort=title&order=asc/);
	await expect
		.poll(() => listed(page, word))
		.toEqual([`Alpha ${word}`, `Beta ${word}`, `Gamma ${word}`]);
	await sort.getByRole('button', { name: 'A to Z; click for z to a' }).click();
	await expect
		.poll(() => listed(page, word))
		.toEqual([`Gamma ${word}`, `Beta ${word}`, `Alpha ${word}`]);

	// Year: newest first, at first.
	await sort.getByLabel('Sort by').selectOption('Year');
	await expect
		.poll(() => listed(page, word))
		.toEqual([`Alpha ${word}`, `Gamma ${word}`, `Beta ${word}`]);
	await sort.getByRole('button', { name: /^Newest first/ }).click();
	await expect
		.poll(() => listed(page, word))
		.toEqual([`Beta ${word}`, `Gamma ${word}`, `Alpha ${word}`]);

	// Kept on reload, and remembered for the next visit.
	await page.reload();
	await expect(sort.getByLabel('Sort by')).toHaveValue('year');
	await page.goto(`/?author=${family}, Sam`);
	await expect
		.poll(() => listed(page, word))
		.toEqual([`Beta ${word}`, `Gamma ${word}`, `Alpha ${word}`]);

	// A collection's papers, sorted the same way.
	const made = await page.request.post('/api/collections', { data: { name: unique('Sorted ') } });
	expect(made.status()).toBe(201);
	const collection = (await made.json()).id;
	expect(
		(
			await page.request.post(`/api/collections/${collection}/items`, {
				data: { item_ids: ids }
			})
		).ok()
	).toBe(true);
	await page.goto(`/collections/${collection}`);
	await sort.getByLabel('Sort by').selectOption('Journal');
	await expect
		.poll(() => listed(page, word))
		.toEqual([`Gamma ${word}`, `Beta ${word}`, `Alpha ${word}`]);
});
