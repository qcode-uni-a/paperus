// Makes a page twin: a publisher's page as the extension sees it (its tags,
// links, frames, headings and the data a site keeps in a script), with
// nothing that could not be passed on: no text of the article, its
// abstract, figures, the site's scripts or styles, nothing of the reader
// (institution, session, signed addresses), and parody names for the
// paper, its authors, the journal and the publisher.
//
//   node twins/make.mjs NAME        (in extension/)
//
// Reads twins/raw/NAME/page.html (the page as saved in the browser: "Web Page,
// complete") and twins/raw/NAME/names.json, both never checked in:
//
//   { "twin": "eeek",                     the twin's (parody) name
//     "url": "https://…",                 the page's address
//     "replace": { "real": "parody" },    names, DOIs, numbers; longest first
//     "forbid": ["…"] }                   must not be left (any case)
//
// Writes twins/pages/TWIN/page.html, or refuses if a real name is left. Look
// it over before it becomes a test (pages/TWIN/expect.json: what to expect).
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const here = new URL('.', import.meta.url);
const name = process.argv[2];
if (!name) throw new Error('Usage: node twins/make.mjs NAME (twins/raw/NAME/page.html and names.json)');
const spec = JSON.parse(readFileSync(new URL(`raw/${name}/names.json`, here), 'utf8'));
// Scripts are not run: the page as saved, after its own scripts ran.
const raw = new JSDOM(readFileSync(new URL(`raw/${name}/page.html`, here), 'utf8'), { url: spec.url }).window
	.document;

/** Data some sites keep in a script instead of tags, cut to the paper's
 * own fields. IEEE Xplore's (EEEK's) "xplGlobal.document.metadata". */
const DATA = [
	{
		assign: 'xplGlobal.document.metadata',
		fields: [
			'title', 'displayDocTitle', 'doi', 'pdfUrl', 'pdfPath', 'articleNumber', 'publicationTitle',
			'displayPublicationTitle', 'publisher', 'publicationDate', 'volume', 'issue', 'startPage',
			'endPage', 'contentType', 'isConference', 'isJournal', 'isOpenAccess', 'isFreeDocument',
			'authors', 'abstract'
		],
		/** Names that must not stay as they are. */
		names: ['title', 'displayDocTitle', 'publicationTitle', 'displayPublicationTitle', 'publisher']
	}
];
const data = DATA.flatMap(({ assign, fields, names }) => {
	const pattern = new RegExp(`${assign.replace(/\./g, '\\.')}\\s*=\\s*\\{`);
	return [...raw.querySelectorAll('script:not([src])')]
		.map((script) => script.textContent ?? '')
		.filter((text) => pattern.test(text))
		.map((text) => ({
			assign,
			fields,
			names,
			value: JSON.parse(
				text.slice(text.indexOf('{', text.search(pattern))).split('\n')[0].trim().replace(/;$/, '')
			)
		}));
});

// The paper's authors: invented names, unless names.json gives them.
const INVENTED = [
	'Skip Connor', 'Ida Entity', 'Res Netson', 'Batch Norman', 'Al Gorithm', 'Max Likelihood',
	'Sue Perposition', 'Bo Sonn', 'Fermi Onn', 'Ella Vator', 'Ray Tracer', 'Hugh Ristic',
	'Polly Morph', 'Quentin Tunneling', 'Norma Lization', 'Dee Coherence', 'Para Meter', 'Eve Ennodd'
];
const replace = { ...spec.replace };
const authors = [
	...[...raw.querySelectorAll('meta[name="citation_author" i], meta[name="dc.creator" i]')].map((tag) =>
		tag.getAttribute('content')
	),
	...data.flatMap(({ value }) => (Array.isArray(value.authors) ? value.authors.map((a) => a?.name) : []))
]
	.map((author) => author?.replace(/\s+/g, ' ').trim())
	.filter(Boolean);
for (const author of authors)
	if (!(author in replace)) {
		const used = Object.keys(replace).filter((real) => INVENTED.includes(replace[real])).length;
		replace[author] = INVENTED[used] ?? `Author ${used + 1}`;
	}
