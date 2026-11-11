// The library on this computer (src-tauri/src/local.rs), driven through
// tauri-driver: made from the app's page from a bundle given
// (PAPERUS_LOCAL_BUNDLE, app/local/build.sh's folder), opened logged in;
// the app ended without a word (as a crash: tauri-driver kills it) and
// started again, which opens it again by itself. Run by local.sh.
import assert from 'node:assert/strict';

const [APP] = process.argv.slice(2);
const DRIVER = 'http://127.0.0.1:4444';

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

async function webdriver(method, path, body) {
	const response = await fetch(DRIVER + path, {
		method,
		headers: { 'Content-Type': 'application/json' },
		body: body && JSON.stringify(body)
	});
	const { value } = await response.json();
	if (value?.error) throw new Error(`${path}: ${value.error}: ${value.message}`);
	return value;
}

/** Until ``check`` gives something (at most ``seconds``). */
async function until(check, seconds) {
	for (let i = 0; i < seconds * 4; i++) {
		const found = await check().catch(() => undefined);
		if (found) return found;
		await sleep(250);
	}
	throw new Error(`waited ${seconds} s for ${check}`);
}

async function session() {
	const { sessionId } = await webdriver('POST', '/session', {
		capabilities: { alwaysMatch: { 'tauri:options': { application: APP } } }
	});
	const inApp = (script) =>
		webdriver('POST', `/session/${sessionId}/execute/async`, {
			script: `const done = arguments[arguments.length - 1]; ${script}`,
			args: []
		});
	const shown = () => webdriver('GET', `/session/${sessionId}/url`);
	const end = () => webdriver('DELETE', `/session/${sessionId}`).catch(() => {});
	return { inApp, shown, end };
}

const atLibrary = (url) => /^http:\/\/127\.0\.0\.1:\d+\/$/.test(url);
const me = (inApp) =>
	inApp(`fetch('/api/auth/me').then((r) => r.json()).then((me) => done(me.username))`);

// Made from the app's page: its parts unpacked, a database, the only
// person, the library open and logged in.
let app = await session();
try {
	await until(async () => (await app.shown()).startsWith('tauri:'), 20);
	app.inApp(`window.__TAURI__.core.invoke('make_local_library').then(done, done)`).catch(() => {});
	await until(async () => atLibrary(await app.shown()), 180);
	assert.equal(await me(app.inApp), 'me');
	const libraries = await app.inApp(`fetch('/api/items?limit=1').then((r) => done(r.status))`);
	assert.equal(libraries, 200);
	console.log('ok: a library on this computer, made and logged in');
} finally {
	await app.end();
}

// Started again: the library open last opens by itself, logged in again.
await sleep(1000);
app = await session();
try {
	await until(async () => atLibrary(await app.shown()), 120);
	assert.equal(await until(() => me(app.inApp), 30), 'me');
	console.log('ok: opened again at the next start, after the app ended without stopping it');
} finally {
	await app.end();
}
