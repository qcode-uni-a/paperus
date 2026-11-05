<script lang="ts">
	let { title, items }: { title: string; items: string[] } = $props();
</script>

<h1>{title}</h1>
<div class="card">
	<p><span class="badge">Not available yet</span></p>
	<p class="muted">Planned for this section:</p>
	<ul>
		{#each items as item (item)}<li>{item}</li>{/each}
	</ul>
</div>
