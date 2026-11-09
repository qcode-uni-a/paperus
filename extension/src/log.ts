/** What went wrong (and some of what happened), in the browser's console
 * and sent to paperus, where its administrators read it (Administration →
 * Logs): which publisher refused a PDF, and why. Sent in small batches; an
 * older paperus without the log, or none connected, lets them go. */
import { type Api, call } from "./paperus";

type Level = "info" | "warning" | "error";
type Context = Record<string, string | number | boolean | null>;

const KEEP = 200;
const BATCH = 50;
const pending: Api.ExtensionReport[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;

export function logIssue(level: Level, message: string, context?: Context): void {
  const write =
    level === "error"
      ? console.error
      : level === "warning"
        ? console.warn
        : console.info;
  write("paperus:", message, context ?? "");
  pending.push({
    level,
    message: message.slice(0, 4000),
    at: new Date().toISOString(),
    context,
  });
  pending.splice(0, Math.max(0, pending.length - KEEP));
  clearTimeout(timer);
  // Soon: a background script may be stopped when idle.
  timer = setTimeout(() => void send(), 1000);
}

async function send(): Promise<void> {
  while (pending.length) {
    const entries = pending.splice(0, BATCH);
    try {
      await call<Api.ReportData>("/api/logs", {
        method: "POST",
        json: { version: chrome.runtime.getManifest().version, entries },
      });
    } catch {
      return; // not connected, or paperus away: these stay in the console
    }
  }
}
