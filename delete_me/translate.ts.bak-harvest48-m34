/**
 * Module `client/frontend/src/pages/video-page/translate.ts`: the Translate toggle and the English line shown over the embedded player.
 *
 * One PeerTubePlayer is built per page, on #video-embed, right after its api=1 src is set. A second one on the same iframe window throws, and destroy() removes the iframe, so neither is ever done. The toggle shows only once the embed API's `ready` resolved and a profile key is held; before that no translate request is made. The on-load path and the click path are the same turnOn, so a page loaded with Translate on behaves like a click.
 */

import { PeerTubePlayer } from "@peertube/embed-api";
import { getProfileKey } from "../../data/profile";
import { fetchTranslate, readTranslate, setTranslate, type TranslateCue } from "../../data/translate";

export type TranslateVideo = { id: string; host: string };

const toggleEl = document.getElementById("translate-toggle") as HTMLButtonElement | null;
const statusEl = document.getElementById("translate-status");
const overlayEl = document.getElementById("translate-overlay");
const NO_TRANSLATION = "No English translation is available for this video.";
// The embed's playbackStatusUpdate is the clock; getCurrentPosition is polled only after this much silence.
const POLL_AFTER_SILENCE_MS = 3000;
const POLL_INTERVAL_MS = 1000;

let started = false;
let player: PeerTubePlayer | null = null;
let on = false;
let cues: TranslateCue[] = [];
// Bumped by every turn-on and turn-off, so the reply to an earlier request is dropped.
let requestTicket = 0;
let lastUpdateAt = 0;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let pollInFlight = false;

/**
 * The embed URL with api=1 set, correct with or without an existing query; null when it does not parse.
 */
export function withEmbedApi(embed: string): string | null {
  try {
    const url = new URL(embed.trim());
    url.searchParams.set("api", "1");
    return url.href;
  } catch {
    return null;
  }
}

/**
 * Bind the embed API to the iframe once per page and show the toggle when it answers; never throws.
 */
export function setupTranslate(iframe: HTMLIFrameElement, apiBase: string, video: TranslateVideo): void {
  if (started || !toggleEl || !overlayEl) return;
  started = true;
  let created: PeerTubePlayer;
  try {
    created = new PeerTubePlayer(iframe);
  } catch {
    // jschannel throws strings, not Errors, when this window or the iframe cannot post messages; the page works on with no toggle.
    return;
  }
  // A rejected ready is caught here, so it never surfaces as an unhandled rejection; one that never settles leaves the toggle hidden.
  created.ready.then(() => onReady(created, apiBase, video), () => undefined);
}

/**
 * Binary-search cues sorted by start for the latest-started cue, and return it when it contains position.
 */
function findCue(sorted: TranslateCue[], position: number): TranslateCue | null {
  let low = 0;
  let high = sorted.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (sorted[mid].start <= position) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  const cue = found >= 0 ? sorted[found] : null;
  return cue && position < cue.end ? cue : null;
}

function onReady(ready: PeerTubePlayer, apiBase: string, video: TranslateVideo) {
  if (!toggleEl || !getProfileKey() || !video.id || !video.host) return;
  player = ready;
  // Subscribed once and never removed; updates are ignored while Translate is off.
  ready.addEventListener("playbackStatusUpdate", (status: unknown) => {
    lastUpdateAt = Date.now();
    showAt(finiteNumber((status as { position?: unknown } | null)?.position));
  });
  toggleEl.addEventListener("click", () => {
    if (on) turnOff();
    else void turnOn(apiBase, video);
  });
  renderToggle();
  toggleEl.hidden = false;
  if (readTranslate()) void turnOn(apiBase, video);
}

async function turnOn(apiBase: string, video: TranslateVideo) {
  on = true;
  setTranslate(true);
  renderToggle();
  setStatus("Loading translation…");
  const ticket = ++requestTicket;
  try {
    const state = await fetchTranslate(apiBase, video.id, video.host);
    if (ticket !== requestTicket) return;
    if (state.state === "none") {
      cues = [];
      setStatus(NO_TRANSLATION);
      return;
    }
    cues = state.cues;
    setStatus("");
    startPolling();
  } catch (error) {
    if (ticket !== requestTicket) return;
    setStatus(error instanceof Error ? error.message : "Could not load the translation");
  }
}

function turnOff() {
  on = false;
  requestTicket += 1;
  cues = [];
  setTranslate(false);
  stopPolling();
  renderToggle();
  setStatus("");
  showText("");
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(() => {
    if (!player || pollInFlight || Date.now() - lastUpdateAt < POLL_AFTER_SILENCE_MS) return;
    // rat-tail: getCurrentPosition has no timeout, so one call at a time; a call that never settles stops the fallback for this page, a per-call timeout if that is seen.
    pollInFlight = true;
    player.getCurrentPosition().then((position: unknown) => showAt(finiteNumber(position)), () => undefined).finally(() => { pollInFlight = false; });
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer !== null) clearInterval(pollTimer);
  pollTimer = null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function showAt(position: number | null) {
  if (!on || position === null) return;
  showText(findCue(cues, position)?.text ?? "");
}

// Cue text is untrusted instance text: set with textContent only.
function showText(text: string) {
  if (!overlayEl) return;
  overlayEl.textContent = text;
  overlayEl.hidden = !text;
}

function renderToggle() {
  if (!toggleEl) return;
  toggleEl.setAttribute("aria-pressed", String(on));
  toggleEl.classList.toggle("active", on);
}

function setStatus(text: string) {
  if (statusEl) statusEl.textContent = text;
}
