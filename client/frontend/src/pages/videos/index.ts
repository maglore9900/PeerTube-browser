/**
 * Module `client/frontend/src/pages/videos/index.ts`: provide runtime functionality.
 */

import "../../videos.css";
import {
  createFeedPager,
  fetchSimilarVideosPayload,
  parseSimilarQuery,
  resolveApiBase,
  type ExcludedVideo
} from "../../data/videos";
import { parseFeedMode, persistFeedParams, readNsfwFilter, resolveFeedParams, setNsfwFilter } from "../../data/feed-params";
import { clearLocalLikes } from "../../data/local-likes";
import { resetUserProfileLikes } from "../../data/user-profile";
import { cardReaction, importLocalLikes, sendReaction } from "../../data/reactions";
import {
  ProfileKeyRejectedError,
  createProfile,
  deleteProfile,
  getProfileKey,
  rotateProfileKey,
  storeProfileKey
} from "../../data/profile";
import { blockVideoSource, listBlocks, unblock, type Block } from "../../data/blocks";
import { keyRejectedNotice } from "../../components/key-rejected";
import {
  channelAvatarUrl,
  channelInitials,
  channelName,
  channelUrl,
  escapeHtml,
  formatDuration,
  formatStatValue,
  formatTimeAgo,
  iconEye,
  iconThumbDown,
  iconThumbUp,
  normalizeStatValue,
  publishedAtMs,
  renderVideoCard,
  resolveInstanceDomain,
  resolveVideoId,
  resolveVideoKey,
  thumbnailUrl,
  videoPageUrl,
  videoUrl
} from "../../components/video-card";
import { safeExternalUrl } from "../../utils/safe-url";
import type { SimilarSeed, VideoRow, VideosPayload } from "../../types/videos";

const cards = document.getElementById("video-cards");
const summaryCounts = document.getElementById("summary-counts");
const summaryMeta = document.getElementById("summary-meta");
const resetLink = document.getElementById("reset-feed") as HTMLAnchorElement | null;
const feedModeButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-feed-mode]"));
const feedSentinel = document.getElementById("feed-sentinel");
const profileModal = document.getElementById("profile-modal");
const profileSection = document.getElementById("profile-section");
const showProfileHeaderButton = document.getElementById("show-profile-header") as HTMLButtonElement | null;
const profileModalClose = document.getElementById("profile-modal-close") as HTMLButtonElement | null;

if (!cards || !summaryCounts || !summaryMeta) {
  throw new Error("Missing videos elements");
}

const numberFormat = new Intl.NumberFormat("en-US");
const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium" });
const CHUNK_SIZE = 6;
const params = new URLSearchParams(window.location.search);
const debugMode =
  params.get("debug") === "1" || document.body?.dataset.debug === "true";
if (debugMode && !params.get("debug")) {
  params.set("debug", "1");
}
const similarQuery = parseSimilarQuery(params);
const feedParams = resolveFeedParams(params);
const useSimilar = Boolean(similarQuery.id);
const apiBase = resolveApiBase(similarQuery);
const apiParam = params.get("api");

document.title = "PeerTube - Browser";

const state = {
  rows: [] as VideoRow[],
  sample: [] as VideoRow[],
  generatedAt: null as number | null,
  mode: "random" as "random" | "similar" | "personalized" | "ordered",
  seed: null as SimilarSeed | null,
  visibleCount: CHUNK_SIZE,
  loading: false
};
// One pager per load, so a reload starts with nothing shown and drops a replaced pager's result.
let pager = createFeedPager(fetchVideosPayload);
let fetchingMore = false;
let feedObserver: IntersectionObserver | null = null;
let fallbackListenersAttached = false;

type LiveStats = {
  views: number | null;
  likes: number | null;
  dislikes: number | null;
};

const statsCache = new Map<string, LiveStats>();
const statsLoading = new Set<string>();

// A browser that holds a key hands its local likes to the profile before its first keyed read.
const localLikesImported = importLocalLikes(apiBase).catch((error) => {
  console.warn("[likes] import failed; the local likes are kept for the next load", error);
});

void loadVideos();

if (showProfileHeaderButton) {
  showProfileHeaderButton.addEventListener("click", () => openProfileModal());
}

