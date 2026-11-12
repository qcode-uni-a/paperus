/** Copies text to the clipboard; false if the browser would not.
 *
 * The clipboard API is there only over HTTPS and on localhost; a paperus on
 * the local network over plain HTTP (http://pc01:8000) has none. There the
 * older copy command still works, within a click: the text is put in a
 * field out of sight, selected and copied. */
export async function copyText(text: string): Promise<boolean> {
	if (window.isSecureContext && navigator.clipboard) {
		try {
			await navigator.clipboard.writeText(text);
			return true;
		} catch {
			// Refused (no permission, the page not in front): the old way.
		}
	}
	const field = document.createElement('textarea');
	field.value = text;
	field.setAttribute('readonly', '');
	field.style.position = 'fixed';
	field.style.top = '0';
	field.style.left = '0';
	field.style.opacity = '0';
	document.body.append(field);
	const focused = document.activeElement;
	field.select();
	let copied = false;
	try {
		copied = document.execCommand('copy');
	} catch {
		copied = false;
	}
	field.remove();
	if (focused instanceof HTMLElement) focused.focus();
	return copied;
}