const replacements = Object.entries(replace).sort(([a], [b]) => b.length - a.length);
/** The words of the real authors' names (three letters or more). */
const nameWords = new Set(
	authors.flatMap((name) => name.toLowerCase().split(/[^\p{L}]+/u)).filter((word) => word.length >= 3)
);
/** Names left as they are (a title, a journal, a publisher): refused. */
const unchanged = [];
/** Other works' DOIs (the references'): placeholders, the same for each. */
const otherDois = new Map();
function scrub(text) {
	let out = String(text);
	for (const [real, parody] of replacements) {
		out = out.split(real).join(parody);
		const encoded = encodeURIComponent(real);
		if (encoded !== real) out = out.split(encoded).join(encodeURIComponent(parody));
	}
	return out.replace(/\b10\.(?!5555\/)\d{4,9}(?:\/|%2F)[^\s"'<>&?#]+/gi, (doi) => {
		if (!otherDois.has(doi)) otherDois.set(doi, `10.5555/ref.${otherDois.size + 1}`);
		return otherDois.get(doi);
	});
}

const ABSTRACT = 'An abstract, left out of the twin.';
/** Query parameters whose values say which paper or file; any other's
 * value (sessions, signatures, tokens, the reader) is left out. */
const KEPT_PARAMS = /^(tp|arnumber|isnumber|punumber|doi|download|type|pid|format)$/i;
function cleanUrl(href) {
	let url;
	try {
		url = new URL(href, spec.url);
	} catch {
		return null;
	}
	if (!/^https?:$/.test(url.protocol)) return null;
	for (const key of [...url.searchParams.keys()])
		if (!KEPT_PARAMS.test(key)) url.searchParams.set(key, 'x');
	url.hash = '';
	// The parodies first: what names someone after that has none.
	url = new URL(scrub(url.href));
	// Parts naming an author (search and profile links: /author/M%20Benito,
	// /authored-by/Platero/G): "someone".
	// After an author's part (/author/123/gloria-someone, where the page
	// names its authors only in its text): all "someone".
	let person = false;
	url.pathname = url.pathname
		.split('/')
		.map((part) => {
			let text = part;
			try {
				text = decodeURIComponent(part);
			} catch {
				// As it is.
			}
			if (person) return 'someone';
			if (/^(authors?|authored-by|profiles?|people|person|researchers?|orcid)$/i.test(text)) {
				person = true;
				return part;
			}
			const words = text.toLowerCase().split(/[^\p{L}]+/u).filter(Boolean);
			if (words.some((word) => nameWords.has(word))) return 'someone';
			// A title as a slug (news, topics, other articles): "a-page".
			const long = words.filter((word) => word.length > 2);
			return long.length >= 4 && !long.every((word) => GENERIC.has(word)) ? 'a-page' : part;
		})
		.join('/');
	// ORCID iDs (in groups of four digits, so not caught below) name the
	// real authors: placeholders, the same for each.
	const named = url.href.replace(/\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b/gi, (id) => {
		if (!orcids.has(id)) orcids.set(id, `0000-0000-0000-${String(orcids.size + 1).padStart(4, '0')}`);
		return orcids.get(id);
	});
	// Other numbers that name someone or something (authors' profiles, other
	// papers): placeholders, the same for each.
	return named.replace(/\d{5,}/g, (number) => {
		if (parodies.has(number)) return number;
		if (!otherNumbers.has(number)) otherNumbers.set(number, String(9000001 + otherNumbers.size));
		return otherNumbers.get(number);
	});
}
/** Numbers in the parodies (an article's own), kept. */
const parodies = new Set(replacements.flatMap(([, parody]) => parody.match(/\d{5,}/g) ?? []));
const otherNumbers = new Map();
const orcids = new Map();

/** Link texts kept as they are: words that say what a link is, never whose
 * or about what. Any other text: "Link". */
