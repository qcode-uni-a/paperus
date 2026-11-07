<script lang="ts">
	import { createToken, errorMessage, listTokens, revokeToken } from '#lib/api/client.ts';
	import type { CreatedToken, Scope, TokenOut } from '#lib/api/generated/types.gen.ts';
	import { formatDate } from '#lib/dates.svelte.ts';
	import { ago } from '#lib/format.ts';
	import { libraryName, organize } from '#lib/organize.svelte.ts';

	/** Settings → Access tokens: for scripts and AI assistants (MCP). */
	const SCOPES: { value: Scope; label: string }[] = [
		{ value: 'search', label: 'Search' },
		{ value: 'papers.read', label: 'Read papers, tags and collections' },
		{ value: 'files.read', label: 'Read files (PDFs, notes)' },
		{ value: 'groups.read', label: 'See groups and members' },
		{ value: 'papers.write', label: 'Add and change papers' },
		{ value: 'tags.write', label: 'Tag papers' },
		{ value: 'collections.write', label: 'Change collections' },
		{ value: 'notes.write', label: 'Write and change notes' }
	];
	const PRESETS: { id: string; label: string; help: string; scopes: Scope[] }[] = [
		{
			id: 'assistant',
			label: 'AI assistant',
			help: 'search and read; changes nothing',
			scopes: ['search', 'papers.read', 'files.read']
		},
		{
			id: 'helper',
			label: 'AI assistant that may write',
			help: 'also writes notes, tags papers and adds papers by DOI',
			scopes: ['search', 'papers.read', 'files.read', 'notes.write', 'tags.write', 'papers.write']
		},
		{
			id: 'all',
			label: 'Everything',
			help: 'all a token can do (never your account or administration)',
			scopes: SCOPES.map((s) => s.value)
		},
		{ id: 'custom', label: 'Choose', help: 'pick the rights one by one', scopes: [] }
	];

	let tokens = $state<TokenOut[]>([]);
	let error = $state('');

	async function load() {
		const { data } = await listTokens();
		tokens = data ?? [];
	}
	$effect(() => {
		load();
	});

	let dialog = $state<HTMLDialogElement>();
	let name = $state('');
	let preset = $state('assistant');
	let custom = $state<Scope[]>([]);
	let limited = $state(false);
	let owners = $state<string[]>([]);
	let expiry = $state<number | null>(null);
	let created = $state<CreatedToken | null>(null);
	let saving = $state(false);
	let copied = $state(false);

	const scopes = $derived(
		preset === 'custom' ? custom : (PRESETS.find((p) => p.id === preset)?.scopes ?? [])
	);

	function openNew() {
		name = '';
		preset = 'assistant';
		custom = [];
		limited = false;
		owners = [];
		expiry = null;
		created = null;
		error = '';
		dialog?.showModal();
	}

	async function create(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		saving = true;
		const { data, error: failure } = await createToken({
			body: {
				name,
				scopes,
				library_ids: limited ? owners : null,
				expires_in_days: expiry
			}
		});
		saving = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		created = data;
		await load();
	}

	async function revoke(token: TokenOut) {
		if (!confirm(`Revoke “${token.name}”? Whatever uses it stops working at once.`)) return;
		await revokeToken({ path: { token_id: token.id } });
		await load();
	}

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch {
			// Only over HTTPS or localhost; otherwise select it for copying by hand.
			const code = document.querySelector('.secret code');
			if (code) getSelection()?.selectAllChildren(code);
		}
	}

	const server = $derived(`${location.origin}/mcp`);
	function summary(token: TokenOut): string {
		const labels = token.scopes.map((s) => SCOPES.find((o) => o.value === s)?.label ?? s);
		return labels.join(', ');
	}
</script>

<p class="muted">
	For AI assistants and scripts. A token acts as you, limited to the rights you give it, and never
	manages your account or the administration.
</p>

