<script lang="ts">
	import { fade, slide } from 'svelte/transition';
	import { dismissTask, tasks } from '#lib/tasks.svelte.ts';

	function percent(done: number, total: number): number {
		return total ? Math.min(100, Math.round((done / total) * 100)) : 100;
	}
	const running = $derived(tasks.list.some((t) => !t.finished));
</script>

<!-- Moving around the website keeps them going; leaving it would end
     what runs here (the extension's own work goes on). -->
<svelte:window
	onbeforeunload={(event) => {
		if (running) event.preventDefault();
	}}
/>

{#if tasks.list.length}
	<aside
		class="tray card"
		aria-live="polite"
		aria-label="Tasks"
		transition:fade={{ duration: 200 }}
	>
		<ul>
			{#each tasks.list as task (task.id)}
				<li out:slide={{ duration: 300 }}>
					<div class="name">
						<strong>{task.title}</strong>
						{#if task.finished}
							<button class="icon" onclick={() => dismissTask(task.id)} aria-label="Close">✕</button
							>
						{:else}
							<span class="muted">{task.done} of {task.total}</span>
						{/if}
					</div>
					<div class="bar" class:done={task.finished}>
						<div style:width="{percent(task.done, task.total)}%"></div>
					</div>
					{#if task.failed && !task.finished}
						<small class="muted">{task.failed} not got so far</small>
					{/if}
					{#if task.note}<small>{task.note}</small>{/if}
					{#if task.link}<small><a href={task.link.href}>{task.link.label}</a></small>{/if}
				</li>
			{/each}
		</ul>
	</aside>
{/if}

<style>
	.tray {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.15);
	}
	ul {
		margin: 0;
		padding: 0;
		display: grid;
		gap: 12px;
		max-height: 40vh;
		overflow-y: auto;
	}
	li {
		list-style: none;
		display: grid;
		gap: 4px;
		font-size: 0.9em;
	}
	.name {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.icon {
		padding: 2px 8px;
		line-height: 1.2;
	}
	.bar {
		height: 6px;
		border-radius: 3px;
		background: var(--rail);
		overflow: hidden;
	}
	.bar div {
		height: 100%;
		background: var(--royal);
		transition: width 0.3s;
	}
	.bar.done div {
		background: var(--ok, #1e7a3e);
	}
</style>