const GENERIC = new Set(
	`pdf epdf html view download full text article articles supplementary supplemental supporting
	information material materials data dataset datasets code software github gitlab zenodo figshare
	google scholar crossref pubmed references reference cite cited by this paper abstract get access
	open file files the of and in more show all metrics export citation citations sign institutional
	login log purchase buy rent figures tables media authors author keywords help home contact about
	us privacy terms cookies next previous issue volume journal home page reader read online free
	alerts document sections section metadata introduction conclusion conclusions acknowledgment
	acknowledgments acknowledgement acknowledgements appendix footnotes notes availability available
	statement funding similar related additional extended peer review reviews reviewer reviewers
	referee report reports reporting summary source fig zip history transparent policy process`
		.split(/\s+/)
		.filter(Boolean)
);
function label(text) {
	const clean = text.replace(/\s+/g, ' ').trim();
	const words = clean.toLowerCase().match(/[a-z]+/g) ?? [];
	if (!clean || clean.length > 60) return 'Link';
	return words.every((word) => GENERIC.has(word)) ? clean : 'Link';
}

const escape = (text) =>
	String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// The head: the tags the extension reads.
const head = [`<meta charset="utf-8">`, `<title>${escape(scrub(raw.title))}</title>`];
/** The tags the extension reads (page.ts), and no others: never
 * citation_reference (the cited papers' titles and authors), nor the
 * authors' institutions or e-mail addresses. */
const TAGS = new Set(
	`citation_title citation_author citation_doi citation_pdf_url citation_journal_title
	citation_conference_title citation_publisher citation_publication_date citation_date
	citation_online_date citation_volume citation_issue citation_firstpage citation_lastpage
	citation_arxiv_id citation_abstract citation_abstract_html_url citation_fulltext_html_url
	citation_public_url bepress_citation_doi publication_doi dc.title dc.identifier dc.creator
	dc.date dc.publisher dc.description dc.type prism.doi prism.publicationname prism.volume
	prism.number prism.startingpage prism.endingpage prism.url og:title og:type og:url description`
		.split(/\s+/)
		.filter(Boolean)
);
/** Tags with a name in them: a parody, or the twin is not written. */
const NAMED = /^(citation_title|citation_journal_title|citation_conference_title|citation_publisher|dc\.title|dc\.publisher|prism\.publicationname|og:title)$/i;
for (const tag of raw.querySelectorAll('meta')) {
	const key = tag.getAttribute('name') ?? tag.getAttribute('property');
	const equiv = tag.getAttribute('http-equiv');
	const content = (tag.getAttribute('content') ?? '').replace(/\s+/g, ' ').trim();
	if (equiv && /^refresh$/i.test(equiv)) {
		head.push(`<meta http-equiv="refresh" content="${escape(scrub(content))}">`);
		continue;
	}
	if (!key || !TAGS.has(key.toLowerCase())) continue;
	const value = /abstract|description/i.test(key)
		? ABSTRACT
		: /_url$|^og:url$/i.test(key)
			? cleanUrl(content)
			: scrub(content);
	if (NAMED.test(key) && value === content && content) unchanged.push(content);
	// A value broken across lines (ACS's titles) stays so: a quirk the
	// extension has to cope with.
	const broken =
		/\n/.test((tag.getAttribute('content') ?? '').trim()) && value
			? value.replace(new RegExp(`^(.{${Math.floor(value.length / 2)}}\\S*) `), '$1\n')
			: value;
	const scheme = tag.getAttribute('scheme');
	const attribute = tag.hasAttribute('property') ? 'property' : 'name';
	if (broken)
		head.push(
			`<meta ${attribute}="${escape(key)}"${scheme ? ` scheme="${escape(scheme)}"` : ''} content="${escape(broken)}">`
		);
}

for (const { assign, fields, names, value: found } of data) {
	const kept = {};
	for (const field of fields) {
		if (!(field in found)) continue;
		const value = found[field];
		kept[field] =
			field === 'abstract'
				? ABSTRACT
				: field === 'authors'
					? (Array.isArray(value) ? value : []).map((author) => ({
							name: scrub((author?.name ?? '').replace(/\s+/g, ' ').trim())
						}))
					: typeof value === 'string'
						? scrub(value)
						: value;
		if (names.includes(field) && typeof value === 'string' && value && kept[field] === value)
			unchanged.push(value);
	}
	const json = JSON.stringify(kept).replace(/</g, '\\u003c');
	head.push(`<script>\n\t${assign}=${json};\n</script>`);
}

