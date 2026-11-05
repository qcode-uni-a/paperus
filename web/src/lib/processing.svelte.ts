import { resolve } from '$app/paths';
import { getImport, listItems } from '#lib/api/client.ts';
import { notify } from '#lib/toasts.svelte.ts';

/** Background work the person started, followed while they use the site:
 * a message when uploaded papers are read, or an import is done. (Closing
 * the tab ends the watching; the work itself goes on.) */

const EVERY = 4000;
/** From this many new papers on, they get a "being read" message. */
export const MANY = 6;

/** Follow uploaded papers until their text is read and details looked up. */
export function watchUploads(itemIds: string[]): void {
	if (itemIds.length < MANY) return;
	notify(
		{
			kind: 'info',
			title: `${itemIds.length} papers uploaded`,
			text: 'They are being read now (text and details); you get a message when they are ready.'
		},
		10
	);
	const check = async () => {
		const pending: string[] = [];
		for (let start = 0; start < itemIds.length; start += 200) {
			const ids = itemIds.slice(start, start + 200);
			const { data } = await listItems({ query: { id: ids, limit: 200 } });
			if (!data) {
				setTimeout(check, EVERY * 2); // try again later
				return;
			}
			pending.push(...data.filter((item) => item.processing).map((item) => item.id));
		}
		if (pending.length) {
			setTimeout(check, EVERY);
			return;
		}
		const { data: unsorted } = await listItems({
			query: { id: itemIds.slice(0, 200), unsorted: true, limit: 200 }
		});
		const missing = unsorted?.length ?? 0;
		notify(
			{
				kind: 'success',
				title: `${itemIds.length} papers are ready`,
				text: missing
					? `Text read and searchable. ${missing} had no DOI or arXiv ID: their details need a hand.`
					: 'Text read, details found, all searchable.',
				link: missing
					? { href: resolve('/manage/unsorted'), label: 'Open Unsorted' }
					: { href: resolve('/recent'), label: 'Show them' }
			},
			0
		);
	};
	setTimeout(check, EVERY);
}

const watchedImports = new Set<string>();

/** Follow an import until it is done or failed. */
export function watchImport(importId: string, filename: string): void {
	if (watchedImports.has(importId)) return;
	watchedImports.add(importId);
	const check = async () => {
		const { data } = await getImport({ path: { import_id: importId } });
		if (!data || data.status === 'waiting' || data.status === 'running') {
			setTimeout(check, EVERY);
			return;
		}
		watchedImports.delete(importId);
		const report = (data.report ?? {}) as Record<string, number | string[]>;
		const missing = (report.missing_files as string[] | undefined)?.length ?? 0;
		const problems = (report.problems as string[] | undefined)?.length ?? 0;
		notify(
			data.status === 'done'
				? {
						kind: problems || missing ? 'warning' : 'success',
						title: `Import of ${filename} is done`,
						text:
							`${report.added ?? 0} papers added, ${report.found ?? 0} already here` +
							(missing ? `; ${missing} files were not in the export` : '') +
							(problems ? `; ${problems} problems` : '') +
							'.',
						link: { href: resolve('/import'), label: 'See the report' }
					}
				: {
						kind: 'warning',
						title: `Import of ${filename} failed`,
						text: data.error ?? undefined,
						link: { href: resolve('/import'), label: 'Details' }
					},
			0
		);
	};
	setTimeout(check, EVERY);
}