/**
 * Clear every like, the profile's and this browser's, then reload the feed they shaped.
 */
async function resetLikes() {
  clearLocalLikes();
  await resetUserProfileLikes(apiBase);
  await loadVideos();
}

for (const button of feedModeButtons) {
  const pressed = button.dataset.feedMode === feedParams.mode;
  button.setAttribute("aria-pressed", String(pressed));
  button.classList.toggle("active", pressed);
  button.addEventListener("click", () => chooseFeedMode(button.dataset.feedMode));
}

cards.addEventListener("click", (event) => {
  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>("[data-card-action]");
  const card = button?.closest<HTMLElement>(".video-card");
  const key = card?.dataset.videoKey;
  const row = key ? state.sample.find((candidate) => resolveVideoKey(candidate) === key) : undefined;
  if (button && card && row) void runCardAction(button, card, row);
});

if (profileModalClose) {
  profileModalClose.addEventListener("click", () => closeProfileModal());
}

if (profileModal) {
  profileModal.addEventListener("click", (event) => {
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (target.hasAttribute("data-modal-close")) {
      closeProfileModal();
    }
  });
}

window.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (profileModal?.hasAttribute("hidden")) return;
  closeProfileModal();
});

/**
 * Handle load videos.
 */
async function loadVideos() {
  state.loading = true;
  summaryCounts.textContent = "";
  summaryMeta.textContent = "";
  if (resetLink) resetLink.hidden = true;
  cards.innerHTML = `<div class="loading">Loading...</div>`;
  setupInfiniteScroll();

  const current = createFeedPager(fetchVideosPayload);
  pager = current;
  try {
    await localLikesImported;
    const payload = await current.next();
    // A newer load (an NSFW toggle, a likes reset) replaced this pager; its own result renders instead.
    if (current !== pager) return;
    state.loading = false;
    const rows = Array.isArray(payload) ? payload : payload.rows ?? [];
    state.rows = rows;
    state.generatedAt = Array.isArray(payload) ? null : payload.generatedAt ?? null;
    state.mode = useSimilar ? "similar" : feedParams.mode === "random" ? "random" : feedParams.mode === "recommendations" ? "personalized" : "ordered";
    state.seed = Array.isArray(payload)
      ? null
      : ((payload as VideosPayload & { seed?: SimilarSeed }).seed ?? null);
    pickSample();
    renderCards(true);
    renderSummary();
    maybeFillViewport();
  } catch (error) {
    if (current !== pager) return;
    state.loading = false;
    summaryCounts.textContent = "";
    summaryMeta.textContent = "";
    if (error instanceof ProfileKeyRejectedError) {
      cards.replaceChildren(keyRejectedNotice(() => void loadVideos()));
      return;
    }
    const message = error instanceof Error ? error.message : "Load error";
    cards.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
  }
}

/**
 * Handle fetch videos payload.
 */
async function fetchVideosPayload(exclude: ExcludedVideo[] = []) {
  if (useSimilar) {
    return fetchSimilarVideosPayload(similarQuery, exclude);
  }
  // The feed-params module names the mode; the page's own ?random= is folded into it.
  return fetchSimilarVideosPayload({ ...similarQuery, apiBase, random: null }, exclude, feedParams);
}

/**
 * Fetch the next batch once the revealed rows reach the end of the ones fetched.
 */
async function loadMoreVideos() {
  const current = pager;
  if (state.loading || fetchingMore || current.exhausted) return;
  fetchingMore = true;
  let appended = false;
  try {
    const payload = await current.next();
    if (current !== pager || !payload.rows?.length) return;
    state.rows.push(...payload.rows);
    state.sample.push(...payload.rows);
    appended = true;
  } catch (error) {
    console.warn("[feed] loading more failed; paging stops for this page view", error);
  } finally {
    fetchingMore = false;
  }
  // The sentinel may still be in view, so the observer will not fire again: reveal until it scrolls.
  if (appended) {
    loadNextChunk();
    maybeFillViewport();
  }
}

/**
 * Handle pick sample.
 */
