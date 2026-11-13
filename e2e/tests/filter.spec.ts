import { expect, test, type Page } from '@playwright/test';
import { unique } from './helpers.ts';

async function add(
	page: Page,
	title: string,
	authors: { family: string; given: string }[],
	tags: string[]
): Promise<void> {
	const added = await page.request.post('/api/items', {
		data: { metadata: { title, author: authors } }
	});
	expect(added.status()).toBe(201);
	const { id } = await added.json();
	for (const name of tags) {
		expect((await page.request.post(`/api/items/${id}/tags`, { data: { name } })).status()).toBe(
			201
		);
	}
}

test('filter the library by tags and authors', async ({ page }) => {
	const word = unique('Filtered');
	const radar = unique('radar');
	const read = unique('read');
	const family = unique('Benito');
	await add(page, `${word} one`, [{ family, given: 'Mónica' }], [radar, read]);
	await add(page, `${word} two`, [{ family: 'Platero', given: 'Gloria' }], [radar]);
	await add(page, `${word} three`, [{ family, given: 'M.' }], []);
	const rows = page.getByRole('listitem').filter({ hasText: word });

	// A tag in the list filters by it.
	await page.goto('/');
	await rows
		.filter({ hasText: `${word} two` })
		.getByRole('link', { name: radar })
		.click();
	await expect(page.getByText(`Papers tagged ${radar}.`)).toBeVisible();
	await expect(page.getByRole('heading', { name: '2 items' })).toBeVisible();
	await expect(rows).toHaveCount(2);

	// More rules in the filter's panel: not the ones already read.
	await page.getByRole('button', { name: 'Filter', exact: true }).click();
	await page.getByRole('combobox', { name: 'How the next tag counts' }).selectOption('has not');
	await page
		.getByRole('combobox', { name: 'Add a tag', exact: true })
		.selectOption({ label: read });
	await expect(page.getByText(`Papers tagged ${radar}, not tagged ${read}.`)).toBeVisible();
	await expect(rows).toHaveCount(1);
	await expect(rows.first()).toContainText(`${word} two`);

	// Kept as a smart collection: the dialog starts with these rules.
	await page.getByRole('button', { name: 'Save as smart collection' }).click();
	const dialog = page.getByRole('dialog', { name: 'New collection' });
	await expect(dialog.getByRole('radio', { name: /^Smart/ })).toBeChecked();
	await expect(dialog.getByRole('button', { name: `Remove ${read}` })).toBeVisible();
	await dialog.getByRole('button', { name: 'Cancel' }).click();

	await page.getByRole('button', { name: 'Clear filter' }).click();
	await expect(page.getByText(/^Papers tagged/)).toBeHidden();
	expect(new URL(page.url()).search).toBe('');

	// By an author's name (where authors lead until they are linked to
	// people, see authors.spec.ts): the family name and the first letter.
	await page.goto(`/?${new URLSearchParams({ author: `${family}, Mónica` })}`);
	await expect(page.getByText(`Papers by ${family}, Mónica.`)).toBeVisible();
	await expect(rows).toHaveCount(2);
	await page.goto(`/?${new URLSearchParams({ author: `${family}, M.` })}`);
	await expect(page.getByText(`Papers by ${family}, M.`)).toBeVisible();
	await expect(rows).toHaveCount(2);
});

test.describe('on a phone', () => {
	test.use({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true });

	test('the filter sits beside the number of papers', async ({ page }) => {
		await add(page, unique('Phone filter '), [], []);
		await page.goto('/');
		const count = page.getByRole('heading', { name: /^\d+ items?$/ });
		const button = page.getByRole('button', { name: 'Filter', exact: true });
		// Both measured together (the page may still be moving: getting started).
		const middles = () =>
			Promise.all([count.boundingBox(), button.boundingBox()]).then(([a, b]) => ({
				apart: Math.abs((a?.y ?? 0) + (a?.height ?? 0) / 2 - ((b?.y ?? 0) + (b?.height ?? 0) / 2)),
				right: (b?.x ?? 0) + (b?.width ?? 0)
			}));
		await expect.poll(async () => (await middles()).apart).toBeLessThan(8);
		expect((await middles()).right).toBeGreaterThan(300);
	});
});

test('the panel stays open, with its rules, when no papers match', async ({ page }) => {
	// A paper to come back (the library may be empty yet: tests run in any order).
	await page.request.post('/api/items', { data: { metadata: { title: unique('Matched ') } } });
	await page.goto(`/?${new URLSearchParams({ journal: 'No such journal' })}`);
	await expect(page.getByText('No papers match the filter.')).toBeVisible();
	await page.getByRole('button', { name: 'Filter', exact: true }).click();
	const journal = page.getByRole('button', { name: 'Remove No such journal' });
	await expect(journal).toBeVisible();
	// Taken away: papers again, the panel as it was.
	await journal.click();
	await expect(page.getByRole('heading', { name: /^\d+ items?$/ })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Add a tag', exact: true })).toBeVisible();
});
