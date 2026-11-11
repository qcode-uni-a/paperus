// The app's journeys (app/README.md, Tests): the app itself, driven
// through tauri-driver (WebDriver), against the e2e tests' paperus. The
// browser's side of logging in goes over HTTP here (its page is tested in
// e2e/tests/app-login.spec.ts). Run by run.sh.
import { spawn } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { createServer, connect } from 'node:net';
import { join } from 'node:path';
import assert from 'node:assert/strict';

const [APP, OPENED, PDF, DATA] = process.argv.slice(2);
const DRIVER = 'http://127.0.0.1:4444';
const PORT = Number(process.env.PAPERUS_E2E_PORT ?? 8100);
// The app reaches the library through a stand-in for the network, cut to
// go offline and joined again.
const SERVER = `http://127.0.0.1:${PORT}`;
const LIBRARY = `http://127.0.0.1:${PORT + 1}`;
const ADMIN = { username: 'admin', password: 'e2e-admin-password' };

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const connections = new Set();
/** The network up: connections to LIBRARY go to the server. */
function network() {
	const proxy = createServer((client) => {
		const server = connect(PORT, '127.0.0.1');
		for (const end of [client, server]) {
			connections.add(end);
			end.on('error', () => {});
			end.on('close', () => connections.delete(end));
		}
		client.pipe(server).pipe(client);
	});
	return new Promise((done) => proxy.listen(PORT + 1, '127.0.0.1', () => done(proxy)));
}
/** The network down. */
function cut(proxy) {
	for (const end of connections) end.destroy();
	return new Promise((done) => proxy.close(done));
}
let proxy = await network();

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
async function until(check, seconds = 20) {
	for (let i = 0; i < seconds * 4; i++) {
		const found = await check();
		if (found) return found;
		await sleep(250);
	}
	throw new Error(`waited ${seconds} s for ${check}`);
}

let { sessionId } = await webdriver('POST', '/session', {
	capabilities: { alwaysMatch: { 'tauri:options': { application: APP } } }
});
/** ``script`` in the app's window; it ends by calling ``done(value)``. */
const inApp = (script) =>
	webdriver('POST', `/session/${sessionId}/execute/async`, {
		script: `const done = arguments[arguments.length - 1]; ${script}`,
		args: []
	});
const shown = () => webdriver('GET', `/session/${sessionId}/url`);
const invoke = (command, args) =>
	inApp(`window.__TAURI__.core.invoke('${command}', ${JSON.stringify(args)})
		.then((value) => done({ value }), (error) => done({ refused: String(error) }))`);
/** The text of the window's page. */
const pageText = () => inApp(`done(document.body.innerText)`);

