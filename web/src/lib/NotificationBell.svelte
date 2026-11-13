<script lang="ts">
	import { live } from '#lib/live.svelte.ts';
	import { mdiBellOutline } from '@mdi/js';
	import { resolve } from '$app/paths';
	import { apiHref, listNotifications, markNotificationsRead } from '#lib/api/client.ts';
	import type { NotificationOut } from '#lib/api/generated/types.gen.ts';
	import { closeOnScroll } from '#lib/dismiss.ts';
	import { ago } from '#lib/format.ts';
	import Icon from '#lib/Icon.svelte';

	/** What happened that concerns the person (server: paperus.notifications):
	 * papers added to their groups, published versions found, the zips of
	 * their exports as they are written. The count of
	 * unread ones on the bell; opening the list marks them read (they stay
	 * marked as new while it is open). */
	const WIDTH = 340;
	let notices = $state<NotificationOut[]>([]);
	let unread = $state(0);
	let menu = $state<HTMLElement>();
	let button = $state<HTMLElement>();
	/** Shown as new while the list is open, though read now. */
	let fresh = $state(new Set<number>());

	async function load() {
		const { data } = await listNotifications();
		if (!data) return;
		notices = data.notifications;
		unread = data.unread;
	}

	// At once when the library changes (a paper added to a group, say).
	$effect(() => {
		if (live.changes) void load();
	});
	$effect(() => {
		void load();
		const timer = setInterval(() => !document.hidden && load(), 60_000);
		const focus = () => load();
		window.addEventListener('focus', focus);
		return () => {
			clearInterval(timer);
			window.removeEventListener('focus', focus);
		};
	});
	$effect(() => closeOnScroll(() => menu?.hidePopover()));

	/** On the bell's click, just before the list opens (or closes). */
	async function opening() {
		if (menu?.matches(':popover-open')) return;
		await load();
		fresh = new Set(notices.filter((n) => !n.read).map((n) => n.id));
		if (unread) {
			unread = 0;
			await markNotificationsRead({ body: {} });
		}
	}

	/** Below the bell, right-aligned with it, within the window. */
	function place() {
		if (!menu || !button) return;
		const box = button.getBoundingClientRect();
		const width = Math.min(WIDTH, window.innerWidth - 16);
		menu.style.setProperty('--width', `${width}px`);
		menu.style.setProperty('--top', `${box.bottom + 6}px`);
		menu.style.setProperty(
			'--left',
			`${Math.max(8, Math.min(box.right - width, window.innerWidth - width - 8))}px`
		);
	}

	const plural = (n: number) => `${n.toLocaleString()} ${n === 1 ? 'paper' : 'papers'}`;

	/** What it says, and where it leads. */
	function told(notice: NotificationOut): { text: string; href: string; reload?: boolean } {
		const d = notice.data as Record<string, string | number | null>;
		const item = d.item_id ? resolve('/items/[id]', { id: String(d.item_id) }) : resolve('/');
		if (notice.kind === 'added') {
			const count = Number(d.count ?? 1);
			return count === 1
				? { text: `${d.actor} added “${d.title || 'a paper'}” to ${d.group}`, href: item }
				: {
						text: `${d.actor} added ${plural(count)} to ${d.group}`,
						href: `${resolve('/')}?owner=${d.library_id}`
					};
		}
		if (notice.kind === 'published') {
			const where = [d.journal, d.year ? `(${d.year})` : null].filter(Boolean).join(' ');
			return {
				text: `Published${where ? ` in ${where}` : ''}: “${d.title}”`,
				href: item
			};
		}
		// An export's zip, to download: a link the browser follows itself
		// (once the zip is gone, the server sends it on to the exports).
		if (notice.kind === 'export') {
			const part = Number(d.part ?? 1);
			const parts = Number(d.parts ?? 1);
			return {
				text:
					parts === 1
						? 'Your export is ready to download'
						: part < parts
							? `Part ${part} of ${parts} of your export is ready to download`
							: `Your export is complete: part ${part} of ${parts} is ready to download`,
				href: apiHref(`/api/exports/${d.export_id}/parts/${part}`),
				reload: true
			};
		}
		if (notice.kind === 'import') {
			const href = `${resolve('/settings')}?open=import`;
			if (d.failed) return { text: `Your import of ${d.filename} failed: see why`, href };
			const told = [
				`${plural(Number(d.added ?? 0))} added${d.own_copies ? ` (${d.own_copies} also in a group, as your own)` : ''}`,
				d.found ? `${d.found} already in the library` : '',
				d.found_elsewhere ? `${d.found_elsewhere} already in other libraries` : '',
				d.problems ? `${d.problems} ${d.problems === 1 ? 'problem' : 'problems'}` : ''
			].filter(Boolean);
			return { text: `Import of ${d.filename} done: ${told.join(', ')}`, href };
		}
		if (notice.kind === 'export_failed') {
			return {
				text: 'Your export failed: see why, and start it again',
				href: `${resolve('/settings')}?open=export`
			};
		}
		return { text: String(d.title ?? notice.kind), href: item };
	}
</script>

<button
	bind:this={button}
	class="bell"
	popovertarget="notifications"
	onclick={opening}
	aria-haspopup="true"
	aria-label={unread ? `Notifications: ${unread} new` : 'Notifications'}
	title={unread ? `${unread} new` : 'Notifications'}
>
	<Icon path={mdiBellOutline} size={20} />
	{#if unread}<span class="count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>{/if}
</button>
<div
	id="notifications"
	popover
	bind:this={menu}
	class="list"
	role="dialog"
	aria-label="Notifications"
	onbeforetoggle={(event) => {
		place();
		if (event.newState === 'closed') fresh = new Set();
	}}
>
	<h2>Notifications</h2>
	{#if notices.length}
		<ul>
			{#each notices as notice (notice.id)}
				{@const { text, href, reload } = told(notice)}
				<li class:new={fresh.has(notice.id)}>
					<a {href} data-sveltekit-reload={reload || undefined} onclick={() => menu?.hidePopover()}
						>{text}</a
					>
					<time datetime={notice.at}>{ago(notice.at)}</time>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="muted">
			Nothing yet. Papers others add to your groups, published versions found for your preprints,
			and your exports as they are ready, are told here.
		</p>
	{/if}
</div>

<style>
	.bell {
		position: relative;
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border-color: transparent;
		background: none;
		color: var(--ink);
	}
	.bell:hover {
		background: var(--rail);
	}
	.count {
		position: absolute;
		top: 2px;
		right: 0;
		min-width: 17px;
		height: 17px;
		padding: 0 4px;
		border-radius: 999px;
		background: var(--royal);
		color: var(--surface);
		font-size: 0.68rem;
		font-weight: 700;
		line-height: 17px;
		text-align: center;
	}
	.list {
		position: fixed;
		inset: var(--top) auto auto var(--left);
		margin: 0;
		padding: 12px;
		width: var(--width);
		max-height: min(70vh, 520px);
		overflow-y: auto;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	h2 {
		margin: 0 0 8px;
		font-size: var(--step-0);
		font-family: var(--sans);
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 2px;
	}
	li {
		display: grid;
		gap: 2px;
		padding: 8px 10px;
		border-radius: 8px;
	}
	li.new {
		background: color-mix(in srgb, var(--royal) 8%, transparent);
	}
	li a {
		color: var(--ink);
		text-decoration: none;
		line-height: 1.35;
	}
	li a:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	time {
		font-size: var(--step--1);
		color: var(--muted);
	}
	p {
		margin: 0;
		font-size: var(--step--1);
	}
</style>
