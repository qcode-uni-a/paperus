<script lang="ts">
	/** An icon from Material Design Icons (@mdi/js, Apache-2.0), e.g.
	 * <Icon path={mdiMagnify} />; decorative unless given a label. */
	let { path, size = 20, label }: { path: string; size?: number; label?: string } = $props();
</script>

<svg
	viewBox="0 0 24 24"
	width={size}
	height={size}
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : 'true'}><path d={path} /></svg
>

<style>
	svg {
		flex: none;
		fill: currentColor;
	}
</style>
