<script lang="ts">
	import { mdiChevronDown } from '@mdi/js';
	import type { Snippet } from 'svelte';
	import Icon from '#lib/Icon.svelte';

	/** One section of the settings page, opened and closed. */
	let {
		id,
		title,
		subtitle,
		icon,
		status = null,
		open = false,
		ontoggle,
		children
	}: {
		id: string;
		title: string;
		subtitle: string;
		icon: string;
		/** How it is set, in a word or two (shown while folded). */
		status?: string | null;
		open?: boolean;
		ontoggle: (open: boolean) => void;
		children: Snippet;
	} = $props();
</script>

<section class="section" class:open {id}>
	<button
		class="head"
		aria-expanded={open}
		aria-controls="{id}-body"
		onclick={() => ontoggle(!open)}
	>
		<span class="icon"><Icon path={icon} size={22} /></span>
		<span class="text">
			<span class="title">{title}</span>
			<span class="subtitle">{subtitle}</span>
		</span>
		{#if status && !open}<span class="status">{status}</span>{/if}
		<span class="chevron"><Icon path={mdiChevronDown} size={24} /></span>
	</button>
	{#if open}
		<div class="body" id="{id}-body">{@render children()}</div>
	{/if}
</section>

<style>
	.section {
		border: 1px solid var(--rule);
		border-radius: 18px;
		background: var(--surface);
	}
	.head {
		display: flex;
		align-items: center;
		gap: 16px;
		width: 100%;
		padding: 18px 20px;
		border: none;
		border-radius: 18px;
		background: none;
		text-align: left;
		font-weight: normal;
	}
	.head:hover:not(:disabled) {
		background: var(--rail);
	}
	.open .head {
		border-radius: 18px 18px 0 0;
	}
	.icon {
		display: grid;
		flex: none;
		place-items: center;
		width: 42px;
		height: 42px;
		border-radius: 12px;
		background: color-mix(in srgb, var(--royal) 10%, var(--surface));
		color: var(--royal);
	}
	.open .icon {
		background: var(--royal);
		color: var(--on-royal);
	}
	.status {
		flex: none;
		max-width: 40%;
		overflow: hidden;
		padding: 3px 10px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		color: var(--muted);
		font-size: var(--step--1);
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	@media (max-width: 560px) {
		.status {
			display: none;
		}
	}
	.text {
		display: grid;
		gap: 2px;
		flex: 1;
		min-width: 0;
	}
	.title {
		display: flex;
		align-items: center;
		gap: 10px;
		color: var(--royal);
		font-weight: 650;
		font-size: var(--step-0);
	}
	.subtitle {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.chevron {
		display: flex;
		color: var(--muted);
		transition: transform 0.15s;
	}
	.open .chevron {
		transform: rotate(180deg);
	}
	.body {
		padding: 4px 20px 20px;
		border-top: 1px solid var(--rule);
	}
	@media (prefers-reduced-motion: reduce) {
		.chevron {
			transition: none;
		}
	}
</style>