function pickSample() {
  // Every feed but random arrives in the Engine's order (trending, recent and popular included), so only random is shuffled.
  state.sample = state.mode === "random" ? shuffle([...state.rows]) : state.rows.slice();
  state.visibleCount = CHUNK_SIZE;
}

/**
 * Handle render summary.
 */
function renderSummary() {
  const total = state.rows.length;
  const visible = Math.min(state.visibleCount, state.sample.length);
  if (state.mode === "similar") {
    summaryCounts.textContent = "";
    summaryMeta.textContent = "";
    if (resetLink) resetLink.hidden = false;
    return;
  }
  if (state.mode === "personalized") {
    summaryCounts.textContent = "";
    summaryMeta.textContent = "";
    if (resetLink) resetLink.hidden = true;
    return;
  }
  summaryCounts.textContent = "";
  summaryMeta.textContent = "";
  if (resetLink) resetLink.hidden = true;
}

/**
 * Handle visible sample.
 */
function visibleSample() {
  return state.sample.slice(0, state.visibleCount);
}

/**
 * Handle load next chunk.
 */
function loadNextChunk() {
  const nextCount = Math.min(state.sample.length, state.visibleCount + CHUNK_SIZE);
  if (nextCount <= state.visibleCount) {
    void loadMoreVideos();
    return false;
  }
  state.visibleCount = nextCount;
  renderCards();
  renderSummary();
  return true;
}

/**
 * Handle maybe fill viewport.
 */
function maybeFillViewport() {
  if (state.loading) return;
  let safety = 0;
  // If there is no scroll yet, keep appending chunks until the page can scroll.
  while (
    state.visibleCount < state.sample.length &&
    document.documentElement.scrollHeight <= window.innerHeight + 120 &&
    safety < 50
  ) {
    const changed = loadNextChunk();
    if (!changed) break;
    safety += 1;
  }
}

/**
 * Handle maybe load on scroll.
 */
function maybeLoadOnScroll() {
  if (state.loading) return;
  const nearBottom =
    window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;
  if (nearBottom) {
    loadNextChunk();
  }
}

/**
 * Handle setup infinite scroll.
 */
function setupInfiniteScroll() {
  if (feedObserver) {
    feedObserver.disconnect();
    feedObserver = null;
  }
  if (feedSentinel) {
    feedObserver = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        loadNextChunk();
      },
      { rootMargin: "200px" }
    );
    feedObserver.observe(feedSentinel);
  }
  if (!fallbackListenersAttached) {
    window.addEventListener("scroll", maybeLoadOnScroll, { passive: true });
    window.addEventListener("resize", () => {
      maybeLoadOnScroll();
      maybeFillViewport();
    });
    fallbackListenersAttached = true;
  }
}

/**
 * Render the visible slice of the sample into the grid.
 *
 * Cards come from the shared component; the feed supplies what only it knows - the
 * live-stats cache and, in debug mode, the ranking metrics block.
 */
function renderCards(reset = false) {
  const visibleRows = visibleSample();
  if (!visibleRows.length) {
    cards.innerHTML = `<div class="error">No videos found.</div>`;
    return;
  }

  if (reset) {
    cards.innerHTML = visibleRows.map((row) => renderFeedCard(row)).join("");
    queueStatsForRows(visibleRows);
    return;
  }

  const existingCount = cards.querySelectorAll(".video-card").length;
  if (existingCount >= visibleRows.length) return;
  const newRows = visibleRows.slice(existingCount);
  const markup = newRows.map((row) => renderFeedCard(row)).join("");
  cards.insertAdjacentHTML("beforeend", markup);
  queueStatsForRows(newRows);
}

/**
 * Render one feed card through the shared component.
 */
function renderFeedCard(row: VideoRow) {
  return renderVideoCard(row, {
    stats: resolveCachedStats(row),
    footerExtraHtml: renderDebugMetrics(row),
    apiParam,
    reaction: cardReaction(row),
    actions: true
  });
}

/**
 * Like, dislike or block from a card; a block dislikes the video too. A dislike or a block takes
 * the affected rows off the page at once; the Client already leaves them out of every later page.
 */
