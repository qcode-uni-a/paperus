/** One click on the toolbar button saves the page's paper to paperus, with
 * its PDF (fetched in the page, with the reader's own access); an open PDF
 * is saved as it is, paperus reads its details. The button's menu (right
 * click) saves to another owner. */
import {
  type Cause,
  causeOf,
  EXPLAINED,
  isErrorPage,
  isRobotCheck,
  signalsOfHtml,
} from "./causes";
import {
  type Extras,
  extrasOf,
  type Listed,
  listedOn,
  type PageLink,
  scholarListed,
} from "./extras";
import { directPdf, paperOfLink, readerPdf } from "./links";
import { logIssue, trace } from "./log";
import {
  fetchPdf,
  idsInUrl,
  type PageInfo,
  pageLinks,
  pageSignals,
  readPage,
  scholarProfile,
  showNote,
} from "./page";
import {
  type Api,
  call,
  PaperusError,
  saveSettings,
  type Settings,
  settings,
} from "./paperus";

declare const TEST: boolean;

const MAX_BYTES = 512 * 1024 * 1024;
const FIREFOX = chrome.runtime.getURL("").startsWith("moz-extension:");

type Pdf =
  | { base64: string; size: number }
  | {
      error: string;
      status?: number;
      html?: string;
      next?: string;
      at?: string;
    };
/** Saved; with ``warning``, only in part: the paper without its PDF. */
type Saved = {
  ok: true;
  text: string;
  link: string;
  warning?: boolean;
  /** The paper, for the popup (moving one just added to another owner). */
  item?: {
    id: string;
    libraryId: string | null;
    title: string;
    added: boolean;
  };
};

/** What the popup shows while a tab is saved. */
function step(tabId: number, text: string): void {
  chrome.runtime
    .sendMessage({ type: "saveStep", tabId, text })
    .catch(() => undefined); // no popup open
}
/** How the badge and the note look: saved, saved in part, not saved. */
type Outcome = "ok" | "warning" | "error";
/** A library one may add to, named for menus and messages. */
interface Owner {
  id: string;
  name: string;
}

chrome.action.onClicked.addListener(async (tab) => {
  const asking = askAccess(tab);
  await asking;
  if (!(await settings())) {
    await chrome.runtime.openOptionsPage();
    return;
  }
  await saveTab(tab);
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const id = String(info.menuItemId);
  if (id === "settings") {
    await chrome.runtime.openOptionsPage();
    return;
  }
  if (!tab || !id.startsWith("owner:")) return;
  const asking = askAccess(tab);
  await asking;
  const { owners } = (await chrome.storage.local.get("owners")) as {
    owners?: Owner[];
  };
  const ownerId = id.slice("owner:".length);
  await saveTab(
    tab,
    owners?.find((o) => o.id === ownerId) ?? {
      id: ownerId,
      name: "the owner chosen",
    },
  );
});

chrome.runtime.onInstalled.addListener(() => {
  refreshMenu();
  void registerSite();
});
chrome.runtime.onStartup.addListener(() => {
  refreshMenu();
  void registerSite();
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && "settings" in changes) {
    refreshMenu();
    void registerSite();
  }
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  const handlers: Record<string, () => Promise<unknown>> = {
    lookup: () => lookup(message.ids),
    saveArxiv: () => saveArxiv(message.id),
    connect: () => connect(message.server),
    getPdfs: async () => {
      if (sender.tab?.id !== undefined && (await fromPaperus(sender.url))) {
        void getPdfs(message.papers, sender.tab.id);
      }
      return { ok: true };
    },
    // The message window, once access to the PDF's site is allowed.
    saveAgain: async () => {
      if (!sender.url?.startsWith(chrome.runtime.getURL("note.html")))
        return { ok: false };
      return saveTab(await chrome.tabs.get(message.tabId));
    },
    getPdfsAllowed: async () => {
      const { getPdfs: waiting } = (await chrome.storage.session.get(
        "getPdfs",
      )) as {
        getPdfs?: { papers: Wanted[]; tabId: number };
      };
      await chrome.storage.session.remove("getPdfs");
      if (waiting) void getPdfs(waiting.papers, waiting.tabId);
      return { ok: true };
    },
    // Google Scholar's buttons (scholar.ts).
    lookupKeys: () => lookupKeys(message.keys),
    saveLink: () => saveLink(message.url),
    // The popup: save its tab (the button's click), move a paper it saved.
    popupSave: async () => {
      if (!sender.url?.startsWith(chrome.runtime.getURL("popup.html")))
        return { ok: false };
      return saveTab(await chrome.tabs.get(message.tabId), undefined, true);
    },
    // What the popup offers for its tab: the paper, or a list to choose
    // from; then the chosen ones saved, each telling the popup how it went.
    popupSurvey: async () => {
      if (!sender.url?.startsWith(chrome.runtime.getURL("popup.html")))
        return { ok: false };
      return survey(await chrome.tabs.get(message.tabId));
    },
    popupSaveListed: async () => {
      if (!sender.url?.startsWith(chrome.runtime.getURL("popup.html")))
        return { ok: false };
      const { owners = [] } = (await chrome.storage.local.get("owners")) as {
        owners?: Owner[];
      };
      return saveListed(
        message.tabId,
        message.listed as Listed[],
        owners.find((o) => o.id === message.ownerId),
        message.large === true,
      );
    },
    moveItem: async () => {
      if (!sender.url?.startsWith(chrome.runtime.getURL("popup.html")))
        return { ok: false };
      const { status } = await call<Api.SetOwnerData>(
        "/api/items/{item_id}/owner",
        {
          method: "PUT",
          path: { item_id: message.itemId },
          json: { library_id: message.libraryId },
        },
      );
      return { ok: status < 400 };
    },
  };
  // Automated tests cannot click the button; they send this instead.
  if (TEST) {
    handlers.testSave = async () =>
      saveTab(await chrome.tabs.get(message.tabId), message.owner);
  }
  const handler = handlers[message?.type];
  if (!handler) return false;
  handler()
    .then(reply)
    .catch((error) =>
      reply({ ok: false, text: String(error.message ?? error) }),
    );
  return true; // the reply comes later
});

/** Firefox's PDF viewer lets no extension in, and Firefox lets the
 * extension fetch the PDF itself only with access to its site: asked for
 * on the click, the only moment it may be asked, when the address looks
 * like a PDF's or the last click found one there that it could not fetch.
 * (Granted once, it is not asked again.) */
let pdfWithoutAccess: number | undefined;

function askAccess(tab: chrome.tabs.Tab): Promise<boolean> | undefined {
  if (!FIREFOX || !tab.url || !/^https?:/.test(tab.url)) return undefined;
  const looksLikePdf = /\.pdf(?:$|[?#])|\/pdf\//i.test(tab.url);
  if (!looksLikePdf && tab.id !== pdfWithoutAccess) return undefined;
  return chrome.permissions
    .request({ origins: [site(tab.url)] })
    .catch(() => false);
}

/** Access to a site, as browsers write it (without a port). */
function site(url: string): string {
  const { protocol, hostname } = new URL(url);
  return `${protocol}//${hostname}/*`;
}

async function badge(
  tabId: number,
  text: string,
  color = "#2338a8",
): Promise<void> {
  await chrome.action.setBadgeBackgroundColor({ tabId, color });
  await chrome.action.setBadgeText({ tabId, text });
}

async function inPage<A extends unknown[], R>(
  tabId: number,
  func: (...args: A) => R,
  ...args: A
): Promise<Awaited<R>> {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func,
    args,
    // At once, not when the page is done loading (its trackers, figures,
    // MathJax): what is read is in its head and body by then (readPage
    // waits for those).
    injectImmediately: true,
  });
  return result.result as Awaited<R>;
}

