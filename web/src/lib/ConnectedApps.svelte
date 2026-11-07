<script lang="ts">
	import { connectedApps, disconnectApp } from '#lib/api/client.ts';
	import type { ConnectedApp } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';

	/** Settings → Connected apps: AI assistants connected by signing in
	 * (OAuth), e.g. claude.ai's or ChatGPT's connectors. */
	let apps = $state<ConnectedApp[]>([]);
	const server = typeof location === 'undefined' ? '/mcp' : `${location.origin}/mcp`;
	const WRITES = ['papers.write', 'tags.write', 'collections.write', 'notes.write'];

	async function load() {
		const { data } = await connectedApps();
		apps = data ?? [];
	}
	$effect(() => {
		load();
	});

	async function disconnect(app: ConnectedApp) {
		if (!confirm(`Disconnect ${app.name}? It loses access at once.`)) return;
		await disconnectApp({ path: { grant_id: app.id } });
		await load();
	}

	const rights = (app: ConnectedApp) =>
		app.scopes.some((s) => WRITES.includes(s)) ? 'Reads and changes' : 'Reads only';
</script>

<p class="muted">
	AI assistants that connect by signing in, like a custom connector in claude.ai or ChatGPT: add
	<code>{server}</code> there, then allow it here when asked.
</p>
{#if apps.length}
	<ul class="apps">
		{#each apps as app (app.id)}
			<li>
				<div>
					<strong>{app.name}</strong>
					<small
						>{rights(app)}. Connected {ago(app.created_at)}{app.last_used_at
							? `, used ${ago(app.last_used_at)}`
							: ''}.</small
					>
				</div>
				<button class="link danger" onclick={() => disconnect(app)}>Disconnect</button>
			</li>
		{/each}
	</ul>
{:else}
	<p class="muted">No apps connected.</p>
{/if}

<style>
	p {
		margin: 0 0 12px;
	}
	.apps {
		margin: 0 0 12px;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 2px;
	}
	.apps li {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 12px;
		padding: 10px 0;
		border-bottom: 1px solid var(--rule);
	}
	.apps div {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	code {
		overflow-wrap: anywhere;
	}
</style>
