// The demo's server (e2e/demo/README.md): answers the website's API calls from
// the recording (recording/index.json, made by e2e/demo/record.ts), and
// serves the website's entry for its pages. Changes are not kept.

const BASE = new URL('./', self.registration.scope).pathname.replace(/\/$/, '');
const REFUSED = 'This is the demo: changes are not kept. Install paperus to try them.';
// What opening a paper writes by itself (seen, where one stopped): taken
// without a word, and forgotten.
const QUIET = /^\/api\/items\/[^/]+\/(viewed|reading)$/;

/** Method, path and sorted query, as the recorder writes them. */
function key(method, url, path) {
	const query = [...url.searchParams].sort(([a], [b]) => a.localeCompare(b));
	const search = new URLSearchParams(query).toString();
	return `${method} ${path}${search ? `?${search}` : ''}`;
}

let loaded;
function recording() {
	loaded ??= fetch(`${BASE}/recording/index.json`)
		.then((response) => response.json())
		.then(({ answers, searches }) => {
			// Without its query: the first answer recorded for the path.
			const byPath = {};
			for (const [name, answer] of Object.entries(answers)) {
				const [method, rest] = name.split(' ');
				byPath[`${method} ${rest.split('?')[0]}`] ??= answer;
			}
			return { answers, searches, byPath };
		});
	return loaded;
}

function json(status, body) {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

async function replay(answer) {
	const stored = await fetch(`${BASE}/recording/${answer.file}`);
	const body = await stored.arrayBuffer();
	const headers = new Headers(answer.headers);
	headers.set('Content-Length', String(body.byteLength));
	const empty = answer.status === 204 || answer.status === 304;
	return new Response(empty ? null : body, { status: answer.status, headers });
}

async function search(url, { searches }) {
	const words = (url.searchParams.get('q') ?? '').toLowerCase().match(/\p{L}+/gu) ?? [];
	// One word: its own results; several: those of the first one found.
	const file = searches[words.join(' ')] ?? words.map((word) => searches[word]).find(Boolean);
	if (!file) return json(200, []);
	return replay({ status: 200, headers: { 'content-type': 'application/json' }, file });
}

async function answer(request, url, path) {
	const recorded = await recording();
	const method = request.method;
	if (method === 'GET' && path === '/api/search') return search(url, recorded);
	const found =
		recorded.answers[key(method, url, path)] ??
		(method === 'GET' ? recorded.byPath[`GET ${path}`] : undefined);
	if (found) return replay(found);
	// Logging in again after logging out: as before.
	if (method === 'POST' && path === '/api/auth/login') {
		const me = recorded.answers['GET /api/auth/me'];
		if (me) return replay(me);
	}
	if (method === 'GET') return json(404, { detail: 'Not in the demo.' });
	if (QUIET.test(path)) return new Response(null, { status: 204 });
	return json(403, { detail: REFUSED });
}

self.addEventListener('install', (event) => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
	const url = new URL(event.request.url);
	if (url.origin !== location.origin) return;
	// The website asks /api/… at the server's root; links may carry the base.
	const path = url.pathname.startsWith(`${BASE}/api/`)
		? url.pathname.slice(BASE.length)
		: url.pathname;
	if (/^\/(api|mcp)(\/|$)/.test(path)) {
		event.respondWith(answer(event.request, url, path));
		return;
	}
	// A page of the website (no file name): its entry.
	const page = url.pathname.startsWith(`${BASE}/`) && !/\.[a-z0-9]+$/i.test(url.pathname);
	if (event.request.mode === 'navigate' && page) {
		event.respondWith(fetch(`${BASE}/200.html`));
	}
});
