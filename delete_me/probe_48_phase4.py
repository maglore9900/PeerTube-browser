"""Throwaway probe for phase 4: run the checkpoint's tests against a copy of src/ carrying the plan's §4 code, and against mutants of it."""
from __future__ import annotations

import importlib.util
import shutil
import traceback
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("phase4_checkpoint", HERE / "test_48_translate_instance_captions_phase4.py")
t4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t4)
REAL = t4.FRONTEND

DATA_TS = r'''
import { resolveClientApiBase } from "./api-base";
import { ProfileKeyRejectedError, profileHeaders } from "./profile";
export type TranslateCue = { start: number; end: number; text: string };
export type TranslateState = { state: "ready"; cues: TranslateCue[] } | { state: "none" };
const TRANSLATE_KEY = "translate:v1";
let translateInMemory: boolean | null = null;
export function readTranslate(): boolean {
  if (translateInMemory !== null) return translateInMemory;
  try { return window.localStorage.getItem(TRANSLATE_KEY) === "on"; } catch { return false; }
}
export function setTranslate(on: boolean) {
  translateInMemory = on;
  try { window.localStorage.setItem(TRANSLATE_KEY, on ? "on" : "off"); } catch {}
}
export async function fetchTranslate(apiBase: string, id: string, host: string): Promise<TranslateState> {
  const url = new URL("/api/translate", resolveClientApiBase(apiBase));
  url.searchParams.set("id", id);
  url.searchParams.set("host", host);
  const response = await fetch(url, { headers: profileHeaders(), cache: "no-store" });
  if (response.status === 401) throw new ProfileKeyRejectedError("Your profile key is no longer valid");
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : {};
  if (!response.ok) { const message = (payload as { error?: unknown }).error; throw new Error(typeof message === "string" ? message : `Translate request failed (${response.status})`); }
  const body = payload as { state?: unknown; cues?: unknown };
  if (body?.state === "none") return { state: "none" };
  if (body?.state !== "ready" || !Array.isArray(body.cues)) throw new Error("Translate response was malformed");
  const cues = body.cues.map((cue: any) => ({ start: cue.start, end: cue.end, text: cue.text }));
  return { state: "ready", cues: cues.sort((a: any, b: any) => a.start - b.start || a.end - b.end) };
}
'''

PAGE_TS = r'''
import { PeerTubePlayer } from "@peertube/embed-api";
import { getProfileKey } from "../../data/profile";
import { fetchTranslate, readTranslate, setTranslate, type TranslateCue } from "../../data/translate";
export type TranslateVideo = { id: string; host: string };
const toggleEl = document.getElementById("translate-toggle") as HTMLButtonElement | null;
const statusEl = document.getElementById("translate-status");
const overlayEl = document.getElementById("translate-overlay");
const NO_TRANSLATION = "No English translation is available for this video.";
const POLL_AFTER_SILENCE_MS = 3000;
const POLL_INTERVAL_MS = 1000;
let started = false;
let player: any = null;
let on = false;
let cues: TranslateCue[] = [];
let requestTicket = 0;
let lastUpdateAt = 0;
let pollTimer: any = null;
let pollInFlight = false;
export function withEmbedApi(embed: string): string | null {
  try { const url = new URL(embed.trim()); url.searchParams.set("api", "1"); return url.href; } catch { return null; }
}
export function setupTranslate(iframe: HTMLIFrameElement, apiBase: string, video: TranslateVideo): void {
  if (started || !toggleEl || !overlayEl) return;
  started = true;
  let created: any;
  try { created = new PeerTubePlayer(iframe); } catch { return; }
  /*READY*/created.ready.then(() => onReady(created, apiBase, video), () => undefined);
}
export function findCue(sorted: TranslateCue[], position: number): TranslateCue | null {
  let low = 0; let high = sorted.length - 1; let found = -1;
  while (low <= high) { const mid = (low + high) >> 1; if (sorted[mid].start <= position) { found = mid; low = mid + 1; } else { high = mid - 1; } }
  const cue = found >= 0 ? sorted[found] : null;
  return cue && position < cue.end ? cue : null;
}
function onReady(ready: any, apiBase: string, video: TranslateVideo) {
  if (!toggleEl || !getProfileKey() || !video.id || !video.host) return;
  player = ready;
  ready.addEventListener("playbackStatusUpdate", (status: any) => { lastUpdateAt = Date.now(); showAt(finiteNumber(status?.position)); });
  toggleEl.addEventListener("click", () => { if (on) turnOff(); else void turnOn(apiBase, video); });
  toggleEl.setAttribute("aria-pressed", String(on));
  toggleEl.hidden = false;
  if (readTranslate()) void turnOn(apiBase, video);
}
async function turnOn(apiBase: string, video: TranslateVideo) {
  on = true; setTranslate(true); setStatus("Loading translation…");
  const ticket = ++requestTicket;
  try {
    const state = await fetchTranslate(apiBase, video.id, video.host);
    if (ticket !== requestTicket) return;
    if (state.state === "none") { cues = []; setStatus(NO_TRANSLATION); return; }
    cues = state.cues; setStatus(""); startPolling();
  } catch (error) { if (ticket !== requestTicket) return; setStatus(error instanceof Error ? error.message : "Could not load the translation"); }
}
function turnOff() { on = false; requestTicket += 1; cues = []; setTranslate(false); stopPolling(); setStatus(""); showText(""); }
function startPolling() {
  stopPolling();
  pollTimer = setInterval(() => {
    if (!player || pollInFlight || Date.now() - lastUpdateAt < POLL_AFTER_SILENCE_MS) return;
    pollInFlight = true;
    player.getCurrentPosition().then((position: unknown) => showAt(finiteNumber(position)), () => undefined).finally(() => { pollInFlight = false; });
  }, POLL_INTERVAL_MS);
}
function stopPolling() { if (pollTimer !== null) clearInterval(pollTimer); pollTimer = null; }
function finiteNumber(value: unknown): number | null { return typeof value === "number" && Number.isFinite(value) ? value : null; }
function showAt(position: number | null) { /*OFF*/if (!on || position === null) return; showText(findCue(cues, position)?.text ?? ""); }
function showText(text: string) { if (!overlayEl) return; /*SINK*/overlayEl.textContent = text; overlayEl.hidden = !text; }
function setStatus(text: string) { if (statusEl) statusEl.textContent = text; }
'''

