import { expect, test } from '@playwright/test';
import { PAPERS, seed } from '../demo/seed.ts';

test('the library', async ({ page, browser }) => {
	const options = { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 };
	const pdfs = process.env.PAPERUS_DEMO_PDFS;
	const mira = (await seed(page, browser, { pdfs, options })).page;
	await mira.goto('/');
	await expect(mira.getByRole('link', { name: PAPERS[0][0] })).toBeVisible();
	await mira.waitForLoadState('networkidle');
	await mira.screenshot({ path: '../site/screenshots/library.png' });
	// The website follows the device: dark for a dark homepage.
	await mira.emulateMedia({ colorScheme: 'dark' });
	await mira.screenshot({ path: '../site/screenshots/library-dark.png' });
});
