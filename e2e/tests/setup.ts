import { expect, test as setup } from '@playwright/test';
import { ADMIN, ADMIN_STATE } from './helpers.ts';

setup('first run: create the administrator', async ({ page }) => {
	await page.goto('/');
	await expect(page).toHaveURL(/\/setup$/);
	await expect(page.getByRole('heading', { name: 'Welcome to paperus' })).toBeVisible();
	await page.getByRole('button', { name: /Start new/ }).click();
	await page.getByLabel('Username').fill(ADMIN.username);
	await page.getByLabel('Password', { exact: true }).fill(ADMIN.password);
	await page.getByLabel('Password again').fill(ADMIN.password);
	await page.getByRole('button', { name: 'Create and start' }).click();

	// Then the optional OIDC login, skipped.
	await expect(page.getByRole('heading', { name: 'OIDC login' })).toBeVisible();
	await page.getByRole('button', { name: 'Skip' }).click();
	await expect(page.getByRole('heading', { name: 'Nothing in the library yet' })).toBeVisible();

	// Setting up again is refused.
	const again = await page.request.post('/api/setup/admin', {
		data: { username: 'intruder', password: 'whatever-password' }
	});
	expect(again.status()).toBe(409);

	await page.context().storageState({ path: ADMIN_STATE });
});
