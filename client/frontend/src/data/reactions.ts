/**
 * Module `client/frontend/src/data/reactions.ts`: the visitor's reaction to a video.
 *
 * With a profile key the Client backend holds likes and dislikes, and this browser keeps no
 * copy. Without one only likes exist, kept in `localLikes:v1` once the Client backend
 * accepted them, so a failed request never shows as liked.
 */

import { resolveClientApiBase } from "./api-base";
import { addLocalLike, clearLocalLikes, getStoredLikes, hasLocalLike, removeLocalLike } from "./local-likes";
import { ProfileKeyRejectedError, getProfileKey, profileHeaders } from "./profile";
import { sendUserAction } from "./user-actions";
import type { VideoRow } from "../types/videos";

export type Reaction = { liked: boolean; disliked: boolean };
export type ReactionAction = "like" | "undo_like" | "dislike" | "undo_dislike";
export type ReactionVideo = { uuid: string; host: string };

// The state each accepted action leaves: the server makes a like and a dislike replace each other.
const AFTER: Record<ReactionAction, Reaction> = {
  like: { liked: true, disliked: false },
  undo_like: { liked: false, disliked: false },
  dislike: { liked: false, disliked: true },
  undo_dislike: { liked: false, disliked: false }
};

/**
 * Return the visitor's reaction to one video: the profile's with a key, the local likes without.
 */
export async function fetchReaction(apiBase: string, video: ReactionVideo): Promise<Reaction> {
  if (!getProfileKey()) {
    return { liked: hasLocalLike(video.uuid, video.host), disliked: false };
  }
  const url = new URL("/api/profile/reaction", resolveClientApiBase(apiBase));
  url.searchParams.set("uuid", video.uuid);
  url.searchParams.set("host", video.host);
  // A reaction changed a moment ago must show on the next read.
  const response = await fetch(url, { headers: profileHeaders(), cache: "no-store" });
  if (response.status === 401) throw new ProfileKeyRejectedError("Your profile key is no longer valid");
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as { liked?: boolean; disliked?: boolean; error?: string }) : {};
  if (!response.ok) {
    throw new Error(payload.error ?? `Reaction request failed (${response.status})`);
  }
  return { liked: payload.liked === true, disliked: payload.disliked === true };
}

/**
 * The reaction a card shows for a row: the mark the Client set with a key, the local likes
 * without one. No request is made per card.
 */
export function cardReaction(row: VideoRow): "liked" | "disliked" | null {
  if (getProfileKey()) return row.reaction ?? null;
  const uuid = row.video_uuid ?? row.videoUuid ?? "";
  const host = row.instance_domain ?? row.instanceDomain ?? "";
  return uuid && host && hasLocalLike(uuid, host) ? "liked" : null;
}

/**
 * Move this browser's local likes into the profile, once a key is held. The local store is
 * cleared only after the Client recorded them, so a failed import is retried on a later load.
 *
 * :returns: How many likes the profile recorded; 0 when there was nothing to import.
 */
export async function importLocalLikes(apiBase: string): Promise<number> {
  const likes = getStoredLikes();
  if (!getProfileKey() || !likes.length) return 0;
  const response = await fetch(new URL("/api/profile/likes/import", resolveClientApiBase(apiBase)), {
    method: "POST",
    headers: { "content-type": "application/json", ...profileHeaders() },
    body: JSON.stringify({
      likes: likes.map((entry) => ({ uuid: entry.video_uuid, host: entry.instance_domain }))
    })
  });
  if (response.status === 401) throw new ProfileKeyRejectedError("Your profile key is no longer valid");
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as { imported?: number; error?: string }) : {};
  if (!response.ok) {
    throw new Error(payload.error ?? `Likes import failed (${response.status})`);
  }
  clearLocalLikes();
  return payload.imported ?? 0;
}

/**
 * Send one reaction and return the state it left. Without a key, an accepted like or un-like
 * is recorded in the local likes; a refused request throws the Client's error and records nothing.
 */
export async function sendReaction(
  apiBase: string,
  action: ReactionAction,
  video: ReactionVideo
): Promise<Reaction> {
  await sendUserAction(apiBase, { videoId: video.uuid, uuid: video.uuid, host: video.host, action });
  if (!getProfileKey()) {
    if (action === "like") addLocalLike(video.uuid, video.host);
    if (action === "undo_like") removeLocalLike(video.uuid, video.host);
  }
  return AFTER[action];
}
