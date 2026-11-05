<script lang="ts">
	import { resolve } from '$app/paths';
	import { admin, formatSize } from '#lib/admin/data.svelte.ts';

	const stats = $derived(admin.stats);
	const progress = $derived(
		stats && stats.chunks ? Math.round((stats.embedded / stats.chunks) * 100) : 0
	);
	const servicesUp = $derived(admin.ml?.services.filter((s) => s.ok).length ?? 0);
</script>

<h1>Server stats</h1>

{#if stats}
	<section class="card numbers">
		<div><strong>{stats.items}</strong><span class="muted">items</span></div>
		<div><strong>{stats.files}</strong><span class="muted">files</span></div>
		<div><strong>{stats.files_pending}</strong><span class="muted">files being read</span></div>
		<div><strong>{stats.chunks}</strong><span class="muted">passages</span></div>
	</section>

	<section class="card">
		<h2>Storage</h2>
		{#if stats.storage.disk}
			{@const disk = stats.storage.disk}
			{@const used = Math.round((disk.used / disk.total) * 100)}
			<p>
				{formatSize(disk.used)} of {formatSize(disk.total)} used on the disk of the files ({used}%),
				<strong>{formatSize(disk.free)} free</strong>.
			</p>
			<div class="bar stacked" class:full={used > 90}>
				<div
					class="library"
					style:width="{Math.min(100, (stats.storage.library_bytes / disk.total) * 100)}%"
				></div>
				<div
					style:width="{Math.max(
						0,
						((disk.used - stats.storage.library_bytes) / disk.total) * 100
					)}%"
				></div>
			</div>
			<p class="legend muted">
				<span class="dot library"></span>Library {formatSize(stats.storage.library_bytes)}
				<span class="dot other"></span>Everything else on the disk {formatSize(
					Math.max(0, disk.used - stats.storage.library_bytes)
				)}
			</p>
		{:else}
			<p>
				Library: <strong>{formatSize(stats.storage.library_bytes)}</strong> (stored in the cloud: no fixed
				size).
			</p>
		{/if}
		{#if stats.storage.backups_bytes != null}
			<p>
				Backups: <strong>{formatSize(stats.storage.backups_bytes)}</strong
				>{#if stats.storage.backups_disk}, on another disk with {formatSize(
						stats.storage.backups_disk.free
					)} free of {formatSize(stats.storage.backups_disk.total)}{:else}, on the same disk{/if}.
			</p>
		{/if}
	</section>

	<section class="card">
		<h2>Search by meaning</h2>
		<p>
			{stats.embedded} of {stats.chunks} passages embedded with
			<strong>{stats.embedding_model}</strong> ({progress}%).
		</p>
		<div class="bar"><div style:width="{progress}%"></div></div>
		<p class="muted">
			Machine learning service: {servicesUp} of {admin.ml?.services.length ?? 0} reachable.
			<a href="{resolve('/admin/settings')}?open=ml">Settings</a>
		</p>
	</section>
{:else}
	<p class="muted">Loading…</p>
{/if}

<style>
	section {
		display: grid;
		gap: 12px;
		margin-bottom: 16px;
	}
	h2 {
		margin: 0;
	}
	p {
		margin: 0;
	}
	.numbers {
		grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
	}
	.numbers div {
		display: grid;
	}
	.numbers strong {
		font-size: 1.6em;
	}
	.stacked {
		display: flex;
	}
	.stacked div {
		border-radius: 0;
	}
	.stacked .library {
		background: var(--royal);
	}
	.stacked div + div {
		background: var(--faint);
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 8px;
		font-size: var(--step--1);
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		margin-left: 6px;
	}
	.dot.library {
		background: var(--royal);
	}
	.dot.other {
		background: var(--faint);
	}
	.bar {
		height: 6px;
		border-radius: 3px;
		background: var(--border);
		overflow: hidden;
	}
	.bar div {
		height: 100%;
		background: var(--accent);
		transition: width 0.3s;
	}
</style>
