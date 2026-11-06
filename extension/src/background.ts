/** One click on the toolbar button saves the page's paper to paperus, with
 * its PDF (fetched in the page, with the reader's own access). */
import { fetchPdf, type PageInfo, readPage, showNote } from './page';
import { type Api, call, PaperusError, saveSettings, settings } from './paperus';

const MAX_BYTES = 512 * 1024 * 1024;

chrome.action.onClicked.addListener(async (tab) => {
	if (!(await settings())) {
		await chrome.runtime.openOptionsPage();
		return;
	}
	if (tab.id === undefined) return;
	await saveTab(tab.id);
});

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
	const handlers: Record<string, () => Promise<unknown>> = {
		lookup: () => lookup(message.ids),
		saveArxiv: () => saveArxiv(message.id),
		connect: () => connect(message.server)
	};
	const handler = handlers[message?.type];
	if (!handler) return false;
	handler()
		.then(reply)
		.catch((error) => reply({ ok: false, text: String(error.message ?? error) }));
	return true; // the reply comes later
});

async function badge(tabId: number, text: string, color = '#2338a8'): Promise<void> {
	await chrome.action.setBadgeBackgroundColor({ tabId, color });
	await chrome.action.setBadgeText({ tabId, text });
}

async function inPage<A extends unknown[], R>(
	tabId: number,
	func: (...args: A) => R,
	...args: A
): Promise<Awaited<R>> {
	const [result] = await chrome.scripting.executeScript({ target: { tabId }, func, args });
	return result.result as Awaited<R>;
}

async function saveTab(tabId: number): Promise<void> {
	await badge(tabId, '…');
	try {
		const page = await inPage(tabId, readPage);
		const pdf = page.arxiv
			? await arxivPdf(page.arxiv)
			: page.isPdf || page.pdfUrl
				? await inPage(tabId, fetchPdf, page.isPdf ? page.url : page.pdfUrl!, MAX_BYTES)
				: { error: 'The page links no PDF.' };
		const result = await save(page, pdf);
		await badge(tabId, '✓', '#1e7a3e');
		await inPage(tabId, showNote, result.text, result.link, true);
	} catch (error) {
		const text = error instanceof PaperusError ? error.message : `Not saved: ${String(error)}`;
		await badge(tabId, '!', '#c0392b');
		await inPage(tabId, showNote, text, null, false).catch(() => undefined);
	}
}

/** The paper (found or added) and its PDF; what happened, in words. */
async function save(
	page: Pick<PageInfo, 'doi' | 'arxiv' | 'title' | 'url'> & Partial<PageInfo>,
	pdf: { base64: string; size: number } | { error: string }
): Promise<{ ok: true; text: string; link: string }> {
	const config = await settings();
	const owner = config?.owner ? { library_id: config.owner } : {};
	const doi = page.doi ?? (page.arxiv ? `10.48550/arXiv.${page.arxiv}` : null);
	const addItem = (json: Api.ItemIn) =>
		call<Api.AddItemData, Api.AddItemResponse>('/api/items', { method: 'POST', json });
	let added = doi ? await addItem({ doi, ...owner }).catch(() => null) : null;
	if (!added || added.status >= 400) {
		if (!page.title) throw new PaperusError('This page names no paper (no DOI, arXiv ID or title).');
		added = await addItem({ metadata: csl(page), identifiers: identifiers(page), ...owner });
	}
	const item = added.data;
	const known = added.status === 200;
	let fileNote: string;
	if ('error' in pdf) {
		fileNote = ` ${pdf.error}`;
	} else {
		const bytes = Uint8Array.from(atob(pdf.base64), (c) => c.charCodeAt(0));
		const digest = await crypto.subtle.digest('SHA-256', bytes);
		const sha = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
		const existing = await call<Api.FindUploadData>('/api/uploads/{sha256}', { path: { sha256: sha } });
		if (existing.status === 200) {
			fileNote = ' The PDF is there already.';
		} else {
			const form = new FormData();
			form.append('upload', new Blob([bytes], { type: 'application/pdf' }), filename(page));
			await call<Api.UploadToItemData>('/api/items/{item_id}/files', {
				method: 'POST',
				path: { item_id: item.id },
				form
			});
			fileNote = ' With its PDF.';
		}
	}
	const config2 = await settings();
	return {
		ok: true,
		text: `${known ? 'Already in paperus' : 'Saved to paperus'}: “${item.title}”.${fileNote}`,
		link: new URL(`/items/${item.id}`, config2!.server).href
	};
}

