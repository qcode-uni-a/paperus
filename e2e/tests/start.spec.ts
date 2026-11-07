import { expect, test } from '@playwright/test';
import { LOGGED_OUT, unique, uploadPaper } from './helpers.ts';

test('a new person gets started, step by step', async ({ page, browser }) => {
	// A person of their own, so the steps start at none done.
	const dana = { username: unique('dana'), password: 'dana-password-e2e' };
	const created = await page.request.post('/api/admin/users', { data: dana });
	expect(created.status()).toBe(201);

	const context = await browser.newContext({ storageState: LOGGED_OUT });
	const own = await context.newPage();
	await own.goto('/login');
	await own.getByLabel('Username').fill(dana.username);
	await own.getByLabel('Password').fill(dana.password);
	await own.getByRole('button', { name: 'Log in' }).click();

	const steps = own.getByRole('region', { name: 'Getting started' });
	await expect(steps).toContainText('0 of 4 done');
	// Not an administrator: no server steps.
	await expect(steps.getByRole('heading', { name: 'Your server' })).toBeHidden();
	await expect(steps.getByRole('link', { name: 'Import a library' })).toHaveAttribute(
		'href',
		'/import'
	);

	await uploadPaper(own, 'started');
	await own.goto('/');
	await expect(steps).toContainText('1 of 4 done');
	await expect(
		steps.getByRole('listitem').filter({ hasText: 'Add your first paper' }).getByRole('img')
	).toHaveAccessibleName('Done');

	// Hidden for good, also after reloading.
	await steps.getByRole('button', { name: 'Hide' }).click();
	await expect(steps).toBeHidden();
	await own.reload();
	await expect(own.getByRole('heading', { level: 1 })).toContainText('1 item');
	await expect(steps).toBeHidden();
	await context.close();
});

test('the administrator sees what the server still needs', async ({ page }) => {
	await page.goto('/');
	const steps = page.getByRole('region', { name: 'Getting started' });
	await expect(steps.getByRole('heading', { name: 'Your server' })).toBeVisible();
	// No ML service in these tests.
	await expect(
		steps.getByRole('listitem').filter({ hasText: 'Start the machine learning service' })
	).toContainText('search finds words only');
	// Backups run daily from the start.
	await expect(
		steps.getByRole('listitem').filter({ hasText: 'Turn on backups' }).getByRole('img')
	).toHaveAccessibleName('Done');
	await steps.getByRole('link', { name: 'Server settings' }).click();
	await expect(page).toHaveURL(/\/admin\/settings\?open=server$/);
});
