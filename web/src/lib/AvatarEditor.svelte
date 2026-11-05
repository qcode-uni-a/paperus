<script lang="ts">
	import { mdiImageSizeSelectLarge, mdiImageSizeSelectSmall } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';

	/** Place a picture in the circle: drag to move, zoom with the slider,
	 * the wheel or + and −. Only the result (256 pixels square) leaves the
	 * browser; the original stays here. */
	let {
		file,
		onsave,
		oncancel
	}: { file: File; onsave: (picture: Blob) => void; oncancel: () => void } = $props();

	const VIEW = 300; // the circle on screen, in CSS pixels
	const OUT = 256; // the saved picture
	const MAX_ZOOM = 5;

	let dialog = $state<HTMLDialogElement>();
	let image = $state<HTMLImageElement | null>(null);
	let failed = $state(false);
	let zoom = $state(1);
	let x = $state(0); // the picture's centre, from the circle's centre
	let y = $state(0);
	let saving = $state(false);

	const url = $derived(URL.createObjectURL(file));
	$effect(() => {
		const current = url;
		return () => URL.revokeObjectURL(current);
	});
	$effect(() => {
		dialog?.showModal();
	});

	// At zoom 1 the picture just covers the circle's square.
	const base = $derived(image ? VIEW / Math.min(image.naturalWidth, image.naturalHeight) : 1);
	const width = $derived(image ? image.naturalWidth * base * zoom : VIEW);
	const height = $derived(image ? image.naturalHeight * base * zoom : VIEW);

	/** Keep the square covered: the picture may not move past its edges. */
	function place(nextX: number, nextY: number) {
		const roomX = (width - VIEW) / 2;
		const roomY = (height - VIEW) / 2;
		x = Math.max(-roomX, Math.min(roomX, nextX));
		y = Math.max(-roomY, Math.min(roomY, nextY));
	}

	function setZoom(next: number) {
		const before = zoom;
		zoom = Math.max(1, Math.min(MAX_ZOOM, next));
		// Zoom around the circle's centre.
		place((x * zoom) / before, (y * zoom) / before);
	}

	let dragging: { id: number; x: number; y: number } | null = null;
	function down(event: PointerEvent) {
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		dragging = { id: event.pointerId, x: event.clientX, y: event.clientY };
	}
	function move(event: PointerEvent) {
		if (!dragging || dragging.id !== event.pointerId) return;
		place(x + event.clientX - dragging.x, y + event.clientY - dragging.y);
		dragging = { id: event.pointerId, x: event.clientX, y: event.clientY };
	}
	function up() {
		dragging = null;
	}
	function wheel(event: WheelEvent) {
		event.preventDefault();
		setZoom(zoom * Math.exp(-event.deltaY * 0.0015));
	}
	function key(event: KeyboardEvent) {
		const step = event.shiftKey ? 40 : 10;
		const moves: Record<string, [number, number]> = {
			ArrowLeft: [step, 0],
			ArrowRight: [-step, 0],
			ArrowUp: [0, step],
			ArrowDown: [0, -step]
		};
		if (event.key in moves) {
			const [dx, dy] = moves[event.key];
			place(x + dx, y + dy);
		} else if (event.key === '+' || event.key === '=') {
			setZoom(zoom * 1.1);
		} else if (event.key === '-') {
			setZoom(zoom / 1.1);
		} else {
			return;
		}
		event.preventDefault();
	}

	async function save() {
		if (!image) return;
		saving = true;
		const scale = base * zoom; // screen pixels per picture pixel
		const left = VIEW / 2 - width / 2 + x;
		const top = VIEW / 2 - height / 2 + y;
		const canvas = document.createElement('canvas');
		canvas.width = canvas.height = OUT;
		const context = canvas.getContext('2d');
		if (!context) return;
		context.imageSmoothingQuality = 'high';
		context.drawImage(
			image,
			-left / scale,
			-top / scale,
			VIEW / scale,
			VIEW / scale,
			0,
			0,
			OUT,
			OUT
		);
		const encode = (type: string) =>
			new Promise<Blob | null>((done) => canvas.toBlob(done, type, 0.86));
		// WebP where the browser writes it, else JPEG.
		const webp = await encode('image/webp');
		const blob = webp?.type === 'image/webp' ? webp : await encode('image/jpeg');
		saving = false;
		if (blob) onsave(blob);
	}
</script>

