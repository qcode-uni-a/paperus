<script lang="ts">
	import { resolve } from '$app/paths';
	import { createToken, errorMessage } from '#lib/api/client.ts';

	/** Connecting the browser extension: one click here makes it a token
	 * that may only add papers (with files) and see which ones one has; the
	 * extension picks it up from this page. */
	let token = $state<string | null>(null);
	let connected = $state(false);
	let error = $state('');
	let busy = $state(false);
	let mark = $state<HTMLElement>();

	async function connect() {
		busy = true;
		error = '';
		const { data, error: failure } = await createToken({
			body: {
				name: `Browser extension (${navigator.userAgent.includes('Firefox') ? 'Firefox' : 'Chrome'})`,
				scopes: ['papers.read', 'papers.write', 'groups.read']
			}
		});
		busy = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		token = data.token;
	}

	// The extension marks the page when it has taken the token.
	$effect(() => {
		const element = mark;
		if (!element) return;
		const observer = new MutationObserver(() => {
			connected = element.dataset.paperusExtensionConnected === 'yes';
		});
		observer.observe(element, { attributes: true });
		return () => observer.disconnect();
	});
</script>

<svelte:head><title>Browser extension · paperus</title></svelte:head>

<h1>Browser extension</h1>
<section>
	{#if connected}
		<p class="done">Connected. You can close this tab.</p>
		<p class="muted">
			One click on the paperus button now saves the paper you are reading, with its PDF. On arXiv,
			the small button next to each paper does the same.
		</p>
	{:else if token}
		<!-- Read by the extension; not shown. -->
		<span bind:this={mark} data-paperus-extension-token={token} hidden></span>
		<p>Handing the connection to the extension…</p>
		<p class="muted">
			If nothing happens, open the extension’s settings and click Connect again with this address.
		</p>
	{:else}
		<p>
			The paperus extension asks to connect to your library. It may then add papers (with their
			PDFs) and see which papers you have, nothing else. You can end it any time under
			<a href="{resolve('/settings')}?open=tokens">Settings → Access tokens</a>.
		</p>
		{#if error}<p class="error">{error}</p>{/if}
		<button class="primary" onclick={connect} disabled={busy}>Connect the extension</button>
	{/if}
</section>

<style>
	h1 {
		margin: 0 0 16px;
	}
	section {
		display: grid;
		gap: 12px;
		max-width: 560px;
	}
	p {
		margin: 0;
	}
	.done {
		font-weight: 600;
		color: var(--success);
	}
</style>
