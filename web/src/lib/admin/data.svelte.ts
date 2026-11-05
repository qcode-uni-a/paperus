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

export const SETTINGS = [
	['integrity', 'Integrity checks'],
	['jobs', 'Job settings'],
	['logging', 'Logging'],
	['ml', 'Machine learning'],
	['server', 'Server'],
	['storage-template', 'Storage template'],
	['trash', 'Trash'],
	['users', 'Users'],
	['authentication', 'Authentication']
] as const;

export type SettingsSection = (typeof SETTINGS)[number][0];
