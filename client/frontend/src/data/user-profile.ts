/**
 * Module `client/frontend/src/data/user-profile.ts`: provide runtime functionality.
 */

import type { VideoRow } from "../types/videos";
import { getStoredLikes } from "./local-likes";
import { resolveClientApiBase } from "./api-base";
import { getProfileKey, profileHeaders } from "./profile";

interface UserProfileResponse {
  user_id?: string;
  likes?: VideoRow[];
}

/**
 * Return the visitor's likes as video rows: the profile's with a key, the local likes without.
 */
export async function fetchUserProfileLikes(apiBase: string): Promise<VideoRow[]> {
  const clientApiBase = resolveClientApiBase(apiBase);
  if (!getProfileKey()) {
    const stored = getStoredLikes();
    if (!stored.length) return [];
    const response = await fetch(new URL("/api/user-profile/likes", clientApiBase), {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        likes: stored.map((entry) => ({
          uuid: entry.video_uuid,
          host: entry.instance_domain
        }))
      })
    });
    if (!response.ok) {
      const message = await readErrorMessage(response);
      throw new Error(message ?? "Failed to fetch user profile");
    }
    const payload = (await response.json()) as UserProfileResponse;
    return Array.isArray(payload.likes) ? payload.likes : [];
  }

  const response = await fetch(new URL("/api/user-profile/likes", clientApiBase), {
    headers: profileHeaders()
  });
  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(message ?? "Failed to fetch user profile");
  }
  const payload = (await response.json()) as UserProfileResponse;
  return Array.isArray(payload.likes) ? payload.likes : [];
}

/**
 * Handle reset user profile likes.
 */
export async function resetUserProfileLikes(apiBase: string): Promise<VideoRow[]> {
  // Without a profile there are no server-side likes to clear; local likes are the caller's.
  if (!getProfileKey()) return [];
  const clientApiBase = resolveClientApiBase(apiBase);
  const response = await fetch(new URL("/api/user-profile/reset", clientApiBase), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...profileHeaders()
    },
    body: JSON.stringify({})
  });
  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(message ?? "Failed to reset user profile");
  }
  const payload = (await response.json()) as UserProfileResponse;
  return Array.isArray(payload.likes) ? payload.likes : [];
}

/**
 * Handle read error message.
 */
async function readErrorMessage(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { error?: string };
    return payload.error ?? null;
  } catch {
    return null;
  }
}
