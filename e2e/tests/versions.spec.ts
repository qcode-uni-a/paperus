import { expect, test } from '@playwright/test';
import { uploadPaper } from './helpers.ts';

// In the app (window.paperusApp, app/src-tauri): an app older than the
// server supports is asked to update; the website itself works on.
test('an app too old for the server is asked to update', async ({ page }) => {
	const banner = page.getByRole('note').filter({ hasText: 'This app is older' });

	await page.addInitScript(() => {
		(window as unknown as { paperusApp: object }).paperusApp = { version: '0.0.1' };
	});
	await page.goto('/');
	await expect(banner).toBeVisible();
	await expect(banner.getByRole('link', { name: 'Download the app' })).toHaveAttribute(
		'href',
		/releases\/latest$/
	);
	await expect(page.getByRole('main')).toBeVisible();
});

test('an app new enough, or none, is not', async ({ page, context }) => {
	await context.addInitScript(() => {
		(window as unknown as { paperusApp: object }).paperusApp = { version: '999.0.0' };
	});
	await page.goto('/');
	await expect(page.getByRole('main')).toBeVisible();
	await expect(page.getByText('This app is older')).toHaveCount(0);
});

// "Keep offline on this device": only in an app that can, showing what the
// app says it keeps (window.paperusApp.kept, after each page load).
test('keep a paper offline, in the app only', async ({ page }) => {
	const paper = await uploadPaper(page, 'Kept');
	const entry = page.getByRole('menuitemcheckbox', { name: 'Keep offline on this device' });
	await page.getByRole('button', { name: 'Item actions' }).click();
	await expect(page.getByRole('menuitem', { name: 'Copy BibTeX' })).toBeVisible();
	await expect(entry).toHaveCount(0);

	await page.addInitScript((id) => {
		(window as unknown as { paperusApp: object }).paperusApp = {
			version: '999.0.0',
			features: { offline: 1 },
			kept: { items: [id], collections: [], available: [id] }
		};
	}, paper.id);
	await page.reload();
	await page.getByRole('button', { name: 'Item actions' }).click();
	await expect(entry).toHaveAttribute('aria-checked', 'true');
	// Kept whole: marked in the lists and on its page.
	const mark = page.getByRole('img', { name: 'Available offline on this device' });
	await expect(mark).toBeVisible();
	await page.goto('/');
	await expect(
		page.getByRole('listitem').filter({ hasText: paper.title }).getByRole('img', {
			name: 'Available offline on this device'
		})
	).toBeVisible();
});