async function runCardAction(button: HTMLButtonElement, card: HTMLElement, row: VideoRow) {
  const action = button.dataset.cardAction ?? "";
  const uuid = resolveVideoId(row);
  const host = resolveInstanceDomain(row);
  const status = card.querySelector<HTMLElement>(".card-action-status");
  const say = (text: string) => {
    if (status) status.textContent = text;
  };
  if (action !== "like" && !getProfileKey()) {
    say(`${action === "dislike" ? "Disliking" : "Blocking"} needs a profile. Create one from the Profile button.`);
    return;
  }
  button.disabled = true;
  say("");
  try {
    if (action === "like") {
      const liked = cardReaction(row) === "liked";
      await sendReaction(apiBase, liked ? "undo_like" : "like", { uuid, host });
      row.reaction = liked ? null : "liked";
      card.outerHTML = renderFeedCard(row);
    } else if (action === "dislike") {
      await sendReaction(apiBase, "dislike", { uuid, host });
      removeRows((candidate) => candidate === row);
    } else if (action === "channel" || action === "account") {
      const block = await blockVideoSource(apiBase, action, uuid, host);
      // Blocking also dislikes the video, so the feed steers away from videos like it.
      const disliked = await sendReaction(apiBase, "dislike", { uuid, host }).then(
        () => null,
        (error: unknown) => (error instanceof Error ? error.message : "Dislike failed")
      );
      if (disliked !== null) {
        say(`Blocked ${block.label || action}, but the dislike failed: ${disliked}`);
        return;
      }
      removeRows(
        block.kind === "channel"
          ? (candidate) =>
              String(candidate.instance_domain ?? "") === block.instance_domain &&
              String(candidate.channel_id ?? "") === block.channel_id
          : (candidate) => String(candidate.account_url ?? "") === block.account_url
      );
    }
  } catch (error) {
    say(error instanceof Error ? error.message : "Action failed");
  } finally {
    button.disabled = false;
  }
}

/**
 * Drop matching rows from the feed and re-render; later rows move up into the freed slots.
 */
function removeRows(match: (row: VideoRow) => boolean) {
  state.rows = state.rows.filter((row) => !match(row));
  state.sample = state.sample.filter((row) => !match(row));
  renderCards(true);
  maybeFillViewport();
}

function shuffle<T>(items: T[]) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

/**
 * Handle render debug metrics.
 */
function renderDebugMetrics(row: VideoRow) {
  if (!debugMode) return "";
  const debug = row.debug ?? null;
  if (!debug) {
    return `<div class="video-debug empty">Debug not available</div>`;
  }
  const score = formatDebugNumber(debug.score);
  const similarity = formatDebugNumber(debug.similarity_score);
  const freshness = formatDebugNumber(debug.freshness_score);
  const popularity = formatDebugNumber(debug.popularity_score);
  const layer = debug.layer ?? "--";
  const rankBefore = formatDebugInt(debug.rank_before);
  const rankAfter = formatDebugInt(debug.rank_after);
  return `
    <div class="video-debug">
      <div><span class="label">score</span> ${score}</div>
      <div><span class="label">sim</span> ${similarity}</div>
      <div><span class="label">fresh</span> ${freshness}</div>
      <div><span class="label">pop</span> ${popularity}</div>
      <div><span class="label">layer</span> ${escapeHtml(layer)}</div>
      <div><span class="label">rank</span> ${rankBefore} → ${rankAfter}</div>
    </div>
  `;
}

/**
 * Handle format debug number.
 */
function formatDebugNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return Number(value).toFixed(3);
}

/**
 * Handle format debug int.
 */
function formatDebugInt(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return String(Math.trunc(value));
}

/**
 * Handle resolve cached stats.
 */
function resolveCachedStats(row: VideoRow) {
  const key = resolveVideoKey(row);
  if (!key) return null;
  if (statsCache.has(key)) return statsCache.get(key) ?? null;
  if (hasServerStats(row)) return resolveServerStats(row);
  return null;
}

/**
 * Check whether has server stats.
 */