{#snippet picture()}
	{#if image}
		<img
			src={url}
			alt=""
			draggable="false"
			style:width="{width}px"
			style:height="{height}px"
			style:left="{VIEW / 2 - width / 2 + x}px"
			style:top="{VIEW / 2 - height / 2 + y}px"
		/>
	{/if}
{/snippet}

{#snippet preview(size: number)}
	<span class="preview" style:width="{size}px" style:height="{size}px">
		<span class="scaled" style:transform="scale({size / VIEW})">{@render picture()}</span>
	</span>
{/snippet}

<dialog
	bind:this={dialog}
	aria-labelledby="avatar-title"
	onclose={() => {
		if (!saving) oncancel();
	}}
>
	<h2 id="avatar-title">Profile picture</h2>
	<!-- Loads the picture and learns its size; not shown itself. -->
	<img
		class="probe"
		src={url}
		alt=""
		onload={(event) => (image = event.currentTarget as HTMLImageElement)}
		onerror={() => (failed = true)}
	/>
	{#if failed}
		<p class="error">This browser cannot read the picture. Try a JPEG or PNG.</p>
	{:else}
		<div
			class="stage"
			style:width="{VIEW}px"
			style:height="{VIEW}px"
			role="slider"
			tabindex="0"
			aria-label="Picture position: arrow keys move it, + and − zoom"
			aria-valuenow={Math.round(zoom * 100)}
			aria-valuemin={100}
			aria-valuemax={MAX_ZOOM * 100}
			onpointerdown={down}
			onpointermove={move}
			onpointerup={up}
			onpointercancel={up}
			onwheel={wheel}
			onkeydown={key}
		>
			{@render picture()}
			<span class="mask" aria-hidden="true"></span>
		</div>
		<label class="zoom">
			<Icon path={mdiImageSizeSelectSmall} size={18} />
			<input
				type="range"
				min="1"
				max={MAX_ZOOM}
				step="0.01"
				value={zoom}
				oninput={(event) => setZoom(Number(event.currentTarget.value))}
				aria-label="Zoom"
			/>
			<Icon path={mdiImageSizeSelectLarge} size={18} />
		</label>
		<div class="previews" aria-hidden="true">
			{@render preview(88)}
			{@render preview(40)}
			{@render preview(28)}
			<span class="muted">As others see it</span>
		</div>
	{/if}
	<div class="buttons">
		<button type="button" onclick={() => dialog?.close()}>Cancel</button>
		<button class="primary" onclick={save} disabled={!image || saving}>
			{saving ? 'Saving…' : 'Save'}
		</button>
	</div>
</dialog>

<style>
	dialog {
		width: min(380px, calc(100vw - 32px));
		padding: 22px 24px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	h2 {
		margin: 0 0 16px;
		font-size: var(--step-2);
	}
	.probe {
		display: none;
	}
	.stage {
		position: relative;
		max-width: 100%;
		margin: 0 auto;
		overflow: hidden;
		border-radius: 12px;
		background: var(--desk);
		cursor: grab;
		touch-action: none;
		user-select: none;
	}
	.stage:active {
		cursor: grabbing;
	}
	.stage:focus-visible {
		outline: 2px solid var(--royal);
		outline-offset: 3px;
	}
	.stage img,
	.scaled img {
		position: absolute;
		max-width: none;
		pointer-events: none;
	}
	/* Darkens what falls outside the circle. */
	.mask {
		position: absolute;
		inset: 0;
		border-radius: 12px;
		background: radial-gradient(
			circle closest-side,
			transparent calc(100% - 1px),
			rgb(10 14 30 / 0.55) 100%
		);
		box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.15);
		pointer-events: none;
	}
	.zoom {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 16px 0 0;
		color: var(--muted);
	}
	.zoom input {
		flex: 1;
		accent-color: var(--royal);
	}
	.previews {
		display: flex;
		align-items: center;
		gap: 14px;
		margin-top: 16px;
		padding-top: 14px;
		border-top: 1px solid var(--rule);
	}
	.previews .muted {
		font-size: var(--step--1);
	}
	.preview {
		position: relative;
		flex: none;
		overflow: hidden;
		border-radius: 50%;
		background: var(--desk);
	}
	.scaled {
		position: absolute;
		top: 0;
		left: 0;
		width: 300px;
		height: 300px;
		transform-origin: 0 0;
	}
	.error {
		margin: 0;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 20px;
	}
</style>