/** How long reading a page in its tab may take. */
const READ_MS = 20_000;

/** A step in the page, given up after a while: a page busy with its own
 * scripts can keep the browser from running ours (Science Advances), and
 * the save would wait for ever. */
async function within<T>(ms: number, step: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () => reject(new Error(`no answer from the page in ${ms / 1000} s`)),
      ms,
    );
  });
  try {
    return await Promise.race([step, late]);
  } finally {
    clearTimeout(timer);
  }
}

async function saveTab(
  tab: chrome.tabs.Tab,
  owner?: Owner,
  inPopup = false,
): Promise<Saved | { ok: false; text: string }> {
  const tabId = tab.id!;
  await badge(tabId, "…");
  step(tabId, "Reading the page…");
  trace("Saving a page", {
    page: tab.url ?? null,
    owner: owner?.id ?? null, // not its name: one's own
    popup: inPopup,
  });
  try {
    const result = await saveFrom(tab, owner);
    if (result.warning)
      // Not the library's name (often one's own): which one is in "owner".
      logIssue("warning", unnamed(result.text, owner), {
        page: tab.url ?? null,
        item: result.link,
      });
    if (result.warning) await badge(tabId, "!", "#b26a00");
    else await badge(tabId, "✓", "#1e7a3e");
    if (!inPopup)
      await tell(
        tabId,
        result.text,
        result.link,
        result.warning ? "warning" : "ok",
      );
    return result;
  } catch (error) {
    const text =
      error instanceof PaperusError
        ? error.message
        : `Not saved: ${String(error)}`;
    // Ours are explained to the person; anything else is a fault here.
    logIssue(error instanceof PaperusError ? "warning" : "error", text, {
      page: tab.url ?? null,
      ...(error instanceof PaperusError
        ? {}
        : { stack: String((error as Error)?.stack ?? "").slice(0, 2000) }),
    });
    await badge(tabId, "!", "#c0392b");
    if (!inPopup) await tell(tabId, text, null, "error");
    return { ok: false, text };
  } finally {
    refreshMenu(); // groups one joined since
  }
}

/** In the page's corner; where no extension may go (a PDF viewer), as the
 * button's tooltip, and what went wrong in a small window (with a button
 * that allows access to the PDF's site, if that is missing). */
async function tell(
  tabId: number,
  text: string,
  link: string | null,
  outcome: Outcome,
): Promise<void> {
  try {
    await inPage(tabId, showNote, text, link, outcome);
  } catch {
    await chrome.action.setTitle({ tabId, title: text });
    if (outcome === "ok") return;
    const query = new URLSearchParams({ text, tab: String(tabId), outcome });
    if (tabId === pdfWithoutAccess) {
      const url = (await chrome.tabs.get(tabId).catch(() => null))?.url;
      if (url) query.set("site", site(url));
    }
    await chrome.windows.create({
      url: chrome.runtime.getURL(`note.html?${query}`),
      type: "popup",
      width: 460,
      height: 280,
    });
  }
}

async function saveFrom(tab: chrome.tabs.Tab, owner?: Owner): Promise<Saved> {
  let unread = "";
  const page = await within(READ_MS, inPage(tab.id!, readPage)).catch(
    (error) => {
      unread = String(error?.message ?? error);
      return null;
    },
  );
  const url = page?.url ?? tab.url ?? "";
  const inUrl = idsInUrl(url);
  if (!page) {
    trace("The page could not be read in its tab", {
      page: url,
      reason: unread,
    });
    return saveClosedTab(tab, url, inUrl, owner, unread);
  }
  trace("Page read", {
    page: url,
    title: page.title,
    doi: page.doi ?? inUrl.doi,
    arxiv: page.arxiv ?? inUrl.arxiv,
    pdfLink: page.pdfUrl,
    isPdf: page.isPdf,
  });
  const info = {
    ...page,
    doi: page.doi ?? inUrl.doi,
    arxiv: page.arxiv ?? inUrl.arxiv,
  };
  // A check for robots in front of the paper: with a DOI or arXiv ID the
  // paper is saved still, without its PDF, and the check says why; without
  // one the page's title would name the paper: not that of the check, nor
  // of a page that did not load.
  const signals = page.isPdf
    ? null
    : await within(READ_MS, inPage(tab.id!, pageSignals)).catch(() => null);
  const robot = signals !== null && isRobotCheck(signals);
  if (robot)
    trace("A check for robots on the page", {
      page: url,
      title: signals?.title ?? null,
    });
  if (!info.doi && !info.arxiv && signals) {
    if (robot) throw new PaperusError(EXPLAINED["robot-check"]);
    if (isErrorPage(signals))
      throw new PaperusError(
        `The page did not load (“${signals.title.trim()}”): reload it, then save again.`,
      );
  }
  // The PDF's own address (a reader's link mapped to its download).
  const pdfLink = page.isPdf
    ? null
    : page.pdfUrl
      ? directPdf(page.pdfUrl)
      : readerPdf(url);
  if (pdfLink !== page.pdfUrl && pdfLink)
    trace("The PDF link leads to a reader: its download instead", {
      link: page.pdfUrl ?? url,
      pdf: pdfLink,
    });
  if (info.arxiv || page.isPdf || pdfLink) step(tab.id!, "Fetching the PDF…");
  // Fetched while the paper is added (save): not waited for here.
  const pdfComing = (async (): Promise<Pdf> =>
    info.arxiv
      ? await arxivPdf(info.arxiv)
      : page.isPdf || pdfLink
        ? await orInTab(
            await onwards(
              await inPage(
                tab.id!,
                fetchPdf,
                page.isPdf ? page.url : pdfLink!,
                MAX_BYTES,
              ),
            ),
            pdfLink,
          )
        : {
            error: robot ? EXPLAINED["robot-check"] : "The page links no PDF.",
          })();
  void pdfComing.then((pdf) => {
    trace("The PDF", { page: url, ...fetched(pdf) });
    step(tab.id!, "Saving to paperus…");
  });
  // Its supplementary files, code and data, from the article's links.
  const extrasComing = page.isPdf
    ? Promise.resolve(null)
    : within(READ_MS, inPage(tab.id!, pageLinks))
        .then((links) => extrasOf(links, [url, page.pdfUrl, pdfLink]))
        .catch(() => null);
  return page.isPdf && !info.doi && !info.arxiv
    ? saveFile(await pdfComing, url, owner)
    : save(info, pdfComing, owner, extrasComing);
}

/** A message for the log, without the library's name. */
function unnamed(text: string, owner?: Owner): string {
  return owner ? text.replaceAll(owner.name, "the library") : text;
}

/** A PDF's fetch, for the log: its size, or what came back instead. */
function fetched(pdf: Pdf): Record<string, string | number | null> {
  if (!("error" in pdf)) return { pdf: `${pdf.size} bytes` };
  return {
    error: pdf.error,
    status: pdf.status ?? null,
    landed: pdf.at ?? null,
    next: pdf.next ?? null,
    title: pdf.html
      ? signalsOfHtml(pdf.html, 200).title.trim().slice(0, 120)
      : null,
  };
}

/** A tab the extension may not read: a browser's own PDF viewer (Firefox's),
 * or a page closed to extensions. A PDF there is fetched from here. */