function hasServerStats(row: VideoRow) {
  const hasViews =
    Object.prototype.hasOwnProperty.call(row, "views") ||
    Object.prototype.hasOwnProperty.call(row, "viewsCount") ||
    Object.prototype.hasOwnProperty.call(row, "views_count");
  const hasLikes =
    Object.prototype.hasOwnProperty.call(row, "likes") ||
    Object.prototype.hasOwnProperty.call(row, "likesCount") ||
    Object.prototype.hasOwnProperty.call(row, "likes_count");
  return hasViews && hasLikes;
}

/**
 * Handle resolve server stats.
 */
function resolveServerStats(row: VideoRow) {
  return {
    views: normalizeStatValue(row.views ?? row.viewsCount ?? row.views_count),
    likes: normalizeStatValue(row.likes ?? row.likesCount ?? row.likes_count),
    dislikes: normalizeStatValue(row.dislikes ?? row.dislikesCount ?? row.dislikes_count)
  };
}

/**
 * Handle queue stats for rows.
 */
function queueStatsForRows(rows: VideoRow[]) {
  if (!rows.length) return;
  const groups = new Map<string, { key: string; id: string }[]>();

  for (const row of rows) {
    const host = resolveInstanceDomain(row);
    const id = resolveVideoId(row);
    if (!host || !id) continue;
    const key = `${host}::${id}`;
    if (hasServerStats(row)) {
      if (!statsCache.has(key)) {
        statsCache.set(key, resolveServerStats(row));
      }
      continue;
    }
    const cached = statsCache.get(key);
    if (cached) {
      applyStatsToDom(key, cached);
      continue;
    }
    if (statsLoading.has(key)) continue;
    statsLoading.add(key);
    const batch = groups.get(host) ?? [];
    batch.push({ key, id });
    groups.set(host, batch);
  }

  for (const [host, entries] of groups) {
    void fetchStatsForHost(host, entries);
  }
}

/**
 * Handle fetch stats for host.
 */
async function fetchStatsForHost(host: string, entries: { key: string; id: string }[]) {
  const ids = entries.map((entry) => entry.id);
  try {
    const statsById = await fetchBatchStats(host, ids);
    const missing: { key: string; id: string }[] = [];
    for (const entry of entries) {
      if (!statsById.has(entry.id)) {
        missing.push(entry);
        continue;
      }
      const stats = statsById.get(entry.id) ?? { views: null, likes: null, dislikes: null };
      statsCache.set(entry.key, stats);
      statsLoading.delete(entry.key);
      applyStatsToDom(entry.key, stats);
    }
    if (missing.length) {
      await fetchStatsIndividually(host, missing);
    }
  } catch {
    await fetchStatsIndividually(host, entries);
  }
}

/**
 * Handle fetch stats individually.
 */
async function fetchStatsIndividually(host: string, entries: { key: string; id: string }[]) {
  await Promise.all(
    entries.map(async (entry) => {
      try {
        const stats = await fetchSingleStats(host, entry.id);
        const normalized = stats ?? { views: null, likes: null, dislikes: null };
        statsCache.set(entry.key, normalized);
        applyStatsToDom(entry.key, normalized);
      } finally {
        statsLoading.delete(entry.key);
      }
    })
  );
}

/**
 * Handle fetch batch stats.
 */
async function fetchBatchStats(host: string, ids: string[]) {
  const url = new URL(`https://${host}/api/v1/videos`);
  for (const id of ids) {
    url.searchParams.append("id", id);
  }
  url.searchParams.set("count", String(ids.length));
  const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error("Batch stats request failed");
  }
  const payload = (await response.json()) as Record<string, unknown>;
  const data = Array.isArray(payload.data) ? payload.data : null;
  if (!data) {
    throw new Error("Unexpected batch stats response");
  }
  const stats = new Map<string, LiveStats>();
  for (const item of data) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const uuid = record.uuid ?? record.video_uuid ?? record.videoUuid;
    const id = record.id ?? record.video_id ?? record.videoId;
    const views = normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
    const likes = normalizeStatValue(record.likes ?? record.likesCount ?? record.likes_count);
    const dislikes = normalizeStatValue(record.dislikes ?? record.dislikesCount ?? record.dislikes_count);
    const entry = { views, likes, dislikes };
    if (uuid) stats.set(String(uuid), entry);
    if (id) stats.set(String(id), entry);
  }
  return stats;
}

