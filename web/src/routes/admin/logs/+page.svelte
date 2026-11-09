<script lang="ts">
	import { errorMessage, readLogs } from '#lib/api/client.ts';
	import type { LogEntryOut } from '#lib/api/generated/types.gen.ts';
	import { formatDateTime } from '#lib/dates.svelte.ts';

	/** The log of the server, the worker and people's browser extensions
	 * (paperus.logbook), newest first; it follows new entries while the
	 * newest are shown. */
	type Level = 'debug' | 'info' | 'warning' | 'error';
	const LEVELS: [Level, string][] = [
		['debug', 'Everything'],
		['info', 'Info and up'],
		['warning', 'Warnings and errors'],
		['error', 'Errors']
	];
	const SOURCES: [string, string][] = [
		['', 'All'],
		['server', 'Server'],
		['worker', 'Worker'],
		['extension', 'Browser extensions']
	];

	let level = $state<Level>('info');
	let source = $state('');
	let words = $state('');
	let entries = $state<LogEntryOut[]>([]);
	let more = $state(false);
	let error = $state('');
	let loading = $state(false);

	function query(before?: number) {
		return {
			level,
			source: source ? [source] : undefined,
			q: words.trim() || undefined,
			before
		};
	}

	let latest = 0;
	async function load() {
		const request = ++latest;
		loading = true;
		const { data, error: failure } = await readLogs({ query: query() });
		if (request !== latest) return;
		loading = false;
		error = data ? '' : errorMessage(failure);
		entries = data?.entries ?? [];
		more = data?.more ?? false;
	}

	async function older() {
		const { data } = await readLogs({ query: query(entries.at(-1)?.id) });
		entries = [...entries, ...(data?.entries ?? [])];
		more = data?.more ?? false;
	}

	// Again when the filter changes (words after a pause), and every few
	// seconds while only the newest are shown.
	$effect(() => {
		void level;
		void source;
		const typed = words;
		const timer = setTimeout(load, typed ? 300 : 0);
		return () => clearTimeout(timer);
	});
	$effect(() => {
		const timer = setInterval(() => {
			if (entries.length <= 200 && !document.hidden) void load();
		}, 5000);
		return () => clearInterval(timer);
	});

	const SHOWN = 600;
</script>

<svelte:head><title>Logs · paperus</title></svelte:head>

<h1>Logs</h1>
<p class="muted">
	What the server, the worker and people’s browser extensions report, for the last two weeks. How
	much the server and worker write is set under Settings → Logging; the extensions send their
	warnings and errors.
</p>

<div class="filters">
	<label
		>Level
		<select bind:value={level}>
			{#each LEVELS as [value, label] (value)}<option {value}>{label}</option>{/each}
		</select>
	</label>
	<label
		>From
		<select bind:value={source}>
			{#each SOURCES as [value, label] (value)}<option {value}>{label}</option>{/each}
		</select>
	</label>
	<label class="words"
		>Words <input
			type="search"
			bind:value={words}
			placeholder="e.g. a paper’s title or DOI"
		/></label
	>
</div>

{#if error}<p class="error">{error}</p>{/if}
{#if !entries.length && !loading && !error}
	<p class="muted">Nothing logged{words.trim() ? ' with these words' : ''}.</p>
{/if}

<ol class="entries">
	{#each entries as entry (entry.id)}
		<li class="level-{entry.level}">
			<div class="meta">
				<time datetime={entry.at}>{formatDateTime(entry.at)}</time>
				<span class="level">{entry.level}</span>
				<span>{entry.source}{entry.username ? `, ${entry.username}` : ''}</span>
				<span class="logger">{entry.logger}</span>
			</div>
			<pre class="message">{entry.message.length > SHOWN
					? `${entry.message.slice(0, SHOWN)}…`
					: entry.message}</pre>
			{#if entry.message.length > SHOWN}
				<details>
					<summary>All of it</summary>
					<pre class="message">{entry.message}</pre>
				</details>
			{/if}
			{#if entry.context && Object.keys(entry.context).length}
				<dl class="context">
					{#each Object.entries(entry.context) as [key, value] (key)}
						<div>
							<dt>{key}</dt>
							<dd>{String(value)}</dd>
						</div>
					{/each}
				</dl>
			{/if}
		</li>
	{/each}
</ol>
{#if more}<p><button onclick={older}>Older entries</button></p>{/if}

<style>
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		align-items: end;
		margin: 16px 0;
	}
	.filters select,
	.filters input {
		font-weight: 400;
	}
	.filters label {
		display: grid;
		gap: 4px;
		font-size: var(--step--1);
		font-weight: 600;
		color: var(--muted);
	}
	.filters .words {
		flex: 1;
		min-width: 200px;
	}
	.entries {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.entries li {
		display: grid;
		gap: 4px;
		padding: 10px 12px;
		border-left: 3px solid var(--rule);
		border-bottom: 1px solid var(--rule);
	}
	.entries li.level-warning {
		border-left-color: var(--highlighter);
	}
	.entries li.level-error,
	.entries li.level-critical {
		border-left-color: var(--danger);
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		font-size: var(--step--1);
		color: var(--muted);
	}
	.level {
		font-weight: 700;
		text-transform: capitalize;
	}
	li.level-error .level,
	li.level-critical .level {
		color: var(--danger);
	}
	.logger {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
	}
	.message {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.85rem;
	}
	details summary {
		font-size: var(--step--1);
		color: var(--royal);
		cursor: pointer;
	}
	.context {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 14px;
		margin: 0;
		font-size: var(--step--1);
	}
	.context div {
		display: flex;
		gap: 4px;
		min-width: 0;
	}
	.context dt {
		color: var(--muted);
	}
	.context dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
</style>
