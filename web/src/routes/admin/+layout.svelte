<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { loadAdmin, SETTINGS } from '#lib/admin/data.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	$effect(() => {
		if (!session.user?.is_admin) return;
		loadAdmin();
		const timer = setInterval(loadAdmin, 3000);
		return () => clearInterval(timer);
	});

	function current(path: string): boolean {
		return page.url.pathname === path;
	}
</script>

{#if !session.checked}
	<p class="muted">Loading…</p>
{:else if !session.user?.is_admin}
	<p class="muted">Only administrators can see this page.</p>
{:else}
	<div class="admin">
		<nav aria-label="Administration">
			<a href={resolve('/admin')} class:current={current(resolve('/admin'))}>Overview</a>
			<span class="group muted">Settings</span>
			{#each SETTINGS as [slug, label] (slug)}
				{@const href = resolve('/admin/settings/[section]', { section: slug })}
				<a {href} class:current={current(href)}>{label}</a>
			{/each}
		</nav>
		<div class="content">{@render children()}</div>
	</div>
{/if}

<style>
	.admin {
		display: grid;
		grid-template-columns: 200px 1fr;
		gap: 24px;
		align-items: start;
	}
	nav {
		display: grid;
		gap: 2px;
		position: sticky;
		top: 16px;
	}
	nav a {
		padding: 6px 10px;
		border-radius: var(--radius);
		text-decoration: none;
		color: var(--text);
	}
	nav a:hover {
		background: var(--surface);
	}
	nav a.current {
		background: var(--surface);
		color: var(--accent);
		font-weight: 600;
	}
	.group {
		margin: 12px 10px 4px;
		font-size: 0.8em;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.content {
		min-width: 0;
	}
	.content :global(h1) {
		margin-top: 0;
	}
	@media (max-width: 720px) {
		.admin {
			grid-template-columns: 1fr;
		}
		nav {
			position: static;
			display: flex;
			overflow-x: auto;
			gap: 4px;
			padding-bottom: 4px;
		}
		nav a {
			white-space: nowrap;
		}
		.group {
			display: none;
		}
	}
</style>
