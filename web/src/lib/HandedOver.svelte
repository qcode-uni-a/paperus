<script lang="ts">
	import { markHintSeen } from '#lib/api/client.ts';
	import { formatLongDate } from '#lib/dates.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	/** Back after the account was deactivated: what happened to one's own
	 * library meanwhile (an administrator handed it over), shown once. */

	const HINT = 'handed-over';
	const told = $derived(
		session.user?.handed_over && !session.user.seen_hints.includes(HINT)
			? session.user.handed_over
			: null
	);

	async function dismiss() {
		if (!session.user) return;
		session.user.seen_hints = [...session.user.seen_hints, HINT];
		await markHintSeen({ path: { hint: HINT } });
	}
</script>

{#if told}
	<aside class="handed-over" role="status">
		<p>
			While your account was deactivated, the administrator {told.by} handed your papers, notes, tags
			and collections to {told.to} on {formatLongDate(told.at)}
			({told.papers}
			{told.papers === 1 ? 'paper' : 'papers'}). Ask them or {told.to} if you need them back.
		</p>
		<button onclick={dismiss}>OK</button>
	</aside>
{/if}

<style>
	.handed-over {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 16px;
		margin: 0 0 16px;
		padding: 12px 16px;
		border: 1px solid var(--rule);
		border-left: 4px solid var(--highlighter);
		border-radius: 10px;
	}
	.handed-over p {
		flex: 1 1 20rem;
		margin: 0;
	}
</style>
