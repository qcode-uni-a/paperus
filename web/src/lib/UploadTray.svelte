<script lang="ts">
	import { resolve } from '$app/paths';
	import { fade, slide } from 'svelte/transition';
	import { clearFinished, remove, uploads } from '#lib/uploads.svelte.ts';

	let collapsed = $state(false);

	const active = $derived(
		uploads.list.filter((u) => u.status === 'waiting' || u.status === 'uploading').length
	);
	const failed = $derived(uploads.list.filter((u) => u.status === 'failed').length);
	const summary = $derived(
		active
			? `Uploading ${uploads.list.length - active + 1} of ${uploads.list.length}`
			: failed
				? `${failed} of ${uploads.list.length} failed`
				: `${uploads.list.length} uploaded`
	);

	function percent(loaded: number, size: number): number {
		return size ? Math.min(100, Math.round((loaded / size) * 100)) : 100;
	}
</script>

{#if uploads.list.length}
	<aside
		class="tray card"
		aria-live="polite"
		aria-label="Uploads"
		transition:fade={{ duration: 200 }}
	>
		<div class="head">
			<strong>{summary}</strong>
			<div class="row">
				<button
					class="icon"
					onclick={() => (collapsed = !collapsed)}
					aria-label={collapsed ? 'Show uploads' : 'Hide uploads'}>{collapsed ? '▴' : '▾'}</button
				>
				{#if !active}
					<button class="icon" onclick={clearFinished} aria-label="Close">✕</button>
				{/if}
			</div>
		</div>
		{#if !collapsed}
			<ul>
				{#each uploads.list as upload (upload.id)}
					<li out:slide={{ duration: 300 }}>
						<div class="name">
							<span title={upload.name}>{upload.name}</span>
							{#if upload.status === 'done' && upload.itemId}
								{#if upload.existing}<span class="muted">Already in the library</span>{/if}
								<a href={resolve('/items/[id]', { id: upload.itemId })}>Open</a>
							{:else if upload.status === 'waiting'}
								<span class="muted">waiting</span>
							{:else if upload.status === 'uploading'}
								<span class="muted">{percent(upload.loaded, upload.size)}%</span>
							{/if}
						</div>
						{#if upload.status === 'failed'}
							<div class="failed">
								<span class="error">{upload.error}</span>
								<button class="icon" onclick={() => remove(upload.id)} aria-label="Dismiss"
									>✕</button
								>
							</div>
						{:else}
							<div class="bar" class:done={upload.status === 'done'}>
								<div style:width="{percent(upload.loaded, upload.size)}%"></div>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</aside>
{/if}

<style>
	.tray {
		position: fixed;
		right: 16px;
		bottom: 16px;
		width: min(340px, calc(100vw - 32px));
		max-height: 50vh;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.15);
		z-index: 20;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.icon {
		padding: 2px 8px;
		line-height: 1.2;
	}
	ul {
		margin: 0;
		padding: 0;
		overflow-y: auto;
		display: grid;
		gap: 10px;
	}
	li {
		list-style: none;
		display: grid;
		gap: 4px;
		font-size: 0.9em;
	}
	.name {
		display: flex;
		justify-content: space-between;
		gap: 8px;
	}
	.name .muted {
		white-space: nowrap;
	}
	.name span:first-child {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.failed {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.bar {
		height: 4px;
		border-radius: 2px;
		background: var(--border);
		overflow: hidden;
	}
	.bar div {
		height: 100%;
		background: var(--accent);
		transition: width 0.2s;
	}
	.bar.done div {
		background: #2e7d32;
	}
</style>
