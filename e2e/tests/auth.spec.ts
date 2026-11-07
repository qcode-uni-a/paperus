import { expect, test } from '@playwright/test';
import { ADMIN, LOGGED_OUT } from './helpers.ts';

// Logs in itself: logging out ends only this session, not the shared one.
test.use({ storageState: LOGGED_OUT });

test('pages need a login', async ({ page }) => {
	await page.goto('/settings');
	await expect(page).toHaveURL(/\/login/);
	await expect(page.getByRole('heading', { name: 'paperus' })).toBeVisible();
});

test('a wrong password is refused', async ({ page }) => {
	await page.goto('/login');
	await page.getByLabel('Username').fill(ADMIN.username);
	await page.getByLabel('Password').fill('not-the-password');
	await page.getByRole('button', { name: 'Log in' }).click();
	await expect(page.getByRole('alert')).toBeVisible();
	await expect(page).toHaveURL(/\/login/);
});

test('log in and out', async ({ page }) => {
	await page.goto('/login');
	await page.getByLabel('Username').fill(ADMIN.username);
	await page.getByLabel('Password').fill(ADMIN.password);
	await page.getByRole('button', { name: 'Log in' }).click();

	const account = page.getByTitle('Account');
	await expect(account).toBeVisible();
	await expect(page).not.toHaveURL(/\/login/);
	await account.click();
	const menu = page.getByRole('menu');
	await expect(menu.getByText('Administrator')).toBeVisible();
	await menu.getByRole('menuitem', { name: 'Log out' }).click();
	await expect(page).toHaveURL(/\/login/);

	// The session is gone: pages lead back to the login.
	await page.goto('/settings');
	await expect(page).toHaveURL(/\/login/);
	expect((await page.request.get('/api/auth/me')).status()).toBe(401);
});
