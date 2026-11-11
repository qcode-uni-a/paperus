// The import moved to Settings → Import (usually done once); old links and
// bookmarks go there.
import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';

export function load() {
	redirect(307, `${resolve('/settings')}?open=import`);
}
