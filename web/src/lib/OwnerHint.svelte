<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { dismissFirstOwner, hints } from '#lib/hints.svelte.ts';
	import { isShared, libraryName } from '#lib/organize.svelte.ts';

	/** Once, after someone's first paper: who owns it and how to change that. */
	let dialog = $state<HTMLDialogElement>();
	const hint = $derived(hints.firstOwner);
	const owner = $derived(hint && isShared(hint.libraryId) ? libraryName(hint.libraryId) : 'you');

	$effect(() => {
		if (hint && !dialog?.open) dialog?.showModal();
	});

	async function close(next?: string) {
		dialog?.close();
		await dismissFirstOwner();
		if (next) await goto(next);
	}
</script>

<dialog bind:this={dialog} aria-labelledby="owner-hint-title" onclose={() => dismissFirstOwner()}>
	{#if hint}
		<h2 id="owner-hint-title">Who owns your papers</h2>
		<p>
			<em>{hint.title}</em> belongs to <strong>{owner}</strong>{isShared(hint.libraryId)
				? ': everyone in the group sees it.'
				: ': only you see it.'}
		</p>
		<ol>
			<li>
				<strong>New papers, tags and collections</strong> belong to {owner}. Change that under
				<em>Settings → Owner of new things</em>.
			</li>
			<li>
				<strong>To give one paper to someone else</strong>, open it and choose <em>Edit</em> in its ⋯
				menu; there you can give it to a group to share it, for example.
			</li>
		</ol>
		<div class="buttons">
			<button onclick={() => close(resolve('/settings'))}>Settings</button>
			<button onclick={() => close(resolve('/items/[id]', { id: hint.itemId }))}
				>Open the paper</button
			>
			<button class="primary" onclick={() => close()}>Got it</button>
		</div>
	{/if}
</dialog>

<style>
	dialog {
		width: min(480px, calc(100vw - 32px));
		padding: 22px 24px 20px;
		border: 1px solid var(--rule);
		border-top: 4px solid var(--highlighter);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	h2 {
		margin: 0 0 10px;
		font-size: var(--step-2);
	}
	p {
		margin: 0 0 12px;
	}
	ol {
		margin: 0 0 18px;
		padding-left: 20px;
		display: grid;
		gap: 8px;
		color: var(--ink);
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
