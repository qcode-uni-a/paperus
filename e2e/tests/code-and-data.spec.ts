import { expect, test } from '@playwright/test';
import { uploadPaper } from './helpers.ts';

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
