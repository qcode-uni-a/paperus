import { createHash, randomBytes } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { unique } from './helpers.ts';

/** An AI assistant's connector (e.g. claude.ai's) connecting by OAuth:
 * registers itself, sends the person to the consent page, gets a code back
 * at its redirect address and trades it for a token. */
const REDIRECT = 'https://e2e-client.example/callback';

test('an app connects through the consent page', async ({ page, playwright, baseURL }) => {
	const clientName = unique('E2E Assistant ');
	const registered = await page.request.post('/api/oauth/register', {
		data: { client_name: clientName, redirect_uris: [REDIRECT] }
	});
	expect(registered.status()).toBe(201);
	const { client_id: clientId } = await registered.json();

	const verifier = randomBytes(32).toString('base64url');
	const challenge = createHash('sha256').update(verifier).digest('base64url');
	const state = randomBytes(8).toString('hex');
	const authorize = new URLSearchParams({
		client_id: clientId,
		redirect_uri: REDIRECT,
		response_type: 'code',
		code_challenge: challenge,
		code_challenge_method: 'S256',
		scope: 'search papers.read tags.write',
		state
	});

	// The app's own page, which the browser is sent back to.
	await page.route(`${REDIRECT}**`, (route) =>
		route.fulfill({ contentType: 'text/html', body: '<h1>Back in the app</h1>' })
	);
	await page.goto(`/oauth/authorize?${authorize}`);
	await expect(
		page.getByRole('heading', { name: `Connect ${clientName} to paperus?` })
	).toBeVisible();
	await expect(page.getByText('e2e-client.example')).toBeVisible();
	// Reading is ticked; changing things only when asked for.
	await expect(page.getByRole('checkbox', { name: 'Search your library' })).toBeChecked();
	await expect(page.getByRole('checkbox', { name: 'Tag papers' })).not.toBeChecked();
	await page.getByRole('button', { name: 'Allow' }).click();

	await expect(page.getByRole('heading', { name: 'Back in the app' })).toBeVisible();
	const back = new URL(page.url());
	expect(`${back.origin}${back.pathname}`).toBe(REDIRECT);
	expect(back.searchParams.get('state')).toBe(state);
	const code = back.searchParams.get('code');
	expect(code).toBeTruthy();

	// The app trades the code (with its PKCE verifier) for tokens.
	const api = await playwright.request.newContext({ baseURL });
	const tokenResponse = await api.post('/api/oauth/token', {
		form: {
			grant_type: 'authorization_code',
			code: code ?? '',
			redirect_uri: REDIRECT,
			code_verifier: verifier,
			client_id: clientId
		}
	});
	expect(tokenResponse.status()).toBe(200);
	const tokens = await tokenResponse.json();
	expect(tokens.scope.split(' ').sort()).toEqual(['papers.read', 'search']);
	// A code works once.
	const again = await api.post('/api/oauth/token', {
		form: {
			grant_type: 'authorization_code',
			code: code ?? '',
			redirect_uri: REDIRECT,
			code_verifier: verifier,
			client_id: clientId
		}
	});
	expect(again.status()).toBe(400);
	const asApp = { Authorization: `Bearer ${tokens.access_token}` };
	expect((await api.get('/api/items', { headers: asApp })).status()).toBe(200);

	// Settings shows the app; disconnecting ends its access.
	await page.goto('/settings');
	const app = page.getByRole('listitem').filter({ hasText: clientName });
	await expect(app).toBeVisible();
	page.once('dialog', (confirm) => confirm.accept());
	await app.getByRole('button', { name: 'Disconnect' }).click();
	await expect(app).toBeHidden();
	expect((await api.get('/api/items', { headers: asApp })).status()).toBe(401);
	await api.dispose();
});

test('the consent page refuses an unknown app', async ({ page }) => {
	const authorize = new URLSearchParams({
		client_id: 'not-registered',
		redirect_uri: REDIRECT,
		response_type: 'code',
		code_challenge: 'x'.repeat(43),
		code_challenge_method: 'S256'
	});
	await page.goto(`/oauth/authorize?${authorize}`);
	await expect(page.getByRole('heading', { name: 'This app cannot connect' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Allow' })).toBeHidden();
});
