<script lang="ts">
	import { mdiCheckCircle, mdiCircleOutline } from '@mdi/js';
	import { resolve } from '$app/paths';
	import { gettingStarted, markHintSeen } from '#lib/api/client.ts';
	import type { GettingStarted, GpuStep } from '#lib/api/generated/types.gen.ts';
	import Icon from '#lib/Icon.svelte';
	import { session } from '#lib/session.svelte.ts';
	import { uploads } from '#lib/uploads.svelte.ts';

	/** The first steps, on the library page until done or hidden; for
	 * administrators also what the server needs before others rely on it. */
	const HINT = 'getting-started';
	const EXTENSION_HELP = 'https://github.com/qcode-uni-a/paperus/tree/main/extension#readme';
	const GPU_HELP =
		'https://github.com/qcode-uni-a/paperus/blob/main/docs/operations.md#on-an-nvidia-gpu';

	/** Whether the steps are shown (the page leaves out its own hint then). */
	let { shown = $bindable(false) }: { shown?: boolean } = $props();

	let steps = $state<GettingStarted | null>(null);
	const hidden = $derived(session.user?.seen_hints.includes(HINT) ?? true);

	$effect(() => {
		if (hidden) return;
		void uploads.finished;
		gettingStarted().then(({ data }) => (steps = data ?? null));
	});

	type Step = {
		done: boolean;
		title: string;
		text: string;
		links: [string, string][];
		/** Said also once done. */
		doneText?: string;
	};

	/** Whether the machine learning service uses the machine's GPU, and if
	 * not, what to change. */
	function gpuStep(gpu: GpuStep): Step {
		const links: [string, string][] = [[GPU_HELP, 'On an NVIDIA GPU']];
		const has = `This machine has a GPU, the ${gpu.card}`;
		const faster =
			'search by meaning, OCR and reranking run many times faster on it (embedding about 20 times)';
		switch (gpu.advice) {
			case 'in_use':
				return {
					done: true,
					title: 'Machine learning on the GPU',
					text: '',
					doneText: `Runs on the ${gpu.card}.`,
					links: []
				};
			case 'use_cuda_image':
				return {
					done: false,
					title: 'Use the GPU for machine learning',
					text: `${has}, but the ML service runs its CPU image. With the -cuda image, ${faster}.`,
					links
				};
			case 'pass_gpu':
				return {
					done: false,
					title: 'Give the ML service the GPU',
					text: `${has}, but the ML service runs on the CPU${gpu.problem ? `: ${gpu.problem}` : ''}. Pass the GPU to its container (devices in compose.yaml).`,
					links
				};
			case 'update_driver':
				return {
					done: false,
					title: 'Update the NVIDIA driver',
					text: `${has}. The ML service's -cuda image needs NVIDIA's driver ${gpu.driver_needed} or newer; this machine has ${gpu.driver}.`,
					links
				};
			case 'install_driver':
				return {
					done: false,
					title: 'Install the NVIDIA driver',
					text: `${has}. With NVIDIA's driver (${gpu.driver_needed} or newer) and the ML service's -cuda image, ${faster}.`,
					links
				};
		}
	}

	const mine = $derived<Step[]>(
		steps
			? [
					{
						done: steps.papers,
						title: 'Add your first paper',
						text: 'Drop PDFs anywhere in this window, or use Add for a DOI or an arXiv link.',
						links: []
					},
					{
						done: steps.imported,
						title: 'Bring your library from Zotero',
						text: 'Or from Mendeley, JabRef or EndNote: its export, with the files.',
						links: [[resolve('/import'), 'Import a library']]
					},
					{
						done: steps.extension,
						title: 'Save papers while you browse',
						text: 'The browser extension saves the paper you are reading, with its PDF, in one click.',
						links: [
							[EXTENSION_HELP, 'Install the extension'],
							[resolve('/settings/extension'), 'Connect it']
						]
					},
					{
						done: steps.assistant,
						title: 'Ask your AI assistant about your papers',
						text: `Add ${location.origin}/mcp as a connector in claude.ai or ChatGPT, or make an access token for another assistant.`,
						links: [[resolve('/settings'), 'Settings']]
					}
				]
			: []
	);

	const server = $derived<Step[]>(
		steps?.server
			? [
					{
						done: steps.server.backups,
						title: 'Turn on backups',
						text: 'They are switched off: nothing is backed up on its own.',
						links: [[resolve('/admin/backups'), 'Backups']]
					},
					{
						done: steps.server.contact_email,
						title: 'Give a contact email',
						text: 'Crossref and Unpaywall ask for one, and answer more reliably with it.',
						links: [[`${resolve('/admin/settings')}?open=server`, 'Server settings']]
					},
					{
						done: steps.server.search,
						title: 'Start the machine learning service',
						text: 'It does not answer: search finds words only, not meaning, and scans stay unread.',
						links: [[resolve('/admin/server'), 'Server status']]
					},
					...(steps.server.gpu ? [gpuStep(steps.server.gpu)] : []),
					{
						done: steps.server.people,
						title: 'Add people',
						text: 'Make accounts for them, or let them log in with OIDC.',
						links: [
							[resolve('/admin/users'), 'Users'],
							[`${resolve('/admin/settings')}?open=authentication`, 'OIDC login']
						]
					}
				]
			: []
	);

	const all = $derived([...mine, ...server]);
	const done = $derived(all.filter((step) => step.done).length);
	$effect(() => {
		shown = !hidden && steps !== null && done < all.length;
	});

	async function hide() {
		if (!session.user) return;
		session.user.seen_hints = [...session.user.seen_hints, HINT];
		await markHintSeen({ path: { hint: HINT } });
	}
