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

export type LinkKind = "code" | "data" | "other";

export interface Extras {
  files: { url: string; name: string }[];
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

/** The file's name: Wiley's file=…, else the address's last part. */
function nameOf(url: URL, text: string): string {
  const given = url.searchParams.get("file");
  let last = given ?? url.pathname.split("/").filter(Boolean).at(-1) ?? "";
  try {
    last = decodeURIComponent(last);
  } catch {
    // As it is.
  }
  if (FILE_EXTENSION.test(last)) return last;
  return (
    text.replace(/\s+/g, " ").trim().slice(0, 100) || last || "supplementary"
  );
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
    if (!url || own.has(url.href) || ELSEWHERE.test(link.heading)) continue;
    if (isSupplement(link, url)) {
      if (extras.files.length < MAX_FILES)
        extras.files.push({ url: url.href, name: nameOf(url, link.text) });
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
