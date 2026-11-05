import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';

// One settings page now; old links open their section there.
export const load = ({ params }: { params: { section: string } }) =>
	redirect(308, `${resolve('/admin/settings')}?open=${encodeURIComponent(params.section)}`);
