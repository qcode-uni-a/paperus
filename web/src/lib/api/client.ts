import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { client } from './generated/client.gen';
import type {
	FileOut,
	FileRole,
	ItemDetail,
	ItemOut,
	Passage,
	UserOut,
	VersionKind,
	VersionOut
} from './generated';

export * from './generated/sdk.gen';
export type {
	FileOut as FileInfo,
	FileRole,
	ItemDetail,
	ItemOut as Item,
	Passage,
	UserOut as User,
	VersionKind,
	VersionOut as Version
};

// Same origin as the website; the schema names no server.
client.setConfig({ baseUrl: '', credentials: 'same-origin' });

/** A link into the API (a file to open or download), below the website's
 * own path: none at a paperus server, the demo's on GitHub Pages
 * (#lib/demo.ts), where its service worker answers it. */
export function apiHref(path: `/api/${string}`): string {
	return resolve('/').replace(/\/$/, '') + path;
}

// Back to the login page when the session has ended.
client.interceptors.response.use(async (response) => {
	const login = resolve('/login');
	if (response.status === 401 && location.pathname !== login) {
		const next = encodeURIComponent(location.pathname + location.search);
		await goto(`${login}?next=${next}`);
	}
	return response;
});

/** Sent on the window after each change the website made (a merge, a paper
 * sorted, an author kept apart): what counts what waits refreshes then. */
export const CHANGED = 'paperus:changed';
client.interceptors.response.use((response, request) => {
	if (response.ok && request.method !== 'GET') window.dispatchEvent(new Event(CHANGED));
	return response;
});

/** A readable message from an API error body. */
export function errorMessage(error: unknown): string {
	if (error && typeof error === 'object' && 'detail' in error) {
		const detail = (error as { detail: unknown }).detail;
		if (typeof detail === 'string') return detail;
		if (Array.isArray(detail)) {
			return detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; ');
		}
		if (detail && typeof detail === 'object' && 'message' in detail) {
			return String((detail as { message: unknown }).message);
		}
	}
	// A server error's plain text ("Internal Server Error"), or the
	// connection failing: said as it is, so a report tells what happened.
	if (typeof error === 'string' && error.trim() && error.length < 200 && !error.includes('<')) {
		return `Something went wrong (${error.trim()}).`;
	}
	if (error instanceof Error && error.message) {
		return `Something went wrong (${error.message}).`;
	}
	return 'Something went wrong.';
}

/** The change number in an ETag header, for If-Match on edits. */
export function etagOf(response: Response | undefined): string | undefined {
	return response?.headers.get('ETag') ?? undefined;
}

export const VERSION_KINDS: VersionKind[] = [
	'published',
	'accepted',
	'submitted',
	'preprint',
	'draft',
	'edition',
	'other'
];

export const FILE_ROLES: FileRole[] = [
	'main',
	'supplementary',
	'code',
	'data',
	'slides',
	'peer_review',
	'transcript',
	'recording',
	'other'
];
