/**
 * Module `client/frontend/src/data/follows.ts`: the profile's channel and account follows.
 *
 * A follow is made from a video the visitor is looking at, as a block is, or from a channels-page row by the channel's key;
 * either way the Client backend stores the Engine's own key and label. A page fetches the list once and labels its controls
 * from a `FollowLookup`, which each toggle then updates.
 */

import { resolveClientApiBase } from "./api-base";
import { profileHeaders } from "./profile";

export type FollowKind = "channel" | "account";

export interface Follow {
  kind: FollowKind;
  instance_domain: string;
  channel_id: string;
  account_url: string;
  label: string;
  created_at?: number;
}

/** The identity fields a feed row, a follow or a block carries. */
export type FollowSource = { instance_domain?: string | null; channel_id?: string | null; account_url?: string | null };

/** Followed channels as `instance_domain::channel_id`, followed accounts by URL. */
export type FollowLookup = { channels: Set<string>; accounts: Set<string> };

/**
 * Return the profile's follows.
 */
export async function listFollows(apiBase: string): Promise<Follow[]> {
  const payload = await request(apiBase, "/api/profile/follows");
  return Array.isArray(payload.follows) ? (payload.follows as Follow[]) : [];
}

/**
 * Follow the channel or the account of the video identified by uuid and host.
 */
export async function followVideoSource(apiBase: string, kind: FollowKind, uuid: string, host: string): Promise<Follow> {
  const payload = await request(apiBase, "/api/profile/follows", { kind, uuid, host });
  return payload.follow as Follow;
}

/**
 * Follow a channel by its key; the Client stores it only once the Engine's catalogue confirms it.
 */
export async function followChannel(apiBase: string, instance_domain: string, channel_id: string): Promise<Follow> {
  const payload = await request(apiBase, "/api/profile/follows", { kind: "channel", instance_domain, channel_id });
  return payload.follow as Follow;
}

/**
 * Remove one follow, named by its key fields.
 */
export async function unfollow(apiBase: string, follow: Pick<Follow, "kind" | "instance_domain" | "channel_id" | "account_url">): Promise<void> {
  const { kind, instance_domain, channel_id, account_url } = follow;
  await request(apiBase, "/api/profile/follows/remove", { kind, instance_domain, channel_id, account_url });
}

/**
 * Build the lookup a page labels its controls from.
 */
export function followLookup(follows: Follow[] = []): FollowLookup {
  const lookup: FollowLookup = { channels: new Set(), accounts: new Set() };
  for (const follow of follows) setFollowed(lookup, follow.kind, follow, true);
  return lookup;
}

/**
 * Whether the source's channel or account is followed; a source lacking that identity never is.
 */
export function isFollowed(lookup: FollowLookup, kind: FollowKind, source: FollowSource): boolean {
  const key = lookupKey(kind, source);
  return Boolean(key) && (kind === "channel" ? lookup.channels : lookup.accounts).has(key);
}

/**
 * Record a follow or its removal. A block drops the follow on the same key, so pages call this with false after blocking.
 */
export function setFollowed(lookup: FollowLookup, kind: FollowKind, source: FollowSource, followed: boolean): void {
  const key = lookupKey(kind, source);
  if (!key) return;
  const set = kind === "channel" ? lookup.channels : lookup.accounts;
  if (followed) set.add(key);
  else set.delete(key);
}

/**
 * Follow or unfollow a video's channel or account by its state in `lookup`, and update the lookup.
 *
 * :returns: The stored follow, or null after an unfollow.
 */
export async function toggleVideoSourceFollow(
  apiBase: string,
  lookup: FollowLookup,
  kind: FollowKind,
  uuid: string,
  host: string,
  source: FollowSource
): Promise<Follow | null> {
  if (isFollowed(lookup, kind, source)) {
    await unfollow(apiBase, {
      kind,
      instance_domain: kind === "channel" ? String(source.instance_domain ?? "") : "",
      channel_id: kind === "channel" ? String(source.channel_id ?? "") : "",
      account_url: kind === "account" ? String(source.account_url ?? "") : ""
    });
    setFollowed(lookup, kind, source, false);
    return null;
  }
  const follow = await followVideoSource(apiBase, kind, uuid, host);
  setFollowed(lookup, kind, follow, true);
  return follow;
}

function lookupKey(kind: FollowKind, source: FollowSource): string {
  if (kind === "account") return String(source.account_url ?? "");
  const host = String(source.instance_domain ?? "");
  const id = String(source.channel_id ?? "");
  return host && id ? `${host}::${id}` : "";
}

async function request(
  apiBase: string,
  path: string,
  body?: Record<string, string>
): Promise<{ follows?: unknown; follow?: unknown; error?: string }> {
  const response = await fetch(new URL(path, resolveClientApiBase(apiBase)), {
    method: body ? "POST" : "GET",
    headers: { "content-type": "application/json", ...profileHeaders() },
    body: body ? JSON.stringify(body) : undefined
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as { follows?: unknown; follow?: unknown; error?: string }) : {};
  if (!response.ok) {
    throw new Error(payload.error ?? `Follow request failed (${response.status})`);
  }
  return payload;
}
