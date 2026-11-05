import { errorMessage, setConfig } from '#lib/api/client.ts';
import type { SystemConfig } from '#lib/api/generated/types.gen.ts';
import { admin, loadAdmin } from '#lib/admin/data.svelte.ts';
import { notify } from '#lib/toasts.svelte.ts';

/** Save some of the installation's settings (the rest as they are now);
 * a message says whether it worked. */
export async function saveConfig(change: Partial<SystemConfig>, what: string): Promise<boolean> {
	await loadAdmin(); // the latest, so another section's save is not undone
	if (!admin.config) return false;
	const { error } = await setConfig({ body: { ...admin.config, ...change } });
	if (error) {
		notify({ kind: 'warning', title: `${what} not saved`, text: errorMessage(error) });
		return false;
	}
	notify({ kind: 'success', title: `${what} saved` });
	await loadAdmin();
	return true;
}
