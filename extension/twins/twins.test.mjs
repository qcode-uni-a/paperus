// Each page twin (pages/NAME/page.html, made by make.mjs) read as the
// extension reads a page in its tab (readPage, in jsdom at the page's own
// address), against what pages/NAME/expect.json expects: "mode" (the
// popup's choice: "paper" or "list") and any of readPage's fields; pageIds
// (the IDs alone) finds the same DOI and arXiv ID.
//
// A twin with a "chain" also has its PDF fetched as the extension does in
// the page (fetchPdf), the network played by the chain: what each address
// answers a script's fetch ("fetch") and a page load ("load", for tests in
// a browser). An answer is "pdf", "robot-check", {"redirect": address},
// {"html": …} (with "status"); another site than the page's refuses a
// fetch unless its step says "cors": true, as browsers do. "expectPdf"
// says how it ends: {"pdf": true}, {"next": address} (left to the
// extension) or {"error": …, "at": address}.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { JSDOM } from 'jsdom';
import { extrasOf } from '../src/extras.ts';
import { fetchPdf, namesPaper, pageIds, pageLinks, readPage } from '../src/page.ts';

const pages = new URL('pages/', import.meta.url);
const PDF = '%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n';
const ROBOT_CHECK =
	'<!doctype html><title>Security verification</title><form id="challenge-form"></form>';
const NOT_FOUND = { status: 404, html: '<!doctype html><title>Not found</title>' };

/** A fetch that plays the chain for a page at ``origin``. */
function network(chain, origin) {
	return async (input) => {
		let url = new URL(String(input)).href;
		for (let hops = 0; hops < 10; hops++) {
			const step = chain[url] ?? {};
			const answer = step.fetch ?? NOT_FOUND;
			if (answer.redirect) {
				url = new URL(answer.redirect, url).href;
				continue;
			}
			if (new URL(url).origin !== origin && !step.cors)
				throw new TypeError('NetworkError when attempting to fetch resource.');
			const pdf = answer === 'pdf';
			const response = new Response(
				pdf ? PDF : answer === 'robot-check' ? ROBOT_CHECK : answer.html,
				{
					status: answer.status ?? 200,
					headers: { 'content-type': pdf ? 'application/pdf' : 'text/html; charset=utf-8' }
				}
			);
			// Where it ended up, as a browser's answer says.
			Object.defineProperty(response, 'url', { value: url });
			return response;
		}
		throw new TypeError('Too many redirects.');
	};
}

for (const name of readdirSync(pages).sort()) {
	const folder = new URL(`${name}/`, pages);
	const spec = JSON.parse(readFileSync(new URL('expect.json', folder), 'utf8'));
	/** The twin, open as in a tab: what the page's functions see. */
	const open = () => {
		const { window } = new JSDOM(readFileSync(new URL('page.html', folder), 'utf8'), {
			url: spec.url
		});
		Object.assign(globalThis, { document: window.document, location: window.location, Node: window.Node });
	};

	test(`${name}: ${spec.about}`, async () => {
		open();
		const page = await readPage();
		for (const [key, expected] of Object.entries(spec.expect)) {
			const found = key === 'mode' ? (namesPaper(page, spec.url) ? 'paper' : 'list') : page[key];
			assert.deepEqual(found, expected, key);
		}
		// What marks a paper one has when its page opens: the same IDs.
		const ids = pageIds();
		assert.equal(ids.doi, page.doi, 'pageIds: doi');
		assert.equal(ids.arxiv, page.arxiv, 'pageIds: arxiv');
	});

	if (spec.extras)
		test(`${name}: its supplementary files and links, each as what it is`, async () => {
			open();
			const page = await readPage();
			assert.deepEqual(extrasOf(pageLinks(), [spec.url, page.pdfUrl]), spec.extras);
		});

	if (spec.chain)
		test(`${name}: its PDF, fetched in the page`, async (t) => {
			open();
			const page = await readPage();
			t.mock.method(globalThis, 'fetch', network(spec.chain, new URL(spec.url).origin));
			const pdf = await fetchPdf(page.pdfUrl, 10_000_000);
			if (spec.expectPdf.pdf) {
				assert.ok('base64' in pdf, `no PDF: ${JSON.stringify(pdf).slice(0, 300)}`);
				assert.equal(atob(pdf.base64), PDF);
				return;
			}
			for (const [key, expected] of Object.entries(spec.expectPdf)) assert.equal(pdf[key], expected, key);
		});
}

test('extrasOf: published reviews on a page of their own, and what files are', () => {
	const at = 'https://journals.plosish.org/physics/article?id=10.5555/x.1';
	const review = 'https://journals.plosish.org/physics/article/peerReview?id=10.5555/x.1';
	const link = (url, text, heading = '', context = '') => ({ url, text, heading, context, abstract: false });
	const extras = extrasOf(
		[
			link(review, 'Peer Review History'),
			link('https://journals.plosish.org/physics/s/peer-review-policy', 'Peer review policy'),
			link(`${at}#peer-review`, 'Peer review'),
			link('https://example.org/files/x/mmc2.xlsx', 'Source data', 'Supplementary material'),
			link('https://example.org/files/x/mmc3.pdf', 'Reviewer reports', 'Supplementary material'),
			link('https://example.org/files/x/figures.pdf', 'Link', 'Supplementary material')
		],
		[at]
	);
	assert.deepEqual(extras.links, [{ url: review, kind: 'peer_review' }]);
	assert.deepEqual(
		extras.files.map((f) => [f.name, f.role]),
		[
			['Source data.xlsx', 'data'],
			['Reviewer reports.pdf', 'peer_review'],
			['figures.pdf', 'supplementary']
		]
	);
});
