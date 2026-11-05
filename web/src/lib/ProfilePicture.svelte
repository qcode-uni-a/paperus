<script lang="ts">
	import { errorMessage, removeAvatar, setAvatar } from '#lib/api/client.ts';
	import Avatar from '#lib/Avatar.svelte';
	import { session } from '#lib/session.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** One's profile picture: cut to a square in the middle and scaled to
	 * 256 pixels here in the browser, then sent. */
	const SIZE = 256;
	let busy = $state(false);

	async function square(file: File): Promise<Blob> {
		const image = await createImageBitmap(file);
		const side = Math.min(image.width, image.height);
		const canvas = document.createElement('canvas');
		canvas.width = canvas.height = SIZE;
		const context = canvas.getContext('2d');
		if (!context) throw new Error('this browser cannot scale pictures');
		context.imageSmoothingQuality = 'high';
		context.drawImage(
			image,
			(image.width - side) / 2,
			(image.height - side) / 2,
			side,
			side,
			0,
			0,
			SIZE,
			SIZE
		);
		image.close();
		const encode = (type: string) =>
			new Promise<Blob | null>((done) => canvas.toBlob(done, type, 0.86));
		// WebP where the browser writes it, else JPEG.
		const webp = await encode('image/webp');
		const blob = webp?.type === 'image/webp' ? webp : await encode('image/jpeg');
		if (!blob) throw new Error('the picture could not be converted');
		return blob;
	}

	async function choose(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (!file) return;
		busy = true;
		try {
			const blob = await square(file);
			const { data, error } = await setAvatar({ body: { upload: blob } });
			if (error || !data) throw new Error(errorMessage(error));
			session.user = data;
			notify({ kind: 'success', title: 'Profile picture saved' });
		} catch (failure) {
			notify({
				kind: 'warning',
				title: 'Picture not saved',
				text: failure instanceof Error ? failure.message : String(failure)
			});
		} finally {
			busy = false;
		}
	}

	async function remove() {
		const { data } = await removeAvatar();
		if (data) session.user = data;
		notify({ kind: 'success', title: 'Profile picture removed' });
	}
</script>

<div class="picture">
	<Avatar name={session.user?.username ?? ''} url={session.user?.avatar_url} size={88} />
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
