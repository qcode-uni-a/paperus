<script lang="ts">
	import { page } from '$app/state';
	import { errorMessage, me, unlinkOidc } from '#lib/api/client.ts';
	import { session } from '#lib/session.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** Link the account one is logged in with to the OIDC login (one
	 * login there), or unlink it; the password stays either way. */
	let { label, next }: { label: string; next: string } = $props();

	const linked = $derived(!!session.user?.oidc_linked);
	const failed = $derived(page.url.searchParams.get('link_error'));
	const href = $derived(`/api/auth/oidc/start?link=true&next=${encodeURIComponent(next)}`);

	async function unlink() {
		const { error } = await unlinkOidc();
		if (error) {
			notify({ kind: 'warning', title: 'Not unlinked', text: errorMessage(error) });
			return;
		}
		const { data } = await me();
		if (data) session.user = data;
		notify({ kind: 'success', title: 'OIDC login unlinked' });
	}
</script>

<div class="link" class:linked>
	{#if linked}
		<p><strong>Linked.</strong> “{label}” logs you in as {session.user?.username}.</p>
		<button onclick={unlink}>Unlink</button>
	{:else}
		<p>
			Log in once through OIDC to link it to this account ({session.user?.username}); then “{label}”
			on the login page logs you in.
		</p>
		<a class="button" {href} data-sveltekit-reload>Link my account</a>
	{/if}
</div>
{#if failed && !linked}<p class="error" role="alert">{failed}</p>{/if}

<style>
	.link {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 10px 16px;
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-radius: 12px;
	}
	.link.linked {
		border-color: color-mix(in srgb, var(--success) 60%, var(--rule));
		background: color-mix(in srgb, var(--success) 8%, var(--surface));
	}
	p {
		margin: 0;
		flex: 1 1 240px;
	}
	.button {
		display: inline-block;
		padding: 7px 16px;
		border-radius: 999px;
		background: var(--royal);
		color: var(--on-royal);
		font-weight: 600;
		text-decoration: none;
	}
	.error {
		margin: 8px 0 0;
	}
</style>
