import {
	mdiAccountGroupOutline,
	mdiBrain,
	mdiCogSyncOutline,
	mdiFolderTextOutline,
	mdiServerOutline,
	mdiShieldCheckOutline,
	mdiShieldKeyOutline,
	mdiTextBoxOutline,
	mdiTrashCanOutline
} from '@mdi/js';
import { getConfig, mlStatus, stats as getStats } from '#lib/api/client.ts';
import type { MlStatus, Stats, SystemConfig } from '#lib/api/generated/types.gen.ts';
import { localTime } from '#lib/format.ts';

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

/** The sections of the settings page: slug, title, what it is about, its
 * icon, and a word or two on how it is set (shown while folded). */
export const SETTINGS: {
	slug: string;
	title: string;
	subtitle: string;
	icon: string;
	status: (config: SystemConfig) => string | null;
}[] = [
	{
		slug: 'ml',
		title: 'Machine learning',
		subtitle: 'Search by meaning: the model, its speed, the CPU cores it uses',
		icon: mdiBrain,
		status: (c) => c.embedding_model
	},
	{
		slug: 'integrity',
		title: 'Integrity checks',
		subtitle: 'Whether every file’s stored contents are there and unchanged',
		icon: mdiShieldCheckOutline,
		status: (c) =>
			({ weekly: 'Every Sunday', daily: 'Every night', off: 'Off' })[
				c.integrity_schedule ?? 'weekly'
			]
	},
	{
		slug: 'jobs',
		title: 'Job settings',
		subtitle: 'How many background jobs run at once, and when the night jobs run',
		icon: mdiCogSyncOutline,
		status: (c) => `Nights at ${localTime(c.night_hour ?? 2)}`
	},
	{
		slug: 'logging',
		title: 'Logging',
		subtitle: 'How much the server and the worker write to their logs',
		icon: mdiTextBoxOutline,
		status: (c) => {
			const level = c.log_level ?? 'info';
			return level[0].toUpperCase() + level.slice(1);
		}
	},
	{
		slug: 'server',
		title: 'Server',
		subtitle: 'Public address, contact email for metadata services, upload limits',
		icon: mdiServerOutline,
		status: (c) => (c.public_url ? new URL(c.public_url).host : null)
	},
	{
		slug: 'storage-template',
		title: 'Storage template',
		subtitle: 'A readable copy of the library on disk, in folders',
		icon: mdiFolderTextOutline,
		status: (c) => (c.copy_enabled ? 'On' : 'Off')
	},
	{
		slug: 'trash',
		title: 'Trash',
		subtitle: 'When the trash empties itself',
		icon: mdiTrashCanOutline,
		status: (c) => (c.trash_days != null ? `After ${c.trash_days} days` : 'By hand')
	},
	{
		slug: 'users',
		title: 'Users',
		subtitle: 'Groups new people join, and handing over the things of people who left',
		icon: mdiAccountGroupOutline,
		status: (c) => {
			const n = c.new_user_groups?.length ?? 0;
			return n ? `New people join ${n} ${n === 1 ? 'group' : 'groups'}` : null;
		}
	},
	{
		slug: 'authentication',
		title: 'Authentication',
		subtitle: 'OIDC login, passwords, how long one stays logged in',
		icon: mdiShieldKeyOutline,
		status: (c) => (c.oidc_enabled ? 'OIDC and passwords' : 'Passwords')
	}
];
