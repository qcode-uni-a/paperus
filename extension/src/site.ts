/** On the connected paperus only: says the extension is there (Manage →
 * Missing then offers getting PDFs with it) and passes on the page's
 * requests and the extension's progress. Registered for the paperus
 * site's host (match patterns have no port), so it checks the address. */

import { settings } from "./paperus";

interface Wanted {
  item_id: string;
  version_id?: string | null;
  title: string;
  url: string;
  copies?: string[];
}

settings().then((config) => {
  if (!config || new URL(config.server).origin !== location.origin) return;
  const root = document.documentElement;
  root.dataset.paperusExtension = chrome.runtime.getManifest().version;
  root.dataset.paperusExtensionFeatures = "get-pdfs";

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== location.origin) return;
    const data = event.data as { type?: string; papers?: Wanted[] } | null;
    if (data?.type !== "paperus:get-pdfs" || !Array.isArray(data.papers))
      return;
    const papers = data.papers
      .filter(
        (p) => typeof p?.item_id === "string" && typeof p.url === "string",
      )
      .slice(0, 500)
      .map((p) => ({
        ...p,
        copies: (Array.isArray(p.copies) ? p.copies : [])
          .filter((c) => typeof c === "string" && c.startsWith("https://"))
          .slice(0, 10),
      }));
    chrome.runtime.sendMessage({ type: "getPdfs", papers });
  });

  // Progress and results, back to the page.
  chrome.runtime.onMessage.addListener((message) => {
    if (
      message?.type === "getPdfsProgress" ||
      message?.type === "getPdfsDone"
    ) {
      window.postMessage(
        { ...message, type: `paperus:${message.type}` },
        location.origin,
      );
    }
  });
});