// The body: headings, links, frames and robot checks, in the page's order,
// each in its landmark (header, nav, footer: links there are the site's).
const LANDMARK =
	'header, footer, nav, [role="banner"], [role="contentinfo"], [role="navigation"]';
const CAPTCHA = /g-recaptcha|h-captcha|cf-turnstile|challenge-form|px-captcha|captcha/i;
const body = [];
let open = null;
function place(element, html) {
	const landmark = element.closest(LANDMARK);
	const kind = landmark
		? (landmark.getAttribute('role') ?? landmark.tagName.toLowerCase())
				.replace('banner', 'header')
				.replace('contentinfo', 'footer')
				.replace('navigation', 'nav')
		: null;
	if (kind !== open) {
		if (open) body.push(`</${open}>`);
		if (kind) body.push(`<${kind}>`);
		open = kind;
	}
	body.push(`${kind ? '\t' : ''}${html}`);
}
for (const element of raw.body.querySelectorAll('*')) {
	const tag = element.tagName.toLowerCase();
	if (/^h[1-6]$/.test(tag)) {
		// The site's and the usual sections' ("Abstract", "Supplementary
		// Material"); the article's own: "A heading".
		const text = element.textContent.replace(/\s+/g, ' ').trim().replace(/:$/, '');
		const words = text.toLowerCase().match(/[a-z]+/g) ?? [];
		const generic = text.length <= 40 && words.length > 0 && words.every((w) => GENERIC.has(w));
		if (text) place(element, `<${tag}>${escape(generic ? text : 'A heading')}</${tag}>`);
	} else if (tag === 'a' && element.hasAttribute('href')) {
		const href = cleanUrl(element.getAttribute('href'));
		if (href) place(element, `<p><a href="${escape(href)}">${escape(label(element.textContent))}</a></p>`);
	} else if (
		(tag === 'iframe' || tag === 'embed') &&
		element.getAttribute('src') &&
		// Not the browser's copies of a saved page's frames (its "…_files"
		// folder; trackers, as a rule): their own addresses are gone.
		!/_files\//.test(element.getAttribute('src'))
	) {
		const src = cleanUrl(element.getAttribute('src'));
		if (src) place(element, `<${tag} src="${escape(src)}"></${tag}>`);
	} else {
		const marker = `${element.id} ${element.getAttribute('class') ?? ''}`.match(CAPTCHA);
		if (marker) place(element, `<div class="${escape(marker[0])}"></div>`);
	}
}
if (open) body.push(`</${open}>`);

const twin = `<!doctype html>
<!-- A page twin (extension/twins/README.md): made by make.mjs, parody names. -->
<html>
<head>
${head.join('\n')}
</head>
<body>
${body.join('\n')}
</body>
</html>
`;

// Nothing real left: the names replaced (as written), the forbidden words
// (any case) and ORCID iDs other than the placeholders.
const left = [
	...replacements.map(([real]) => real).filter((real) => twin.includes(real)),
	...(spec.forbid ?? []).filter((word) => twin.toLowerCase().includes(word.toLowerCase())),
	...(twin.match(/\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b/gi) ?? []).filter((id) => !id.startsWith('0000-0000-0000-'))
];
if (unchanged.length)
	throw new Error(
		`Not written: no parody in names.json for ${[...new Set(unchanged)].map((w) => `"${w}"`).join(', ')}`
	);
if (left.length) {
	const where = (word) => {
		const at = twin.toLowerCase().indexOf(word.toLowerCase());
		return twin.slice(Math.max(0, at - 60), at + word.length + 30).replace(/\s+/g, ' ');
	};
	throw new Error(
		`Not written: the twin still has\n${left.map((word) => `  "${word}" in …${where(word)}…`).join('\n')}`
	);
}
const out = new URL(`pages/${spec.twin}/`, here);
mkdirSync(out, { recursive: true });
writeFileSync(new URL("page.html", out), twin);
console.log(
	`twins/pages/${spec.twin}/page.html: ${head.length} tags, ${body.length} lines of body, ${otherDois.size} other DOIs replaced`
);
