<script lang="ts">
	import { mdiChevronDown } from '@mdi/js';
	import type { Snippet } from 'svelte';
	import Icon from '#lib/Icon.svelte';

	/** One section of the settings page, opened and closed like Immich's. */
	let {
		id,
		title,
		subtitle,
		open = false,
		later = false,
		ontoggle,
		children
	}: {
		id: string;
		title: string;
		subtitle: string;
		open?: boolean;
		later?: boolean;
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
		<span class="text">
			<span class="title"
				>{title}{#if later}<span class="badge">Later</span>{/if}</span
			>
			<span class="subtitle">{subtitle}</span>
		</span>
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
