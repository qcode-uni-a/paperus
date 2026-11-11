/** On Google Scholar's results: the small paperus button after each
 * paper's title, as on arXiv (mark.ts). Which ones one has: by the DOI or
 * arXiv ID in the result's link (links.ts); a result without one gets the
 * button all the same. A click saves the paper from its page, opened out
 * of sight, with its PDF. */

import icon from '../icons/icon-32.png';
import { paperOfLink } from './links';
import { paperusButton } from './mark';
import { settings } from './paperus';

async function start(): Promise<void> {
	if (!(await settings())) return;
	const links = [...document.querySelectorAll<HTMLAnchorElement>('h3.gs_rt a[href]')].filter(
		(link) => /^https?:/.test(link.href)
	);
	if (!links.length) return;
	const marked = links.map((link) => {
		const mark = paperusButton(icon, () =>
			chrome.runtime.sendMessage({ type: 'saveLink', url: link.href })
		);
		link.after(mark.host);
		return { key: paperOfLink(link.href), mark };
	});
	const keys = [...new Set(marked.map((m) => m.key).filter((key): key is string => !!key))];
	if (!keys.length) return;
	const known: Record<string, string | null> =
		(await chrome.runtime.sendMessage({ type: 'lookupKeys', keys })) ?? {};
	const server = (await settings())?.server;
	for (const { key, mark } of marked) {
		const item = key ? known[key] : null;
		if (item && server) mark.set('have', new URL(`/items/${item}`, server).href);
	}
}

void start();
