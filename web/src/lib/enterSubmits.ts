/** Enter in a field with suggestions (a datalist) submits its form, once.
 * Safari's WebKit only closes the suggestions shown with that Enter, so a
 * second one was needed; where the browser submitted, nothing more. */
export function enterSubmits(input: HTMLInputElement): () => void {
	const key = (event: KeyboardEvent) => {
		const form = input.form;
		if (event.key !== 'Enter' || event.isComposing || !form) return;
		let submitted = false;
		const submit = () => (submitted = true);
		form.addEventListener('submit', submit, { once: true });
		// The browser's own submitting happens within this key press.
		setTimeout(() => {
			form.removeEventListener('submit', submit);
			if (!submitted && input.isConnected) form.requestSubmit();
		});
	};
	input.addEventListener('keydown', key);
	return () => input.removeEventListener('keydown', key);
}
