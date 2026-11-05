import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';

// Administration opens with the users.
export const load = () => redirect(307, resolve('/admin/users'));
