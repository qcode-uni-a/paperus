import { createHash, randomBytes } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { ADMIN } from './helpers.ts';

/** The paperus app's login in the system's browser (app/src-tauri/src/
 * login.rs): the app registers, opens /app-login, gets a code back on its
 * loopback address and trades it, with its PKCE verifier, for a session. */
const APP = 'http://127.0.0.1:53124/done';

test('the app logs in through the browser', async ({ page, playwright, baseURL }) => {
	const registered = await page.request.post('/api/oauth/register', {
		data: { client_name: 'the paperus app', redirect_uris: ['http://127.0.0.1/done'] }
	});
	const { client_id: clientId } = await registered.json();
	const verifier = randomBytes(32).toString('base64url');
	const challenge = createHash('sha256').update(verifier).digest('base64url');
	const login = new URLSearchParams({
		client_id: clientId,
		redirect_uri: APP,
		code_challenge: challenge,
		state: 's1'
	});

	// The app's loopback address, which the browser is sent back to.
	await page.route(`${APP}**`, (route) =>
		route.fulfill({ contentType: 'text/html', body: '<h1>Back in the app</h1>' })
	);
	await page.goto(`/app-login?${login}`);
	await expect(page.getByRole('heading', { name: 'Log in to the paperus app?' })).toBeVisible();
	await expect(page.getByText(`logged in as ${ADMIN.username}`)).toBeVisible();
	await page.getByRole('button', { name: 'Log in to the app' }).click();
	await expect(page.getByRole('heading', { name: 'Back in the app' })).toBeVisible();
	const back = new URL(page.url());
	expect(back.searchParams.get('state')).toBe('s1');
	const code = back.searchParams.get('code') ?? '';

	// The app (no login of its own) trades the code for a session.
	const app = await playwright.request.newContext({ baseURL });
	const traded = await app.post('/api/oauth/app-session', {
		data: { client_id: clientId, code, redirect_uri: APP, code_verifier: verifier }
	});
	expect(traded.status()).toBe(200);
	const { token } = await traded.json();
	const me = await app.get('/api/auth/me', { headers: { Cookie: `paperus_session=${token}` } });
	expect((await me.json()).username).toBe(ADMIN.username);
	await app.dispose();

	// Cancelled: the app hears so, without a code.
	await page.goto(`/app-login?${login}`);
	await page.getByRole('button', { name: 'Cancel' }).click();
	await expect(page.getByRole('heading', { name: 'Back in the app' })).toBeVisible();
	expect(new URL(page.url()).searchParams.get('error')).toBe('access_denied');
	expect(new URL(page.url()).searchParams.has('code')).toBe(false);
});

test('only an app on this computer logs in this way', async ({ page }) => {
	const registered = await page.request.post('/api/oauth/register', {
		data: { client_name: 'Elsewhere', redirect_uris: ['https://e2e-client.example/callback'] }
	});
	const { client_id: clientId } = await registered.json();
	const login = new URLSearchParams({
		client_id: clientId,
		redirect_uri: 'https://e2e-client.example/callback',
		code_challenge: 'x'.repeat(43)
	});
	await page.goto(`/app-login?${login}`);
	await expect(page.getByRole('heading', { name: 'The app cannot log in' })).toBeVisible();
	await expect(page.getByRole('alert')).toContainText('Only the paperus app');
});
