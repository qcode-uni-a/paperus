import { startExtensionTask } from '#lib/tasks.svelte.ts';

/** The paperus browser extension, if installed and connected to this
 * paperus: its page script marks the page with what it can do
 * (``data-paperus-extension-features``), possibly after the page loaded. */
export const extension = $state({ getPdfs: false });

if (typeof document !== 'undefined') {
	const root = document.documentElement;
	const check = () => {
		extension.getPdfs = (root.dataset.paperusExtensionFeatures ?? '')
			.split(' ')
			.includes('get-pdfs');
	};
	check();
	new MutationObserver(check).observe(root, {
		attributes: true,
		attributeFilter: ['data-paperus-extension-features']
	});
}

/** A paper for the extension to get the PDF of: its publisher's page,
 * opened with the person's own access; into this version, if given. */
export interface Wanted {
	item_id: string;
	version_id: string | null;
	title: string;
	url: string;
	/** Open copies that refused the server: the browser may get them. */
	copies: string[];
}

/** Ask the extension for these papers' PDFs; its progress shows in the
 * corner (a task), ``done`` when it is through. */
export function getPdfsWithExtension(wanted: Wanted[], done?: () => void): void {
	if (!wanted.length) return;
	startExtensionTask(wanted.length);
	if (done) {
		const listen = (event: MessageEvent) => {
			if (event.source !== window || event.origin !== location.origin) return;
			if (event.data?.type !== 'paperus:getPdfsDone') return;
			window.removeEventListener('message', listen);
			done();
		};
		window.addEventListener('message', listen);
	}
	window.postMessage({ type: 'paperus:get-pdfs', papers: wanted }, location.origin);
}
