import DOMPurify from 'dompurify';
import { Marked } from 'marked';

// Links in a note open in a new tab, away from paperus.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
	if (node.tagName === 'A' && node.getAttribute('href')) {
		node.setAttribute('target', '_blank');
		node.setAttribute('rel', 'noreferrer');
	}
});

/** Math between $…$ or $$…$$, or in a ```math block. */
const MATH = /\$|```math/;

let withMath: Promise<Marked> | null = null;

/** A Markdown reader with KaTeX, loaded the first time a note has math. */
function mathReader(): Promise<Marked> {
	withMath ??= Promise.all([
		import('katex'),
		import('marked-katex-extension'),
		import('katex/dist/katex.min.css')
	]).then(([{ default: katex }, { default: markedKatex }]) => {
		const options = { throwOnError: false, output: 'htmlAndMathml' as const };
		return new Marked(markedKatex(options), {
			renderer: {
				code({ text, lang }) {
					if (lang !== 'math') return false;
					return katex.renderToString(text, { ...options, displayMode: true });
				}
			}
		});
	});
	return withMath;
}

const plain = new Marked();

/** Markdown as safe HTML: the file is someone's upload, never trust its HTML. */
export async function renderMarkdown(text: string): Promise<string> {
	const reader = MATH.test(text) ? await mathReader() : plain;
	const html = reader.parse(text, { async: false, gfm: true });
	return DOMPurify.sanitize(html);
}
