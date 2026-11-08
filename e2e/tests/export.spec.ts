import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { uploadPaper } from './helpers.ts';

test('export the library and download it', async ({ page }) => {
	await uploadPaper(page, 'Export');
	await page.goto('/settings#export');
	const section = page.locator('section#export');
	await expect(section.getByRole('button', { name: /^Export Your papers/ })).toHaveAttribute(
		'aria-expanded',
		'true'
	);
	// The size is estimated before exporting.
	await expect(section.getByText(/\d+ papers?, \d+ notes?, \d+ files?: about/)).toBeVisible();
	await section.getByRole('button', { name: 'Export', exact: true }).click();

	const download = section.getByRole('link', { name: 'Download' }).first();
	await expect(download).toBeVisible({ timeout: 30_000 });
	const [file] = await Promise.all([page.waitForEvent('download'), download.click()]);
	expect(file.suggestedFilename()).toMatch(/^paperus-export-\d{4}-\d{2}-\d{2}-\d{4}\.zip$/);
	const zip = await readFile((await file.path()) ?? '');
	// A zip whose first entry is the database.
	expect(zip.subarray(0, 4).toString('latin1')).toBe('PK\x03\x04');
	const firstName = zip.subarray(30, 30 + zip.readUInt16LE(26)).toString();
	expect(firstName).toMatch(/^paperus-export-[\d-]+\/library\.sqlite$/);
});
