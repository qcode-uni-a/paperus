import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from '@playwright/test';
import { makePdf } from '../fixtures/pdf.ts';

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
