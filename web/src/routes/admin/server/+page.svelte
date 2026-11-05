<script lang="ts">
	import { resolve } from '$app/paths';
	import { admin } from '#lib/admin/data.svelte.ts';

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
		<h2>Search by meaning</h2>
		<p>
			{stats.embedded} of {stats.chunks} passages embedded with
			<strong>{stats.embedding_model}</strong> ({progress}%).
		</p>
		<div class="bar"><div style:width="{progress}%"></div></div>
		<p class="muted">
			Machine learning service: {servicesUp} of {admin.ml?.services.length ?? 0} reachable.
			<a href={resolve('/admin/settings/[section]', { section: 'ml' })}>Settings</a>
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
