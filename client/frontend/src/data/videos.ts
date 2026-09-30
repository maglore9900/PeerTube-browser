/**
 * Module `client/frontend/src/data/videos.ts`: provide runtime functionality.
 */

import type { VideoRow, VideosPayload } from "../types/videos";
import { fetchJsonWithCache } from "./cache";
import { getRandomLikes } from "./local-likes";
import { resolveClientApiBase } from "./api-base";
import { ProfileKeyRejectedError, getProfileKey, profileHeaders } from "./profile";
import { feedParamsToQuery, nsfwQuery, type FeedParams } from "./feed-params";

export interface SimilarQuery {
  id?: string | null;
  host?: string | null;
  limit?: string | null;
  apiBase?: string | null;
  random?: string | null;
  debug?: string | null;
}

export type ExcludedVideo = { id: string; host: string };

export type FeedPager = {
  readonly exhausted: boolean;
  next(): Promise<VideosPayload>;
};

// The Client refuses a feed request excluding more than this many videos.
export const MAX_FEED_EXCLUDE = 500;

/**
 * Page through a feed: each batch excludes the rows earlier batches returned, and drops any the
 * Engine repeats anyway. A batch that adds no new row, or fails, ends the feed.
 *
 * Rows are keyed by `video_id`, not the UUID `resolveVideoId` prefers, because that is the
 * identity the Engine excludes by.
 */
export function createFeedPager(
  fetchBatch: (exclude: ExcludedVideo[]) => Promise<VideosPayload>
): FeedPager {
  const shown: ExcludedVideo[] = [];
  const keys = new Set<string>();
  let exhausted = false;
  return {
    get exhausted() {
      return exhausted;
    },
    async next() {
      if (exhausted) return { rows: [] };
      let payload: VideosPayload;
      try {
        payload = await fetchBatch(shown.slice(-MAX_FEED_EXCLUDE));
      } catch (error) {
        exhausted = true;
        throw error;
      }
      const fresh: VideoRow[] = [];
      for (const row of payload.rows ?? []) {
        const id = String(row.video_id ?? "");
        const host = String(row.instance_domain ?? "");
        const key = `${id}::${host}`;
        if (!id || !host || keys.has(key)) continue;
        keys.add(key);
        shown.push({ id, host });
        fresh.push(row);
      }
      if (!fresh.length) exhausted = true;
      return { ...payload, rows: fresh };
    }
  };
}

const STATIC_VIDEO_URLS = ["/videos.json", "./videos.json", "videos.json"];

/**
 * Handle parse similar query.
 */
export function parseSimilarQuery(params: URLSearchParams): SimilarQuery {
  return {
    id: params.get("id"),
    host: params.get("host"),
    limit: params.get("limit"),
    apiBase: params.get("api"),
    random: params.get("random"),
    debug: params.get("debug")
  };
}

/**
 * Handle resolve api base.
 */
export function resolveApiBase(query: SimilarQuery) {
  return resolveClientApiBase(query.apiBase);
}

/**
 * Handle build similar url.
 */
export function buildSimilarUrl(query: SimilarQuery, feedParams?: FeedParams) {
  const apiBase = resolveApiBase(query);
  const url = new URL("/recommendations", apiBase);
  if (query.id) url.searchParams.set("id", query.id);
  if (query.host) url.searchParams.set("host", query.host);
  if (query.limit) url.searchParams.set("limit", query.limit);
  if (query.random) url.searchParams.set("random", query.random);
  if (query.debug) url.searchParams.set("debug", query.debug);
  if (feedParams) {
    for (const [key, value] of feedParamsToQuery(feedParams)) url.searchParams.set(key, value);
  }
  // Outside the feedParams block: the ?id= and video-page up-next feeds pass no feed params and still honour the setting.
  for (const [key, value] of nsfwQuery()) url.searchParams.set(key, value);
  return url.toString();
}

/**
 * Handle fetch static videos payload.
 */
export async function fetchStaticVideosPayload(options: { cacheTtlMs?: number } = {}) {
  let lastError: string | null = null;
  for (const url of STATIC_VIDEO_URLS) {
    try {
      return await fetchJsonWithCache<VideosPayload | VideoRow[]>(url, {
        cacheKey: `videos:${url}`,
        ttlMs: options.cacheTtlMs ?? 0
      });
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
  }
  throw new Error(lastError ?? "Failed to load videos.json");
}

/**
 * Handle fetch similar videos payload.
 */
export async function fetchSimilarVideosPayload(query: SimilarQuery, exclude: ExcludedVideo[] = [], feedParams?: FeedParams) {
  const url = buildSimilarUrl(query, feedParams);
  // With a key the Client sends the profile's own likes; the browser holds none of them.
  const body: Record<string, unknown> = getProfileKey() ? {} : { likes: getRandomLikes() };
  if (exclude.length) body.exclude = exclude;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...profileHeaders()
    },
    body: JSON.stringify(body)
  });
  if (response.status === 401) {
    throw new ProfileKeyRejectedError("Your profile key is no longer valid");
  }
  if (!response.ok) {
    let message = "Failed to load recommendations";
    try {
      const body = (await response.json()) as { error?: string };
      message = body?.error ?? message;
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(message);
  }
  return (await response.json()) as VideosPayload;
}
