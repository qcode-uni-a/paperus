import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { test, type Page, type Response } from '@playwright/test';
import { PAPERS, seed } from './seed.ts';

/** Records the demo (README.md here): the website, as Mira, goes through
 * every page it can reach, on a computer and on a phone, and each answer
 * from the API is kept for the demo's service worker; and a search for
 * the library's words (titles, the lecture notes, the scans' frequent ones
 * from words.py), so that searching works there for single words (by
 * words, as here without the ML service). */

const OUT = process.env.PAPERUS_DEMO_OUT ?? '../site/demo/recording';
const PDFS = process.env.PAPERUS_DEMO_PDFS;
const PAPERS_FOLDER = process.env.PAPERUS_DEMO_PAPERS;
/** The scans' words worth searching for (words.py). */
const WORDS = process.env.PAPERUS_DEMO_WORDS;
/** What the recorded answers show as the server's address. */
const SHOWN = 'https://paperus.example.org';
/** The answer headers the website reads. */
const HEADERS = ['content-type', 'etag', 'x-total-count', 'x-search-mode', 'content-disposition'];
/** Not visited: logging in and out, the first start, the administration. */
const SKIP = /^\/(login|logout|setup|admin|app-login|oauth)(\/|$)/;
const PAGES = 300;

type Answer = { status: number; headers: Record<string, string>; file: string };

/** Method, path and sorted query: how the service worker finds an answer. */
export function key(method: string, url: URL): string {
	const query = [...url.searchParams].sort(([a], [b]) => a.localeCompare(b));
	const search = new URLSearchParams(query).toString();
	return `${method} ${url.pathname}${search ? `?${search}` : ''}`;
}

class Recording {
	answers: Record<string, Answer> = {};
	searches: Record<string, string> = {};
	waiting: Promise<void>[] = [];

	constructor(readonly origin: string) {
		rmSync(OUT, { recursive: true, force: true });
		mkdirSync(join(OUT, 'r'), { recursive: true });
	}

	store(body: Buffer, type: string): string {
		const text = /json|text|html/.test(type);
		const kept = text ? Buffer.from(body.toString('utf8').replaceAll(this.origin, SHOWN)) : body;
		const file = `r/${createHash('sha1').update(kept).digest('hex').slice(0, 20)}`;
		writeFileSync(join(OUT, file), kept);
		return file;
	}

	watch(page: Page): void {
		page.on('response', (response) => this.waiting.push(this.take(page, response)));
	}

	async take(page: Page, response: Response): Promise<void> {
		const url = new URL(response.url());
		if (url.origin !== this.origin || !/^\/(api|mcp)(\/|$)/.test(url.pathname)) return;
		const request = response.request();
		let status = response.status();
		let body: Buffer;
		try {
			// A PDF read in parts: the whole file instead.
			if (status === 206) {
				const whole = await page.request.get(url.toString());
				status = whole.status();
				body = await whole.body();
			} else {
				body = await response.body();
			}
		} catch {
			return; // a redirect, or the page went on
		}
		const all = await response.allHeaders();
		const headers = Object.fromEntries(
			HEADERS.filter((name) => all[name]).map((name) => [name, all[name]])
		);
		this.answers[key(request.method(), url)] = {
			status,
			headers,
			file: this.store(body, headers['content-type'] ?? '')
		};
	}

	async save(): Promise<void> {
		await Promise.all(this.waiting);
		writeFileSync(
			join(OUT, 'index.json'),
			JSON.stringify({ answers: this.answers, searches: this.searches })
		);
	}
}

/** Visits ``start`` and every page linked from there (up to ``PAGES``). */
async function crawl(page: Page, start: string[]): Promise<string[]> {
	const seen = new Set(start);
	const queue = [...start];
	for (let i = 0; i < queue.length && i < PAGES; i++) {
		await page.goto(queue[i]);
		await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
		const links = await page.evaluate(() =>
			[...document.querySelectorAll('a[href]')].map((a) => (a as HTMLAnchorElement).href)
		);
		for (const link of links) {
			const url = new URL(link);
			const path = url.pathname + url.search;
			if (url.origin !== new URL(page.url()).origin || /^\/(api|mcp)\//.test(url.pathname))
				continue;
			if (SKIP.test(url.pathname) || seen.has(path)) continue;
			seen.add(path);
			queue.push(path);
		}
	}
	return queue;
}

/** The library's words, for the searches. */
function words(ids: Record<string, string>): string[] {
	const text = [
		...PAPERS.flatMap(([title, authors, , journal, tags]) => [
			title,
			journal,
			...tags,
			...authors.flat()
		]),
		...Object.keys(ids),
		PDFS
			? readFileSync('demo/oscillator.tex', 'utf8').replace(/\\[a-zA-Z]+|\$[^$]*\$|%.*$/gm, ' ')
			: ''
	].join(' ');
	const found = text.toLowerCase().match(/\p{L}{3,}/gu) ?? [];
	const scans: string[] = WORDS ? JSON.parse(readFileSync(WORDS, 'utf8')) : [];
	return [...new Set([...found, ...scans])];
}

test('record the demo', async ({ page, browser, baseURL }) => {
	test.setTimeout(20 * 60_000);
	const { page: mira, ids } = await seed(page, browser, {
		pdfs: PDFS,
		papers: PAPERS_FOLDER,
		options: { viewport: { width: 1440, height: 900 } }
	});
	const recording = new Recording(new URL(baseURL ?? '').origin);
	recording.watch(mira);

	// On a computer: everything linked from the menu and the pages.
	const visited = await crawl(mira, [
		'/',
		'/recent',
		'/favourites',
		'/collections',
		'/notes',
		'/archive',
		'/trash',
		'/settings',
		'/settings/extension',
		'/manage/authors',
		'/manage/collections',
		'/manage/tags',
		'/manage/groups',
		'/manage/duplicates',
		'/manage/unsorted',
		'/manage/missing'
	]);

	// On a phone: the papers in fluent mode, read to the end.
	await mira.setViewportSize({ width: 390, height: 844 });
	for (const path of ['/', ...visited.filter((path) => path.startsWith('/items/'))]) {
		await mira.goto(path);
		await mira.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
		for (let i = 0; i < 12; i++) {
			await mira.mouse.wheel(0, 1200);
			await mira.waitForTimeout(150);
		}
		await mira.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
	}

	// The searches: the website's own once, for how it asks; then each word.
	await mira.setViewportSize({ width: 1440, height: 900 });
	const asked = mira.waitForRequest((request) => new URL(request.url()).pathname === '/api/search');
	await mira.goto('/?q=quantum');
	const query = new URL((await asked).url());
	for (const word of words(ids)) {
		query.searchParams.set('q', word);
		const found = await mira.request.get(query.toString());
		const body = await found.body();
		if (!found.ok() || body.toString() === '[]') continue;
		recording.searches[word] = recording.store(body, 'application/json');
	}
	await recording.save();
});
