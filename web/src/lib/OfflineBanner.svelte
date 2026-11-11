<script lang="ts">
	/** Above every page of a library's copy in the app, opened when the
	 * library could not be reached (app/src-tauri/src/offline): what it is,
	 * and the way back. */
	import { offline } from '#lib/app.ts';
</script>

{#if offline}
	<p class="offline" role="note">
		<strong>Offline:</strong> your library as last synced. Changes and search by meaning wait for
		the connection. <a href="paperus-app://online">Go online</a>
	</p>
{/if}

<style>
	.offline {
		margin: 0;
		padding: 8px 16px;
		background: var(--highlighter);
		color: var(--on-highlighter);
		font-size: var(--step--1);
		text-align: center;
	}
	.offline a {
		color: inherit;
		font-weight: 600;
	}
</style>
