/** The small paperus button next to a paper on someone else's page (arXiv,
 * Google Scholar): dimmed, not in paperus yet, a click saves it with its
 * PDF; full with a check, in paperus, a click opens it there. In a shadow
 * root, so the page's styles leave it alone. */

export type State = 'save' | 'busy' | 'have' | 'failed';
export type Saving = Promise<{ ok: boolean; link?: string; text?: string } | undefined>;

export function paperusButton(
	icon: string,
	save: () => Saving
): { host: HTMLElement; set: (state: State, link?: string, why?: string) => void } {
	const host = document.createElement('span');
	host.className = 'paperus-save';
	const shadow = host.attachShadow({ mode: 'closed' });
	const style = document.createElement('style');
	style.textContent = `
		button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;
			margin: 0 6px; padding: 1px 6px 1px 2px; border-radius: 999px; font: 12px system-ui, sans-serif;
			color: #2338a8; vertical-align: middle; }
		button:hover { background: #e9ecfa; }
		button:focus-visible { outline: 2px solid #2338a8; }
		img { width: 16px; height: 16px; opacity: .6; filter: grayscale(1); transition: opacity .15s; }
		button.have img { opacity: 1; filter: none; }
		button.busy img { animation: pulse 1s infinite; }
		@keyframes pulse { 50% { opacity: .9 } }
		.label { display: none; }
		button:hover .label, button.busy .label, button.have .label { display: inline; }
		button.failed { color: #c0392b; }
	`;
	const element = document.createElement('button');
	const image = document.createElement('img');
	image.src = icon;
	image.alt = '';
	const label = document.createElement('span');
	label.className = 'label';
	element.append(image, label);
	shadow.append(style, element);
	let target: string | undefined;
	element.addEventListener('click', async (event) => {
		event.preventDefault();
		event.stopPropagation();
		if (target) {
			window.open(target, '_blank', 'noopener');
			return;
		}
		set('busy');
		const result = await save();
		if (result?.ok) set('have', result.link);
		else set('failed', undefined, result?.text);
	});
	function set(state: State, link?: string, why?: string): void {
		element.className = state;
		target = link;
		const words: Record<State, string> = {
			save: 'Save to paperus',
			busy: 'Saving…',
			have: '✓ in paperus',
			failed: 'Not saved'
		};
		label.textContent = words[state];
		element.title = why ?? (state === 'have' ? 'Open in paperus' : words[state]);
		element.setAttribute('aria-label', element.title);
	}
	set('save');
	return { host, set };
}
