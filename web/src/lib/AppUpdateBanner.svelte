<script lang="ts">
	/** In the app, when it is older than this server supports
	 * (``/api/version``): its own parts (logging in in the browser,
	 * notifications, offline use) may not work; the website does. */
	import { onMount } from 'svelte';
	import { serverVersion } from '#lib/api/client.ts';
	import { appVersion, offline, older } from '#lib/app.ts';

	let needed = $state<string | null>(null);

	onMount(async () => {
		if (!appVersion || offline) return;
		const { data } = await serverVersion();
		if (data && older(appVersion, data.oldest_app)) needed = data.oldest_app;
	});
</script>

{#if needed}
	<p class="update" role="note">
		This app is older than this server supports: update it to paperus {needed} or newer.
		<a href="https://github.com/qcode-uni-a/paperus/releases/latest">Download the app</a>
	</p>
{/if}

<style>
	.update {
		margin: 0;
		padding: 8px 16px;
		background: var(--highlighter);
		color: var(--on-highlighter);
		font-size: var(--step--1);
		text-align: center;
	}
	.update a {
		color: inherit;
		font-weight: 600;
	}
</style>
