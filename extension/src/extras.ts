/** A paper's supplementary material, code and data, from the links on its
 * publisher's page (``pageLinks`` in page.ts): which are its supplementary
 * files (to save with it), which lead to its code or data (to keep as
 * links). No browser needed: tested with Node. */

export interface PageLink {
  url: string;
  text: string;
  /** The heading of the section it is in. */
  heading: string;
  /** The sentence or list item it is in. */
  context: string;
  abstract: boolean;
}

export type LinkKind = "code" | "data" | "peer_review" | "other";
/** What a supplementary file is: paperus has only its name afterwards, so
 * the page says it (the link's text, its section, its file name). */
export type FileRole = "supplementary" | "peer_review" | "code" | "data";

export interface Extras {
  files: { url: string; name: string; role: FileRole }[];
  links: { url: string; kind: LinkKind }[];
}

const MAX_FILES = 10;
const MAX_LINKS = 10;

/** Sections whose links are other works': the reference list and the
 * publisher's suggestions. */
const ELSEWHERE =
  /^\s*(\d+\.?\s*)?(references?|bibliography|literature cited|works cited|notes and references|cited by|citing articles|related (articles|content)|recommended|similar articles|more from|you may also like)\b/i;

const SUPPLEMENT_HEADING =
  /supplementary|supporting information|supplemental|additional (files|information)|extended data|source data|ancillary files/i;

/** Publishers' addresses of supplementary files: Atypon's (ACS, Science,
 * PNAS, Taylor & Francis: /doi/suppl/…), Springer Nature's (/esm/),
 * Elsevier's (…-mmc1.pdf), Wiley's (downloadSupplement), PLOS's
 * (type=supplementary), APS's (/supplemental/), IOP's (_suppdata). */
const SUPPLEMENT_URL = [
  /\/doi\/suppl\//i,
  /static-content\.springer\.com\/esm\//i,
  /els-cdn\.com\/.+-mmc\d+\.\w+$/i,
  /\/action\/downloadSupplement\b/i,
  /[?&]type=supplementary\b/i,
  /\/supplemental\//i,
  /_suppdata?\.\w+$/i,
  /\/suppl(ementary)?[_-]?(file|data|material|info)/i,
];

const FILE_EXTENSION =
  /\.(pdf|zip|gz|tgz|tar|7z|rar|docx?|xlsx?|pptx?|csv|tsv|txt|json|xml|h5|hdf5|nc|mat|npz|ipynb|py|m|r|mp4|mov|avi|gif|png|jpe?g|tiff?|cif|pdb|fasta|fa)$/i;

/** Where code lives. */
const CODE_HOSTS =
  /^(www\.)?(github\.com|gitlab\.com|bitbucket\.org|codeocean\.com|archive\.softwareheritage\.org|codeberg\.org|sourceforge\.net)$|^gitlab\./i;
/** Where data lives (or code and data alike: Zenodo, Figshare). */
const DATA_HOSTS =
  /^(www\.)?(zenodo\.org|figshare\.com|[\w-]+\.figshare\.com|datadryad\.org|osf\.io|data\.mendeley\.com|pangaea\.de|doi\.pangaea\.de|kaggle\.com|huggingface\.co|dataverse\.[\w.]+|[\w.-]+\.dataverse\.[\w.]+|openneuro\.org|ebi\.ac\.uk|ncbi\.nlm\.nih\.gov)$/i;
/** DOIs of data repositories: Zenodo, Figshare, Dryad, PANGAEA, Mendeley
 * Data, Dataverse (Harvard's). */
const DATA_DOI = /^10\.(5281|6084|5061|1594|17632|7910)\//;

const AVAILABILITY_HEADING =
  /availability|code and data|data and code|software|data access|accession|deposit|resources|materials and data/i;
/** "The code is available at …", "spectra have been deposited at …". */
const AVAILABLE_SENTENCE =
  /\b(code|codes|data|dataset|datasets|software|scripts?|implementation|notebooks?|repository|package|library|tool)\b[^.]{0,120}\b(available|deposited|accessible|found|provided|released|hosted|archived|published|shared|obtained)\b|\b(available|deposited|archived)\b[^.]{0,60}\b(at|on|from|via|in|under|with)\b|\b(code|data)\s*:\s/i;
const SAYS_CODE =
  /\b(code|codes|software|scripts?|implementation|package|program)\b/i;
const SAYS_DATA = /\b(data|dataset|datasets|measurements)\b/i;

