/**
 * Module `client/frontend/src/pages/search/index.ts`: the video search page.
 *
 * Query, sort and page live in the URL so a result set is linkable and the back button
 * works. Results are appended a page at a time rather than scrolled infinitely: search
 * has a finite candidate count and a stable list is easier to compare against.
 */

import "../../videos.css";
import "../../search.css";
import { renderVideoCard } from "../../components/video-card";
import {
  fetchSearchResults,
  SearchUnavailableError,
  type SearchSort
} from "../../data/search";
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
const moreButton = requireElement<HTMLButtonElement>("search-more");

const PAGE_SIZE = 24;
const SORTS: SearchSort[] = ["relevance", "published_at", "views", "popularity"];

const params = new URLSearchParams(window.location.search);
const apiParam = params.get("api");

const state = {
  query: (params.get("q") ?? "").trim(),
  sort: resolveSort(params.get("sort")),
  page: resolvePage(params.get("page")),
  loadedRows: 0,
  total: 0,
  loading: false,
  /** Discards responses that arrive after a newer request was issued. */
  requestSeq: 0
};

input.value = state.query;
sortSelect.value = state.sort;

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

moreButton.addEventListener("click", () => {
  if (state.loading) return;
  void loadPage(state.page + 1, false);
});

window.addEventListener("popstate", () => {
  const current = new URLSearchParams(window.location.search);
  state.query = (current.get("q") ?? "").trim();
  state.sort = resolveSort(current.get("sort"));
  state.page = resolvePage(current.get("page"));
  input.value = state.query;
  sortSelect.value = state.sort;
  if (!state.query) {
    showIdle();
    return;
  }
  void loadPage(state.page, true);
});

if (state.query) {
  document.title = `${state.query} - Search - PeerTube - Browser`;
  void loadPage(state.page, true);
} else {
  showIdle();
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
  moreButton.disabled = true;
  setStatus(reset ? "Searching..." : "Loading more...");
  if (reset) {
    results.innerHTML = "";
    state.loadedRows = 0;
  }

  let payload: SearchPayload;
  try {
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
    moreButton.disabled = false;
    moreButton.hidden = true;
    if (error instanceof SearchUnavailableError) {
      setStatus("Search is not ready yet: the dataset has no full-text index.", true);
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
    moreButton.hidden = true;
    return;
  }

  // `total` is the Engine's fused candidate pool, not a corpus count, so the wording
  // stays deliberately about what is shown.
  setStatus(`Showing ${state.loadedRows} of ${state.total} matched videos.`);
  moreButton.disabled = false;
  moreButton.hidden = state.loadedRows >= state.total || rows.length === 0;
  if (page !== 1) pushUrl(true);
}

/**
 * Render rows into the grid through the shared card component.
 */
function renderRows(rows: VideoRow[], reset: boolean) {
  const markup = rows.map((row) => renderVideoCard(row, { apiParam })).join("");
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
  results.innerHTML = "";
  moreButton.hidden = true;
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
  if (state.page > 1) next.set("page", String(state.page));
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

/**
 * Coerce a page parameter to a positive integer.
 */
function resolvePage(value: string | null): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}
