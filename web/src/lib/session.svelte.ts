import { logout as apiLogout, me, type User } from '#lib/api/client.ts';
import { forgetPdfs } from '#lib/pdfCache.ts';

/** The logged-in user, loaded once by the layout. */
export const session = $state<{ user: User | null; checked: boolean }>({
	user: null,
	checked: false
});

export async function loadUser(): Promise<void> {
	const { data } = await me();
	session.user = data ?? null;
	session.checked = true;
}

export async function logout(): Promise<void> {
	await apiLogout();
	await forgetPdfs();
	session.user = null;
}
