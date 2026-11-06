/** Paper titles with formulas: publishers write them in LaTeX between
 * dollar signs (APS: ``$\ensuremath{\nu}=1/3$``) and Crossref with a few
 * HTML tags (``<i>g</i>-tensors``). Shown with KaTeX, which is loaded only
 * when a title has a formula. */

type Katex = typeof import('katex').default;

const state = $state<{ katex: Katex | null }>({ katex: null });
let loading = false;

// A formula: $…$ not starting or ending with a space, so "$5 and $10"
// stays text.
const MATH = /\$(?=\S)((?:\\\$|[^$])+?)(?<=\S)\$/g;
const HAS_MATH = new RegExp(MATH.source);
// The tags Crossref puts in titles; everything else stays text.
const TAGS = /&lt;(\/?)(i|b|em|strong|sub|sup|scp)&gt;/gi;

function escape(text: string): string {
	return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** KaTeX knows no \ensuremath (math mode, which a formula is in anyway). */
function cleanTex(tex: string): string {
	return tex
		.replace(/\\(?:text|mathrm)\{\\ensuremath\{([^{}]*)\}\}/g, '{$1}')
		.replace(/\\ensuremath\{([^{}]*)\}/g, '{$1}');
}

function textHtml(text: string): string {
	return escape(text).replace(TAGS, (_, close: string, tag: string) => {
		const name = tag.toLowerCase() === 'scp' ? 'span' : tag.toLowerCase();
		return `<${close}${name}>`;
	});
}

export function hasMarkup(title: string): boolean {
	// Not MATH.test: a global pattern would remember where it stopped.
	return HAS_MATH.test(title) || /<\/?(i|b|em|strong|sub|sup|scp)>/i.test(title);
}

/** The title as HTML: formulas typeset (once KaTeX is there; until then as
 * written), Crossref's tags kept, everything else escaped. */
export function titleHtml(title: string): string {
	if (!hasMarkup(title)) return escape(title);
	const katex = state.katex;
	if (!katex && !loading) {
		loading = true;
		Promise.all([import('katex'), import('katex/dist/katex.min.css')]).then(([module]) => {
			state.katex = module.default;
		});
	}
	let html = '';
	let last = 0;
	for (const match of title.matchAll(MATH)) {
		html += textHtml(title.slice(last, match.index));
		html += katex
			? katex.renderToString(cleanTex(match[1]), { throwOnError: false })
			: escape(match[0]);
		last = match.index + match[0].length;
	}
	return html + textHtml(title.slice(last));
}

/** For places that take plain text only (the tab's title, notices, labels):
 * formulas roughly as they read, tags left out. */
export function plainTitle(title: string): string {
	if (!hasMarkup(title)) return title;
	return title
		.replace(MATH, (_, tex: string) =>
			cleanTex(tex)
				.replace(/\\(?:text|mathrm|mathit|mathbf|mathcal)\{([^{}]*)\}/g, '$1')
				.replace(/\\([a-zA-Z]+)/g, (__, name: string) => GREEK[name] ?? name)
				.replace(/[{}]/g, '')
				.replace(/[_^]/g, '')
		)
		.replace(/<\/?(i|b|em|strong|sub|sup|scp)>/gi, '');
}

const GREEK: Record<string, string> = {
	alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', zeta: 'ζ', eta: 'η',
	theta: 'θ', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', rho: 'ρ',
	sigma: 'σ', tau: 'τ', phi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω', Gamma: 'Γ',
	Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Pi: 'Π', Sigma: 'Σ', Phi: 'Φ', Psi: 'Ψ',
	Omega: 'Ω'
}; // prettier-ignore
