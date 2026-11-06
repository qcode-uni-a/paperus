/** Asks the browser for access to publisher sites (only an extension page
 * may, and only on a click), then lets the background get the PDFs. */

export {};

const $ = (id: string) => document.getElementById(id)!;

const { getPdfs } = (await chrome.storage.session.get('getPdfs')) as {
	getPdfs?: { papers: unknown[] };
};
const count = getPdfs?.papers.length ?? 0;
$('count').textContent = count === 1 ? 'this paper' : `these ${count} papers`;

$('allow').addEventListener('click', async () => {
	// First, while the click counts as the person's.
	const asking = chrome.permissions.request({ origins: ['https://*/*', 'http://*/*'] });
	if (!(await asking)) {
		$('message').textContent = 'Without access to the publishers’ sites the PDFs cannot be fetched.';
		return;
	}
	await chrome.runtime.sendMessage({ type: 'getPdfsAllowed' });
	window.close();
});