OLD_BLOCK = '''    if (embed && /^https:\\/\\//i.test(embed.trim())) {
      embedEl.src = embed;
    } else {
      embedEl.removeAttribute("src");
    }'''
NEW_BLOCK = '''    const apiEmbed = embed && /^https:\\/\\//i.test(embed.trim()) ? withEmbedApi(embed) : null;
    if (apiEmbed) {
      /*ORDER*/embedEl.src = apiEmbed;
      setupTranslate(embedEl, apiBase, { id: metadata?.videoUuid || resolveVideoSource()?.id || "", host: resolveVideoSource()?.host || "" });
    } else {
      embedEl.removeAttribute("src");
    }'''

MUTANTS = {
    "plan": {},
    # R6 parallel wording: request on load alongside ready, gated by key only
    "parallel request": {"page": ("/*READY*/created.ready.then(", "if (getProfileKey() && readTranslate()) { void fetchTranslate(apiBase, video.id, video.host); } created.ready.then(")},
    "no key gate": {"page": ("if (!toggleEl || !getProfileKey() ||", "if (!toggleEl ||")},
    "unhandled reject": {"page": ("() => onReady(created, apiBase, video), () => undefined)", "() => onReady(created, apiBase, video))")},
    "uncaught constructor": {"page": ("try { created = new PeerTubePlayer(iframe); } catch { return; }", "created = new PeerTubePlayer(iframe);")},
    "innerHTML sink": {"page": ("/*SINK*/overlayEl.textContent = text;", "overlayEl.innerHTML = text;")},
    "forward-only search": {"page": ("export function findCue(sorted: TranslateCue[], position: number): TranslateCue | null {", "let cursor = 0;\nexport function findCue(sorted: TranslateCue[], position: number): TranslateCue | null {\n  while (cursor < sorted.length && sorted[cursor].end <= position) cursor += 1;\n  const c = sorted[cursor];\n  return c && c.start <= position && position < c.end ? c : null;\n}\nexport function unusedFindCue(sorted: TranslateCue[], position: number): TranslateCue | null {")},
    "end inclusive first match": {"page": ("export function findCue(sorted: TranslateCue[], position: number): TranslateCue | null {", "export function findCue(sorted: TranslateCue[], position: number): TranslateCue | null {\n  return sorted.find((c) => c.start <= position && position <= c.end) ?? null;\n}\nexport function unusedFindCue(sorted: TranslateCue[], position: number): TranslateCue | null {")},
    "gap keeps last cue": {"page": ("showText(findCue(cues, position)?.text ?? \"\");", "const hit = findCue(cues, position); if (hit) showText(hit.text);")},
    "off not ignored": {"page": ("/*OFF*/if (!on || position === null) return;", "if (position === null) return;")},
    "player before src": {"index": ("/*ORDER*/embedEl.src = apiEmbed;\n      setupTranslate(embedEl, apiBase, { id: metadata?.videoUuid || resolveVideoSource()?.id || \"\", host: resolveVideoSource()?.host || \"\" });", "setupTranslate(embedEl, apiBase, { id: metadata?.videoUuid || resolveVideoSource()?.id || \"\", host: resolveVideoSource()?.host || \"\" });\n      embedEl.src = apiEmbed;")},
    "seed id": {"index": ("{ id: metadata?.videoUuid || resolveVideoSource()?.id || \"\"", "{ id: resolveVideoSource()?.id || \"\"")},
    "no polling": {"page": ('cues = state.cues; setStatus(""); startPolling();', 'cues = state.cues; setStatus("");')},
    "off hides only": {"page": ("function turnOff() { on = false; requestTicket += 1; cues = []; setTranslate(false); stopPolling(); setStatus(\"\"); showText(\"\"); }\n", "function turnOff() { on = false; requestTicket += 1; setTranslate(false); stopPolling(); setStatus(\"\"); showText(\"\"); }\n"), "page2": ("/*OFF*/if (!on || position === null) return;", "if (position === null) return;")},
}