</script>

{#if shown}
	<section class="start" aria-labelledby="getting-started">
		<header>
			<h2 id="getting-started">Getting started</h2>
			<span class="progress">{done} of {all.length} done</span>
			<button class="hide" onclick={hide}>Hide</button>
		</header>
		{@render list(mine)}
		{#if server.length}
			<h3>Your server</h3>
			{@render list(server)}
		{/if}
	</section>
{/if}

{#snippet list(items: Step[])}
	<ul>
		{#each items as step (step.title)}
			<li class:done={step.done}>
				<span class="mark" aria-label={step.done ? 'Done' : 'To do'} role="img">
					<Icon path={step.done ? mdiCheckCircle : mdiCircleOutline} size={20} />
				</span>
				<div>
					<strong>{step.title}</strong>
					{#if step.done && step.doneText}
						<p>{step.doneText}</p>
					{/if}
					{#if !step.done}
						<p>{step.text}</p>
						{#if step.links.length}
							<p class="links">
								{#each step.links as [href, label] (href)}
									<a
										{href}
										target={href.startsWith('http') ? '_blank' : undefined}
										rel={href.startsWith('http') ? 'noopener' : undefined}>{label}</a
									>
								{/each}
							</p>
						{/if}
					{/if}
				</div>
			</li>
		{/each}
	</ul>
{/snippet}

<style>
	.start {
		margin: 8px 0 28px;
		padding: 18px 20px 8px;
		max-width: 680px;
		border: 1px solid var(--rule);
		border-left: 4px solid var(--highlighter);
		border-radius: 12px;
		background: var(--surface);
	}
	header {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 12px;
		margin-bottom: 8px;
	}
	h2 {
		margin: 0;
		font-size: var(--step-1);
	}
	h3 {
		margin: 12px 0 4px;
		font-family: inherit;
		font-size: var(--step--1);
		font-weight: 600;
		color: var(--muted);
	}
	.progress {
		color: var(--muted);
		font-size: var(--step--1);
		white-space: nowrap;
	}
	.hide {
		margin-left: auto;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: flex;
		gap: 12px;
		padding: 10px 0;
		border-top: 1px solid var(--rule);
	}
	li:first-child {
		border-top: none;
	}
	.mark {
		flex: none;
		color: var(--faint);
		line-height: 0;
		padding-top: 1px;
	}
	.done .mark {
		color: var(--success);
	}
	.done strong {
		color: var(--muted);
		font-weight: 500;
	}
	p {
		margin: 2px 0 0;
		color: var(--muted);
		overflow-wrap: anywhere;
	}
	.links {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 16px;
		margin-top: 4px;
	}
</style>
