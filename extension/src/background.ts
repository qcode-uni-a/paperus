/** One click on the toolbar button saves the page's paper to paperus, with
 * its PDF (fetched in the page, with the reader's own access); an open PDF
 * is saved as it is, paperus reads its details. The button's menu (right
 * click) saves to another owner. */
import { type Cause, causeOf, EXPLAINED, signalsOfHtml } from "./causes";
import {
  fetchPdf,
  idsInUrl,
  type PageInfo,
  pageSignals,
  readPage,
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
  | { error: string; status?: number; html?: string };
/** Saved; with ``warning``, only in part: the paper without its PDF. */
type Saved = { ok: true; text: string; link: string; warning?: boolean };
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
  });
  return result.result as Awaited<R>;
}

async function saveTab(
  tab: chrome.tabs.Tab,
  owner?: Owner,
): Promise<Saved | { ok: false; text: string }> {
  const tabId = tab.id!;
  await badge(tabId, "…");
  try {
    const result = await saveFrom(tab, owner);
    if (result.warning) await badge(tabId, "!", "#b26a00");
    else await badge(tabId, "✓", "#1e7a3e");
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
    await badge(tabId, "!", "#c0392b");
    await tell(tabId, text, null, "error");
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
  const page = await inPage(tab.id!, readPage).catch(() => null);
  const url = page?.url ?? tab.url ?? "";
  const inUrl = idsInUrl(url);
  if (!page) return saveClosedTab(tab, url, inUrl, owner);
  const info = {
    ...page,
    doi: page.doi ?? inUrl.doi,
    arxiv: page.arxiv ?? inUrl.arxiv,
  };
  const pdf = info.arxiv
    ? await arxivPdf(info.arxiv)
    : page.isPdf || page.pdfUrl
      ? await inPage(
          tab.id!,
          fetchPdf,
          page.isPdf ? page.url : page.pdfUrl!,
          MAX_BYTES,
        )
      : { error: "The page links no PDF." };
  return page.isPdf && !info.doi && !info.arxiv
    ? saveFile(pdf, url, owner)
    : save(info, pdf, owner);
}

/** A tab the extension may not read: a browser's own PDF viewer (Firefox's),
 * or a page closed to extensions. A PDF there is fetched from here. */
async function saveClosedTab(
  tab: chrome.tabs.Tab,
  url: string,
  inUrl: { doi: string | null; arxiv: string | null },
  owner?: Owner,
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
  const pdf = await fetchPdf(url, MAX_BYTES);
  if ("error" in pdf && !inUrl.doi)
    throw new PaperusError("The browser lets no extension into this page.");
  return inUrl.doi
    ? save({ ...inUrl, title: null, url, isPdf: true }, pdf, owner)
    : saveFile(pdf, url, owner);
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
  pdf: Pdf,
  owner?: Owner,
): Promise<Saved> {
  const target = owner ?? defaultOwner(await settings());
  const library = target ? { library_id: target.id } : {};
  const doi = page.doi ?? (page.arxiv ? `10.48550/arXiv.${page.arxiv}` : null);
  const addItem = (json: Api.ItemIn) =>
    call<Api.AddItemData, Api.AddItemResponse>("/api/items", {
      method: "POST",
      json,
    });
  let added = doi ? await addItem({ doi, ...library }).catch(() => null) : null;
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
  const where = owner ? owner.name : "paperus";
  const saved = `${known ? "Already in paperus" : `Saved to ${where}`}: “${item.title}”`;
  return missing
    ? {
        ok: true,
        warning: true,
        text: `${saved}, without its PDF. ${missing}`,
        link: await itemLink(item.id),
      }
    : { ok: true, text: `${saved}.${fileNote}`, link: await itemLink(item.id) };
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
    return status === 404 ? "The paper was not found when its PDF was added." : null;
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

/** arXiv's PDFs are open: fetched here directly. */
async function arxivPdf(id: string): Promise<Pdf> {
  try {
    const response = await fetch(`https://arxiv.org/pdf/${id}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (!response.ok || String.fromCharCode(...bytes.slice(0, 5)) !== "%PDF-") {
      return { error: "arXiv gave no PDF." };
    }
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    return { base64: btoa(binary), size: bytes.length };
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
// One at a time: publishers take many quick downloads for a robot.
const PAGE_WAIT_MS = 45_000;

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
  const failed: { item_id: string; reason: string; cause: Cause }[] = [];
  for (const [index, paper] of papers.entries()) {
    const problem = await getOne(paper);
    if (problem) failed.push({ item_id: paper.item_id, ...problem });
    else saved++;
    await report({
      type: "getPdfsProgress",
      done: index + 1,
      total: papers.length,
      saved,
      item_id: paper.item_id,
      ok: problem === null,
      ...(problem ?? {}),
    });
  }
  await report({ type: "getPdfsDone", total: papers.length, saved, failed });
}

/** Why a PDF link gave no PDF, in words: a robot check, no access, … */
function pdfProblem(pdf: {
  error: string;
  status?: number;
  html?: string;
}): string {
  if (pdf.html === undefined) return pdf.error;
  const cause = causeOf(signalsOfHtml(pdf.html, pdf.status ?? 200));
  return cause === "no-pdf" ? pdf.error : EXPLAINED[cause];
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
    const page = await inPage(tabId, readPage);
    const pdfUrl = page.isPdf ? page.url : page.pdfUrl;
    if (!pdfUrl) return because(causeOf(await inPage(tabId, pageSignals)));
    const pdf = await inPage(tabId, fetchPdf, pdfUrl, MAX_BYTES);
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
