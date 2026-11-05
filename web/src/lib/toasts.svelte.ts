/** Short messages in the corner, e.g. when
 * uploads are read or an import is done. They close themselves; while the
 * pointer rests on one, it waits. */

export type ToastKind = 'info' | 'success' | 'warning';

export interface Toast {
	id: number;
	kind: ToastKind;
	title: string;
	text?: string;
	link?: { href: string; label: string };
}

export const toasts = $state<{ list: Toast[] }>({ list: [] });
let nextId = 1;
const timers = new Map<
	number,
	{ timer?: ReturnType<typeof setTimeout>; left: number; since: number }
>();

/** Show a message for ``seconds`` (a little longer if it has a link). */
export function notify(toast: Omit<Toast, 'id'>, seconds = toast.link ? 15 : 8): void {
	const id = nextId++;
	toasts.list.push({ ...toast, id });
	timers.set(id, { left: seconds * 1000, since: 0 });
	resume(id);
}

export function dismiss(id: number): void {
	clearTimeout(timers.get(id)?.timer);
	timers.delete(id);
	toasts.list = toasts.list.filter((toast) => toast.id !== id);
}

/** The pointer is on it: wait. */
export function hold(id: number): void {
	const entry = timers.get(id);
	if (!entry?.timer) return;
	clearTimeout(entry.timer);
	entry.timer = undefined;
	entry.left = Math.max(2000, entry.left - (Date.now() - entry.since));
}

export function resume(id: number): void {
	const entry = timers.get(id);
	if (!entry || entry.timer) return;
	entry.since = Date.now();
	entry.timer = setTimeout(() => dismiss(id), entry.left);
}
