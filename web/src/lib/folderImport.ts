/** A folder imported from the browser file by file (a Zotero export with
 * its files, too large to zip or to upload at once; server:
 * ``api/imports.py``). Each request is one file, so no limit on uploads in
 * between stops it; choosing the same folder again after an interruption
 * sends only what has not arrived. */
import { apiHref, folderFiles, startFolderImport } from '#lib/api/client.ts';
import type { ImportOut } from '#lib/api/generated/types.gen.ts';

/** Files sent at once. */
const AT_ONCE = 3;
/** Tries per file before giving up (the person can go on later). */
const TRIES = 3;

type Entry = { file: File; path: string };

/** The folder's name and its files, by their paths inside it (hidden
 * files of the system left out). */
function entries(chosen: File[]): { name: string; files: Entry[] } {
	const relative = (file: File) => file.webkitRelativePath || file.name;
	const name = relative(chosen[0]).split('/')[0] || 'folder';
	const files = chosen
		.map((file) => ({ file, path: relative(file).split('/').slice(1).join('/') || file.name }))
		.filter(
			({ path }) => !path.split('/').some((part) => part.startsWith('.') || part === '__MACOSX')
		);
	return { name, files };
}

function remembered(name: string, files: Entry[]): string {
	const bytes = files.reduce((sum, { file }) => sum + file.size, 0);
	return `paperus-folder-import:${name}:${files.length}:${bytes}`;
}

function recall(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

function keep(key: string, id: string | null) {
	try {
		if (id) localStorage.setItem(key, id);
		else localStorage.removeItem(key);
	} catch {
		// Without the browser's storage it starts anew after an interruption.
	}
}

async function send(id: string, { file, path }: Entry): Promise<void> {
	const address = apiHref(
		`/api/imports/${id}/files/${path.split('/').map(encodeURIComponent).join('/')}`
	);
	for (let attempt = 1; ; attempt++) {
		try {
			const response = await fetch(address, { method: 'PUT', body: file });
			if (response.ok) return;
			if (response.status < 500 || attempt >= TRIES) {
				const detail = await response.json().catch(() => ({}));
				throw new Error(`${path}: ${detail.detail ?? response.status}`);
			}
		} catch (error) {
			if (attempt >= TRIES) throw error;
		}
		await new Promise((done) => setTimeout(done, 1000 * attempt));
	}
}

/** Send the chosen folder (``input webkitdirectory``) and start its import;
 * ``progress`` hears the bytes sent of all. */
export async function importFolder(
	chosen: File[],
	owner: string,
	progress: (sent: number, total: number, files: number, of: number) => void
): Promise<ImportOut> {
	const { name, files } = entries(chosen);
	const key = remembered(name, files);
	let id = recall(key);
	let arrived = new Set<string>();
	if (id) {
		const { data } = await folderFiles({ path: { import_id: id } });
		if (data) arrived = new Set(data.map((f) => `${f.path}\u0000${f.size}`));
		else id = null;
	}
	if (!id) {
		const { data, error } = await startFolderImport({
			body: { name, library_id: owner || null }
		});
		if (!data)
			throw new Error((error as { detail?: string })?.detail ?? 'The import could not start.');
		id = data.id;
		keep(key, id);
	}
	const waiting = files.filter(({ file, path }) => !arrived.has(`${path}\u0000${file.size}`));
	const total = files.reduce((sum, { file }) => sum + file.size, 0);
	let sent = total - waiting.reduce((sum, { file }) => sum + file.size, 0);
	let done = files.length - waiting.length;
	progress(sent, total, done, files.length);
	const queue = [...waiting];
	const importId = id;
	await Promise.all(
		Array.from({ length: AT_ONCE }, async () => {
			for (let next = queue.shift(); next; next = queue.shift()) {
				await send(importId, next);
				sent += next.file.size;
				done += 1;
				progress(sent, total, done, files.length);
			}
		})
	);
	const finished = await fetch(apiHref(`/api/imports/${importId}/finish`), { method: 'POST' });
	if (!finished.ok) {
		const detail = await finished.json().catch(() => ({}));
		throw new Error(detail.detail ?? `The import could not start (${finished.status}).`);
	}
	keep(key, null);
	return (await finished.json()) as ImportOut;
}
