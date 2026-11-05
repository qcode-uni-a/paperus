import { addItems, errorMessage, findUpload } from '#lib/api/client.ts';
import { addedPaper } from '#lib/hints.svelte.ts';
import { defaultLibrary, libraryForCollection, loadOrganize } from '#lib/organize.svelte.ts';
import type { NewItemUpload } from '#lib/api/generated/types.gen.ts';

export type UploadStatus = 'waiting' | 'uploading' | 'done' | 'failed';

export interface Upload {
	id: number;
	name: string;
	size: number;
	loaded: number;
	status: UploadStatus;
	error?: string;
	itemId?: string;
	/** Also put the new item into this collection. */
	collection?: string;
	/** Who owns the new item (a library ID); the person's default if not set. */
	library?: string;
	/** The file was already in the library; no new item was made. */
	existing?: boolean;
}

/** Files being added; each becomes a new item, identified by the server. */
export const uploads = $state<{ list: Upload[]; finished: number }>({ list: [], finished: 0 });

const PARALLEL = 2;
/** How long a finished upload stays in the list. */
const SHOW_DONE_MS = 4000;
const queue: { upload: Upload; file: File }[] = [];
let running = 0;
let nextId = 1;

export function addFiles(files: Iterable<File>, collection?: string): void {
	const library = libraryForCollection(collection);
	for (const file of files) {
		const upload: Upload = {
			id: nextId++,
			collection,
			library,
			name: file.name,
			size: file.size,
			loaded: 0,
			status: 'waiting'
		};
		uploads.list.push(upload);
		// The proxied object, so changes show up in the UI.
		queue.push({ upload: uploads.list[uploads.list.length - 1], file });
	}
	pump();
}

export function remove(id: number): void {
	uploads.list = uploads.list.filter((u) => u.id !== id);
}

export function clearFinished(): void {
	uploads.list = uploads.list.filter((u) => u.status === 'waiting' || u.status === 'uploading');
}

function pump(): void {
	while (running < PARALLEL && queue.length) {
		const next = queue.shift()!;
		running++;
		run(next.upload, next.file).finally(() => {
			running--;
			pump();
		});
	}
}

async function run(upload: Upload, file: File): Promise<void> {
	upload.status = 'uploading';
	try {
		const known = await knownItem(file);
		const result = known
			? { item_id: known, existing: true }
			: await send(file, upload.library, (loaded) => (upload.loaded = loaded));
		upload.itemId = result.item_id;
		upload.existing = result.existing ?? false;
		if (upload.collection) {
			const { error } = await addItems({
				path: { collection_id: upload.collection },
				body: { item_ids: [result.item_id] }
			});
			if (error) throw new Error(errorMessage(error));
			await loadOrganize();
		}
		upload.loaded = upload.size;
		upload.status = 'done';
		if (!upload.existing) {
			addedPaper(result.item_id, upload.name, upload.library ?? defaultLibrary()?.id);
		}
		uploads.finished++;
		setTimeout(() => remove(upload.id), SHOW_DONE_MS);
	} catch (error) {
		upload.status = 'failed';
		upload.error = error instanceof Error ? error.message : String(error);
	}
}

/** Files up to this size are fingerprinted before uploading. */
const HASH_LIMIT = 512 * 1024 ** 2;

/** The item that already has this exact file, so it need not be sent again.
 * Hashing needs a secure context (HTTPS or localhost); elsewhere the server
 * still recognizes the file after the upload. */
async function knownItem(file: File): Promise<string | null> {
	if (!globalThis.crypto?.subtle || file.size > HASH_LIMIT) return null;
	try {
		const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
		const sha256 = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join(
			''
		);
		const { data } = await findUpload({ path: { sha256 } });
		return data?.item_id ?? null;
	} catch {
		return null;
	}
}

/** POST a file with progress reports (fetch cannot report upload progress). */
function send(
	file: File,
	library: string | undefined,
	progress: (loaded: number) => void
): Promise<NewItemUpload> {
	return new Promise((resolve, reject) => {
		const request = new XMLHttpRequest();
		request.open('POST', '/api/uploads');
		request.responseType = 'json';
		request.upload.onprogress = (event) => progress(event.loaded);
		request.onload = () => {
			if (request.status >= 200 && request.status < 300) resolve(request.response as NewItemUpload);
			else if (request.status === 401) reject(new Error('Not logged in any more.'));
			else if (request.status === 413) reject(new Error('File too large.'));
			else reject(new Error(errorMessage(request.response)));
		};
		request.onerror = () => reject(new Error('Network error.'));
		const form = new FormData();
		form.append('upload', file);
		if (library) form.append('library_id', library);
		request.send(form);
	});
}
