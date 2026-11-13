import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from '@playwright/test';
import { makePdf } from '../fixtures/pdf.ts';
import { LOGGED_OUT, unique } from './helpers.ts';

// Settings → Import: a Zotero export as the folder Zotero writes (no zip),
// sent file by file, then imported.
test('import a whole folder, without zipping it', async ({ page }) => {
	const folder = test.info().outputPath('Exported Items');
	const rdf = readFileSync(join(import.meta.dirname, '../../server/tests/zotero_sample.rdf'));
	const files: Record<string, Buffer> = {
		'Exported Items.rdf': rdf,
		'files/13/van Gogh - 2024 - Radar gaps.pdf': makePdf([['Radar gaps']], 'Radar gaps'),
		'files/30/Note241029.pdf': makePdf([['Scribbles']], 'Scribbles'),
		'files/31/2601.pdf': makePdf([['Floquet']], 'Floquet')
	};
	for (const [path, content] of Object.entries(files)) {
		mkdirSync(join(folder, path, '..'), { recursive: true });
		writeFileSync(join(folder, path), content);
	}

	// Old links lead here too.
	await page.goto('/import');
	await expect(page).toHaveURL(/\/settings\?open=import$/);
	const section = page.locator('section#import');
	await expect(section.getByText('How to export')).toBeVisible();
	await section.locator('input[webkitdirectory]').setInputFiles(folder);
	const imported = section.getByRole('listitem').filter({ hasText: 'Exported Items' }).first();
	await expect(imported).toContainText(/5 papers: \d+ added/, { timeout: 60_000 });
	await expect(imported).toContainText('3 files');
});

// A paper already in a group one may only read, with a file: added as
// one's own, so the file comes too; the bell says the import is done.
test('an import says what was there already, and where', async ({
	page,
	browser,
	playwright,
	baseURL
}) => {
	const kim = { username: unique('kim'), password: 'kim-password-e2e' };
	const made = await page.request.post('/api/admin/users', { data: kim });
	expect(made.status()).toBe(201);
	const kimId = (await made.json()).id;
	// The group is lea's (in the admin's own groups it would change the
	// other tests' uploads: they would ask where to).
	const lea = { username: unique('lea'), password: 'lea-password-e2e' };
	const leaMade = await page.request.post('/api/admin/users', { data: lea });
	const leaApi = await playwright.request.newContext({ baseURL });
	expect((await leaApi.post('/api/auth/login', { data: lea })).ok()).toBe(true);
	const lab = await (
		await page.request.post('/api/groups', {
			data: { name: unique('Lab'), admin_id: (await leaMade.json()).id }
		})
	).json();
	await leaApi.put(`/api/groups/${lab.id}/members/${kimId}`, { data: { role: 'reader' } });
	const doi = `10.5555/${unique('e2e').toLowerCase()}`;
	await leaApi.post('/api/items', {
		data: {
			metadata: { title: 'In the lab already' },
			identifiers: [{ scheme: 'doi', value: doi }],
			library_id: lab.library_id
		}
	});

	const folder = test.info().outputPath('Kim export');
	mkdirSync(folder, { recursive: true });
	writeFileSync(
		join(folder, 'library.bib'),
		`@article{lab, title={In the lab already}, doi={${doi}}, file={lab.pdf}}\n` +
			`@article{new, title={${unique('Brand new')}}}\n`
	);
	writeFileSync(join(folder, 'lab.pdf'), makePdf([['Lab paper']], 'Lab paper'));

	const context = await browser.newContext({ storageState: LOGGED_OUT });
	const own = await context.newPage();
	await own.goto('/login');
	await own.getByLabel('Username').fill(kim.username);
	await own.getByLabel('Password').fill(kim.password);
	await own.getByRole('button', { name: 'Log in' }).click();
	await expect(own).toHaveURL(/\/$/);
	await own.goto('/settings?open=import');
	const section = own.locator('section#import');
	await section.locator('input[webkitdirectory]').setInputFiles(folder);
	const imported = section.getByRole('listitem').filter({ hasText: 'Kim export' }).first();
	await expect(imported).toContainText(`2 papers: 2 added, 0 already here.`, { timeout: 60_000 });
	await expect(imported).toContainText(
		`Of those added, 1 is also in ${lab.name}, which you can only read: added as your own, so its files could come too.`
	);

	await own.getByRole('button', { name: /Notifications/ }).click();
	await expect(
		own.getByText('Import of Kim export done: 2 papers added (1 also in a group, as your own)')
	).toBeVisible();
	await context.close();
	await leaApi.dispose();
});
