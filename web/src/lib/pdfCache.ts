/** Recently opened PDFs kept in the browser (IndexedDB), so a paper opened
 * again shows without downloading it again: the last ``KEEP_FILES``, at
 * most ``KEEP_BYTES``, the least recently opened going first. Kept by file
 * and content (SHA-256), so a file whose content was replaced is fetched
 * anew; one person's at a time, and all gone on logging out. The viewer
 * only gets here after the server let the person see the paper, so a
 * paper out of reach is never shown from here.
 *
 * Without IndexedDB (a private window, blocked site data), nothing is
 * kept and PDFs load as before. */

const NAME = 'paperus-pdfs';
const KEEP_FILES = 30;
const KEEP_BYTES = 300 * 1024 * 1024;

type Kept = { fileId: string; sha256: string; user: string; size: number; used: number };

let opened: Promise<IDBDatabase | null> | null = null;

function open(): Promise<IDBDatabase | null> {
	opened ??= new Promise((done) => {
		try {
			const request = indexedDB.open(NAME, 1);
			request.onupgradeneeded = () => {
				// What is kept (small, read whole) apart from the PDFs.
				request.result.createObjectStore('kept', { keyPath: 'fileId' });
				request.result.createObjectStore('pdfs');
			};
			request.onsuccess = () => done(request.result);
			request.onerror = () => done(null);
			request.onblocked = () => done(null);
		} catch {
			done(null);
		}
	});
	return opened;
}

function finished(transaction: IDBTransaction): Promise<void> {
	return new Promise((done, fail) => {
		transaction.oncomplete = () => done();
		transaction.onerror = transaction.onabort = () => fail(transaction.error);
	});
}

function read<T>(request: IDBRequest<T>): Promise<T> {
	return new Promise((done, fail) => {
		request.onsuccess = () => done(request.result);
		request.onerror = () => fail(request.error);
	});
}

/** The kept copy of a file with this content, for this person, or null. */
export async function cachedPdf(
	fileId: string,
	sha256: string,
	user: string
): Promise<Uint8Array | null> {
	try {
		const db = await open();
		if (!db) return null;
		const transaction = db.transaction(['kept', 'pdfs'], 'readwrite');
		const kept = transaction.objectStore('kept');
		const entry = (await read(kept.get(fileId))) as Kept | undefined;
		if (!entry || entry.sha256 !== sha256 || entry.user !== user) return null;
		const bytes = await read(transaction.objectStore('pdfs').get(fileId));
		if (!(bytes instanceof ArrayBuffer)) return null;
		kept.put({ ...entry, used: Date.now() });
		await finished(transaction);
		return new Uint8Array(bytes);
	} catch {
		return null;
	}
}

/** Keep a file's PDF (its whole content, as downloaded), making room. */
export async function keepPdf(
	fileId: string,
	sha256: string,
	user: string,
	data: Uint8Array
): Promise<void> {
	try {
		if (data.byteLength > KEEP_BYTES / 4 || !(await sameContent(data, sha256))) return;
		const db = await open();
		if (!db) return;
		const transaction = db.transaction(['kept', 'pdfs'], 'readwrite');
		const kept = transaction.objectStore('kept');
		const pdfs = transaction.objectStore('pdfs');
		const entries = ((await read(kept.getAll())) as Kept[])
			// Another person's PDFs go: one person's at a time.
			.filter((entry) => {
				const stays = entry.user === user && entry.fileId !== fileId;
				if (!stays) {
					kept.delete(entry.fileId);
					pdfs.delete(entry.fileId);
				}
				return stays;
			})
			.sort((a, b) => b.used - a.used);
		let bytes = data.byteLength;
		entries.forEach((entry, index) => {
			bytes += entry.size;
			if (index + 1 >= KEEP_FILES || bytes > KEEP_BYTES) {
				kept.delete(entry.fileId);
				pdfs.delete(entry.fileId);
			}
		});
		kept.put({ fileId, sha256, user, size: data.byteLength, used: Date.now() });
		// The bytes, not a Blob: Safari's private windows refuse Blobs here.
		pdfs.put(data.slice().buffer, fileId);
		await finished(transaction);
	} catch {
		// Full, or storage refused: shown, just not kept.
	}
}

/** Whether these are the bytes the server's details describe (not a copy
 * replaced in between). Without SubtleCrypto (only on HTTPS and
 * localhost) taken as they are: the details are read before the file, so
 * a copy replaced in between is newer than they say, kept under a hash no
 * later details name, never shown. */
async function sameContent(data: Uint8Array, sha256: string): Promise<boolean> {
	if (!globalThis.crypto?.subtle) return true;
	const digest = new Uint8Array(
		await crypto.subtle.digest('SHA-256', data as Uint8Array<ArrayBuffer>)
	);
	return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('') === sha256;
}

/** Everything kept removed (on logging out). */
export async function forgetPdfs(): Promise<void> {
	try {
		const db = await open();
		if (!db) return;
		const transaction = db.transaction(['kept', 'pdfs'], 'readwrite');
		transaction.objectStore('kept').clear();
		transaction.objectStore('pdfs').clear();
		await finished(transaction);
	} catch {
		// Nothing kept, or storage gone already.
	}
}
