/** The log without what is the person's own: web addresses keep their site
 * and path, but not what may stand for them there (a signed PDF address's
 * signature and token, a session in the path, a proxy's ticket, a search's
 * words, a name and password in the address). Query parameters keep their
 * names, so the log still shows what kind of address it was; only the
 * values below are harmless and kept (Wiley's download=true). */

const KEPT = new Set(["download", "format", "type", "version", "v"]);
const ADDRESS = /\bhttps?:\/\/[^\s"'<>]+/g;

export function redact(text: string): string {
  return text.replace(ADDRESS, (match) => {
    // A full stop or bracket after an address in a sentence is the
    // sentence's.
    const end = /[.,;:!?)\]]+$/.exec(match)?.[0] ?? "";
    const found = match.slice(0, match.length - end.length);
    let url: URL;
    try {
      url = new URL(found);
    } catch {
      return `[an address]${end}`;
    }
    const names = [...new Set(url.searchParams.keys())];
    const query = names
      .map((name) =>
        KEPT.has(name.toLowerCase())
          ? `${encodeURIComponent(name)}=${encodeURIComponent(url.searchParams.get(name) ?? "")}`
          : encodeURIComponent(name),
      )
      .join("&");
    // ;jsessionid=… and its kind, in the path.
    const path = url.pathname.replace(/;[^/]*/g, "");
    return `${url.protocol}//${url.host}${path}${query ? `?${query}` : ""}${end}`;
  });
}
