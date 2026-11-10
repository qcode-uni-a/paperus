<script lang="ts">
	/** Above every page of the demo: what it is, and what it cannot do. */
	import { resolve } from '$app/paths';

	// The homepage, one folder up from the demo's own (/paperus/demo/).
	const homepage = resolve('/').replace(/[^/]+\/?$/, '');
</script>

<p class="demo" role="note">
	<strong>Demo:</strong> a recorded library to look around in. Uploads, changes and search by
	meaning don't work here; search finds single words. <a href={homepage}>Install paperus</a> for all of
	it.
</p>

<style>
	.demo {
		margin: 0;
		padding: 8px 16px;
		background: var(--highlighter);
		color: var(--on-highlighter);
		font-size: var(--step--1);
		text-align: center;
	}
	.demo a {
		color: inherit;
		font-weight: 600;
	}
</style>