/**
 * Handle fetch single stats.
 */
async function fetchSingleStats(host: string, id: string) {
  const url = `https://${host}/api/v1/videos/${encodeURIComponent(id)}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) return null;
  const record = (await response.json()) as Record<string, unknown>;
  const views = normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
  const likes = normalizeStatValue(record.likes ?? record.likesCount ?? record.likes_count);
  const dislikes = normalizeStatValue(record.dislikes ?? record.dislikesCount ?? record.dislikes_count);
  return { views, likes, dislikes };
}

/**
 * Handle apply stats to dom.
 */
function applyStatsToDom(key: string, stats: LiveStats) {
  const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(key) : key;
  const card = cards.querySelector<HTMLElement>(`[data-video-key="${escaped}"]`);
  if (!card) return;
  const viewsEl = card.querySelector<HTMLElement>('[data-stat="views"]');
  if (viewsEl) viewsEl.textContent = formatStatValue(stats.views);
  const likesEl = card.querySelector<HTMLElement>('[data-stat="likes"]');
  if (likesEl) likesEl.textContent = formatStatValue(stats.likes);
  const dislikesEl = card.querySelector<HTMLElement>('[data-stat="dislikes"]');
  if (dislikesEl) dislikesEl.textContent = formatStatValue(stats.dislikes);
}

/**
 * Handle open profile modal.
 */
function openProfileModal() {
  if (!profileModal) return;
  renderProfileSection();
  profileModal.removeAttribute("hidden");
  profileModalClose?.focus();
}

/**
 * The profile's "Reset likes" control, confirmed first because it cannot be undone.
 */
function resetLikesButton(status: HTMLElement): HTMLButtonElement {
  return profileButton("Reset likes", async () => {
    if (!window.confirm("Remove all your likes? Your recommendations start over. This cannot be undone.")) return;
    try {
      await resetLikes();
      renderStatus(status, "Likes reset.");
    } catch (error) {
      renderStatus(status, errorText(error));
    }
  });
}

// The shape the Client backend issues; anything else is refused before it is stored.
const PROFILE_KEY_PATTERN = /^[A-Za-z0-9_-]{43}$/;

/**
 * Render the profile controls. Built with textContent throughout, so nothing here is
 * parsed as HTML. `issuedKey` is shown once, right after the server returns it.
 */
function renderProfileSection(issuedKey?: string, message?: string) {
  if (!profileSection) return;
  profileSection.replaceChildren();
  const status = document.createElement("p");
  status.className = "profile-status";

  if (issuedKey) {
    const warning = document.createElement("p");
    warning.className = "profile-warning";
    warning.textContent =
      "This is the only copy of your key. Save it now: it cannot be recovered, and without it this profile is lost.";
    const field = document.createElement("input");
    field.className = "profile-key";
    field.readOnly = true;
    field.value = issuedKey;
    field.setAttribute("aria-label", "Your profile key");
    const copy = profileButton("Copy key", async () => {
      field.select();
      try {
        await navigator.clipboard.writeText(issuedKey);
        renderStatus(status, "Copied.");
      } catch {
        renderStatus(status, "Copy failed; select the key and copy it by hand.");
      }
    });
    const done = profileButton("I saved it", () => renderProfileSection());
    profileSection.append(warning, field, profileActions(copy, done), nsfwToggle(), status);
    return;
  }

  if (getProfileKey()) {
    const intro = document.createElement("p");
    intro.textContent = "This browser holds a profile key.";
    const rotate = profileButton("Rotate key", async () => {
      if (!window.confirm("Replace your key? Every other browser using the old key will stop working until you paste the new one there.")) return;
      try {
        renderProfileSection(await rotateProfileKey(apiBase));
      } catch (error) {
        renderStatus(status, errorText(error));
      }
    });
    const remove = profileButton("Delete profile", async () => {
      if (!window.confirm("Delete this profile and everything stored with it? This cannot be undone.")) return;
      try {
        await deleteProfile(apiBase);
        renderProfileSection(undefined, "Profile deleted.");
      } catch (error) {
        renderStatus(status, errorText(error));
      }
    });
    const blocks = document.createElement("div");
    blocks.className = "profile-blocks";
    blocks.hidden = true;
    const showBlocked = profileButton("Blocked", async () => {
      if (!blocks.hidden) {
        blocks.hidden = true;
        return;
      }
      await renderBlocks(blocks);
      blocks.hidden = false;
    });
    profileSection.append(intro, profileActions(showBlocked, resetLikesButton(status), rotate, remove), nsfwToggle(), status, blocks);
    if (message) renderStatus(status, message);
    return;
  }

  const intro = document.createElement("p");
  intro.textContent =
    "No profile. A profile keeps your likes on the server, and is needed to block channels and accounts.";
  const create = profileButton("Create profile", async () => {
    try {
      renderProfileSection(await createProfile(apiBase));
    } catch (error) {
      renderStatus(status, errorText(error));
    }
  });
  const pasted = document.createElement("input");
  pasted.className = "profile-key";
  pasted.placeholder = "Paste a key from another browser";
  pasted.setAttribute("aria-label", "Existing profile key");
  const use = profileButton("Use this key", () => {
    const value = pasted.value.trim();
    if (!PROFILE_KEY_PATTERN.test(value)) {
      renderStatus(status, "That is not a profile key.");
      return;
    }
    storeProfileKey(value);
    renderProfileSection(undefined, "Key saved in this browser.");
  });
  profileSection.append(intro, profileActions(create, resetLikesButton(status)), pasted, profileActions(use), nsfwToggle(), status);
  if (message) renderStatus(status, message);
}

/**
 * List the profile's blocks, each with an Unblock control. Labels come from crawled data,
 * so they are set with textContent only.
 */
async function renderBlocks(container: HTMLElement) {
  const heading = document.createElement("h3");
  heading.textContent = "Blocked";
  let blocks: Block[];
  try {
    blocks = await listBlocks(apiBase);
  } catch (error) {
    const failed = document.createElement("p");
    failed.textContent = errorText(error);
    container.replaceChildren(heading, failed);
    return;
  }
  if (!blocks.length) {
    const empty = document.createElement("p");
    empty.textContent = "Nothing blocked. Block a channel or an account from a video card or a video's page.";
    container.replaceChildren(heading, empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "profile-block-list";
  for (const block of blocks) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${block.kind === "channel" ? "Channel" : "Account"}: ${block.label || block.account_url || block.channel_id}`;
    const remove = profileButton("Unblock", async () => {
      try {
        await unblock(apiBase, block);
        await renderBlocks(container);
      } catch (error) {
        label.textContent = errorText(error);
      }
    });
    item.append(label, remove);
    list.append(item);
  }
  container.replaceChildren(heading, list);
}

