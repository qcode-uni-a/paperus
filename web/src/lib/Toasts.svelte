<script lang="ts">
	import { mdiAlertOutline, mdiCheckCircleOutline, mdiClose, mdiInformationOutline } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import { dismiss, hold, resume, toasts, type ToastKind } from '#lib/toasts.svelte.ts';

	const ICONS: Record<ToastKind, string> = {
		info: mdiInformationOutline,
		success: mdiCheckCircleOutline,
		warning: mdiAlertOutline
	};
</script>

<div class="toasts" aria-live="polite">
	{#each toasts.list as toast (toast.id)}
		<div
			class="toast {toast.kind}"
			role="status"
			onmouseenter={() => hold(toast.id)}
			onmouseleave={() => resume(toast.id)}
			onfocusin={() => hold(toast.id)}
			onfocusout={() => resume(toast.id)}
		>
			<span class="mark"><Icon path={ICONS[toast.kind]} size={22} /></span>
			<div class="body">
				<strong>{toast.title}</strong>
				{#if toast.text}<p>{toast.text}</p>{/if}
				{#if toast.link}<a href={toast.link.href} onclick={() => dismiss(toast.id)}
						>{toast.link.label}</a
					>{/if}
			</div>
			<button class="close" onclick={() => dismiss(toast.id)} aria-label="Close">
				<Icon path={mdiClose} size={18} />
			</button>
		</div>
	{/each}
</div>

<style>
	/* Top right, below the bar. */
	.toasts {
		position: fixed;
		top: 84px;
		right: 16px;
		z-index: 60;
		display: grid;
		gap: 10px;
		width: min(380px, calc(100vw - 32px));
		pointer-events: none;
	}
	.toast {
		display: flex;
		gap: 12px;
		align-items: flex-start;
		padding: 14px 12px 14px 16px;
		border: 1px solid var(--rule);
		border-left: 4px solid var(--royal);
		border-radius: 14px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
		pointer-events: auto;
		animation: in 0.2s ease-out;
	}
	.toast.success {
		border-left-color: var(--success);
	}
	.toast.warning {
		border-left-color: var(--highlighter);
	}
	.mark {
		display: flex;
		color: var(--royal);
	}
	.success .mark {
		color: var(--success);
	}
	.body {
		flex: 1;
		min-width: 0;
		display: grid;
		gap: 2px;
	}
	.body p {
		margin: 0;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.body a {
		justify-self: start;
		margin-top: 4px;
		font-size: var(--step--1);
		font-weight: 600;
	}
	.close {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		padding: 0;
		border: none;
		background: none;
		color: var(--muted);
	}
	@keyframes in {
		from {
			opacity: 0;
			transform: translateY(-6px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.toast {
			animation: none;
		}
	}
</style>
