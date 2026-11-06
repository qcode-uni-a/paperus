// An access token for the Chrome Web Store API from a service account's
// JSON key (OAuth 2.0 JWT bearer grant), written to $GITHUB_OUTPUT as
// "token" and masked in the log. Key in CHROME_SERVICE_ACCOUNT_KEY.
import { createSign } from 'node:crypto';
import { appendFileSync } from 'node:fs';

const key = JSON.parse(process.env.CHROME_SERVICE_ACCOUNT_KEY);
const b64 = (value) => Buffer.from(JSON.stringify(value)).toString('base64url');
const now = Math.floor(Date.now() / 1000);
const claims = {
	iss: key.client_email,
	scope: 'https://www.googleapis.com/auth/chromewebstore',
	aud: key.token_uri,
	iat: now,
	exp: now + 600
};
const body = `${b64({ alg: 'RS256', typ: 'JWT' })}.${b64(claims)}`;
const signature = createSign('RSA-SHA256').update(body).sign(key.private_key, 'base64url');
const response = await fetch(key.token_uri, {
	method: 'POST',
	body: new URLSearchParams({
		grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
		assertion: `${body}.${signature}`
	})
});
const data = await response.json();
if (!response.ok) {
	console.error(response.status, data);
	process.exit(1);
}
console.log(`::add-mask::${data.access_token}`);
appendFileSync(process.env.GITHUB_OUTPUT, `token=${data.access_token}\n`);
console.log(`Token for ${key.client_email}.`);
