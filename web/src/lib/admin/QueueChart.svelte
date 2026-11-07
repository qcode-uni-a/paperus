<script lang="ts">
	import type { Sample } from '#lib/admin/data.svelte.ts';
	import { formatTime } from '#lib/dates.svelte.ts';

	/** One queue over the last two minutes: jobs waiting or running (the
	 * area) and jobs finished per minute (the dashed line), each on its own
	 * scale (left and right), with times along the bottom. */
	let { samples, queue, color }: { samples: Sample[]; queue: string; color: string } = $props();

	const WINDOW = 2 * 60_000;
	const W = 520;
	const H = 120;

	function nice(n: number): number {
		if (n <= 5) return 5;
		const step = 10 ** Math.floor(Math.log10(n));
		return Math.ceil(n / step) * step;
	}

	const chart = $derived.by(() => {
		const end = samples.at(-1)?.at ?? Date.now();
		const shown = samples.filter((s) => s.at >= end - WINDOW);
		const x = (at: number) => W - ((end - at) / WINDOW) * W;
		const load = shown.map((s) => (s.waiting[queue] ?? 0) + (s.running[queue] ?? 0));
		const rate = shown.map((s) => {
			const before = samples.find((b) => b.at >= s.at - 60_000);
			if (!before || s.at - before.at < 5_000) return 0;
			const finished = Math.max(0, (s.done[queue] ?? 0) - (before.done[queue] ?? 0));
			return (finished * 60_000) / (s.at - before.at);
		});
		const loadTop = nice(Math.max(0, ...load));
		const rateTop = nice(Math.max(0, ...rate));
		const y = (n: number, top: number) => H - (n / top) * (H - 6);
		const points = (values: number[], top: number) =>
			shown.map((s, i) => `${x(s.at).toFixed(1)},${y(values[i], top).toFixed(1)}`).join(' ');
		const line = points(load, loadTop);
		const first = shown[0] ? x(shown[0].at).toFixed(1) : '0';
		const last = shown.at(-1) ? x(shown.at(-1)!.at).toFixed(1) : String(W);
		const ticks = [];
		for (let at = end - (end % 30_000); at >= end - WINDOW; at -= 30_000) {
			ticks.push({
				x: x(at),
				label: formatTime(at, { seconds: true })
			});
		}
		return {
			enough: shown.length > 1,
			area: `${first},${H} ${line} ${last},${H}`,
			line,
			rate: points(rate, rateTop),
			loadTop,
			rateTop,
			ticks,
			now: load.at(-1) ?? 0,
			perMinute: Math.round(rate.at(-1) ?? 0)
		};
	});
</script>

{#if chart.enough}
	<figure>
		<div class="plot">
			<div class="scale left" aria-hidden="true">
				<span>{chart.loadTop}</span><span>{chart.loadTop / 2}</span><span>0</span>
			</div>
			<svg
				viewBox="0 0 {W} {H}"
				preserveAspectRatio="none"
				role="img"
				aria-label="{chart.now} waiting or running, {chart.perMinute} finished per minute"
			>
				{#each [0, 0.5, 1] as level (level)}
					<line x1="0" x2={W} y1={H - level * (H - 6)} y2={H - level * (H - 6)} class="grid" />
				{/each}
				{#each chart.ticks as tick (tick.label)}
					<line x1={tick.x} x2={tick.x} y1="0" y2={H} class="grid" />
				{/each}
				<polygon points={chart.area} style:fill={color} class="area" />
				<polyline points={chart.line} style:stroke={color} />
				<polyline points={chart.rate} class="rate" />
			</svg>
			<div class="scale right" aria-hidden="true">
				<span>{chart.rateTop}</span><span>{chart.rateTop / 2}</span><span>0</span>
			</div>
		</div>
		<div class="times" aria-hidden="true">
			{#each chart.ticks as tick (tick.label)}
				<span style:left="{(tick.x / W) * 100}%">{tick.label}</span>
			{/each}
		</div>
		<figcaption>
			<span><i class="swatch" style:background={color}></i>waiting or running (left)</span>
			<span><i class="swatch dashed"></i>finished per minute (right)</span>
		</figcaption>
	</figure>
{:else}
	<p class="muted small">Collecting… the chart fills while this page is open.</p>
{/if}

<style>
	figure {
		display: grid;
		gap: 4px;
		margin: 0;
	}
	.plot {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		gap: 6px;
	}
	svg {
		width: 100%;
		height: 120px;
		overflow: visible;
	}
	.scale {
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		color: var(--muted);
		font-size: 0.72rem;
		font-variant-numeric: tabular-nums;
	}
	.scale.left {
		text-align: right;
	}
	.grid {
		stroke: var(--rule);
		stroke-dasharray: 2 4;
		vector-effect: non-scaling-stroke;
	}
	.area {
		opacity: 0.15;
	}
	polyline {
		fill: none;
		stroke-width: 2;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
	}
	.rate {
		stroke: var(--ink);
		stroke-dasharray: 4 3;
		opacity: 0.55;
	}
	.times {
		position: relative;
		height: 1.1em;
		margin: 0 2.2em;
		color: var(--muted);
		font-size: 0.72rem;
		font-variant-numeric: tabular-nums;
	}
	.times span {
		position: absolute;
		transform: translateX(-50%);
		white-space: nowrap;
	}
	figcaption {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.swatch {
		display: inline-block;
		width: 12px;
		height: 3px;
		margin-right: 6px;
		vertical-align: middle;
		border-radius: 2px;
	}
	.swatch.dashed {
		background: none;
		border-top: 2px dashed var(--ink);
	}
	.small {
		margin: 0;
		font-size: var(--step--1);
	}
</style>
