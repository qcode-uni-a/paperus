<script lang="ts">
	import { closeOnScroll } from '#lib/dismiss.ts';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import Avatar from '#lib/Avatar.svelte';
	import { logout, session } from '#lib/session.svelte.ts';

	let menu = $state<HTMLElement>();

	$effect(() => closeOnScroll(() => menu?.hidePopover()));

	const name = $derived(session.user?.username ?? '');

	async function signOut() {
		menu?.hidePopover();
		await logout();
		await goto(resolve('/login'));
	}
</script>

<button class="user" popovertarget="user-menu" aria-haspopup="menu" title="Account">
	<Avatar {name} url={session.user?.avatar_url} />
	<span class="name">{name}</span>
</button>

<div id="user-menu" popover bind:this={menu} role="menu" class="menu">
	<div class="who">
		<Avatar {name} url={session.user?.avatar_url} size={40} />
		<div>
			<strong>{name}</strong>
			<span>{session.user?.is_admin ? 'Administrator' : 'Member'}</span>
		</div>
	</div>
	<a role="menuitem" href={resolve('/settings')} onclick={() => menu?.hidePopover()}>Settings</a>
	{#if session.user?.is_admin}
		<a role="menuitem" href={resolve('/admin')} onclick={() => menu?.hidePopover()}>
			Administration
		</a>
	{/if}
	<button role="menuitem" onclick={signOut}>Log out</button>
</div>

<style>
	.user {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		height: 36px;
		padding: 0 10px 0 4px;
		border-color: transparent;
		border-radius: 999px;
		background: none;
	}
	.user:hover:not(:disabled),
	.user:focus-visible {
		background: var(--rail);
		border-color: transparent;
	}
	.name {
		color: var(--ink);
	}
	.menu {
		/* Below the button at the header's right end. */
		position: fixed;
		inset: 60px 12px auto auto;
		margin: 0;
		padding: 6px;
		width: min(260px, calc(100vw - 24px));
		border: 1px solid var(--rule);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	.who {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 12px 12px;
		margin-bottom: 4px;
		border-bottom: 1px solid var(--rule);
	}
	.who div {
		display: grid;
	}
	.who div span {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.menu a,
	.menu button {
		display: block;
		width: 100%;
		text-align: left;
		padding: 9px 12px;
		border: none;
		border-radius: var(--radius);
		background: none;
		color: var(--ink);
		text-decoration: none;
	}
	.menu a:hover,
	.menu button:hover:not(:disabled) {
		background: var(--rail);
	}
	@media (max-width: 720px) {
		.user {
			padding: 0 4px;
		}
		.name {
			display: none;
		}
	}
</style>
