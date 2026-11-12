/** Publishers' PDF links that lead to a reader, not the file: mapped to
 * the file's own address (no browser needed: tested with Node). */

/** The PDF itself where a publisher's link leads to its reader: Wiley's
 * "/doi/epdf/…" and "/doi/pdf/…" open its ePDF reader (a page, with a
 * sidebar); its download is "/doi/pdfdirect/…?download=true". Other links
 * as they are. */
export function directPdf(url: string): string {
  try {
    const address = new URL(url);
    const wiley = /(^|\.)wiley\.com$/.test(address.hostname);
    const doi = address.pathname.match(
      /^\/doi\/(?:e?pdf|pdfdirect|epub)\/(10\..+)$/,
    )?.[1];
    if (wiley && doi)
      return `${address.origin}/doi/pdfdirect/${doi}?download=true`;
  } catch {
    // Not an address: as it is.
  }
  return url;
}

/** On a publisher's reader page itself (Wiley's ePDF): its PDF. */
export function readerPdf(url: string): string | null {
  const direct = directPdf(url);
  return direct !== url ? direct : null;
}

/** The paper a link leads to, as paperus looks papers up ("doi:…",
 * "arxiv:…"), from its address alone: arXiv's IDs, Nature's articles (DOI
 * 10.1038/ and the article's name), a DOI in the path or query (APS,
 * Wiley, ACS, IOP, Springer, Taylor & Francis, doi.org). Null where it
 * names none (ScienceDirect's /pii/…, IEEE's /document/…). */
export function paperOfLink(url: string): string | null {
  let address: URL;
  try {
    address = new URL(url);
  } catch {
    return null;
  }
  let path = address.pathname;
  try {
    path = decodeURIComponent(path);
  } catch {
    // A malformed address: as it is.
  }
  const arxiv =
    /(^|\.)arxiv\.org$/.test(address.hostname) &&
    path.match(
      /^\/(?:abs|pdf|html)\/(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?/,
    );
  if (arxiv) return `arxiv:${arxiv[1]}`;
  const nature =
    /(^|\.)nature\.com$/.test(address.hostname) &&
    path.match(/^\/articles\/([a-z0-9.-]+?)(?:\.pdf)?$/i);
  if (nature) return `doi:10.1038/${nature[1]}`;
  let query = address.search;
  try {
    query = decodeURIComponent(query);
  } catch {
    // As it is.
  }
  const doi = `${path} ${query}`.match(/(10\.\d{4,9}\/[^\s?#&"']+)/)?.[1];
  if (!doi) return null;
  // What publishers put after the DOI in their addresses (IOP's /meta).
  const clean = doi
    .replace(/\/(meta|pdf|epdf|full|abstract|fulltext|html|references)$/i, "")
    .replace(/\.pdf$/i, "")
    .replace(/[.,;)]+$/, "");
  return `doi:${clean}`;
}
