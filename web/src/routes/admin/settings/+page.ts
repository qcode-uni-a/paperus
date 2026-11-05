import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { SETTINGS } from '#lib/admin/data.svelte.ts';

export const load = () =>
	redirect(307, resolve('/admin/settings/[section]', { section: SETTINGS[0][0] }));
