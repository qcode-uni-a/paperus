<script lang="ts">
	import { apiHref } from '#lib/api/client.ts';
	import {
		mdiFileDocumentOutline,
		mdiFileImageOutline,
		mdiFileMusicOutline,
		mdiFileOutline,
		mdiFilePdfBox,
		mdiFileVideoOutline
	} from '@mdi/js';
	import type { FileLink } from '#lib/api/generated/types.gen.ts';
	import Icon from '#lib/Icon.svelte';

	/** A paper's file as a small icon by its kind; a click opens the file
	 * itself in a new tab. */
	let { files, size = 18 }: { files: FileLink[]; size?: number } = $props();

	const file = $derived(files[0]);
	const kind = $derived.by(() => {
		const type = file?.media_type ?? '';
		if (type === 'application/pdf') return { icon: mdiFilePdfBox, name: 'PDF' };
		if (type.startsWith('image/')) return { icon: mdiFileImageOutline, name: 'Image' };
		if (type.startsWith('video/')) return { icon: mdiFileVideoOutline, name: 'Video' };
		if (type.startsWith('audio/')) return { icon: mdiFileMusicOutline, name: 'Recording' };
		if (type.startsWith('text/')) return { icon: mdiFileDocumentOutline, name: 'Text' };
		return { icon: mdiFileOutline, name: 'File' };
	});
	const title = $derived(
		file
			? `Open ${file.filename}${files.length > 1 ? ` (${files.length - 1} more on the paper's page)` : ''}`
			: ''
	);
</script>

{#if file}
	<a
		class="file"
		class:pdf={file.media_type === 'application/pdf'}
		href={apiHref(`/api/files/${file.id}/content`)}
		target="_blank"
		rel="noopener"
		{title}
		aria-label="{kind.name}: {title}"
		data-sveltekit-reload
	>
		<Icon path={kind.icon} {size} />
	</a>
{/if}

<style>
	.file {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: 50%;
		color: var(--muted);
	}
	.file.pdf {
		color: var(--danger);
	}
	.file:hover {
		background: var(--rail);
	}
	.file:focus-visible {
		outline: 2px solid var(--royal);
		outline-offset: 1px;
	}
</style>