function address(url: string): URL | null {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

/** Referees' reports and the authors' replies, as pages call them. */
const PEER_REVIEW =
  /\bpeer[\s-]*reviews?\b|\breferee(s|['’]s)?\s+reports?\b|\breviewer(s|['’]s?)?\s+(reports?|comments?)\b|\breview\s+(history|file|reports?)\b/i;
/** The journal's, not the paper's: its policy, its process. */
const ABOUT_REVIEWING =
  /\b(policy|policies|process|guidelines?|ethics|editorial|for reviewers)\b/i;
/** Publishers' names for files that say nothing (Springer Nature's
 * …_MOESM2_ESM.pdf, Elsevier's mmc1.pdf, bioRxiv's media-1.pdf). */
export const OPAQUE_NAME =
  /(_MOESM\d+_ESM|^mmc\d+|-mmc\d+|^media-\d+|_suppdata?|^suppl?\d*|^sm\d*|^S\d+_File)\b/i;
const CODE_FILE = /\.(py|ipynb|m|r|jl|c|cpp|f90|nb)$/i;
const DATA_FILE =
  /\.(csv|tsv|xlsx?|h5|hdf5|nc|mat|npz|json|cif|pdb|fasta|fa)$/i;

/** The link's own words, if they say something ("Peer Review File"). */
function wordsOf(text: string): string {
  const words = text.replace(/\s+/g, " ").trim().slice(0, 100);
  return GENERIC_TEXT.test(words) || /^link$/i.test(words) ? "" : words;
}

/** The file's name: Wiley's file=…, else the address's last part; one
 * that says nothing (…_MOESM2_ESM.pdf) as the link says it, with its
 * ending ("Peer Review File.pdf"). */
function nameOf(url: URL, text: string): string {
  const given = url.searchParams.get("file");
  let last = given ?? url.pathname.split("/").filter(Boolean).at(-1) ?? "";
  try {
    last = decodeURIComponent(last);
  } catch {
    // As it is.
  }
  const words = wordsOf(text)
    .replace(/[\\/:*?"<>|]/g, " ")
    .trim();
  if (FILE_EXTENSION.test(last)) {
    const ending = last.match(/\.\w+$/)?.[0] ?? "";
    return OPAQUE_NAME.test(last) && words
      ? `${words.replace(new RegExp(`\\${ending}$`, "i"), "")}${ending}`
      : last;
  }
  return words || last || "supplementary";
}

/** What a supplementary file is, from what the page says of it. */
export function roleOf(link: PageLink, name: string): FileRole {
  const said = `${link.text} ${name}`;
  if (PEER_REVIEW.test(said) && !ABOUT_REVIEWING.test(link.text))
    return "peer_review";
  if (CODE_FILE.test(name) || /\b(source\s+)?code\b/i.test(link.text))
    return "code";
  if (
    DATA_FILE.test(name) ||
    /\b(source|supplementary)\s+data\b|\bdata\s*set\b/i.test(link.text)
  )
    return "data";
  return "supplementary";
}

function isSupplement(link: PageLink, url: URL): boolean {
  const where = url.href;
  if (SUPPLEMENT_URL.some((pattern) => pattern.test(where))) return true;
  // arXiv's ancillary files.
  if (
    /(^|\.)arxiv\.org$/.test(url.hostname) &&
    /\/src\/[^/]+\/anc\/./.test(url.pathname)
  )
    return true;
  // A file in a section of supplementary material (bioRxiv's media-1.pdf).
  return (
    SUPPLEMENT_HEADING.test(link.heading) &&
    (FILE_EXTENSION.test(url.pathname) || /\/media-\d+/.test(url.pathname))
  );
}

/** Code or data, by where it is; null if neither. */
function kindOf(link: PageLink, url: URL): LinkKind | null {
  const host = url.hostname;
  const path = url.pathname.split("/").filter(Boolean);
  let doi = /(^|\.)doi\.org$/.test(host) ? url.pathname.slice(1) : null;
  try {
    if (doi) doi = decodeURIComponent(doi);
  } catch {
    // As it is.
  }
  if (doi && !DATA_DOI.test(doi)) doi = null;
  // A repository, not its site or a person's page.
  if (CODE_HOSTS.test(host)) return path.length >= 2 ? "code" : null;
  if (!doi && !DATA_HOSTS.test(host)) return null;
  if (!doi && path.length < 1) return null;
  if (/^(www\.)?huggingface\.co$/.test(host) && path[0] !== "datasets")
    return "code"; // a model
  // Zenodo and Figshare keep code too: what the sentence says.
  const said = `${link.heading} ${link.context}`;
  return SAYS_CODE.test(said) && !SAYS_DATA.test(said) ? "code" : "data";
}

/** The paper's own supplementary files, code and data on its page. */
export function extrasOf(
  links: PageLink[],
  skip: (string | null | undefined)[] = [],
): Extras {
  const extras: Extras = { files: [], links: [] };
  const own = new Set(
    skip.filter(Boolean).map((url) => String(url).replace(/#.*$/, "")),
  );
  for (const link of links) {
    const url = address(link.url);
    if (!url || ELSEWHERE.test(link.heading)) continue;
    // Not the page itself, nor a place on it ("#peer-review").
    if (own.has(url.href) || own.has(url.href.replace(/#.*$/, ""))) continue;
    if (isSupplement(link, url)) {
      if (extras.files.length < MAX_FILES) {
        const name = nameOf(url, link.text);
        extras.files.push({ url: url.href, name, role: roleOf(link, name) });
      }
      continue;
    }
    // The paper's published reviews, on a page of their own.
    if (
      PEER_REVIEW.test(link.text) &&
      !ABOUT_REVIEWING.test(link.text) &&
      extras.links.length < MAX_LINKS &&
      !extras.links.some((known) => known.url === url.href)
    ) {
      extras.links.push({ url: url.href, kind: "peer_review" });
      continue;
    }
    const kind = kindOf(link, url);
    if (
      kind &&
      extras.links.length < MAX_LINKS &&
      (link.abstract ||
        AVAILABILITY_HEADING.test(link.heading) ||
        AVAILABLE_SENTENCE.test(link.context)) &&
      !extras.links.some((known) => known.url === url.href)
    )
      extras.links.push({ url: url.href, kind });
  }
  return extras;
}

/** One thing a page lists that can be saved as a paper of its own: a file
 * it links (saved as it is, paperus reads its details), a paper it links
 * by DOI or arXiv ID, or a paper it names (Google Scholar's profiles: by
 * title, paperus looks its DOI up). */
export interface Listed {
  key: string;
  kind: "file" | "paper";
  name: string;
  /** What it is and where: "PDF · example.org", "arXiv 2101.00001". */
  detail: string;
  url: string;
  doi?: string;
  arxiv?: string;
  /** Details as listed, for a paper without an identifier. */
  csl?: Record<string, unknown>;
  /** Ticked at first: papers and documents, not archives or videos. */
  chosen: boolean;
  /** The paper one has already, if so. */
  itemId?: string;
}

const MAX_LISTED = 300;
/** Documents one saves as papers; archives, data and media at one's wish. */
const DOCUMENT = /\.(pdf|ps|djvu|epub|docx?|odt|pptx?|odp|md|tex)$/i;
const OTHER_FILE =
  /\.(zip|gz|tgz|tar|7z|xlsx?|ods|csv|ipynb|mp4|mov|webm|mkv|mp3|m4a|wav)$/i;
/** Links that are PDFs without saying so: arXiv's, OpenReview's,
 * publishers' /doi/pdf/. */
const PDF_ADDRESS = [
  /(^|\.)arxiv\.org\/pdf\//i,
  /openreview\.net\/pdf\b/i,
  /\/doi\/(pdf|pdfdirect|epdf)\//i,
  /\/pdfft\b/i,
];
/** Link texts that say nothing of what they lead to. */
const GENERIC_TEXT =
  /^\W*(pdf|ps|download|slides?|paper|preprint|here|link|full ?text|view|open|file|arxiv|doi|journal|publisher|video|code|data|poster|abstract|html|bib(tex)?|\[.*\])\W*$/i;

function plainPath(url: URL): string {
  try {
    return decodeURIComponent(url.pathname);
  } catch {
    return url.pathname;
  }
}

/** A name to show: the link's text, or its line's when the text is only
 * "[pdf]", or the file's name. */
function shownName(link: PageLink, url: URL): string {
  const text = link.text.replace(/\s+/g, " ").trim();
  if (text.length > 3 && !GENERIC_TEXT.test(text)) return text.slice(0, 160);
  let line = link.context.replace(/\s+/g, " ").replace(text, "").trim();
  // What is left of "[pdf]", "(zip)", "— Slides" at its end.
  for (let before = ""; before !== line;) {
    before = line;
    line = line
      .replace(/[[(]\s*[\w .-]{0,12}\s*[\])]?\s*$/, (end) =>
        GENERIC_TEXT.test(end) ||
        /^\W*$/.test(end) ||
        /^[[(]\s*\w{1,5}\s*[\])]?$/.test(end.trim())
          ? ""
          : end,
      )
      .replace(/[\s\-–—:|·,;/]+$/, "")
      .trim();
  }
  if (line.length > 10) return line.slice(0, 160);
  return plainPath(url).split("/").filter(Boolean).at(-1) ?? url.host;
}

function fileType(url: URL): string {
  const extension = /\.([a-z0-9]+)$/i.exec(plainPath(url))?.[1];
  return extension ? extension.toUpperCase() : "PDF";
}

/** What a page lists that can each be saved as a paper: files and links
 * to papers (by DOI or arXiv ID), in the page's order, without the
 * reference list's (a paper's own page) or the page's own. ``paperOf``:
 * links.ts's paperOfLink (a link's DOI or arXiv ID). */
export function listedOn(
  links: PageLink[],
  pageUrl: string,
  paperOf: (url: string) => string | null,
): Listed[] {
  const listed: Listed[] = [];
  const keys = new Set<string>();
  const page = address(pageUrl);
  const ownPaper = paperOf(pageUrl);
  for (const link of links) {
    if (listed.length >= MAX_LISTED) break;
    const url = address(link.url);
    if (!url || url.href === page?.href || ELSEWHERE.test(link.heading))
      continue;
    const path = plainPath(url);
    const paper = paperOf(url.href);
    const document = DOCUMENT.test(path);
    const other = OTHER_FILE.test(path);
    const pdf = PDF_ADDRESS.some((pattern) => pattern.test(url.href));
    let entry: Listed | null = null;
    if (paper && paper !== ownPaper && !(document || other)) {
      const [scheme, value] = [
        paper.slice(0, paper.indexOf(":")),
        paper.slice(paper.indexOf(":") + 1),
      ];
      // Datasets' DOIs (Zenodo, …) are no papers.
      if (scheme === "doi" && DATA_DOI.test(value)) continue;
      // arXiv's PDF link is its paper: saved with its details.
      entry = {
        key: paper,
        kind: "paper",
        name: shownName(link, url),
        detail: scheme === "arxiv" ? `arXiv ${value}` : `DOI ${value}`,
        url: url.href,
        ...(scheme === "arxiv" ? { arxiv: value } : { doi: value }),
        chosen: true,
      };
    } else if (document || other || pdf) {
      const host =
        page && url.hostname !== page.hostname
          ? ` · ${url.hostname.replace(/^www\./, "")}`
          : "";
      entry = {
        key: `file:${url.href}`,
        kind: "file",
        name: shownName(link, url),
        detail: `${fileType(url)}${host}`,
        url: url.href,
        chosen: !other,
      };
    }
    if (entry && !keys.has(entry.key)) {
      keys.add(entry.key);
      listed.push(entry);
    }
  }
  return listed;
}

/** A paper as a Google Scholar profile lists it. */
export interface ScholarRow {
  title: string;
  /** "PY Mai, M Benito, …" (Scholar shortens long lists). */
  authors: string;
  /** "Physical Review B 101 (4), 045002" or "arXiv preprint arXiv:…". */
  venue: string;
  year: string;
  url: string;
}

/** A profile's papers to choose from: by arXiv ID where the venue names
 * one, else by their details (paperus looks the DOI up by title). */
export function scholarListed(rows: ScholarRow[]): Listed[] {
  const listed: Listed[] = [];
  const keys = new Set<string>();
  for (const row of rows) {
    const title = row.title.replace(/\s+/g, " ").trim();
    if (!title) continue;
    const arxiv = /arXiv:(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})/i.exec(
      row.venue,
    )?.[1];
    const key = arxiv ? `arxiv:${arxiv}` : `title:${title}`;
    if (keys.has(key)) continue;
    keys.add(key);
    const authors = row.authors
      .split(",")
      .map((name) => name.trim())
      .filter((name) => name && name !== "..." && name !== "…")
      .map((name) => {
        const words = name.split(/\s+/);
        const family = words.pop() ?? name;
        return words.length
          ? { family, given: words.join(" ") }
          : { literal: family };
      });
    const year = Number.parseInt(row.year, 10);
    const venue = row.venue.replace(/,\s*(19|20)\d{2}\s*$/, "").trim();
    listed.push({
      key,
      kind: "paper",
      name: title,
      detail: [venue, row.year].filter(Boolean).join(", ") || "Google Scholar",
      url: row.url,
      ...(arxiv ? { arxiv } : {}),
      csl: {
        type: "article-journal",
        title,
        author: authors,
        ...(venue && !arxiv
          ? { "container-title": venue.replace(/\s+\d.*$/, "") }
          : {}),
        ...(year ? { issued: { "date-parts": [[year]] } } : {}),
      },
      chosen: true,
    });
  }
  return listed;
}
