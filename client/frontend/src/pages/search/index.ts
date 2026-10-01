/**
 * Module `client/frontend/src/pages/search/index.ts`: the video search page.
 *
 * Query and sort live in the URL so a result set is linkable and the back button works.
 * The next page is fetched and appended as the end of the results scrolls into view, as the
 * home feed does, until the Engine's candidate pool is exhausted.
 *
 * Each card carries Like, Dislike, Block channel and Block account. Unlike home, Dislike toggles and
 * the card stays, marked, because search is not filtered by dislikes (D6).
 */

import "../../videos.css";
import "../../search.css";
import {
  renderVideoCard,
  resolveInstanceDomain,
  resolveVideoId,
  resolveVideoKey
} from "../../components/video-card";
import {
  fetchSearchResults,
  SearchUnavailableError,
  type SearchSort
} from "../../data/search";
import { getProfileKey, ProfileKeyRejectedError } from "../../data/profile";
import { cardReaction, importLocalLikes, sendReaction } from "../../data/reactions";
import { blockVideoSource } from "../../data/blocks";
import { keyRejectedNotice } from "../../components/key-rejected";
import type { SearchPayload, VideoRow } from "../../types/videos";

/**
 * Resolve a required element, failing loudly rather than degrading silently.
 *
 * Returning a non-nullable type keeps every later use narrowed, which the older pages
 * achieve with a combined guard that TypeScript cannot carry across function boundaries.
 */
function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id) as T | null;
  if (!element) {
    throw new Error(`Missing search page element: ${id}`);
  }
  return element;
}

const form = requireElement<HTMLFormElement>("search-form");
const input = requireElement<HTMLInputElement>("search-input");
const sortSelect = requireElement<HTMLSelectElement>("search-sort");
const results = requireElement<HTMLElement>("search-results");
const status = requireElement<HTMLElement>("search-status");
const sentinel = requireElement<HTMLElement>("search-sentinel");

const PAGE_SIZE = 24;
const SORTS: SearchSort[] = ["relevance", "published_at", "views", "popularity"];

const params = new URLSearchParams(window.location.search);
const apiParam = params.get("api");

const state = {
  query: (params.get("q") ?? "").trim(),
  sort: resolveSort(params.get("sort")),
  page: 1,
  loadedRows: 0,
  total: 0,
  /** Rows rendered into the grid, in order; card actions find their row here by video key. */
  rows: [] as VideoRow[],
  loading: false,
  /** Another page exists and has not been fetched. */
  hasMore: false,
  /** Discards responses that arrive after a newer request was issued. */
  requestSeq: 0
};

input.value = state.query;
sortSelect.value = state.sort;

// A browser that holds a key hands its local likes to the profile before its first keyed read.
const localLikesImported = importLocalLikes(apiParam ?? "").catch((error) => {
  console.warn("[likes] import failed; the local likes are kept for the next load", error);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const next = input.value.trim();
  if (!next) {
    showIdle();
    return;
  }
  startSearch(next, state.sort);
});

sortSelect.addEventListener("change", () => {
  if (!state.query) return;
  startSearch(state.query, resolveSort(sortSelect.value));
});

results.addEventListener("click", (event) => {
  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>("[data-card-action]");
  const card = button?.closest<HTMLElement>(".video-card");
  const key = card?.dataset.videoKey;
  const row = key ? state.rows.find((candidate) => resolveVideoKey(candidate) === key) : undefined;
  if (button && card && row) void runCardAction(button, card, row);
});

// Fetch the next page once the end of the results comes within 200px of the viewport.
new IntersectionObserver(
  (entries) => {
    if (entries.some((entry) => entry.isIntersecting)) loadNextPage();
  },
  { rootMargin: "200px" }
).observe(sentinel);

window.addEventListener("popstate", () => {
  const current = new URLSearchParams(window.location.search);
  state.query = (current.get("q") ?? "").trim();
  state.sort = resolveSort(current.get("sort"));
  input.value = state.query;
  sortSelect.value = state.sort;
  if (!state.query) {
    showIdle();
    return;
  }
  void loadPage(1, true);
});

if (state.query) {
  document.title = `${state.query} - Search - PeerTube - Browser`;
  void loadPage(1, true);
} else {
  showIdle();
}

/**
 * Append the next page, unless one is loading or none is left.
 */
function loadNextPage() {
  if (state.loading || !state.hasMore) return;
  void loadPage(state.page + 1, false);
}

/**
 * Keep fetching while the end of the results is still on screen. The observer fires only when
 * the sentinel enters view, so a page too short to push it out would otherwise stop paging.
 */
function fillViewport() {
  if (sentinel.getBoundingClientRect().top <= window.innerHeight + 200) loadNextPage();
}

/**
 * Begin a fresh search, resetting paging and pushing the new URL.
 */
function startSearch(query: string, sort: SearchSort) {
  state.query = query;
  state.sort = sort;
  state.page = 1;
  pushUrl();
  document.title = `${query} - Search - PeerTube - Browser`;
  void loadPage(1, true);
}

/**
 * Fetch one page and render it, replacing or appending to the grid.
 *
 * :param page: 1-based page number.
 * :param reset: Replace the grid rather than append to it.
 */
