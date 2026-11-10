<script lang="ts">
	import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
	import { pdfFiles } from '#lib/pdfjs.ts';
	import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

	GlobalWorkerOptions.workerSrc = workerUrl;

	/** A PDF's first page as a small picture (to compare papers). */
	let { url, width = 240 }: { url: string; width?: number } = $props();

	let canvas = $state<HTMLCanvasElement>();
	let failed = $state(false);
	let loading = $state(true);

	$effect(() => {
		const target = canvas;
		const size = width;
		if (!target) return;
		failed = false;
		loading = true;
		const task = getDocument({ ...pdfFiles(), url, withCredentials: true });
		let cancelled = false;
		task.promise
			.then(async (pdf) => {
				const page = await pdf.getPage(1);
				if (cancelled) return;
				const ratio = window.devicePixelRatio || 1;
				const viewport = page.getViewport({ scale: size / page.getViewport({ scale: 1 }).width });
				target.width = Math.floor(viewport.width * ratio);
				target.height = Math.floor(viewport.height * ratio);
				target.style.width = `${viewport.width}px`;
				target.style.height = `${viewport.height}px`;
				await page.render({
					canvas: target,
					viewport,
					transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0]
				}).promise;
				if (!cancelled) loading = false;
			})
			.catch(() => {
				if (!cancelled) failed = true;
			});
		return () => {
			cancelled = true;
			task.destroy();
		};
	});
</script>

<div class="thumb" style:width="{width}px" style:min-height="{Math.round(width * 1.3)}px">
	{#if failed}
		<span class="muted">The PDF could not be shown.</span>
	{:else if loading}
		<span class="muted">Opening…</span>
	{/if}
	<canvas bind:this={canvas} class:hidden={failed || loading}></canvas>
</div>

<style>
	.thumb {
		display: grid;
		place-items: center;
		background: white;
		border-radius: 4px;
		box-shadow:
			0 1px 2px rgb(27 36 64 / 0.12),
			0 4px 14px rgb(27 36 64 / 0.1);
		overflow: hidden;
	}
	.thumb > * {
		grid-area: 1 / 1;
	}
	.hidden {
		visibility: hidden;
	}
	.muted {
		padding: 12px;
		color: #6b7186;
		font-size: var(--step--1);
		text-align: center;
	}
	canvas {
		display: block;
	}
</style>
