import { expect, test } from '@playwright/test';
import { unique } from './helpers.ts';

test('create an access token, use it, revoke it', async ({ page, playwright, baseURL }) => {
	const name = unique('Script ');
	await page.goto('/settings');
	await expect(page.getByRole('heading', { name: 'Access tokens' })).toBeVisible();
	await page.getByRole('button', { name: 'New token' }).click();
	const dialog = page.getByRole('dialog', { name: 'New access token' });
	await dialog.getByLabel('Name').fill(name);
	await dialog.getByRole('radio', { name: /^AI assistant search and read/ }).check();
	await dialog.getByRole('button', { name: 'Create token' }).click();

	const created = page.getByRole('dialog', { name: 'Token created' });
	await expect(created.getByText('it is shown only this once')).toBeVisible();
	const token = (await created.locator('.secret code').textContent())?.trim() ?? '';
	expect(token.length).toBeGreaterThan(20);
	await created.getByRole('button', { name: 'Done' }).click();
	const listed = page.getByRole('listitem').filter({ hasText: name });
	await expect(listed).toContainText('Not used yet');

	// The token works without the browser's login, for reading only.
	const api = await playwright.request.newContext({
		baseURL,
		extraHTTPHeaders: { Authorization: `Bearer ${token}` }
	});
	expect((await api.get('/api/items')).status()).toBe(200);
	expect((await api.post('/api/tags', { data: { name: 'nope' } })).status()).toBe(403);

	page.once('dialog', (confirm) => confirm.accept());
	await listed.getByRole('button', { name: 'Revoke' }).click();
	await expect(listed).toBeHidden();
	expect((await api.get('/api/items')).status()).toBe(401);
	await api.dispose();
});
