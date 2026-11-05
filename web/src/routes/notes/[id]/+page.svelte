<script lang="ts">
	import { page } from '$app/state';
	import NoteEditor from '#lib/NoteEditor.svelte';

	const id = $derived(page.params.id ?? '');
</script>

<!-- Anew for each note: switching notes never mixes their texts or saves. -->
{#key id}
	<NoteEditor {id} write={page.url.searchParams.has('write')} />
{/key}
