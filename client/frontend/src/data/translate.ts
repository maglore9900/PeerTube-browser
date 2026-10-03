/**
 * Module `client/frontend/src/data/translate.ts`: the Translate setting and the gateway read of a video's English cues.
 *
 * The setting lives in this browser only (`translate:v1`), off unless the visitor turned it on; it does not follow the profile key.
 */

import { resolveClientApiBase } from "./api-base";
import { ProfileKeyRejectedError, profileHeaders } from "./profile";

export type TranslateCue = { start: number; end: number; text: string };
export type TranslateState = { state: "ready"; cues: TranslateCue[] } | { state: "none" };

const TRANSLATE_KEY = "translate:v1";

// Set on every change, so the choice holds on this page even when storage refuses the write.
let translateInMemory: boolean | null = null;

/**
 * Whether Translate is on: only a stored "on" means on; missing, unreadable or corrupt storage means off.
 */
export function readTranslate(): boolean {
  if (translateInMemory !== null) return translateInMemory;
  try {
    return window.localStorage.getItem(TRANSLATE_KEY) === "on";
  } catch {
    return false;
  }
}

/**
 * Turn Translate on or off for this page and, when storage allows, for later videos.
 */
export function setTranslate(on: boolean) {
  translateInMemory = on;
  try {
    window.localStorage.setItem(TRANSLATE_KEY, on ? "on" : "off");
  } catch {
    // Ignore storage failures (quota/private mode): the in-memory value above still applies on this page.
  }
}

/**
 * Read a video's English translate state from the Client gateway; a 401 throws ProfileKeyRejectedError, a malformed body throws.
 */
export async function fetchTranslate(apiBase: string, id: string, host: string): Promise<TranslateState> {
  const url = new URL("/api/translate", resolveClientApiBase(apiBase));
  url.searchParams.set("id", id);
  url.searchParams.set("host", host);
  // A none can become ready once a track exists, so a stored answer must never be reused.
  const response = await fetch(url, { headers: profileHeaders(), cache: "no-store" });
  if (response.status === 401) throw new ProfileKeyRejectedError("Your profile key is no longer valid");
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : {};
  if (!response.ok) {
    const message = (payload as { error?: unknown } | null)?.error;
    throw new Error(typeof message === "string" ? message : `Translate request failed (${response.status})`);
  }
  return parseTranslateState(payload);
}

/**
 * Check the gateway's payload rather than trust it; cues come back sorted by start for the page's binary search.
 */
function parseTranslateState(payload: unknown): TranslateState {
  const body = payload as { state?: unknown; cues?: unknown } | null;
  if (body?.state === "none") return { state: "none" };
  if (body?.state !== "ready" || !Array.isArray(body.cues)) throw new Error("Translate response was malformed");
  const cues = body.cues.map((cue: { start?: unknown; end?: unknown; text?: unknown } | null) => {
    if (!Number.isFinite(cue?.start) || !Number.isFinite(cue?.end) || typeof cue?.text !== "string") throw new Error("Translate response was malformed");
    return { start: cue.start as number, end: cue.end as number, text: cue.text };
  });
  return { state: "ready", cues: cues.sort((a, b) => a.start - b.start || a.end - b.end) };
}
