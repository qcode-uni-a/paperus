import { expect, test, type Page } from '@playwright/test';
import { itemAction, unique, uploadPaper } from './helpers.ts';

/** The library's list (not a search), loaded. */
async function openLibrary(page: Page): Promise<void> {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: /^\d+ items?$/ })).toBeVisible();
}

test('collections: create one, put a paper in, take it out, delete it', async ({ page }) => {
	const paper = await uploadPaper(page, 'Collected');
	const name = unique('Reading list ');

	await page.goto('/collections');
	await page
		.getByRole('button', { name: /^(Create the first collection|New collection)$/ })
		.click();
	const dialog = page.getByRole('dialog', { name: 'New collection' });
	await dialog.getByLabel('Name').fill(name);
	await dialog.getByLabel(/Description/).fill('Made by the end-to-end tests');
	await dialog.getByRole('button', { name: 'Create collection' }).click();
	await expect(page).toHaveURL(/\/collections\/[0-9a-f-]+$/);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
	const collectionUrl = page.url();

	await page.goto(`/items/${paper.id}`);
	await page.getByRole('button', { name: 'Add to a collection' }).click();
	await page.getByRole('combobox', { name: 'Add to collection' }).selectOption({ label: name });
	await expect(page.getByRole('link', { name })).toBeVisible();

	await page.goto(collectionUrl);
	await expect(page.getByText('Made by the end-to-end tests')).toBeVisible();
	await expect(page.getByRole('link', { name: paper.title })).toBeVisible();

	// Out of the collection again, from the paper's page.
	await page.goto(`/items/${paper.id}`);
	await page.getByRole('button', { name: `Remove from ${name}` }).click();
	await expect(page.getByRole('link', { name })).toBeHidden();

	await page.goto(collectionUrl);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
	await expect(page.getByRole('link', { name: paper.title })).toBeHidden();
	page.once('dialog', (confirm) => confirm.accept());
	await page.getByRole('button', { name: 'Collection actions' }).click();
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	await expect(page).toHaveURL(/\/collections$/);
	await expect(page.getByText(name)).toBeHidden();
	// The paper stays in the library.
	await page.goto(`/items/${paper.id}`);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(paper.title);
});

test('trash and restore', async ({ page }) => {
	const paper = await uploadPaper(page, 'Trashed');

	await itemAction(page, 'Move to trash');
	await expect(page).toHaveURL(/\/$/);
	await openLibrary(page);
	await expect(page.getByRole('link', { name: paper.title })).toBeHidden();
	// Not found by search either.
	await page.goto(`/?q=${paper.word}`);
	await expect(page.getByText(`Nothing found for “${paper.word}”.`)).toBeVisible();

	await page.goto('/trash');
	const row = page.getByRole('listitem').filter({ hasText: paper.title });
	await row.getByRole('button', { name: 'Restore' }).click();
	await expect(row).toBeHidden();

	await openLibrary(page);
	await expect(page.getByRole('link', { name: paper.title })).toBeVisible();
	await page.goto(`/?q=${paper.word}`);
	await expect(page.getByRole('link', { name: paper.title })).toBeVisible();
});

test('a trashed paper can be restored from its own page', async ({ page }) => {
	const paper = await uploadPaper(page, 'Retrieved');

	await itemAction(page, 'Move to trash');
	await expect(page).toHaveURL(/\/$/);
	await page.goto(`/items/${paper.id}`);
	await expect(page.getByText('This item is in the trash.')).toBeVisible();
	await page.getByRole('button', { name: 'Restore' }).click();
	await expect(page.getByText('This item is in the trash.')).toBeHidden();
	await expect(page.getByRole('button', { name: 'Item actions' })).toBeVisible();
});

test('archive and take out', async ({ page }) => {
	const paper = await uploadPaper(page, 'Archived');

	await itemAction(page, 'Archive');
	await expect(page.getByText(/This paper is in the archive/)).toBeVisible();
	await openLibrary(page);
	await expect(page.getByRole('link', { name: paper.title })).toBeHidden();

	await page.goto('/archive');
	const row = page.getByRole('listitem').filter({ hasText: paper.title });
	await expect(row).toBeVisible();
	await row.getByRole('button', { name: 'Take out' }).click();
	await expect(row).toBeHidden();

	await openLibrary(page);
	await expect(page.getByRole('link', { name: paper.title })).toBeVisible();

	// Archive again, and take out from the paper's page.
	await page.goto(`/items/${paper.id}`);
	await itemAction(page, 'Archive');
	await page.getByRole('button', { name: 'Take out of the archive' }).click();
	await expect(page.getByText(/This paper is in the archive/)).toBeHidden();
});
