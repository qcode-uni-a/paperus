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

	const settingsPath = resolve('/admin/settings');
	const MAIN = [
		[resolve('/admin/users'), 'Users'],
		[resolve('/admin/jobs'), 'Jobs'],
		[settingsPath, 'Settings'],
		[resolve('/admin/server'), 'Server stats']
	] as const;

	function active(path: string): boolean {
		return page.url.pathname === path || page.url.pathname.startsWith(`${path}/`);
	}
</script>

{#if !session.checked}
	<p class="muted">Loading…</p>
{:else if !session.user?.is_admin}
	<p class="muted">Only administrators can see this page.</p>
{:else}
	<div class="admin">
		<nav aria-label="Administration">
			{#each MAIN as [path, label] (path)}
				<a href={path} class:current={active(path)}>{label}</a>
				{#if path === settingsPath && active(settingsPath)}
					{#each SETTINGS as [slug, sublabel] (slug)}
						{@const href = resolve('/admin/settings/[section]', { section: slug })}
						<a {href} class="sub" class:current={page.url.pathname === href}>{sublabel}</a>
					{/each}
				{/if}
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
	nav a.sub {
		padding-left: 24px;
		font-size: 0.95em;
	}
	nav a.current:not(.sub):has(+ .sub) {
		background: none;
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
		nav a.sub {
			padding-left: 10px;
			color: var(--muted);
		}
	}
</style>
