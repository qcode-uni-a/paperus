/** Live signals (#46): an open stream (``/api/changes/live``) says when
 * the library changed; what changed, the pages ask as usual. Not in the
 * demo (recorded) nor in the app's copy offline. */
import { apiHref } from '#lib/api/client.ts';
import { offline } from '#lib/app.ts';
import { DEMO } from '#lib/demo.ts';

/** Goes up at each signal: pages reload what they show when it moves. */
export const live = $state({ changes: 0 });

/** Listen while logged in (the browser reconnects by itself); returns the
 * way to stop. */
export function listen(): () => void {
	if (DEMO || offline || typeof EventSource === 'undefined') return () => {};
	const stream = new EventSource(apiHref('/api/changes/live'));
	stream.addEventListener('change', () => live.changes++);
	return () => stream.close();
}
