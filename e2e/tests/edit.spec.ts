import { expect, test, type Page } from '@playwright/test';
import { itemAction, unique } from './helpers.ts';

/** An ORCID iD no other test uses (its check digit fits, ISO 7064 11-2):
 * authors with the same iD are one person across the installation. */
function uniqueOrcid(): string {
	const digits = Array.from({ length: 15 }, () => Math.floor(Math.random() * 10));
	const total = digits.reduce((sum, digit) => ((sum + digit) * 2) % 11, 0);
	const check = (12 - total) % 11;
	const all = `${digits.join('')}${check === 10 ? 'X' : check}`;
	return all.match(/.{4}/g)!.join('-');
}

async function add(page: Page, metadata: Record<string, unknown>): Promise<string> {
	const added = await page.request.post('/api/items', { data: { metadata } });
	expect(added.status()).toBe(201);
	return (await added.json()).id;
}

test("a paper's details by hand: authors from the library's, year, journal", async ({ page }) => {
	const family = unique('Benito');
	const orcid = uniqueOrcid();
	const word = unique('Edited ');
	await add(page, {
		title: `${word} qubits`,
		author: [{ family, given: 'Mónica', ORCID: `https://orcid.org/${orcid}` }]
	});
	// Link authors now (the job runs every 5 minutes by itself).
	expect((await page.request.post('/api/admin/jobs/authors')).status()).toBe(202);
	await expect
		.poll(
			async () =>
				(await (await page.request.get('/api/authors', { params: { q: family } })).json()).length,
			{ timeout: 20_000 }
		)
		.toBe(1);
	const smith = unique('Smith');
	const id = await add(page, {
		type: 'article-journal',
		title: `${word} dots`,
		author: [{ family: smith, given: 'Jane' }],
		'container-title': 'Physical Review B',
		issued: { 'date-parts': [[2020, 5]] }
	});

	await page.goto(`/items/${id}`);
	await itemAction(page, 'Edit');
	const dialog = page.getByRole('dialog', { name: 'Edit' });
	await expect(dialog.getByRole('textbox', { name: 'Author 1', exact: true })).toHaveValue(
		`${smith}, Jane`
	);
	// A second author, from the library's: picked, with their ORCID iD.
	await dialog.getByRole('button', { name: 'Add author' }).click();
	await dialog.getByRole('textbox', { name: 'Author 2', exact: true }).fill(family.slice(0, 8));
	await dialog
		.getByRole('group', { name: 'Authors in the library' })
		.getByRole('button', { name: `${family}, Mónica 1 paper` })
		.click();
	await expect(dialog.getByRole('textbox', { name: 'Author 2', exact: true })).toHaveValue(
		`${family}, Mónica`
	);
	await dialog.getByRole('button', { name: 'Move author 2 up' }).click();
	await dialog.getByLabel('Year', { exact: true }).fill('2021');
	await dialog.getByLabel('Journal or venue').fill('Phys. Rev. B');
	await dialog.getByRole('button', { name: 'Save' }).click();
	await expect(dialog).toBeHidden();

	const authors = page.getByText(`${family}, Mónica;`);
	await expect(authors).toHaveText(`${family}, Mónica; ${smith}, Jane`);
	await expect(page.getByText('Phys. Rev. B')).toBeVisible();
	await expect(page.getByText('2021', { exact: true })).toBeVisible();
	const edited = await (await page.request.get(`/api/items/${id}`)).json();
	expect(edited.overrides.author[0].ORCID).toContain(orcid);
	expect(edited.overrides.author[1]).toEqual({ family: smith, given: 'Jane' });
	expect(edited.overrides.issued).toEqual({ 'date-parts': [[2021]] });

	// The year as its details have it again; the rest stays.
	await itemAction(page, 'Edit');
	await dialog.getByRole('button', { name: 'Restore original year' }).click();
	await expect(dialog.getByLabel('Year', { exact: true })).toHaveValue('2020');
	await dialog.getByRole('button', { name: 'Save' }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByText('2020', { exact: true })).toBeVisible();
	const restored = await (await page.request.get(`/api/items/${id}`)).json();
	expect(restored.overrides.issued).toBeUndefined();
	expect(restored.overrides['container-title']).toBe('Phys. Rev. B');
	expect(restored.csl.issued).toEqual({ 'date-parts': [[2020, 5]] });
});

test('saved over a change by paperus, not over one to its edits', async ({ page }) => {
	const id = await add(page, { title: unique('Changed meanwhile ') });
	await page.goto(`/items/${id}`);
	await itemAction(page, 'Edit');
	const dialog = page.getByRole('dialog', { name: 'Edit' });
	await dialog.getByLabel('Journal or venue').fill('Physical Review B');
	// Meanwhile the paper changes, its edits do not (as when paperus links
	// its authors): saved all the same.
	const link = await page.request.post(`/api/items/${id}/links`, {
		data: { url: 'https://github.com/example/code', kind: 'code' }
	});
	expect(link.status()).toBe(200);
	await dialog.getByRole('button', { name: 'Save' }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByText('Physical Review B')).toBeVisible();

	// Someone else's edit meanwhile: not overwritten.
	await itemAction(page, 'Edit');
	await dialog.getByLabel('Journal or venue').fill('Phys. Rev. B');
	const item = await page.request.get(`/api/items/${id}`);
	const theirs = await page.request.put(`/api/items/${id}/overrides`, {
		data: { ...(await item.json()).overrides, 'container-title': 'PRB' },
		headers: { 'if-match': item.headers()['etag'] }
	});
	expect(theirs.status()).toBe(200);
	await dialog.getByRole('button', { name: 'Save' }).click();
	await expect(dialog.getByText('Someone changed this paper in the meantime')).toBeVisible();
});