async function saveClosedTab(
  tab: chrome.tabs.Tab,
  url: string,
  inUrl: { doi: string | null; arxiv: string | null },
  owner?: Owner,
  unread = "",
): Promise<Saved> {
  if (!/^https?:/.test(url))
    throw new PaperusError("The browser lets no extension into this page.");
  if (inUrl.arxiv)
    return save(
      { ...inUrl, title: null, url, isPdf: true },
      await arxivPdf(inUrl.arxiv),
      owner,
    );
  if (!(await chrome.permissions.contains({ origins: [site(url)] }))) {
    pdfWithoutAccess = tab.id;
    throw new PaperusError(
      `To save this PDF, paperus needs to fetch it from ${new URL(url).host}, and the browser asks you first.`,
    );
  }
  let pdf = await onwards(await fetchPdf(url, MAX_BYTES));
  trace("Fetched the tab's address from the extension", {
    url,
    ...fetched(pdf),
  });
  // Firefox's PDF viewer, and the site gave the extension a web page: the
  // PDF as Firefox loads it for the reader.
  if ("error" in pdf && unread && FIREFOX) {
    step(tab.id!, "Loading the PDF again…");
    const copy = await loadedCopy(url);
    trace("Loaded again in a tab out of sight, a copy kept", {
      url,
      ...(copy ? fetched(copy) : { pdf: "none" }),
    });
    if (copy) pdf = copy;
  }
  // A web page after all, which the browser did not let the extension read
  // in its tab: the paper's details from the page as fetched from here.
  if ("error" in pdf && pdf.html !== undefined && !inUrl.doi) {
    const found = detailsOfHtml(pdf.html, url);
    if (found.doi) {
      const itsPdf = found.pdfUrl
        ? await onwards(await fetchPdf(found.pdfUrl, MAX_BYTES))
        : { error: "The page links no PDF." };
      return save({ ...found, url, isPdf: false }, itsPdf, owner);
    }
    if (isRobotCheck(signalsOfHtml(pdf.html, pdf.status ?? 200)))
      throw new PaperusError(EXPLAINED["robot-check"]);
  }
  if ("error" in pdf && !inUrl.doi) {
    logIssue("warning", "A page the extension could not read", {
      page: url,
      reason: unread || null,
      fetched: pdf.error,
    });
    const sent = pdf.html
      ? signalsOfHtml(pdf.html, pdf.status ?? 200).title.trim()
      : "";
    throw new PaperusError(
      unread
        ? `The browser shows this page in its own viewer (a PDF, most likely), which no extension may read, and ${new URL(url).host} sent ${sent ? `a web page (“${sent.slice(0, 80)}”)` : "no PDF"} when asked again. Open the PDF from the article's page and save there, or drop the downloaded PDF into paperus.`
        : "The browser lets no extension into this page.",
    );
  }
  return inUrl.doi
    ? save({ ...inUrl, title: null, url, isPdf: true }, pdf, owner)
    : saveFile(pdf, url, owner);
}

/** A PDF the page could not fetch (from another site: where a page in
 * between sent it, or a redirect): fetched by the extension, if it may go
 * there; once. */
async function onwards(pdf: Pdf): Promise<Pdf> {
  if (!("error" in pdf) || !pdf.next) return pdf;
  const next = pdf.next;
  trace("The page could not fetch the PDF: fetching it from the extension", {
    url: next,
    because: pdf.error,
  });
  if (!(await chrome.permissions.contains({ origins: [site(next)] })))
    return {
      error: `The PDF is at ${new URL(next).host}, which paperus may not fetch from yet: allow it there, then save again.`,
    };
  const again = await fetchPdf(next, MAX_BYTES);
  trace("Fetched from the extension", { url: next, ...fetched(again) });
  return again;
}

/** A paper's details from a page's HTML (Highwire's citation_* tags, Dublin
 * Core), for a page the extension could not read in its tab. */
