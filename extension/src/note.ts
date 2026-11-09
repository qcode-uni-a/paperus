/** Why saving went wrong, where the page could not show it (a browser's own
 * PDF viewer lets no extension in); and, if access to the PDF's site is
 * what is missing, a button that asks for it (only an extension page may,
 * and only on a click) and saves again. */

export {};

const $ = (id: string) => document.getElementById(id)!;
const query = new URLSearchParams(location.search);
const site = query.get('site');
const tabId = Number(query.get('tab'));

$('text').textContent = query.get('text') ?? '';
$('allow').hidden = !site;

$('allow').addEventListener('click', async () => {
	// First, while the click counts as the person's.
	const asking = chrome.permissions.request({ origins: [site!] });
	if (!(await asking)) {
		$('message').textContent = 'Without access to the site the PDF cannot be fetched.';
		return;
	}
	$('message').textContent = 'Saving…';
	const result = await chrome.runtime.sendMessage({ type: 'saveAgain', tabId });
	if (result?.ok) window.close();
	else $('message').textContent = result?.text ?? 'Not saved.';
});

$('close').addEventListener('click', () => window.close());
