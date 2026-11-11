/** The app around the website, if it runs in one (app/src-tauri, lib.rs
 * puts this in): its version and what it can do. */
export interface App {
	version?: string;
	features?: Record<string, number>;
	/** What this device keeps offline (told after each page load). */
	kept?: { items: string[]; collections: string[]; available?: string[] };
}

export const app: App | null =
	typeof window !== 'undefined' && 'paperusApp' in window
		? ((window as unknown as { paperusApp: App }).paperusApp ?? {})
		: null;

/** The app's version; apps before 0.0.22 did not say theirs. */
export const appVersion = app ? (app.version ?? '0.0.21') : null;

/** Whether version ``a`` is older than ``b`` ("0.0.9" before "0.0.10"). */
export function older(a: string, b: string): boolean {
	const parts = (version: string) => version.split('.').map((part) => parseInt(part, 10) || 0);
	const [x, y] = [parts(a), parts(b)];
	for (let i = 0; i < Math.max(x.length, y.length); i++) {
		if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) < (y[i] ?? 0);
	}
	return false;
}

/** Whether this is a library's copy opened offline in the app (its own
 * address: `paperus-offline://localhost`, `http://paperus-offline.localhost`
 * on Windows). */
export const offline =
	typeof location !== 'undefined' &&
	(location.protocol === 'paperus-offline:' || location.hostname === 'paperus-offline.localhost');
