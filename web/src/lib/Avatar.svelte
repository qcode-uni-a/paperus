<script lang="ts">
	/** A person's profile picture, or the first letter of their name. */
	let {
		name,
		url = null,
		size = 28,
		tone = 'royal'
	}: { name: string; url?: string | null; size?: number; tone?: 'royal' | 'desk' } = $props();

	let failed = $state(false);
	$effect(() => {
		void url;
		failed = false;
	});
	const initial = $derived(name.slice(0, 1).toUpperCase());
</script>

<span
	class="avatar {tone}"
	style:width="{size}px"
	style:height="{size}px"
	style:font-size="{Math.round(size * 0.45)}px"
	aria-hidden="true"
>
	{#if url && !failed}
		<img src={url} alt="" width={size} height={size} onerror={() => (failed = true)} />
	{:else}
		{initial}
	{/if}
</span>

<style>
	.avatar {
		display: inline-grid;
		flex: none;
		place-items: center;
		overflow: hidden;
		border-radius: 50%;
		font-weight: 700;
		line-height: 1;
	}
	.royal {
		background: var(--royal);
		color: var(--on-royal);
	}
	.desk {
		background: var(--desk);
		color: var(--ink);
	}
	img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
</style>