try {
	// The app's own page; connecting to a library, checked first.
	await until(async () => (await shown()).startsWith('tauri:'));
	const nowhere = await invoke('add_library', { address: 'http://127.0.0.1:9' });
	assert.match(nowhere.refused, /could not be reached/);
	const added = await invoke('add_library', { address: LIBRARY });
	assert.deepEqual(added.value, { url: LIBRARY, name: '127.0.0.1' });
	invoke('open_library', { url: LIBRARY }).catch(() => {});
	await until(async () => (await shown()).startsWith(`${LIBRARY}/login`));
	console.log('ok: connected, at the login page');

	// The website knows it is in the app, and may not call it.
	assert.equal((await inApp(`done('paperusApp' in window)`)), true);
	const refused = await invoke('libraries', {});
	assert.match(refused.refused, /not allowed/);
	console.log('ok: the website cannot call the app');

	// Logging in in the browser: the login page's OIDC link asks the app.
	await inApp(`location.href = 'paperus-app:login?next=%2Fsettings'; done()`);
	const opened = await until(() => existsSync(OPENED) && readFileSync(OPENED, 'utf8').trim());
	const login = new URL(opened.split('\n').pop());
	assert.equal(login.pathname, '/app-login');
	// The browser, logged in there, confirms (as the page does).
	const browser = await fetch(`${LIBRARY}/api/auth/login`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(ADMIN)
	});
	const cookie = browser.headers.get('set-cookie').split(';')[0];
	const asked = Object.fromEntries(login.searchParams);
	const confirmed = await fetch(`${LIBRARY}/api/oauth/app-login`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Cookie: cookie },
		body: JSON.stringify({ ...asked, allow: true })
	});
	const { redirect } = await confirmed.json();
	// Back to the app's loopback address, which answers with a page.
	const back = await fetch(redirect);
	assert.match(await back.text(), /logged in to the paperus app/);
	await until(async () => (await shown()) === `${LIBRARY}/settings`);
	const me = await inApp(`fetch('/api/auth/me').then((r) => r.json()).then((me) => done(me.username))`);
	assert.equal(me, ADMIN.username);
	// The website's own cookie, out of its scripts' reach.
	assert.equal(await inApp(`done(document.cookie.includes('paperus_session'))`), false);
	console.log('ok: logged in in the browser');

	// "Open with": a second start with a PDF hands it to this one.
	const second = spawn(APP, [PDF], { stdio: 'ignore' });
	assert.equal(await new Promise((done) => second.on('exit', done)), 0);
	await until(async () => /\/items\/[0-9a-f-]+$/.test(await shown()));
	console.log('ok: a PDF opened with the app is added');

	// Offline: the copy kept while online (synced when a page loads), the
	// paper just opened whole, with its PDF.
	const paper = (await shown()).split('/').pop();
	const title = await until(() => inApp(`done(document.querySelector('h1')?.innerText)`));
	// Marked "Keep offline" on this device: the app keeps it, and says so.
	await inApp(`location.href = 'paperus-app://keep?kind=item&id=${paper}&on=true'; done()`);
	await until(() => inApp(`done((window.paperusApp.kept?.items ?? []).includes('${paper}'))`));
	console.log('ok: kept offline on this device, the page told');
	await sleep(1000);
	await inApp(`location.reload(); done()`);
	const copy = () => {
		const folder = join(DATA, 'offline');
		const [library] = existsSync(folder) ? readdirSync(folder) : [];
		const kept = library && join(folder, library);
		return (
			kept &&
			existsSync(join(kept, 'site', 'listing.json')) &&
			existsSync(join(kept, 'files')) &&
			readdirSync(join(kept, 'files')).length > 0 &&
			kept
		);
	};
	await until(copy, 60);
	await webdriver('DELETE', `/session/${sessionId}`).catch(() => {});
	// The network goes; the app, started again, opens the copy.
	await cut(proxy);
	({ sessionId } = await webdriver('POST', '/session', {
		capabilities: { alwaysMatch: { 'tauri:options': { application: APP } } }
	}));
	await until(async () => /^paperus-offline:\/\/localhost\//.test(await shown()), 30);
	await until(async () => (await pageText()).includes('Offline:'), 30);
	await until(async () => (await pageText()).includes(title), 30);
	console.log('ok: offline, the library as last synced');
	await inApp(`location.href = '/items/${paper}'; done()`);
	await until(async () => (await pageText()).includes(title), 30);
	const pdf = await inApp(
		`fetch('/api/items/${paper}').then((r) => r.json())` +
			`.then((item) => fetch('/api/files/' + item.files[0].id + '/content'))` +
			`.then((r) => r.arrayBuffer()).then((bytes) => done(new TextDecoder().decode(bytes.slice(0, 5))))`
	);
	assert.equal(pdf, '%PDF-');
	// Changes the app cannot keep say they need the server.
	const offlineChange = await inApp(
		`fetch('/api/tags', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})` +
			`.then((r) => done(r.status))`
	);
	assert.equal(offlineChange, 503);
	console.log('ok: a paper opened last, read offline with its PDF');

	// Annotated offline: kept at once, saved when the library is back.
	const file = await inApp(
		`fetch('/api/items/${paper}').then((r) => r.json()).then((item) => done(item.files[0].id))`
	);
	const mark = {
		kind: 'note',
		page_index: 0,
		position: { rects: [[10, 10, 20, 20]] },
		color: '#ffd400',
		comment: 'Written offline'
	};
	const made = await inApp(
		`fetch('/api/files/${file}/annotations', {method: 'POST',` +
			` headers: {'Content-Type': 'application/json'}, body: ${JSON.stringify(JSON.stringify(mark))}})` +
			`.then((r) => r.json()).then(done)`
	);
	assert.equal(made.comment, 'Written offline');
	const listed = await inApp(
		`fetch('/api/files/${file}/annotations').then((r) => r.json())` +
			`.then((found) => done(found.annotations.map((a) => a.comment)))`
	);
	assert.deepEqual(listed, ['Written offline']);
	proxy = await network();
	await inApp(`location.href = 'paperus-app://online'; done()`);
	await until(async () => (await shown()).startsWith(LIBRARY), 30);
	const saved = async () => {
		const found = await fetch(`${SERVER}/api/files/${file}/annotations`, {
			headers: { Cookie: cookie }
		}).then((r) => r.json());
		return found.annotations?.some((a) => a.id === made.id && a.comment === 'Written offline');
	};
	await until(saved, 60);
	console.log('ok: annotated offline, saved when the library was back');
} finally {
	await webdriver('DELETE', `/session/${sessionId}`).catch(() => {});
}
