/** Close a popup when the page scrolls or the window resizes. Clicks outside
 * and Escape already close popovers (and the search options handle them). */
export function closeOnScroll(close: () => void): () => void {
	const options = { capture: true, passive: true } as const;
	window.addEventListener('scroll', close, options);
	window.addEventListener('resize', close, options);
	return () => {
		window.removeEventListener('scroll', close, options);
		window.removeEventListener('resize', close, options);
	};
}
