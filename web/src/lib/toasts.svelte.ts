/** Short messages in the corner (like Immich's notifications), e.g. when
 * uploads are read or an import is done. */

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

/** Show a message; it goes away after ``seconds`` (0: only when closed). */
export function notify(toast: Omit<Toast, 'id'>, seconds = 8): void {
	const id = nextId++;
	toasts.list.push({ ...toast, id });
	if (seconds > 0) setTimeout(() => dismiss(id), seconds * 1000);
}

export function dismiss(id: number): void {
	toasts.list = toasts.list.filter((toast) => toast.id !== id);
}
