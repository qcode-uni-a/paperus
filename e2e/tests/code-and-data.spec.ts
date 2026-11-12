import { expect, test } from '@playwright/test';
import { itemAction, unique, uploadPaper } from './helpers.ts';

// A paper's code and data: links added on its page (the kind guessed from
// the address), opened in a tab of their own, and removed again.
test("a paper's links to its code and data", async ({ page }) => {
	await uploadPaper(page, 'Coded');
	await page.getByRole('button', { name: '+ Code or data' }).click();
	await page.getByRole('textbox', { name: 'Address' }).fill('github.com/ada/qubits');
	await expect(page.getByRole('combobox', { name: 'Kind' })).toHaveValue('code');
	await page.getByRole('button', { name: 'Add link' }).click();

	const code = page.getByRole('link', { name: /github\.com\/ada\/qubits/ });
	await expect(code).toHaveAttribute('href', 'https://github.com/ada/qubits');
	await expect(code).toHaveAttribute('target', '_blank');

	await page.getByRole('button', { name: '+ Code or data' }).click();
	await page.getByRole('textbox', { name: 'Address' }).fill('https://doi.org/10.5281/zenodo.1234');
	await expect(page.getByRole('combobox', { name: 'Kind' })).toHaveValue('data');
	await page.getByRole('textbox', { name: 'Name' }).fill('Measured spectra');
	await page.getByRole('button', { name: 'Add link' }).click();
	await expect(page.getByRole('link', { name: /Measured spectra/ })).toBeVisible();
	await page.locator('.links').screenshot({ path: 'test-results/code-and-data.png' });

	await page.getByRole('button', { name: 'Remove the link to github.com/ada/qubits' }).click();
	await expect(code).toHaveCount(0);
	await expect(page.getByRole('link', { name: /Measured spectra/ })).toBeVisible();
});

// Code merged into its paper by mistake: split off again; then attached to
// the paper as its code, as it should have been.
test('code split off its paper, then attached as its code', async ({ page }) => {
	const word = unique('qubits');
	const add = async (metadata: Record<string, unknown>, doi?: string) => {
		const added = await page.request.post('/api/items', {
			data: { metadata, identifiers: doi ? [{ scheme: 'doi', value: doi }] : [] }
		});
		expect(added.status()).toBe(201);
		return (await added.json()).id as string;
	};
	const paper = await add({ title: `Spin ${word}` });
	const zenodo = `10.5281/zenodo.${Date.now()}`;
	const code = await add({ type: 'software', title: `Code of Spin ${word}` }, zenodo);
	const merged = await page.request.post(`/api/items/${code}/merge`, { data: { into: paper } });
	expect(merged.status()).toBe(200);

	await page.goto(`/items/${paper}`);
	const versions = page.locator('article.card');
	await expect(versions).toHaveCount(2);
	page.once('dialog', (confirm) => confirm.accept());
	await versions.filter({ hasText: zenodo }).getByRole('button', { name: 'Split off' }).click();
	await expect(page.getByText(`Split off: Code of Spin ${word}`)).toBeVisible();
	await expect(versions).toHaveCount(1);
	await expect(page.getByRole('button', { name: 'Split off' })).toHaveCount(0);

	// The split-off item: attached to the paper as its code.
	await page.getByRole('link', { name: 'Open it' }).click();
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Code of Spin ${word}`);
	await itemAction(page, 'Attach to a paper…');
	const dialog = page.getByRole('dialog', { name: 'Attach to a paper' });
	// Suggested by its title: "Code of Spin …" is Spin …'s.
	await expect(dialog.getByRole('heading', { name: 'Likely its paper' })).toBeVisible();
	await dialog.getByRole('button', { name: new RegExp(`^Spin ${word}`) }).click();
	await dialog.getByRole('button', { name: 'Attach as its code' }).click();
	await expect(page).toHaveURL(new RegExp(`/items/${paper}$`));
	await expect(
		page.getByRole('link', { name: new RegExp(`Code of Spin ${word}`) })
	).toHaveAttribute('href', `https://doi.org/${zenodo}`);
	await expect(versions).toHaveCount(1);
});
