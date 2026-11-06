import type { TransitionConfig } from 'svelte/transition';

/** A row filed away: it slides a little to the right and fades, then the
 * gap closes, so the rows below move up. With reduced motion, a short
 * fade. */
export function packUp(node: Element): TransitionConfig {
	if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
		return { duration: 150, css: (t) => `opacity: ${t}` };
	}
	const style = getComputedStyle(node);
	const height = (node as HTMLElement).offsetHeight;
	const top = parseFloat(style.paddingTop);
	const bottom = parseFloat(style.paddingBottom);
	const border = parseFloat(style.borderBottomWidth);
	return {
		duration: 700,
		css: (_t, u) => {
			// 0 → 1 while leaving: first filed away, then the gap closes.
			const away = Math.min(1, u / 0.55);
			const close = Math.max(0, (u - 0.35) / 0.65);
			const ease = (x: number) => x * x * (3 - 2 * x);
			const left = 1 - ease(close);
			return `
				overflow: hidden;
				transform-origin: left center;
				transform: translateX(${ease(away) * 56}px) scale(${1 - ease(away) * 0.05});
				opacity: ${1 - ease(away)};
				height: ${height * left}px;
				padding-top: ${top * left}px;
				padding-bottom: ${bottom * left}px;
				border-bottom-width: ${border * left}px;`;
		}
	};
}

/** No transition (the default for rows that just disappear). */
export function none(): TransitionConfig {
	return { duration: 0 };
}
