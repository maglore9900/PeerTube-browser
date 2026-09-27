/**
 * Module `client/frontend/src/pages/search/index.ts`: the video search page.
 *
 * Query and sort live in the URL so a result set is linkable and the back button works.
 * The next page is fetched and appended as the end of the results scrolls into view, as the
 * home feed does, until the Engine's candidate pool is exhausted.
 */

import "../../videos.css";
import "../../search.css";
import { renderVideoCard } from "../../components/video-card";
import {
  fetchSearchResults,
  SearchUnavailableError,
  type SearchSort
} from "../../data/search";
import { ProfileKeyRejectedError } from "../../data/profile";
import { cardReaction, importLocalLikes } from "../../data/reactions";
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
 * Render rows into the grid through the shared card component.
 */
function renderRows(rows: VideoRow[], reset: boolean) {
  const markup = rows.map((row) => renderVideoCard(row, { apiParam, reaction: cardReaction(row) })).join("");
  if (reset) {
    results.innerHTML = markup;
    return;
  }
  results.insertAdjacentHTML("beforeend", markup);
}

/**
 * Show the state before any query has been entered.
 */
function showIdle() {
  state.query = "";
  state.loadedRows = 0;
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

