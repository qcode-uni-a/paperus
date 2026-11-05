import { error } from '@sveltejs/kit';
import { SETTINGS, type SettingsSection } from '#lib/admin/data.svelte.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = ({ params }) => {
	const entry = SETTINGS.find(([slug]) => slug === params.section);
	if (!entry) error(404, 'Unknown settings section');
	return { section: entry[0] as SettingsSection, title: entry[1] };
};