function identifiers(page: Partial<PageInfo>): Api.IdentifierIn[] {
	const found: Api.IdentifierIn[] = [];
	if (page.doi) found.push({ scheme: 'doi', value: page.doi });
	if (page.arxiv) found.push({ scheme: 'arxiv', value: page.arxiv });
	return found;
}

/** CSL-JSON from the page's tags, for papers without a DOI. */
function csl(page: Partial<PageInfo>): Record<string, unknown> {
	const year = page.date?.match(/\d{4}/)?.[0];
	const authors = (page.authors ?? []).map((name) => {
		const [family, given] = name.includes(',')
			? name.split(',').map((part) => part.trim())
			: [name.split(' ').at(-1)!, name.split(' ').slice(0, -1).join(' ')];
		return given ? { family, given } : { literal: name };
	});
	const pages = [page.firstPage, page.lastPage].filter(Boolean).join('-');
	return Object.fromEntries(
		Object.entries({
			type: page.journal ? 'article-journal' : 'webpage',
			title: page.title,
			author: authors.length ? authors : undefined,
			issued: year ? { 'date-parts': [[Number(year)]] } : undefined,
			'container-title': page.journal,
			volume: page.volume,
			issue: page.issue,
			page: pages || undefined,
			publisher: page.publisher,
			abstract: page.abstract,
			URL: page.url
		}).filter(([, value]) => value !== undefined && value !== null && value !== '')
	);
}

function filename(page: Partial<PageInfo>): string {
	const last = new URL(page.pdfUrl ?? page.url ?? 'https://x/paper.pdf').pathname.split('/').pop();
	const name = last && /\.pdf$/i.test(last) ? last : `${(page.arxiv ?? page.title ?? 'paper').slice(0, 80)}.pdf`;
	return name.replace(/[\\/:*?"<>|]+/g, ' ');
}

/** arXiv's PDFs are open: fetched here directly. */
async function arxivPdf(id: string): Promise<{ base64: string; size: number } | { error: string }> {
	try {
		const response = await fetch(`https://arxiv.org/pdf/${id}`);
		const bytes = new Uint8Array(await response.arrayBuffer());
		if (!response.ok || String.fromCharCode(...bytes.slice(0, 5)) !== '%PDF-') {
			return { error: 'arXiv gave no PDF.' };
		}
		let binary = '';
		for (let i = 0; i < bytes.length; i += 0x8000) {
			binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
		}
		return { base64: btoa(binary), size: bytes.length };
	} catch (error) {
		return { error: `arXiv could not be reached: ${String(error)}` };
	}
}

/** For the buttons on arXiv: which of these papers one has. */
async function lookup(ids: string[]): Promise<Record<string, string | null>> {
	if (!(await settings()) || ids.length === 0) return {};
	const { data } = await call<Api.LookupItemsData, Api.LookupItemsResponse>('/api/items/lookup', {
		query: { id: ids.map((id) => `arxiv:${id}`) }
	});
	return Object.fromEntries(ids.map((id) => [id, data[`arxiv:${id}`] ?? null]));
}

async function saveArxiv(id: string): Promise<{ ok: boolean; text: string; link?: string }> {
	if (!(await settings())) {
		await chrome.runtime.openOptionsPage();
		return { ok: false, text: 'Connect the extension to paperus first.' };
	}
	return save(
		{ doi: null, arxiv: id, title: null, url: `https://arxiv.org/abs/${id}` },
		await arxivPdf(id)
	);
}

/** Connect: paperus's page /settings/extension makes a token after the
 * person's click and puts it on the page, where this picks it up. */
async function connect(server: string): Promise<{ ok: boolean; text: string }> {
	const base = new URL(server).origin;
	const tab = await chrome.tabs.create({ url: `${base}/settings/extension` });
	const tabId = tab.id!;
	for (let i = 0; i < 300; i++) {
		await new Promise((done) => setTimeout(done, 1000));
		const token = await inPage(tabId, () =>
			document.querySelector<HTMLElement>('[data-paperus-extension-token]')?.dataset
				.paperusExtensionToken ?? null
		).catch(() => null);
		if (token) {
			await saveSettings({ server: base, token });
			const { data } = await call<Api.ListLibrariesData, Api.ListLibrariesResponse>('/api/libraries');
			const writable = (data ?? []).filter((l) => l.writable);
			await inPage(tabId, () => {
				const mark = document.querySelector<HTMLElement>('[data-paperus-extension-token]');
				if (mark) mark.dataset.paperusExtensionConnected = 'yes';
			});
			return { ok: true, text: `Connected. ${writable.length} owners to choose from.` };
		}
	}
	return { ok: false, text: 'No connection: the paperus page was not confirmed within 5 minutes.' };
}
