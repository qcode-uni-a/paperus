import { getConfig, mlStatus, stats as getStats } from '#lib/api/client.ts';
import type { MlStatus, Stats, SystemConfig } from '#lib/api/generated/types.gen.ts';

/** Shared by the admin pages; refreshed while one of them is open. */
export const admin = $state<{
	config: SystemConfig | null;
	ml: MlStatus | null;
	stats: Stats | null;
}>({ config: null, ml: null, stats: null });

export async function loadAdmin(): Promise<void> {
	const [config, ml, stats] = await Promise.all([getConfig(), mlStatus(), getStats()]);
	admin.config = config.data ?? null;
	admin.ml = ml.data ?? null;
	admin.stats = stats.data ?? null;
}

export function formatSize(bytes: number | null | undefined): string {
	if (bytes == null) return 'not downloaded';
	if (bytes < 1024 ** 3) return `${Math.round(bytes / 1024 ** 2)} MB`;
	return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

/** The sections of the settings page: slug, title, what it is
 * about, and whether it can be set yet. */
export const SETTINGS = [
	[
		'ml',
		'Machine learning',
		'Search by meaning: the model, its speed, the CPU cores it uses',
		false
	],
	[
		'integrity',
		'Integrity checks',
		'Whether every file’s stored contents are there and unchanged',
		false
	],
	[
		'jobs',
		'Job settings',
		'How many background jobs run at once, and when the night jobs run',
		false
	],
	['logging', 'Logging', 'How much the server and the worker write to their logs', false],
	['server', 'Server', 'Public address, contact email for metadata services, upload limits', false],
	['storage-template', 'Storage template', 'A readable copy of the library on disk', true],
	['trash', 'Trash', 'When the trash empties itself', false],
	['users', 'Users', "What happens to a removed person's papers and notes", true],
	['authentication', 'Authentication', 'OIDC login, passwords, how long one stays logged in', false]
] as const;

export type SettingsSection = (typeof SETTINGS)[number][0];
