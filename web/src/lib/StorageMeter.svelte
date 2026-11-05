<script lang="ts">
	import { mdiDatabaseOutline } from '@mdi/js';
	import { storage } from '#lib/api/client.ts';
	import type { Storage } from '#lib/api/generated/types.gen.ts';
	import { formatSize } from '#lib/admin/data.svelte.ts';
	import Icon from '#lib/Icon.svelte';

	/** How full the storage is, at the bottom of the menu. */
	let space = $state<Storage | null>(null);

	$effect(() => {
		storage().then(({ data }) => (space = data ?? null));
		const timer = setInterval(() => storage().then(({ data }) => (space = data ?? space)), 60_000);
		return () => clearInterval(timer);
	});

	const used = $derived(
		space?.disk_total && space.disk_free != null ? space.disk_total - space.disk_free : null
	);
	const share = $derived(
		used != null && space?.disk_total ? Math.min(100, (used / space.disk_total) * 100) : 0
	);
</script>

{#if space}
	<div class="meter" class:full={share > 90}>
		<div class="head"><Icon path={mdiDatabaseOutline} size={18} /><span>Storage</span></div>
		{#if used != null && space.disk_total}
			<div
				class="bar"
				role="meter"
				aria-label="Disk space used"
				aria-valuemin="0"
				aria-valuemax="100"
				aria-valuenow={Math.round(share)}
			>
				<div style:width="{share}%"></div>
			</div>
			<p>{formatSize(used)} of {formatSize(space.disk_total)} used</p>
		{/if}
		<p class="muted">Library: {formatSize(space.library_bytes)}</p>
	</div>
{/if}

<style>
	.meter {
		display: grid;
		gap: 6px;
		margin: 20px 0 8px 24px;
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-radius: 14px;
		font-size: var(--step--1);
	}
	.head {
		display: flex;
		align-items: center;
		gap: 8px;
		font-weight: 600;
		color: var(--ink);
	}
	.head :global(svg) {
		color: var(--muted);
	}
	.bar {
		height: 6px;
		border-radius: 3px;
		background: var(--rail);
		overflow: hidden;
	}
	.bar div {
		height: 100%;
		border-radius: 3px;
		background: var(--royal);
	}
	.full .bar div {
		background: var(--danger);
	}
	p {
		margin: 0;
	}
</style>