{#if tokens.length}
	<ul class="tokens">
		{#each tokens as token (token.id)}
			<li>
				<div>
					<strong>{token.name}</strong> <code>{token.hint}</code>
					<small>{summary(token)}</small>
					<small>
						{token.library_ids
							? `Only ${token.library_ids.map((id) => libraryName(id)).join(', ')}. `
							: ''}{token.last_used_at
							? `Used ${ago(token.last_used_at)}`
							: 'Not used yet'}{token.expires_at
							? `; expires ${formatDate(token.expires_at)}`
							: ''}.
					</small>
				</div>
				<button class="link danger" onclick={() => revoke(token)}>Revoke</button>
			</li>
		{/each}
	</ul>
{/if}
<div><button onclick={openNew}>New token</button></div>

<dialog bind:this={dialog} aria-labelledby="token-title">
	{#if !created}
		<form onsubmit={create}>
			<h2 id="token-title">New access token</h2>
			<label
				>Name <input
					bind:value={name}
					required
					maxlength="100"
					placeholder="e.g. Claude on my laptop"
				/></label
			>
			<fieldset>
				<legend>What it may do</legend>
				{#each PRESETS as option (option.id)}
					<label class="option"
						><input type="radio" bind:group={preset} value={option.id} />
						<span><strong>{option.label}</strong><small>{option.help}</small></span></label
					>
				{/each}
				{#if preset === 'custom'}
					<div class="scopes">
						{#each SCOPES as scope (scope.value)}
							<label class="check"
								><input type="checkbox" bind:group={custom} value={scope.value} />
								{scope.label}</label
							>
						{/each}
					</div>
				{/if}
			</fieldset>
			{#if organize.libraries.length > 1}
				<fieldset>
					<legend>Whose things</legend>
					<label class="option"
						><input type="radio" bind:group={limited} value={false} />
						<span><strong>Everything I can see</strong></span></label
					>
					<label class="option"
						><input type="radio" bind:group={limited} value={true} />
						<span><strong>Only some</strong></span></label
					>
					{#if limited}
						<div class="scopes">
							{#each organize.libraries as library (library.id)}
								<label class="check"
									><input type="checkbox" bind:group={owners} value={library.id} />
									{libraryName(library.id)}</label
								>
							{/each}
						</div>
					{/if}
				</fieldset>
			{/if}
			<label
				>Expires
				<select bind:value={expiry}>
					<option value={null}>Never</option>
					<option value={30}>In 30 days</option>
					<option value={90}>In 90 days</option>
					<option value={365}>In a year</option>
				</select>
			</label>
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button type="button" onclick={() => dialog?.close()}>Cancel</button>
				<button class="primary" disabled={saving || !scopes.length || (limited && !owners.length)}
					>Create token</button
				>
			</div>
		</form>
	{:else}
		<div class="created">
			<h2 id="token-title">Token created</h2>
			<p>Copy it now: it is shown only this once.</p>
			<div class="secret">
				<code>{created.token}</code>
				<button onclick={() => copy(created?.token ?? '')}>{copied ? 'Copied' : 'Copy'}</button>
			</div>
			<h3>Connect an AI assistant</h3>
			<p class="muted">paperus speaks MCP at <code>{server}</code>.</p>
			<details open>
				<summary>Claude Code</summary>
				<pre><code
						>claude mcp add --transport http paperus {server} \
  --header "Authorization: Bearer {created.token}"</code
					></pre>
			</details>
			<details>
				<summary>Claude Desktop, and other clients with a JSON config</summary>
				<pre><code
						>{JSON.stringify(
							{
								mcpServers: {
									paperus: {
										command: 'npx',
										args: [
											'mcp-remote',
											server,
											'--header',
											`Authorization: Bearer ${created.token}`
										]
									}
								}
							},
							null,
							2
						)}</code
					></pre>
			</details>
			<details>
				<summary>Cursor and clients that take a URL with headers</summary>
				<pre><code
						>{JSON.stringify(
							{
								mcpServers: {
									paperus: {
										url: server,
										headers: { Authorization: `Bearer ${created.token}` }
									}
								}
							},
							null,
							2
						)}</code
					></pre>
			</details>
			<div class="buttons">
				<button class="primary" onclick={() => dialog?.close()}>Done</button>
			</div>
		</div>
	{/if}
</dialog>

<style>
	p {
		margin: 0 0 12px;
	}
	.tokens {
		margin: 0 0 12px;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 2px;
	}
	.tokens li {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 12px;
		padding: 10px 0;
		border-bottom: 1px solid var(--rule);
	}
	.tokens div {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	code {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.86em;
		overflow-wrap: anywhere;
	}
	.link {
		padding: 2px 6px;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
	}
	.link.danger {
		color: var(--danger);
	}
	dialog {
		width: min(600px, calc(100vw - 32px));
		max-height: min(860px, calc(100dvh - 32px));
		padding: 22px 24px 22px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
		overflow-y: auto;
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	form,
	.created {
		display: grid;
		gap: 14px;
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	h3 {
		margin: 6px 0 0;
		font-size: var(--step-1);
	}
	form > label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	form > label input,
	form > label select {
		font-weight: 400;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: none;
		display: grid;
		gap: 4px;
	}
	legend {
		padding: 0;
		margin-bottom: 6px;
		font-weight: 600;
	}
	.option {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 4px 0;
	}
	.option input,
	.check input {
		width: auto;
		margin-top: 4px;
	}
	.option span {
		display: grid;
	}
	.scopes {
		display: grid;
		gap: 4px;
		margin: 4px 0 0 26px;
	}
	.check {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}
	.secret {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 12px;
		border: 1px solid var(--highlighter);
		border-radius: 8px;
		background: color-mix(in srgb, var(--highlighter) 14%, var(--surface));
	}
	.secret code {
		flex: 1;
		min-width: 0;
	}
	details summary {
		cursor: pointer;
		font-weight: 600;
	}
	pre {
		margin: 8px 0 0;
		padding: 10px 12px;
		overflow-x: auto;
		border-radius: 8px;
		background: var(--rail);
		font-size: 0.82em;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
