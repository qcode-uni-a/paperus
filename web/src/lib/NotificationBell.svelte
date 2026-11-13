<script lang="ts">
	import { live } from '#lib/live.svelte.ts';
	import { mdiBellOutline, mdiClose } from '@mdi/js';
	import { resolve } from '$app/paths';
	import {
		apiHref,
		dismissNotification,
		dismissNotifications,
		listNotifications,
		markNotificationsRead
	} from '#lib/api/client.ts';
	import type { NotificationOut } from '#lib/api/generated/types.gen.ts';
	import { closeOnScroll } from '#lib/dismiss.ts';
	import { ago } from '#lib/format.ts';
	import Icon from '#lib/Icon.svelte';

	/** What happened that concerns the person (server: paperus.notifications):
	 * papers added to their groups or shared with them, being added to a
	 * group, published versions and corrections found, the zips of their
	 * exports as they are written. The count of
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
		celebrate();
	}

	/** One's own paper published: a few sparkles round the bell, once in
	 * this page while it is new, and a star on its line in the list. */
	const yours = (notice: NotificationOut) =>
		notice.kind === 'published' && Boolean((notice.data as Record<string, unknown>).yours);
	const SPARKLING = 3200;
	let sparkle = $state(false);
	const celebrated = new Set<number>();
	function celebrate() {
		const news = notices.filter((n) => !n.read && yours(n) && !celebrated.has(n.id));
		if (!news.length) return;
		for (const notice of news) celebrated.add(notice.id);
		sparkle = true;
		setTimeout(() => (sparkle = false), SPARKLING);
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

	/** Gone from the list: one, or all. */
	function dismiss(notice: NotificationOut) {
		notices = notices.filter((n) => n.id !== notice.id);
		void dismissNotification({ path: { notification_id: notice.id } });
	}
	function dismissAll() {
		notices = [];
		void dismissNotifications();
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
			// In a group of people: shared with one (its name is just its people).
			const what = count === 1 ? `“${d.title || 'a paper'}”` : plural(count);
			const text = d.people
				? `${d.actor} shared ${what} with you`
				: `${d.actor} added ${what} to ${d.group}`;
			return { text, href: count === 1 ? item : `${resolve('/')}?owner=${d.library_id}` };
		}
		if (notice.kind === 'joined') {
			const papers = Number(d.papers ?? 0);
			return d.people
				? {
						text: `${d.actor} shared ${plural(papers)} with you (${d.group})`,
						href: `${resolve('/')}?owner=${d.library_id}`
					}
				: {
						text: `${d.actor} added you to ${d.group}`,
						href: `${resolve('/manage/groups')}?group=${d.group_id}`
					};
		}
		if (notice.kind === 'erratum') {
			return { text: `A correction to “${d.title}”: ${d.erratum}`, href: item };
		}
		if (notice.kind === 'published') {
			const where = [d.journal, d.year ? `(${d.year})` : null].filter(Boolean).join(' ');
			if (d.yours)
				return {
					text: `Congratulations! Your paper is ${where ? `published in ${where}` : 'out'}: “${d.title}”`,
					href: item
				};
			return { text: `Published${where ? ` in ${where}` : ''}: “${d.title}”`, href: item };
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
	{#if sparkle}<span class="sparkles" aria-hidden="true"><i></i><i></i><i></i></span>{/if}
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
	<div class="head">
		<h2>Notifications</h2>
		{#if notices.length}<button class="link" onclick={dismissAll}>Clear all</button>{/if}
	</div>
	{#if notices.length}
		<ul>
			{#each notices as notice (notice.id)}
				{@const { text, href, reload } = told(notice)}
				<li class:new={fresh.has(notice.id)} class:yours={yours(notice)}>
					{#if yours(notice)}<span class="sparkles round" aria-hidden="true"
							><i></i><i></i><i></i><i></i></span
						>{/if}
					<a {href} data-sveltekit-reload={reload || undefined} onclick={() => menu?.hidePopover()}
						>{#if yours(notice)}<span class="star" aria-hidden="true"></span>{/if}{text}</a
					>
					<time datetime={notice.at}>{ago(notice.at)}</time>
					<button
						class="dismiss"
						aria-label="Dismiss"
						title="Dismiss"
						onclick={() => dismiss(notice)}><Icon path={mdiClose} size={16} /></button
					>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="muted">
			Nothing yet. Papers others add to your groups or share with you, published versions and
			corrections found for your papers, and your exports as they are ready, are told here.
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
	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 8px;
	}
	.head .link {
		padding: 2px 6px;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
		font-weight: 550;
	}
	h2 {
		margin: 0;
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
		position: relative;
		display: grid;
		gap: 2px;
		padding: 8px 34px 8px 10px;
		border-radius: 8px;
	}
	/* Dismiss: there on hover (always on a touch screen). */
	.dismiss {
		position: absolute;
		top: 6px;
		right: 4px;
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
		color: var(--muted);
		opacity: 0;
	}
	li:hover .dismiss,
	.dismiss:focus-visible {
		opacity: 1;
	}
	.dismiss:hover {
		background: var(--rail);
		color: var(--ink);
	}
	@media (pointer: coarse) {
		.dismiss {
			opacity: 1;
		}
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
	/* One's own paper published: gold sparkles, briefly. */
	.sparkles {
		position: absolute;
		inset: -3px;
		pointer-events: none;
	}
	.sparkles i,
	.star {
		display: block;
		background: color-mix(in srgb, var(--highlighter) 55%, var(--tag-amber-ink));
		clip-path: polygon(50% 0, 61% 39%, 100% 50%, 61% 61%, 50% 100%, 39% 61%, 0 50%, 39% 39%);
	}
	.sparkles i {
		position: absolute;
		width: 9px;
		height: 9px;
		opacity: 0;
		animation: twinkle 1.3s ease-in-out 2 both;
	}
	.sparkles i:nth-child(1) {
		top: 0;
		left: 1px;
	}
	.sparkles i:nth-child(2) {
		top: 5px;
		right: -3px;
		width: 7px;
		height: 7px;
		animation-delay: 0.3s;
	}
	.sparkles i:nth-child(3) {
		bottom: -1px;
		left: 9px;
		width: 6px;
		height: 6px;
		animation-delay: 0.6s;
	}
	@keyframes twinkle {
		0% {
			opacity: 0;
			transform: scale(0.2) rotate(0);
		}
		45% {
			opacity: 1;
			transform: scale(1) rotate(45deg);
		}
		100% {
			opacity: 0;
			transform: scale(0.2) rotate(90deg);
		}
	}
	li.yours {
		background: color-mix(in srgb, var(--highlighter) 16%, transparent);
	}
	/* Round one's own published paper in the list, as the list opens. */
	.sparkles.round {
		inset: 0;
	}
	.round i:nth-child(1) {
		top: -4px;
		left: 14px;
	}
	.round i:nth-child(2) {
		top: 6px;
		right: 6px;
		left: auto;
		width: 8px;
		height: 8px;
	}
	.round i:nth-child(3) {
		bottom: -3px;
		left: 45%;
		width: 7px;
		height: 7px;
	}
	.round i:nth-child(4) {
		bottom: 10px;
		left: -3px;
		width: 6px;
		height: 6px;
		animation-delay: 0.9s;
	}
	.star {
		display: inline-block;
		width: 0.85em;
		height: 0.85em;
		margin-right: 6px;
		vertical-align: -0.05em;
		animation: shine 1.2s ease-out both;
	}
	@keyframes shine {
		from {
			transform: scale(0.3) rotate(-45deg);
		}
		60% {
			transform: scale(1.2) rotate(10deg);
		}
		to {
			transform: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.sparkles {
			display: none;
		}
		.star {
			animation: none;
		}
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