function detailsOfHtml(
  html: string,
  url: string,
): {
  doi: string | null;
  arxiv: string | null;
  title: string | null;
  pdfUrl: string | null;
} {
  const meta = (name: string): string | null => {
    const tag = [...html.matchAll(/<meta\b[^>]*>/gi)]
      .map((m) => m[0])
      .find((t) =>
        new RegExp(
          `(name|property)=["']${name.replace(".", "\\.")}["']`,
          "i",
        ).test(t),
      );
    const value = tag?.match(/content=["']([^"']*)["']/i)?.[1]?.trim();
    return value ? value.replace(/&amp;/g, "&").replace(/&quot;/g, '"') : null;
  };
  const doiText =
    meta("citation_doi") ?? meta("dc.identifier") ?? meta("prism.doi");
  const doi = doiText?.match(/\b(10\.\d{4,9}\/[^\s"'<>]+)/)?.[1] ?? null;
  // The page's own link to its PDF (ScienceDirect's …/pdfft?…).
  const own = html.match(/href=["']([^"']*\/pdfft[^"']*)["']/i)?.[1];
  const link =
    meta("citation_pdf_url") ?? (own ? own.replace(/&amp;/g, "&") : null);
  return {
    doi,
    arxiv: meta("citation_arxiv_id"),
    title: meta("citation_title") ?? meta("dc.title"),
    pdfUrl: link ? new URL(link, url).href : null,
  };
}

function defaultOwner(config: Settings | null): Owner | undefined {
  return config?.owner
    ? { id: config.owner, name: config.ownerName ?? "the owner chosen" }
    : undefined;
}

function decode(pdf: { base64: string }): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(atob(pdf.base64), (c) => c.charCodeAt(0));
}

/** The item that has this file already (in a library one can read), if any. */
async function holder(bytes: Uint8Array<ArrayBuffer>): Promise<string | null> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const sha = [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  const { status, data } = await call<
    Api.FindUploadData,
    Api.FindUploadResponse
  >("/api/uploads/{sha256}", {
    path: { sha256: sha },
  });
  return status === 200 ? data.item_id : null;
}

async function itemLink(itemId: string): Promise<string> {
  return new URL(`/items/${itemId}`, (await settings())!.server).href;
}

/** The paper (found or added) and its PDF; what happened, in words. */
async function save(
  page: Pick<PageInfo, "doi" | "arxiv" | "title" | "url"> & Partial<PageInfo>,
  pdfComing: Pdf | Promise<Pdf>,
  owner?: Owner,
  extrasComing: Promise<Extras | null> = Promise.resolve(null),
): Promise<Saved> {
  const target = owner ?? defaultOwner(await settings());
  const library = target ? { library_id: target.id } : {};
  const doi = page.doi ?? (page.arxiv ? `10.48550/arXiv.${page.arxiv}` : null);
  const addItem = (json: Api.ItemIn) =>
    call<Api.AddItemData, Api.AddItemResponse>("/api/items", {
      method: "POST",
      json,
    });
  // The paper added (paperus looks its DOI up) while its PDF is fetched.
  const [first, pdf] = await Promise.all([
    doi ? addItem({ doi, ...library }).catch(() => null) : null,
    pdfComing,
  ]);
  let added = first;
  if (!added || added.status >= 400) {
    // An open PDF whose DOI is unknown: paperus reads it instead.
    if (page.isPdf && !("error" in pdf)) return saveFile(pdf, page.url, owner);
    if (!page.title)
      throw new PaperusError(
        "This page names no paper (no DOI, arXiv ID or title).",
      );
    added = await addItem({
      metadata: csl(page),
      identifiers: identifiers(page),
      ...library,
    });
  }
  const item = added.data;
  const known = added.status === 200;
  trace(known ? "Already in paperus" : "Added to paperus", {
    item: item.id,
    title: item.title,
    by: doi ? "DOI" : "the page's details",
  });
  const hasPdf = item.files?.some((f) => f.media_type === "application/pdf");
  // Why the paper is saved without its PDF, if it is.
  let missing: string | null = null;
  let fileNote = "";
  if ("error" in pdf) {
    if (hasPdf) fileNote = " It has a PDF already.";
    else missing = pdfProblem(pdf);
  } else {
    const bytes = decode(pdf);
    if (await holder(bytes)) {
      fileNote = " The PDF is there already.";
    } else {
      missing = await upload(item.id, bytes, filename(page));
      if (!missing) fileNote = " With its PDF.";
    }
  }
  const extrasNote = await saveExtras(item.id, await extrasComing);
  const where = owner ? owner.name : "paperus";
  // Titles may carry their publisher's markup (Crossref's <i>, <scp>).
  const title = item.title.replace(/<\/?(i|b|em|strong|sub|sup|scp)>/gi, "");
  const saved = `${known ? "Already in paperus" : `Saved to ${where}`}: “${title}”`;
  const paper = {
    id: item.id,
    libraryId: item.library_id,
    title,
    added: !known,
  };
  return missing
    ? {
        ok: true,
        warning: true,
        text: `${saved}, without its PDF. ${missing}${extrasNote}`,
        link: await itemLink(item.id),
        item: paper,
      }
    : {
        ok: true,
        text: `${saved}.${fileNote}${extrasNote}`,
        link: await itemLink(item.id),
        item: paper,
      };
}

/** How long the supplementary files may take, all of them. */
const EXTRAS_MS = 120_000;
/** A supplementary file larger than this is left at the publisher's. */
const MAX_SUPPLEMENT_BYTES = 100 * 1024 * 1024;

/** The paper's supplementary files and its links to code and data, found
 * on its page: saved with it (files a few at a time). What fails is left
 * out, the log says why; an older paperus without links takes the files
 * only. Returns what to tell. */
async function saveExtras(
  itemId: string,
  extras: Extras | null,
): Promise<string> {
  if (!extras || (!extras.files.length && !extras.links.length)) return "";
  trace("Supplementary material, code and data on the page", {
    files: extras.files.map((f) => f.url).join(" "),
    links: extras.links.map((l) => `${l.kind}: ${l.url}`).join(" "),
  });
  const kinds = new Set<string>();
  for (const link of extras.links) {
    try {
      const { status } = await call<Api.AddLinkData>(
        "/api/items/{item_id}/links",
        {
          method: "POST",
          path: { item_id: itemId },
          json: { url: link.url, kind: link.kind, replace: false },
        },
      );
      if (status < 400) kinds.add(link.kind);
    } catch (error) {
      trace("A link not added", { url: link.url, reason: String(error) });
    }
  }
  const queue = [...extras.files];
  let saved = 0;
  const worker = async () => {
    for (let file = queue.shift(); file; file = queue.shift())
      if (await saveSupplement(itemId, file)) saved++;
  };
  await within(
    EXTRAS_MS,
    Promise.all(Array.from({ length: Math.min(3, queue.length) }, worker)),
  ).catch(() => trace("Supplementary files: out of time", { item: itemId }));
  const parts: string[] = [];
  if (saved)
    parts.push(
      saved === 1 ? "a supplementary file" : `${saved} supplementary files`,
    );
  const to = (["code", "data"] as const).filter((kind) => kinds.has(kind));
  if (to.length) parts.push(`the link to its ${to.join(" and ")}`);
  else if (kinds.has("other")) parts.push("a link");
  return parts.length ? ` Also ${parts.join(" and ")}.` : "";
}

/** A file fetched from here, with the reader's access to its site (the
 * extension's own fetch: cookies go along). Larger than ``maxBytes``: not
 * fetched further, its size said. */
async function fetchFile(
  url: string,
  name: string,
  maxBytes: number,
): Promise<{ blob: Blob; name: string } | { error: string; size?: number }> {
  if (!(await chrome.permissions.contains({ origins: [site(url)] })))
    return { error: "no access to its site" };
  try {
    const response = await fetch(url, {
      credentials: "include",
      signal: AbortSignal.timeout(90_000),
    });
    if (!response.ok) return { error: `the site answered ${response.status}` };
    const type = response.headers.get("content-type") ?? "";
    // A page instead of the file: a login, or a list of files.
    if (/text\/html|application\/xhtml/i.test(type))
      return { error: "a web page, not a file (a login?)" };
    const length = Number(response.headers.get("content-length") ?? 0);
    if (length > maxBytes) {
      void response.body?.cancel();
      return { error: "too large", size: length };
    }
    // Counted as it comes: a size the site does not say is no way round.
    const parts: Uint8Array[] = [];
    let size = 0;
    const reader = response.body?.getReader();
    for (
      let part = await reader?.read();
      part && !part.done;
      part = await reader?.read()
    ) {
      size += part.value.byteLength;
      if (size > maxBytes) {
        void reader?.cancel();
        return { error: "too large", size: length || size };
      }
      parts.push(part.value);
    }
    const named =
      /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(
        response.headers.get("content-disposition") ?? "",
      )?.[1] ?? name;
    let shown = named;
    try {
      shown = decodeURIComponent(named);
    } catch {
      // As it is.
    }
    return {
      blob: new Blob(parts as BlobPart[], {
        type: type || "application/octet-stream",
      }),
      name: shown.slice(0, 200),
    };
  } catch (error) {
    return { error: String(error) };
  }
}

/** One supplementary file, fetched from here (with the reader's access to
 * the publisher's site) and added to the paper; whether it was. */
async function saveSupplement(
  itemId: string,
  file: { url: string; name: string },
): Promise<boolean> {
  const why = (reason: string) => {
    trace("A supplementary file not saved", { url: file.url, reason });
    return false;
  };
  const fetched = await fetchFile(file.url, file.name, MAX_SUPPLEMENT_BYTES);
  if ("error" in fetched)
    return why(
      fetched.size ? `too large (${fetched.size} bytes)` : fetched.error,
    );
  try {
    const form = new FormData();
    form.append("upload", fetched.blob, fetched.name);
    form.append("role", "supplementary");
    const { status } = await call<Api.UploadToItemData>(
      "/api/items/{item_id}/files",
      { method: "POST", path: { item_id: itemId }, form },
    );
    return status < 400 || why(`paperus answered ${status}`);
  } catch (error) {
    return why(String(error));
  }
}

/** Add the PDF to the paper: null if it was, else why not. */
async function upload(
  itemId: string,
  bytes: Uint8Array<ArrayBuffer>,
  name: string,
): Promise<string | null> {
  const form = new FormData();
  form.append("upload", new Blob([bytes], { type: "application/pdf" }), name);
  try {
    const { status } = await call<Api.UploadToItemData>(
      "/api/items/{item_id}/files",
      { method: "POST", path: { item_id: itemId }, form },
    );
    return status === 404
      ? "The paper was not found when its PDF was added."
      : null;
  } catch (error) {
    const why = error instanceof Error ? error.message : String(error);
    return `Uploading the PDF failed: ${why.replace(/[^.]$/, "$&.")}`;
  }
}

/** A PDF on its own: a new item from the file, whose details paperus reads
 * from it (a DOI or arXiv ID in the text). */
async function saveFile(pdf: Pdf, url: string, owner?: Owner): Promise<Saved> {
  if ("error" in pdf) throw new PaperusError(pdf.error);
  const bytes = decode(pdf);
  const existing = await holder(bytes);
  if (existing)
    return {
      ok: true,
      text: "This PDF is in paperus already.",
      link: await itemLink(existing),
      item: { id: existing, libraryId: null, title: "", added: false },
    };
  const target = owner ?? defaultOwner(await settings());
  const form = new FormData();
  const name = filename({ url });
  form.append("upload", new Blob([bytes], { type: "application/pdf" }), name);
  if (target) form.append("library_id", target.id);
  const { data } = await call<Api.UploadNewItemData, Api.UploadNewItemResponse>(
    "/api/uploads",
    {
      method: "POST",
      form,
    },
  );
  return {
    ok: true,
    text: `Saved to ${owner ? owner.name : "paperus"}: ${name}. paperus reads its details from the PDF.`,
    link: await itemLink(data.item_id),
    item: {
      id: data.item_id,
      libraryId: target?.id ?? null,
      title: name,
      added: true,
    },
  };
}

function identifiers(page: Partial<PageInfo>): Api.IdentifierIn[] {
  const found: Api.IdentifierIn[] = [];
  if (page.doi) found.push({ scheme: "doi", value: page.doi });
  if (page.arxiv) found.push({ scheme: "arxiv", value: page.arxiv });
  return found;
}

/** CSL-JSON from the page's tags, for papers without a DOI. */
function csl(page: Partial<PageInfo>): Record<string, unknown> {
  const year = page.date?.match(/\d{4}/)?.[0];
  const authors = (page.authors ?? []).map((name) => {
    const [family, given] = name.includes(",")
      ? name.split(",").map((part) => part.trim())
      : [name.split(" ").at(-1)!, name.split(" ").slice(0, -1).join(" ")];
    return given ? { family, given } : { literal: name };
  });
  const pages = [page.firstPage, page.lastPage].filter(Boolean).join("-");
  return Object.fromEntries(
    Object.entries({
      type: page.journal ? "article-journal" : "webpage",
      title: page.title,
      author: authors.length ? authors : undefined,
      issued: year ? { "date-parts": [[Number(year)]] } : undefined,
      "container-title": page.journal,
      volume: page.volume,
      issue: page.issue,
      page: pages || undefined,
      publisher: page.publisher,
      abstract: page.abstract,
      URL: page.url,
    }).filter(
      ([, value]) => value !== undefined && value !== null && value !== "",
    ),
  );
}

function filename(page: Partial<PageInfo>): string {
  const last = new URL(
    page.pdfUrl ?? page.url ?? "https://x/paper.pdf",
  ).pathname
    .split("/")
    .pop();
  const name =
    last && /\.pdf$/i.test(last)
      ? last
      : `${(page.arxiv ?? page.title ?? last ?? "paper").slice(0, 80)}.pdf`;
  return name.replace(/[\\/:*?"<>|]+/g, " ");
}

function encoded(bytes: Uint8Array): Pdf {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return { base64: btoa(binary), size: bytes.length };
}

/** Firefox's webRequest, the part for keeping a copy of a response as it
 * arrives (not in Chrome's types). */
interface StreamFilter {
  ondata: ((event: { data: ArrayBuffer }) => void) | null;
  onstop: (() => void) | null;
  onerror: (() => void) | null;
  write(data: ArrayBuffer): void;
  close(): void;
}
type RequestListener = (details: { requestId: string }) => void;
interface FirefoxWebRequest {
  filterResponseData(requestId: string): StreamFilter;
  onBeforeRequest: {
    addListener(
      listener: RequestListener,
      filter: { urls: string[]; tabId: number; types: string[] },
      extra: string[],
    ): void;
    removeListener(listener: RequestListener): void;
  };
}

/** A PDF as Firefox itself loads it, for a PDF open in Firefox's viewer
 * (which no extension may read) whose site answers the extension's own
 * fetch with a web page (a check for robots, a login): its address opened
 * again in a tab out of sight, as one's own visit, and a copy of the bytes
 * kept as they arrive (they go on to the tab unchanged). Null if what
 * arrives is no PDF, in Chrome (which lets the extension read PDF tabs), or
 * after a minute. */
async function loadedCopy(url: string): Promise<Pdf | null> {
  const webRequest = (
    globalThis as { browser?: { webRequest?: Partial<FirefoxWebRequest> } }
  ).browser?.webRequest as FirefoxWebRequest | undefined;
  if (!FIREFOX || !webRequest?.filterResponseData) return null;
  const tab = await chrome.tabs.create({ url: "about:blank", active: false });
  const tabId = tab.id!;
  let listener: RequestListener | undefined;
  try {
    const bytes = await within(
      60_000,
      new Promise<Uint8Array | null>((resolve) => {
        listener = ({ requestId }) => {
          const filter = webRequest.filterResponseData(requestId);
          const parts: Uint8Array[] = [];
          let size = 0;
          filter.ondata = ({ data }) => {
            filter.write(data);
            size += data.byteLength;
            if (size <= MAX_BYTES) parts.push(new Uint8Array(data));
          };
          filter.onstop = () => {
            filter.close();
            // A redirect has nothing: the next answer is the one.
            if (size === 0) return;
            const all = new Uint8Array(size <= MAX_BYTES ? size : 0);
            let at = 0;
            for (const part of size <= MAX_BYTES ? parts : []) {
              all.set(part, at);
              at += part.byteLength;
            }
            resolve(
              String.fromCharCode(...all.subarray(0, 5)) === "%PDF-"
                ? all
                : null,
            );
          };
          filter.onerror = () => resolve(null);
        };
        webRequest.onBeforeRequest.addListener(
          listener,
          { urls: ["<all_urls>"], tabId, types: ["main_frame"] },
          ["blocking"],
        );
        void chrome.tabs.update(tabId, { url });
      }),
    ).catch(() => null);
    return bytes ? encoded(bytes) : null;
  } finally {
    if (listener) webRequest.onBeforeRequest.removeListener(listener);
    await chrome.tabs.remove(tabId).catch(() => undefined);
  }
}

/** arXiv's PDFs are open: fetched here directly. */
async function arxivPdf(id: string): Promise<Pdf> {
  try {
    const response = await fetch(`https://arxiv.org/pdf/${id}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (!response.ok || String.fromCharCode(...bytes.slice(0, 5)) !== "%PDF-") {
      return { error: "arXiv gave no PDF." };
    }
    return encoded(bytes);
  } catch (error) {
    return { error: `arXiv could not be reached: ${String(error)}` };
  }
}

/** The button's menu: "Save to …" for each owner one may add to (when there
 * is more than one), in a submenu when there are more than fit. */
let menuUpdate = Promise.resolve();

function refreshMenu(): void {
  menuUpdate = menuUpdate.then(updateMenu).catch(() => undefined);
}

async function updateMenu(): Promise<void> {
  await chrome.contextMenus.removeAll();
  const create = (properties: chrome.contextMenus.CreateProperties) =>
    chrome.contextMenus.create(
      { contexts: ["action"], ...properties },
      () => void chrome.runtime.lastError,
    );
  try {
    if (!(await settings())) return;
    const { data } = await call<
      Api.ListLibrariesData,
      Api.ListLibrariesResponse
    >("/api/libraries");
    const owners: Owner[] = (data ?? [])
      .filter((library) => library.writable)
      .map((library) => ({
        id: library.id,
        name:
          library.kind === "personal"
            ? "my library"
            : [...library.path, library.name].join(" › "),
      }));
    await chrome.storage.local.set({ owners });
    if (owners.length < 2) return;
    // One place at the top level stays for the settings.
    const nested =
      owners.length > chrome.contextMenus.ACTION_MENU_TOP_LEVEL_LIMIT - 1;
    if (nested) create({ id: "owners", title: "Save to" });
    for (const owner of owners) {
      create({
        id: `owner:${owner.id}`,
        title: nested ? owner.name : `Save to ${owner.name}`,
        ...(nested ? { parentId: "owners" } : {}),
      });
    }
  } finally {
    // The extension's settings, also when paperus cannot be reached.
    create({ id: "settings", title: "paperus settings" });
  }
}

/** For the buttons on arXiv: which of these papers one has. */
async function lookup(ids: string[]): Promise<Record<string, string | null>> {
  if (!(await settings()) || ids.length === 0) return {};
  const { data } = await call<Api.LookupItemsData, Api.LookupItemsResponse>(
    "/api/items/lookup",
    {
      query: { id: ids.map((id) => `arxiv:${id}`) },
    },
  );
  return Object.fromEntries(ids.map((id) => [id, data[`arxiv:${id}`] ?? null]));
}

/** For papers on someone else's page (Google Scholar): which of these
 * ("doi:…", "arxiv:…") one has. */
async function lookupKeys(
  keys: string[],
): Promise<Record<string, string | null>> {
  if (!(await settings()) || keys.length === 0) return {};
  const { data } = await call<Api.LookupItemsData, Api.LookupItemsResponse>(
    "/api/items/lookup",
    { query: { id: keys.slice(0, 200) } },
  );
  return data ?? {};
}

/** What the popup offers for a tab. */
type Survey =
  | { mode: "paper"; listed: Listed[] }
  | {
      mode: "list";
      source: "page" | "scholar";
      title: string;
      listed: Listed[];
    };

const SCHOLAR_PROFILE =
  /^https:\/\/scholar\.google\.[a-z.]+\/citations\?(?:[^#]*&)?user=/;
/** A file of a list larger than this is saved only when asked again. */
const MAX_LISTED_BYTES = 100 * 1024 * 1024;

/** A paper's page (its details in the page's tags), or a PDF: the paper,
 * saved at once as the button does. A page that lists files or papers
 * instead (a course's, a publication list, a journal's contents), or a
 * Google Scholar profile: the list, to choose from. */
async function survey(tab: chrome.tabs.Tab): Promise<Survey> {
  const url = tab.url ?? "";
  if (SCHOLAR_PROFILE.test(url)) {
    const profile = await within(
      120_000,
      inPage(tab.id!, scholarProfile),
    ).catch(() => null);
    trace("A Google Scholar profile", {
      page: url,
      papers: profile?.rows.length ?? null,
    });
    if (profile?.rows.length)
      return {
        mode: "list",
        source: "scholar",
        title: profile.name
          ? `${profile.name}: papers`
          : "Papers on this profile",
        listed: await known(scholarListed(profile.rows)),
      };
  }
  const [page, links] = await Promise.all([
    within(READ_MS, inPage(tab.id!, readPage)).catch(() => null),
    within(READ_MS, inPage(tab.id!, pageLinks)).catch(() => [] as PageLink[]),
  ]);
  const at = page?.url ?? url;
  const listed = listedOn(links, at, paperOfLink).filter(
    (entry) => entry.url !== page?.pdfUrl,
  );
  const inUrl = idsInUrl(at);
  const paper =
    !page ||
    page.isPdf ||
    page.doi ||
    page.arxiv ||
    page.pdfUrl ||
    page.authors.length > 0 ||
    inUrl.doi ||
    inUrl.arxiv;
  if (paper || listed.length === 0)
    return {
      mode: "paper",
      listed: listed.length >= 2 ? await known(listed) : listed,
    };
  trace("A page that lists files and papers", {
    page: at,
    files: listed.filter((entry) => entry.kind === "file").length,
    papers: listed.filter((entry) => entry.kind === "paper").length,
  });
  return {
    mode: "list",
    source: "page",
    title: page?.title ?? "This page",
    listed: await known(listed),
  };
}

/** Which of the listed papers one has (by DOI, arXiv ID or title): marked,
 * and not ticked. */
async function known(listed: Listed[]): Promise<Listed[]> {
  const keys = listed.filter((l) => l.kind === "paper").map((l) => l.key);
  const found: Record<string, string | null> = {};
  // Titles are long: a few at a time, for the address's length.
  for (let start = 0; start < keys.length; start += 40)
    Object.assign(
      found,
      await lookupKeys(keys.slice(start, start + 40)).catch(() => ({})),
    );
  return listed.map((entry) =>
    found[entry.key]
      ? { ...entry, itemId: found[entry.key]!, chosen: false }
      : entry,
  );
}

type ListedOutcome = {
  state: "saved" | "known" | "failed" | "too-large";
  text: string;
  link?: string;
  size?: number;
};

/** The chosen ones of a list, three at a time, each its own paper; the
 * popup hears how each went (it may close meanwhile: the saving goes on). */
async function saveListed(
  tabId: number,
  listed: Listed[],
  owner: Owner | undefined,
  large: boolean,
): Promise<Record<ListedOutcome["state"], number>> {
  const target = owner ?? defaultOwner(await settings());
  const counts = { saved: 0, known: 0, failed: 0, "too-large": 0 };
  const queue = [...listed];
  const tell = (key: string, state: string, outcome?: ListedOutcome) =>
    chrome.runtime
      .sendMessage({ type: "listedState", tabId, key, state, ...outcome })
      .catch(() => undefined); // the popup closed
  trace("Saving from a list", { entries: listed.length, large });
  const worker = async () => {
    for (let entry = queue.shift(); entry; entry = queue.shift()) {
      void tell(entry.key, "saving");
      const outcome: ListedOutcome = await within(
        PAPER_MS,
        saveOne(entry, target, large),
      ).catch((error) => ({
        state: "failed",
        text: error instanceof Error ? error.message : String(error),
      }));
      counts[outcome.state]++;
      trace("Saved from a list", {
        entry: entry.kind === "file" ? entry.url : entry.key,
        state: outcome.state,
        reason: outcome.text || null,
      });
      void tell(entry.key, outcome.state, outcome);
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(AT_ONCE, listed.length) }, worker),
  );
  return counts;
}

async function saveOne(
  entry: Listed,
  owner: Owner | undefined,
  large: boolean,
): Promise<ListedOutcome> {
  const library = owner ? { library_id: owner.id } : {};
  if (entry.kind === "paper" && entry.arxiv) {
    const saved = await save(
      {
        arxiv: entry.arxiv,
        doi: null,
        title: entry.name,
        url: `https://arxiv.org/abs/${entry.arxiv}`,
      },
      arxivPdf(entry.arxiv),
      owner,
    );
    return {
      state: saved.item?.added === false ? "known" : "saved",
      text: saved.warning ? "Without its PDF." : "",
      link: saved.link,
    };
  }
  if (entry.kind === "paper") {
    const { status, data } = await call<Api.AddItemData, Api.AddItemResponse>(
      "/api/items",
      {
        method: "POST",
        json: entry.doi
          ? { doi: entry.doi, ...library }
          : {
              metadata: entry.csl ?? { title: entry.name },
              find_doi: true,
              ...library,
            },
      },
    );
    if (status === 404) return { state: "failed", text: "Its DOI is unknown." };
    const byDoi = data.identifiers.some((i) => i.scheme === "doi");
    return {
      state: status === 200 ? "known" : "saved",
      text:
        status === 200 || byDoi
          ? ""
          : "By its details as listed: no DOI found for it.",
      link: await itemLink(data.id),
    };
  }
  const file = await fetchFile(
    entry.url,
    entry.name,
    large ? MAX_BYTES : MAX_LISTED_BYTES,
  );
  if ("error" in file)
    return file.size
      ? { state: "too-large", text: "", size: file.size }
      : { state: "failed", text: `Not fetched: ${file.error}.` };
  const form = new FormData();
  form.append("upload", file.blob, file.name);
  if (owner) form.append("library_id", owner.id);
  const { status, data } = await call<
    Api.UploadNewItemData,
    Api.UploadNewItemResponse
  >("/api/uploads", { method: "POST", form });
  if (status >= 400)
    return { state: "failed", text: `paperus answered ${status}.` };
  return {
    state: data.existing ? "known" : "saved",
    text: "",
    link: await itemLink(data.item_id),
  };
}

/** A paper from its page, opened in a tab out of sight and saved as a
 * click on it would (its PDF too); the tab closes. */
async function saveLink(
  url: string,
): Promise<Saved | { ok: false; text: string }> {
  if (!(await settings())) {
    await chrome.runtime.openOptionsPage();
    return { ok: false, text: "Connect the extension to paperus first." };
  }
  if (!/^https?:\/\//.test(url))
    return { ok: false, text: "No address to open." };
  trace("Saving a paper from its link", { url });
  const tab = await chrome.tabs.create({ url, active: false });
  try {
    await loaded(tab.id!);
    return await saveTab(await chrome.tabs.get(tab.id!), undefined, true);
  } catch (error) {
    return {
      ok: false,
      text: error instanceof Error ? error.message : String(error),
    };
  } finally {
    await chrome.tabs.remove(tab.id!).catch(() => undefined);
  }
}

async function saveArxiv(
  id: string,
): Promise<Saved | { ok: false; text: string }> {
  if (!(await settings())) {
    await chrome.runtime.openOptionsPage();
    return { ok: false, text: "Connect the extension to paperus first." };
  }
  return save(
    { doi: null, arxiv: id, title: null, url: `https://arxiv.org/abs/${id}` },
    await arxivPdf(id),
  );
}

/** Connect: paperus's page /settings/extension makes a token after the
 * person's click and puts it on the page, where this picks it up. */
async function connect(server: string): Promise<{ ok: boolean; text: string }> {
  const base = new URL(server).origin;
  const tab = await chrome.tabs.create({ url: `${base}/settings/extension` });
  const tabId = tab.id!;
  for (let i = 0; i < 300; i++) {
    await new Promise((done) => setTimeout(done, 1000));
    const token = await inPage(
      tabId,
      () =>
        document.querySelector<HTMLElement>("[data-paperus-extension-token]")
          ?.dataset.paperusExtensionToken ?? null,
    ).catch(() => null);
    if (token) {
      await saveSettings({ server: base, token });
      const { data } = await call<
        Api.ListLibrariesData,
        Api.ListLibrariesResponse
      >("/api/libraries");
      const writable = (data ?? []).filter((l) => l.writable);
      await inPage(tabId, () => {
        const mark = document.querySelector<HTMLElement>(
          "[data-paperus-extension-token]",
        );
        if (mark) mark.dataset.paperusExtensionConnected = "yes";
      });
      return {
        ok: true,
        text: `Connected. ${writable.length} ${writable.length === 1 ? "owner" : "owners"} to choose from.`,
      };
    }
  }
  return {
    ok: false,
    text: "No connection: the paperus page was not confirmed within 5 minutes.",
  };
}

/** The paperus page script (site.ts): on the connected paperus only. */
async function registerSite(): Promise<void> {
  await chrome.scripting
    .unregisterContentScripts({ ids: ["paperus-site"] })
    .catch(() => undefined);
  const config = await settings();
  if (!config) return;
  await chrome.scripting
    .registerContentScripts([
      {
        id: "paperus-site",
        matches: [site(config.server)],
        js: ["site.js"],
        runAt: "document_start",
      },
    ])
    .catch((error) =>
      console.warn("paperus: page script not registered", error),
    );
}

async function fromPaperus(url: string | undefined): Promise<boolean> {
  const config = await settings();
  return (
    !!config && !!url && new URL(url).origin === new URL(config.server).origin
  );
}

/** Papers paperus has no (journal) PDF for (Manage → Missing): each opened
 * at its publisher in a background tab, its PDF fetched there with the
 * person's access and saved into the paper (``version_id``: that version).
 * Needs access to publisher sites, asked for once on an extension page.
 * Progress and the result go back to the paperus tab. */
interface Wanted {
  item_id: string;
  version_id?: string | null;
  title: string;
  url: string;
  /** Open copies whose sites refused paperus' server: tried first, here. */
  copies?: string[];
}

const PUBLISHERS = { origins: ["https://*/*", "http://*/*"] };
const PAGE_WAIT_MS = 45_000;
/** Papers at once, each from another publisher: one publisher gets one
 * request at a time (many quick downloads look like a robot to it). */
const AT_ONCE = 3;
/** One paper at most this long (its page, its PDF): then the next. */
const PAPER_MS = 90_000;

/** Who publishes a paper: its DOI's prefix (links go through doi.org),
 * else its page's site. */
function publisherOf(paper: Wanted): string {
  const doi = paper.url.match(/doi\.org\/(10\.\d{4,9})\//)?.[1];
  if (doi) return doi;
  try {
    return new URL(paper.url).hostname;
  } catch {
    return paper.url;
  }
}

async function getPdfs(papers: Wanted[], tabId: number): Promise<void> {
  if (!TEST && !(await chrome.permissions.contains(PUBLISHERS))) {
    await chrome.storage.session.set({ getPdfs: { papers, tabId } });
    await chrome.windows.create({
      url: chrome.runtime.getURL("allow.html"),
      type: "popup",
      width: 520,
      height: 440,
    });
    return;
  }
  const report = (message: object) =>
    chrome.tabs.sendMessage(tabId, message).catch(() => undefined);
  let saved = 0;
  let done = 0;
  const failed: { item_id: string; reason: string; cause: Cause }[] = [];
  const waiting = [...papers];
  const busy = new Set<string>();
  // The next paper from a publisher not busy, if any.
  const take = (): Wanted | undefined => {
    const index = waiting.findIndex((paper) => !busy.has(publisherOf(paper)));
    return index < 0 ? undefined : waiting.splice(index, 1)[0];
  };
  const worker = async () => {
    while (waiting.length) {
      const paper = take();
      if (!paper) {
        await new Promise((wait) => setTimeout(wait, 500));
        continue;
      }
      const publisher = publisherOf(paper);
      busy.add(publisher);
      trace("Getting a PDF (Missing)", {
        paper: paper.title,
        page: paper.url,
        publisher,
      });
      let problem: { cause: Cause; reason: string } | null;
      try {
        problem = await Promise.race([
          getOne(paper),
          new Promise<{ cause: Cause; reason: string }>((give) =>
            setTimeout(
              () =>
                give({
                  cause: "error",
                  reason: `The publisher took longer than ${PAPER_MS / 1000} seconds.`,
                }),
              PAPER_MS,
            ),
          ),
        ]);
      } finally {
        busy.delete(publisher);
      }
      if (problem) {
        failed.push({ item_id: paper.item_id, ...problem });
        logIssue("warning", `No PDF for “${paper.title}”: ${problem.reason}`, {
          page: paper.url,
          cause: problem.cause,
          item: paper.item_id,
        });
      } else saved++;
      trace(problem ? "No PDF for it (Missing)" : "PDF saved (Missing)", {
        paper: paper.title,
        reason: problem?.reason ?? null,
      });
      done++;
      await report({
        type: "getPdfsProgress",
        done,
        total: papers.length,
        saved,
        item_id: paper.item_id,
        ok: problem === null,
        ...(problem ?? {}),
      });
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(AT_ONCE, papers.length) }, worker),
  );
  await report({ type: "getPdfsDone", total: papers.length, saved, failed });
}

/** Why a PDF link gave no PDF, in words: a robot check, no access, … */
function pdfProblem(pdf: {
  error: string;
  status?: number;
  html?: string;
  at?: string;
}): string {
  if (pdf.html === undefined) return pdf.error;
  const cause = causeOf(signalsOfHtml(pdf.html, pdf.status ?? 200));
  const said = cause === "no-pdf" ? pdf.error : EXPLAINED[cause];
  // What came back, so the reason can be checked.
  const title = signalsOfHtml(pdf.html, 200).title.replace(/\s+/g, " ").trim();
  let from = "";
  try {
    from = pdf.at ? ` from ${new URL(pdf.at).host}` : "";
  } catch {
    // No address to name.
  }
  return title
    ? `${said} (The PDF link gave “${title.slice(0, 80)}”${from}.)`
    : said;
}

/** The PDF link opened in a tab of its own, out of sight, as a person's
 * click opens it: the browser follows what sends it on (scripts, refreshes)
 * to the PDF, whose address the extension then fetches; the tab closes.
 * For links that give a web page to a fetch (ScienceDirect's, at times). */
async function viaTab(url: string, failed: Pdf): Promise<Pdf> {
  const tab = await chrome.tabs.create({ url, active: false });
  try {
    await loaded(tab.id!);
    const landed = (await chrome.tabs.get(tab.id!)).url ?? "";
    trace("The PDF link opened in a tab", { link: url, landed });
    if (!landed || landed === url || !/^https?:/.test(landed)) return failed;
    if (!(await chrome.permissions.contains({ origins: [site(landed)] })))
      return failed;
    const pdf = await fetchPdf(landed, MAX_BYTES);
    trace("Fetched where the tab landed", { url: landed, ...fetched(pdf) });
    return "error" in pdf ? failed : pdf;
  } catch (error) {
    trace("The tab for the PDF link failed", {
      link: url,
      reason: String(error),
    });
    return failed;
  } finally {
    await chrome.tabs.remove(tab.id!).catch(() => undefined);
  }
}

/** A web page where the PDF should be, and no check for robots: try the
 * link in a tab (``viaTab``). */
async function orInTab(pdf: Pdf, url: string | null): Promise<Pdf> {
  if (!url || !("error" in pdf) || pdf.html === undefined) return pdf;
  if (isRobotCheck(signalsOfHtml(pdf.html, pdf.status ?? 200))) return pdf;
  return viaTab(url, pdf);
}

/** One paper's PDF from its publisher's page: null once saved, else why
 * not (a robot check, no access, no PDF, or another error). */
/** An open copy's PDF, fetched here without cookies (it needs no login);
 * null if it is not a whole PDF. */
async function openCopy(url: string): Promise<Uint8Array<ArrayBuffer> | null> {
  if (!url.startsWith("https://")) return null;
  try {
    const response = await fetch(url, { credentials: "omit" });
    if (!response.ok) return null;
    const bytes = new Uint8Array(await response.arrayBuffer());
    const head = String.fromCharCode(...bytes.slice(0, 5));
    return head === "%PDF-" && bytes.length <= MAX_BYTES ? bytes : null;
  } catch {
    return null;
  }
}

/** Into the paper (or the version it lacks a file for). */
async function saveInto(
  paper: Wanted,
  bytes: Uint8Array<ArrayBuffer>,
  name: string,
): Promise<{ cause: Cause; reason: string } | null> {
  const form = new FormData();
  form.append("upload", new Blob([bytes], { type: "application/pdf" }), name);
  const { status } = paper.version_id
    ? await call<Api.UploadToVersionData>("/api/versions/{version_id}/files", {
        method: "POST",
        path: { version_id: paper.version_id },
        form,
      })
    : await call<Api.UploadToItemData>("/api/items/{item_id}/files", {
        method: "POST",
        path: { item_id: paper.item_id },
        form,
      });
  return status < 300
    ? null
    : { cause: "error", reason: "paperus no longer has this paper." };
}

async function getOne(
  paper: Wanted,
): Promise<{ cause: Cause; reason: string } | null> {
  const because = (cause: Cause, detail?: string) => ({
    cause,
    reason: detail && cause === "error" ? detail : EXPLAINED[cause],
  });
  // Open copies first: publishers often refuse servers, not browsers.
  for (const copy of paper.copies ?? []) {
    const bytes = await openCopy(copy);
    if (bytes)
      return saveInto(paper, bytes, filename({ url: copy, pdfUrl: copy }));
  }
  if (!/^https?:\/\//.test(paper.url))
    return because("error", "No address to open.");
  const tab = await chrome.tabs.create({ url: paper.url, active: false });
  const tabId = tab.id!;
  try {
    await loaded(tabId);
    const page = await within(READ_MS, inPage(tabId, readPage));
    const pdfUrl = page.isPdf
      ? page.url
      : page.pdfUrl
        ? directPdf(page.pdfUrl)
        : readerPdf(page.url);
    trace("Publisher's page read (Missing)", {
      page: paper.url,
      landed: (await chrome.tabs.get(tabId)).url ?? null,
      pdfLink: pdfUrl,
    });
    if (!pdfUrl)
      return because(
        causeOf(await within(READ_MS, inPage(tabId, pageSignals))),
      );
    const pdf = await orInTab(
      await onwards(await inPage(tabId, fetchPdf, pdfUrl, MAX_BYTES)),
      pdfUrl,
    );
    trace("The PDF (Missing)", { paper: paper.title, ...fetched(pdf) });
    if ("error" in pdf) {
      const cause =
        pdf.html === undefined
          ? "no-pdf"
          : causeOf(signalsOfHtml(pdf.html, pdf.status ?? 200));
      return because(cause === "no-pdf" ? "error" : cause, pdf.error);
    }
    return await saveInto(
      paper,
      decode(pdf),
      filename({ url: pdfUrl, pdfUrl }),
    );
  } catch (error) {
    return because(
      "error",
      error instanceof Error ? error.message : String(error),
    );
  } finally {
    await chrome.tabs.remove(tabId).catch(() => undefined);
  }
}

/** Until the tab has loaded (and a moment more: pages fill in their
 * details by script). */
function loaded(tabId: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const finish = (error?: Error) => {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      if (error) reject(error);
      else setTimeout(resolve, 1500);
    };
    const listener = (id: number, change: { status?: string }) => {
      if (id === tabId && change.status === "complete") finish();
    };
    const timer = setTimeout(
      () => finish(new Error("The publisher’s page did not finish loading.")),
      PAGE_WAIT_MS,
    );
    chrome.tabs.onUpdated.addListener(listener);
    // It may have loaded already.
    chrome.tabs.get(tabId).then(
      (tab) => {
        if (tab.status === "complete") finish();
      },
      () => finish(new Error("The tab was closed.")),
    );
  });
}
