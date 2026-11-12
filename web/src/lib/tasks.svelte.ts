import { resolve } from '$app/paths';
import { addItem } from '#lib/api/client.ts';
import { notify } from '#lib/toasts.svelte.ts';

/** Work the person started that goes on while they move around the
 * website, shown in the corner with its progress (TaskTray): getting PDFs
 * with the browser extension, adding someone's papers. (Closing the tab
 * ends what runs here; the extension's goes on.) */

export interface Task {
	id: number;
	title: string;
	done: number;
	total: number;
	failed: number;
	finished: boolean;
	/** What came of it, once finished. */
	note?: string;
	link?: { href: string; label: string };
}

export const tasks = $state<{ list: Task[] }>({ list: [] });
let nextId = 1;

export function startTask(title: string, total: number, link?: Task['link']): number {
	const id = nextId++;
	tasks.list.push({ id, title, done: 0, total, failed: 0, finished: false, link });
	return id;
}

function task(id: number | null): Task | undefined {
	return tasks.list.find((t) => t.id === id);
}

export function finishTask(id: number, note?: string): void {
	const found = task(id);
	if (!found) return;
	found.finished = true;
	found.note = note;
}

export function dismissTask(id: number): void {
	tasks.list = tasks.list.filter((t) => t.id !== id);
}

// The browser extension's progress on getting PDFs (Manage → Missing), on
// whichever page is open: its page script passes it on to the window.
let fromExtension: number | null = null;
let heard = 0;
/** No word from the extension this long: it is not there, or not listening. */
const SILENCE_MS = 3 * 60_000;

export function startExtensionTask(total: number): void {
	const running = task(fromExtension);
	if (running && !running.finished) finishTask(running.id, 'Replaced by a new request.');
	fromExtension = startTask(
		`Getting ${total} ${total === 1 ? 'PDF' : 'PDFs'} with the extension`,
		total,
		{
			href: resolve('/manage/missing'),
			label: 'Missing'
		}
	);
	heard = Date.now();
}

if (typeof window !== 'undefined') {
	window.addEventListener('message', (event) => {
		if (event.source !== window || event.origin !== location.origin) return;
		const data = event.data as {
			type?: string;
			done?: number;
			total?: number;
			ok?: boolean;
			saved?: number;
			/** What it waits for (a check for robots in a tab it opened). */
			note?: string;
		} | null;
		const running = task(fromExtension);
		if (!running || running.finished) return;
		if (data?.type === 'paperus:getPdfsProgress') {
			heard = Date.now();
			running.done = data.done ?? running.done;
			running.total = data.total ?? running.total;
			if (data.ok === false) running.failed += 1;
			running.note = data.note;
		} else if (data?.type === 'paperus:getPdfsDone') {
			const saved = data.saved ?? 0;
			finishTask(
				running.id,
				`${saved} saved${running.failed ? `, ${running.failed} not (see Missing for why)` : ''}.`
			);
		}
	});
	setInterval(() => {
		const running = task(fromExtension);
		if (running && !running.finished && Date.now() - heard > SILENCE_MS)
			finishTask(
				running.id,
				'No word from the browser extension for three minutes. Is it installed, up to date, and connected to this paperus?'
			);
	}, 15_000);
}

/** Add papers by their DOIs, a few at a time, as a task in the corner:
 * the dialog that started it may close, the person may move on. */
export async function addByDoi(
	title: string,
	dois: string[],
	libraryId: string | null,
	added?: () => void
): Promise<void> {
	const id = startTask(title, dois.length);
	const queue = [...dois];
	let failed = 0;
	const worker = async () => {
		for (let doi = queue.shift(); doi; doi = queue.shift()) {
			const { error } = await addItem({ body: { doi, library_id: libraryId } });
			const running = task(id);
			if (error) failed += 1;
			if (running) {
				running.done += 1;
				running.failed = failed;
			}
		}
	};
	await Promise.all(Array.from({ length: Math.min(3, dois.length) }, worker));
	const ok = dois.length - failed;
	finishTask(
		id,
		failed
			? `${ok} added; ${failed} could not be added (their DOI was not found).`
			: `${ok} added. Their details, open-access copies and authors are looked up now.`
	);
	if (!task(id)) notify({ kind: failed ? 'warning' : 'success', title: `${ok} papers added` });
	added?.();
}
