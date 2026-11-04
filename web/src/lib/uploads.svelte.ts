import { addItem, errorMessage, type FileInfo } from '#lib/api/client.ts';

export type UploadStatus = 'waiting' | 'uploading' | 'done' | 'failed';

export interface Upload {
	id: number;
	name: string;
	size: number;
	loaded: number;
	status: UploadStatus;
	error?: string;
	itemId?: string;
}

/** Files being added; each becomes a new item titled after the file. */
export const uploads = $state<{ list: Upload[]; finished: number }>({ list: [], finished: 0 });

const PARALLEL = 2;
/** How long a finished upload stays in the list. */
const SHOW_DONE_MS = 4000;
const queue: { upload: Upload; file: File }[] = [];
let running = 0;
let nextId = 1;

export function addFiles(files: Iterable<File>): void {
	for (const file of files) {
		const upload: Upload = {
			id: nextId++,
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
		const title = file.name.replace(/\.[^.]+$/, '') || file.name;
		const { data: item, error } = await addItem({ body: { metadata: { title } } });
		if (!item) throw new Error(errorMessage(error));
		upload.itemId = item.id;
		await send(`/api/items/${item.id}/files`, file, (loaded) => (upload.loaded = loaded));
		upload.loaded = upload.size;
		upload.status = 'done';
		uploads.finished++;
		setTimeout(() => remove(upload.id), SHOW_DONE_MS);
	} catch (error) {
		upload.status = 'failed';
		upload.error = error instanceof Error ? error.message : String(error);
	}
}

/** POST a file with progress reports (fetch cannot report upload progress). */
function send(url: string, file: File, progress: (loaded: number) => void): Promise<FileInfo> {
	return new Promise((resolve, reject) => {
		const request = new XMLHttpRequest();
		request.open('POST', url);
		request.responseType = 'json';
		request.upload.onprogress = (event) => progress(event.loaded);
		request.onload = () => {
			if (request.status >= 200 && request.status < 300) resolve(request.response as FileInfo);
			else if (request.status === 401) reject(new Error('Not logged in any more.'));
			else if (request.status === 413) reject(new Error('File too large.'));
			else reject(new Error(errorMessage(request.response)));
		};
		request.onerror = () => reject(new Error('Network error.'));
		const form = new FormData();
		form.append('upload', file);
		form.append('role', 'main');
		request.send(form);
	});
}