def _tree(tmp: Path, mutant: dict) -> Path:
    root = tmp / "frontend"
    shutil.copytree(REAL / "src", root / "src")
    (root / "video-page.html").write_text((REAL / "video-page.html").read_text())
    page, index = PAGE_TS, (REAL / "src" / "pages" / "video-page" / "index.ts").read_text()
    assert OLD_BLOCK in index
    index = index.replace(OLD_BLOCK, NEW_BLOCK).replace('import type { VideoRow } from "../../types/videos";', 'import type { VideoRow } from "../../types/videos";\nimport { setupTranslate, withEmbedApi } from "./translate";')
    if "page" in mutant:
        assert mutant["page"][0] in page, mutant
        page = page.replace(*mutant["page"])
    if "page2" in mutant:
        assert mutant["page2"][0] in page, mutant
        page = page.replace(*mutant["page2"])
    if "index" in mutant:
        assert mutant["index"][0] in index, mutant
        index = index.replace(*mutant["index"])
    (root / "src" / "data" / "translate.ts").write_text(DATA_TS)
    (root / "src" / "pages" / "video-page" / "translate.ts").write_text(page)
    (root / "src" / "pages" / "video-page" / "index.ts").write_text(index)
    return root


TESTS = [name for name in dir(t4) if name.startswith("test_")]


@pytest.mark.parametrize("mutant", MUTANTS, ids=MUTANTS.keys())
def test_probe(tmp_path_factory, mutant):
    t4.FRONTEND = _tree(tmp_path_factory.mktemp("tree"), MUTANTS[mutant])
    t4.INITIAL_TEXT = {"translate-toggle": "Translate"}
    bundle = t4.bundle.__wrapped__(tmp_path_factory) if hasattr(t4.bundle, "__wrapped__") else None
    if bundle is None:
        # pytest fixture function object: call the undecorated body
        bundle = t4.bundle.__pytest_wrapped__.obj(tmp_path_factory)
    results = {}
    for name in TESTS:
        fn = getattr(t4, name)
        cases = [{}] if name != "test_without_a_key_or_a_resolved_ready_there_is_no_toggle_no_translate_request_and_no_escaped_failure" else [{"case": c, "_id": k} for k, c in t4.BLOCKED.items()]
        if mutant != "plan" and "position_the_page_asks" in name and mutant != "no polling":
            continue
        for case in cases:
            label = name + (f"[{case.pop('_id')}]" if case else "")
            try:
                fn(bundle, **case)
                results[label] = "PASS"
            except AssertionError as exc:
                tb = traceback.extract_tb(exc.__traceback__)[-1]
                results[label] = f"FAIL line {tb.lineno}: {str(exc).splitlines()[0][:220]}"
    print(f"\n=== {mutant}")
    for label, outcome in results.items():
        print(f"{outcome[:4]}  {label}\n      {outcome}")
    assert False