function profileButton(label: string, onClick: () => void | Promise<void>): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost-button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await onClick();
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function profileActions(...buttons: HTMLButtonElement[]): HTMLDivElement {
  const row = document.createElement("div");
  row.className = "profile-actions";
  row.append(...buttons);
  return row;
}

/**
 * The "Hide NSFW videos" checkbox, shown in every profile state; a change is saved in this browser and reloads the feed.
 */
function nsfwToggle(): HTMLLabelElement {
  const label = document.createElement("label");
  label.className = "profile-nsfw";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = readNsfwFilter();
  input.addEventListener("change", () => {
    setNsfwFilter(input.checked);
    void loadVideos();
  });
  label.append(input, " Hide NSFW videos");
  return label;
}

function renderStatus(element: HTMLElement, text: string) {
  element.textContent = text;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Profile request failed";
}

/**
 * Handle close profile modal.
 */
function closeProfileModal() {
  if (!profileModal) return;
  profileModal.setAttribute("hidden", "true");
}

/**
 * Persist the chosen feed mode, put it in the URL, and reload the feed from its first page.
 */
function chooseFeedMode(raw: string | undefined) {
  const mode = parseFeedMode(raw);
  persistFeedParams({ ...feedParams, mode });
  const next = new URLSearchParams(window.location.search);
  next.set("mode", mode);
  // ?mode= now names the feed, so the legacy flag is dropped rather than left to contradict it.
  next.delete("random");
  next.delete("id");
  next.delete("uuid");
  window.location.search = next.toString();
}
