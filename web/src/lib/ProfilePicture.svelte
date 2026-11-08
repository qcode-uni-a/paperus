<script lang="ts">
	import { errorMessage, removeAvatar, setAvatar } from '#lib/api/client.ts';
	import Avatar from '#lib/Avatar.svelte';
	import AvatarEditor from '#lib/AvatarEditor.svelte';
	import { session } from '#lib/session.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import { shownName } from '#lib/names.svelte.ts';

	/** One's profile picture: placed in the circle in an editor here, then
	 * only the small result is sent. */
	let busy = $state(false);
	let chosen = $state<File | null>(null);

	function choose(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		chosen = input.files?.[0] ?? null;
		input.value = '';
	}

	async function upload(picture: Blob) {
		chosen = null;
		busy = true;
		const { data, error } = await setAvatar({ body: { upload: picture } });
		busy = false;
		if (error || !data) {
			notify({ kind: 'warning', title: 'Picture not saved', text: errorMessage(error) });
			return;
		}
		session.user = data;
		notify({ kind: 'success', title: 'Profile picture saved' });
	}

	async function remove() {
		const { data } = await removeAvatar();
		if (data) session.user = data;
		notify({ kind: 'success', title: 'Profile picture removed' });
	}
</script>

{#if chosen}
	<AvatarEditor file={chosen} onsave={upload} oncancel={() => (chosen = null)} />
{/if}

<div class="picture">
	<Avatar
		name={session.user ? shownName(session.user) : ''}
		url={session.user?.avatar_url}
		size={88}
	/>
	<div class="actions">
		<p class="muted">Shown next to your name in the menu, in groups and to administrators.</p>
		<div class="buttons">
			<label class="button" class:busy>
				{busy ? 'Saving…' : session.user?.avatar_url ? 'Choose another' : 'Choose a picture'}
				<input type="file" accept="image/*" onchange={choose} disabled={busy} />
			</label>
			{#if session.user?.avatar_url}
				<button onclick={remove} disabled={busy}>Remove</button>
			{/if}
		</div>
	</div>
</div>

<style>
	.picture {
		display: flex;
		align-items: center;
		gap: 20px;
	}
	.actions {
		display: grid;
		gap: 10px;
	}
	p {
		margin: 0;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.button {
		position: relative;
		display: inline-flex;
		align-items: center;
		padding: 7px 16px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		font-weight: 600;
		cursor: pointer;
	}
	.button:hover {
		background: var(--rail);
	}
	.button:focus-within {
		outline: 2px solid var(--royal);
		outline-offset: 2px;
	}
	.button.busy {
		opacity: 0.6;
		cursor: progress;
	}
	input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
</style>
