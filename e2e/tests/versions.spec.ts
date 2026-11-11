import { expect, test } from '@playwright/test';

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
