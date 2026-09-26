/**
 * Module `client/frontend/src/data/search.ts`: query the Engine's video search endpoint.
 *
 * The request goes to the Client gateway, never to the Engine directly. The gateway
 * allowlists the route and exactly four query parameters (`q`, `page`, `limit`, `sort`)
 * and answers 400 for anything else, so this client sends those and nothing more; a new
 * filter needs the gateway updated in the same change.
 */

import type { SearchPayload } from "../types/videos";
import { fetchJsonWithCache } from "./cache";
import { resolveClientApiBase } from "./api-base";
import { ProfileKeyRejectedError, getProfileKey, profileHeaders } from "./profile";

const DEFAULT_CACHE_TTL_MS = 30 * 1000;

export const SEARCH_PATH = "/api/v1/search/videos";

/** Sort values the endpoint accepts. */
export type SearchSort = "relevance" | "published_at" | "views" | "popularity";

export type FetchSearchOptions = {
  q: string;
  page?: number;
  limit?: number;
  sort?: SearchSort;
  apiBase?: string | null;
  cacheTtlMs?: number;
};

/**
 * Raised when the Engine has no full-text index yet.
 *
 * Distinct from a transport failure because the page says something different about it:
 * the deployment is mid-setup rather than broken, and retrying will not help until the
 * dataset build's sync stage has run.
 */
export class SearchUnavailableError extends Error {
  /**
   * Build the error with a fixed message.
   */
  constructor(message = "Search index is not built yet") {
    super(message);
    this.name = "SearchUnavailableError";
  }
}

/**
 * Fetch one page of search results.
 *
 * :param options: Query text, paging, sort and an optional dev-only API base.
 * :returns: The payload as the Engine returned it.
 * :throws SearchUnavailableError: When the Engine reports the index is missing.
 */
export async function fetchSearchResults(options: FetchSearchOptions): Promise<SearchPayload> {
  const apiBase = resolveClientApiBase(options.apiBase);
  const url = new URL(SEARCH_PATH, apiBase);
  const query = options.q.trim();
  url.searchParams.set("q", query);
  if (options.page && options.page > 1) url.searchParams.set("page", String(Math.floor(options.page)));
  if (options.limit && options.limit > 0) url.searchParams.set("limit", String(Math.floor(options.limit)));
  if (options.sort) url.searchParams.set("sort", options.sort);

  if (getProfileKey()) {
    // Filtered per profile, so neither cached nor shared with the keyless cache: a block made
    // a moment ago must show on the next search.
    const response = await fetch(url.toString(), { headers: profileHeaders(), cache: "no-store" });
    if (response.status === 401) throw new ProfileKeyRejectedError("Your profile key is no longer valid");
    if (response.status === 503) throw new SearchUnavailableError();
    if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
    return (await response.json()) as SearchPayload;
  }

  try {
    return await fetchJsonWithCache<SearchPayload>(url.toString(), {
      cacheKey: `search:${url}`,
      ttlMs: options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS
    });
  } catch (error) {
    // `fetchJsonWithCache` throws `HTTP <status> for <url>`; 503 is the Engine saying the
    // index is absent, which the page reports differently from a failure.
    if (error instanceof Error && error.message.includes("HTTP 503")) {
      throw new SearchUnavailableError();
    }
    throw error;
  }
}