async function loadPage(page: number, reset: boolean) {
  const seq = ++state.requestSeq;
  state.loading = true;
  setStatus(reset ? "Searching..." : "Loading more...");
  if (reset) {
    results.innerHTML = "";
    state.loadedRows = 0;
    state.rows = [];
  }

  let payload: SearchPayload;
  try {
    await localLikesImported;
    payload = await fetchSearchResults({
      q: state.query,
      page,
      limit: PAGE_SIZE,
      sort: state.sort,
      apiBase: apiParam
    });
  } catch (error) {
    if (seq !== state.requestSeq) return;
    state.loading = false;
    state.hasMore = false; // a failed page stops paging; a new search starts over
    if (error instanceof SearchUnavailableError) {
      setStatus("Search is not ready yet: the dataset has no full-text index.", true);
    } else if (error instanceof ProfileKeyRejectedError) {
      setStatus("", true);
      results.replaceChildren(keyRejectedNotice(() => void loadPage(1, true)));
    } else {
      setStatus("Search failed. The Engine may be unavailable.", true);
    }
    return;
  }

  // A slower earlier request must not overwrite a newer one's results.
  if (seq !== state.requestSeq) return;

  state.loading = false;
  state.page = page;
  state.total = payload.total ?? 0;
  const rows = payload.rows ?? [];
  renderRows(rows, reset);
  state.loadedRows += rows.length;

  if (!state.loadedRows) {
    setStatus(`No results for "${state.query}".`);
    state.hasMore = false;
    return;
  }

  // `total` is the Engine's fused candidate pool, not a corpus count, so the wording
  // stays deliberately about what is shown.
  setStatus(`Showing ${state.loadedRows} of ${state.total} matched videos.`);
  state.hasMore = state.loadedRows < state.total && rows.length > 0;
  fillViewport();
}

/**
 * Render rows into the grid through the shared card component and remember them for card actions.
 */
function renderRows(rows: VideoRow[], reset: boolean) {
  const markup = rows.map(renderSearchCard).join("");
  state.rows.push(...rows);
  if (reset) {
    results.innerHTML = markup;
    return;
  }
  results.insertAdjacentHTML("beforeend", markup);
}

/**
 * Render one search card with its action controls; used for first renders and in-place re-renders.
 */
function renderSearchCard(row: VideoRow) {
  return renderVideoCard(row, { apiParam, reaction: cardReaction(row), actions: true });
}

/**
 * Like, dislike or block from a card. Like and dislike toggle, and the card is redrawn in place with its new mark; a block dislikes the video too and takes every loaded card of the source off the grid.
 */
async function runCardAction(button: HTMLButtonElement, card: HTMLElement, row: VideoRow) {
  const action = button.dataset.cardAction ?? "";
  const apiBase = apiParam ?? "";
  const uuid = resolveVideoId(row);
  const host = resolveInstanceDomain(row);
  const cardStatus = card.querySelector<HTMLElement>(".card-action-status");
  const say = (text: string) => {
    if (cardStatus) cardStatus.textContent = text;
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
      // A reset during the request detaches the card, and outerHTML on a detached node throws.
      if (card.isConnected) card.outerHTML = renderSearchCard(row);
    } else if (action === "dislike") {
      const disliked = cardReaction(row) === "disliked";
      await sendReaction(apiBase, disliked ? "undo_dislike" : "dislike", { uuid, host });
      row.reaction = disliked ? null : "disliked";
      if (card.isConnected) card.outerHTML = renderSearchCard(row);
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
 * Drop matching rows from the grid and redraw it, then refill. `loadedRows` still counts what the Engine returned, so paging and the status line are unaffected.
 */
function removeRows(match: (row: VideoRow) => boolean) {
  state.rows = state.rows.filter((row) => !match(row));
  results.innerHTML = state.rows.map(renderSearchCard).join("");
  fillViewport();
}

/**
 * Show the state before any query has been entered.
 */
function showIdle() {
  state.query = "";
  state.loadedRows = 0;
  state.rows = [];
  state.total = 0;
  state.hasMore = false;
  results.innerHTML = "";
  document.title = "Search - PeerTube - Browser";
  setStatus("Enter a search term to begin.");
  pushUrl();
}

/**
 * Write the current query, sort and page into the address bar.
 */
function pushUrl(replace = false) {
  const next = new URLSearchParams();
  if (state.query) next.set("q", state.query);
  if (state.sort !== "relevance") next.set("sort", state.sort);
  if (apiParam && import.meta.env.DEV) next.set("api", apiParam);
  const url = next.toString() ? `?${next.toString()}` : window.location.pathname;
  if (replace) {
    window.history.replaceState({}, "", url);
  } else {
    window.history.pushState({}, "", url);
  }
}

/**
 * Set the status line, optionally as an error.
 */
function setStatus(message: string, isError = false) {
  status.textContent = message;
  status.classList.toggle("error", isError);
}

/**
 * Coerce a sort parameter to a supported value.
 */
function resolveSort(value: string | null): SearchSort {
  const candidate = (value ?? "").trim() as SearchSort;
  return SORTS.includes(candidate) ? candidate : "relevance";
}

