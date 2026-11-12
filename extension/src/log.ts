/** What the extension did, to find out why something failed: every step
 * (``trace``) and every problem (``logIssue``)
 *
 * - sent to paperus, where its administrators read them (Administration →
 *   Logs): the page read, each fetch and its answer, which publisher
 *   refused a PDF, and why;
 * - kept in the browser too, the last twenty, for the settings page
 *   (to copy).
 *
 * Sent in small batches; an older paperus without the log, or none
 * connected, lets them go. */
import { type Api, call } from "./paperus";

type Level = "info" | "warning" | "error";
export type Context = Record<
  string,
  string | number | boolean | null | undefined
>;

export interface Entry {
  at: string;
  level: Level;
  message: string;
  context?: Context;
}

const KEEP = 200;
const BATCH = 50;
/** Entries kept in the browser for the settings page: enough for one save
 * or two, to copy into an issue or for an AI agent. */
const KEEP_HERE = 20;
const pending: Api.ExtensionReport[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;
let written: Promise<void> = Promise.resolve();

/** Something went wrong (or only partly right): kept and sent. */
export function logIssue(
  level: Level,
  message: string,
  context?: Context,
): void {
  const write =
    level === "error"
      ? console.error
      : level === "warning"
        ? console.warn
        : console.info;
  write("paperus:", message, context ?? "");
  keep(level, message, context);
  queue(level, message, context);
}

/** A step on the way (the page read, a fetch and its answer, a tab). */
export function trace(message: string, context?: Context): void {
  console.info("paperus:", message, context ?? "");
  keep("info", message, context);
  queue("info", message, context);
}

function clean(context?: Context): Api.ExtensionReport["context"] {
  if (!context) return undefined;
  return Object.fromEntries(
    Object.entries(context)
      .filter(([, value]) => value !== undefined)
      .map(([key, value]) => [
        key,
        typeof value === "string" ? value.slice(0, 1000) : (value ?? null),
      ]),
  ) as Api.ExtensionReport["context"];
}

function keep(level: Level, message: string, context?: Context): void {
  const entry: Entry = {
    at: new Date().toISOString(),
    level,
    message: message.slice(0, 2000),
    context: clean(context) ?? undefined,
  };
  // One after another: two steps at once must not lose each other.
  written = written
    .then(async () => {
      const { log = [] } = (await chrome.storage.local.get("log")) as {
        log?: Entry[];
      };
      log.push(entry);
      await chrome.storage.local.set({ log: log.slice(-KEEP_HERE) });
    })
    .catch(() => undefined);
}

function queue(level: Level, message: string, context?: Context): void {
  pending.push({
    level,
    message: message.slice(0, 4000),
    at: new Date().toISOString(),
    context: clean(context),
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
      return; // not connected, or paperus away: kept here all the same
    }
  }
}
