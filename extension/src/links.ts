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
