import { expect, test } from '@playwright/test';
import { itemAction, uploadPaper } from './helpers.ts';

test('an uploaded PDF is read by the worker and found by its words', async ({ page }) => {
	const paper = await uploadPaper(page, 'Upload');
	// Its upload done, the tray closes by itself once the pointer is off it.
	await page.mouse.move(0, 0);
	await expect(page.getByRole('complementary', { name: 'Uploads' })).toBeHidden({
		timeout: 15_000
	});

	// Its file, read: the text is searchable.
	await itemAction(page, 'Details and files');
	const file = page
		.getByRole('main')
		.getByRole('listitem')
		.filter({ hasText: `${paper.word}.pdf` });
	await expect(file).toContainText('Searchable');
	// The PDF itself is served.
	const href = await file.getByRole('link', { name: `${paper.word}.pdf` }).getAttribute('href');
	const content = await page.request.get(href ?? '');
	expect(content.headers()['content-type']).toContain('application/pdf');
	expect((await content.body()).subarray(0, 5).toString()).toBe('%PDF-');

	// Search by a word from page 2 (keywords: no ML service in these tests).
	await page.goto('/');
	await page.getByRole('searchbox', { name: 'Search the library' }).fill(paper.word);
	await expect(page).toHaveURL(new RegExp(`[?&]q=${paper.word}`));
	await expect(page.getByRole('heading', { name: `1 item for “${paper.word}”` })).toBeVisible();
	const result = page.getByRole('link', { name: paper.title });
	await expect(result).toBeVisible();
	await expect(page.locator('mark').first()).toHaveText(new RegExp(paper.word, 'i'));
	await result.click();
	await expect(page).toHaveURL(new RegExp(`/items/${paper.id}`));
	// Reading a paper: no search bar.
	await expect(page.getByRole('searchbox', { name: 'Search the library' })).toHaveCount(0);

	// A word in no paper finds nothing.
	await page.goto('/?q=zzzxqvnotthere');
	await expect(page.getByText('Nothing found for “zzzxqvnotthere”.')).toBeVisible();
});

test('edit the title and the tags', async ({ page }) => {
	const paper = await uploadPaper(page, 'Edit');

	await itemAction(page, 'Edit');
	const dialog = page.getByRole('dialog', { name: 'Edit' });
	const newTitle = `Renamed ${paper.word} paper`;
	await dialog.getByLabel('Title').fill(newTitle);
	await dialog.getByRole('button', { name: 'Save' }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(newTitle);

	// Tags: two added, one removed.
	const tag = `tag-${paper.word}`;
	for (const name of [tag, `${tag}-2`]) {
		await page.getByRole('button', { name: 'Add a tag' }).click();
		await page.getByRole('combobox', { name: 'Add a tag' }).fill(name);
		await page.getByRole('combobox', { name: 'Add a tag' }).press('Enter');
		await expect(page.getByRole('link', { name, exact: true })).toBeVisible();
	}
	await page.getByRole('button', { name: `Remove tag ${tag}-2` }).click();
	await expect(page.getByRole('link', { name: `${tag}-2`, exact: true })).toBeHidden();
	// One Enter adds a tag also while suggestions show (the removed one is
	// one now): Safari's suggestions took that Enter for themselves.
	await page.getByRole('button', { name: 'Add a tag' }).click();
	await page.getByRole('combobox', { name: 'Add a tag' }).fill(`${tag}-3`);
	await page.getByRole('combobox', { name: 'Add a tag' }).press('Enter');
	await expect(page.getByRole('link', { name: `${tag}-3`, exact: true })).toBeVisible();

	// Both stay after a reload; the library filters by the tag.
	await page.reload();
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(newTitle);
	await page.getByRole('link', { name: tag, exact: true }).click();
	await expect(page.getByText(`Papers tagged ${tag}.`)).toBeVisible();
	await expect(page.getByRole('link', { name: newTitle })).toBeVisible();
	await expect(page.getByRole('heading', { name: '1 item' })).toBeVisible();
});
