/**
 * Module `client/frontend/src/components/video-card.ts`: render one video card.
 *
 * Extracted from the videos feed so the feed and the search page produce identical cards
 * from one definition. Card markup interpolates remote text - titles and channel names
 * from arbitrary PeerTube instances - so every value here passes through `escapeHtml` and
 * every external URL through `safeExternalUrl`. Keeping one copy keeps that discipline in
 * one place.
 *
 * Feed-specific behaviour stays with the feed: the live-stats cache and the debug metrics
 * block are passed in rather than reached for, because this module has no page state.
 */

import { safeExternalUrl } from "../utils/safe-url";
import type { FollowKind } from "../data/follows";
import type { VideoRow } from "../types/videos";

const numberFormat = new Intl.NumberFormat("en-US");

/** Live view/like counts resolved by the calling page, when it has them. */
export type CardStats = {
  views: number | null;
  likes: number | null;
  dislikes: number | null;
};

/** Per-call hooks a page supplies without this module knowing about page state. */
export type VideoCardOptions = {
  /** Stats the page already resolved; omitted renders placeholders. */
  stats?: CardStats | null;
  /** Extra markup appended inside the card footer, already escaped by the caller. */
  footerExtraHtml?: string;
  /** Dev-only `?api=` override propagated to the video page link. */
  apiParam?: string | null;
  /** The visitor's reaction to the video, shown on its likes or dislikes stat. */
  reaction?: "liked" | "disliked" | null;
  /** Render like, dislike, block and follow buttons; the page handles their `data-card-action` clicks. */
  actions?: boolean;
  /** Whether the row's channel and account are followed, which labels the follow buttons. */
  follow?: CardFollow;
};

export type CardFollow = { channel: boolean; account: boolean };

/**
 * The text of a follow control: "Follow channel", "Unfollow account" and so on.
 */
export function followLabel(kind: FollowKind, followed: boolean) {
  return `${followed ? "Unfollow" : "Follow"} ${kind}`;
}

/**
 * Relabel every card follow button under `container` from the current follow state, without redrawing a card, so its status line survives.
 */
export function refreshFollowButtons(container: ParentNode, rowForKey: (key: string) => VideoRow | undefined, followState: (row: VideoRow) => CardFollow) {
  for (const button of Array.from(container.querySelectorAll<HTMLButtonElement>('[data-card-action^="follow-"]'))) {
    const row = rowForKey(button.closest<HTMLElement>(".video-card")?.dataset.videoKey ?? "");
    if (!row) continue;
    const kind = button.dataset.cardAction === "follow-channel" ? "channel" : "account";
    button.textContent = followLabel(kind, followState(row)[kind]);
  }
}

/**
 * Escape a string for interpolation into HTML.
 */
export function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "\"":
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return char;
    }
  });
}

/**
 * Resolve the instance domain of a row, across snake and camel spellings.
 */
export function resolveInstanceDomain(row: VideoRow) {
  return row.instance_domain ?? row.instanceDomain ?? "";
}

/**
 * Resolve the identifier used for stats lookups, preferring the UUID.
 */
export function resolveVideoId(row: VideoRow) {
  const value = row.video_uuid ?? row.videoUuid ?? row.video_id ?? "";
  return value ? String(value) : "";
}

/**
 * Build the host-qualified key a page uses to cache stats for a row.
 */
export function resolveVideoKey(row: VideoRow) {
  const host = resolveInstanceDomain(row);
  const id = resolveVideoId(row);
  if (!host || !id) return null;
  return `${host}::${id}`;
}

/**
 * Resolve the thumbnail URL of a row, or null when it has none.
 */
export function thumbnailUrl(row: VideoRow) {
  return row.thumbnail_url ?? row.thumbnailUrl ?? row.preview_path ?? row.previewPath ?? null;
}

/**
 * Resolve the display name of a row's channel.
 */
export function channelName(row: VideoRow) {
  return (
    row.channel_display_name ??
    row.channelDisplayName ??
    row.channel_name ??
    row.channelName ??
    "Unknown channel"
  );
}

/**
 * Build the initials shown when a channel has no avatar.
 */
export function channelInitials(row: VideoRow) {
  const label = channelName(row).trim();
  if (!label) return "•";
  const cleaned = label.replace(/[_\-]+/g, " ").replace(/\s+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

/**
 * Resolve a channel avatar URL from any of the spellings rows carry.
 */
export function channelAvatarUrl(row: VideoRow) {
  return (
    row.channel_avatar_url ??
    row.channelAvatarUrl ??
    row.account_avatar_url ??
    row.accountAvatarUrl ??
    row.avatar_url ??
    row.avatarUrl ??
    null
  );
}

/**
 * Resolve the remote channel page URL, or "#" when it cannot be built.
 */
export function channelUrl(row: VideoRow) {
  if (row.channel_url) return row.channel_url;
  if (row.channelUrl) return row.channelUrl;
  const name = row.channel_name ?? row.channelName;
  const host = row.instance_domain ?? row.instanceDomain;
  if (name && host) {
    return `https://${host}/video-channels/${encodeURIComponent(name)}`;
  }
  return "#";
}

/**
 * Resolve the canonical watch URL on the origin instance.
 */
export function videoUrl(row: VideoRow) {
  if (row.video_url) return row.video_url;
  if (row.videoUrl) return row.videoUrl;
  const uuid = row.video_uuid ?? row.videoUuid;
  const host = row.instance_domain ?? row.instanceDomain;
  if (uuid && host) {
    return `https://${host}/videos/watch/${encodeURIComponent(uuid)}`;
  }
  return "#";
}

/**
 * Resolve the embeddable player URL for a row.
 */
export function embedUrl(row: VideoRow) {
  const raw = row.embed_path ?? row.embedPath ?? "";
  if (raw.startsWith("http")) return raw;
  const host = row.instance_domain ?? row.instanceDomain;
  if (raw && host) {
    return `https://${host}${raw}`;
  }
  const uuid = row.video_uuid ?? row.videoUuid;
  if (uuid && host) {
    return `https://${host}/videos/embed/${encodeURIComponent(uuid)}`;
  }
  return "";
}

/**
 * Normalize a publication timestamp to milliseconds, or null when absent.
 */
export function publishedAtMs(row: VideoRow) {
  const raw = row.published_at ?? row.publishedAt ?? null;
  if (!raw || !Number.isFinite(raw)) return null;
  const value = Number(raw);
  if (value < 1e12) return value * 1000;
  return value;
}

/**
 * Render a coarse relative time, as feeds show it.
 */
export function formatTimeAgo(timestampMs: number) {
  const now = Date.now();
  const diffMs = Math.max(0, now - timestampMs);
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const month = 30 * day;
  const year = 365 * day;

  if (diffMs < minute) return "just now";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)} minutes ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)} hours ago`;
  if (diffMs < month) return `${Math.floor(diffMs / day)} days ago`;
  if (diffMs < year) return `${Math.floor(diffMs / month)} months ago`;
  return `${Math.floor(diffMs / year)} years ago`;
}

/**
 * Format a duration in seconds as h:mm:ss or m:ss.
 */
export function formatDuration(value: number | null) {
  if (!value || !Number.isFinite(value)) return "0:00";
  const total = Math.max(0, Math.round(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * Format a counter, showing "--" when the value is unknown.
 */
export function formatStatValue(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return numberFormat.format(value);
}

/**
 * Coerce an arbitrary payload value into a finite number or null.
 */
export function normalizeStatValue(value: unknown) {
  if (value == null) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

/**
 * Thumbs-up glyph.
 */
export function iconThumbUp() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

/**
 * Eye glyph.
 */
export function iconEye() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="3.2" />
    </svg>
  `;
}

/**
 * Thumbs-down glyph.
 */
export function iconThumbDown() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

/**
 * Build the internal link to the video page for a row.
 *
 * `apiParam` is propagated only in a dev build: honouring it from a production bundle
 * would make an injected API base sticky across navigation.
 */
export function videoPageUrl(row: VideoRow, apiParam?: string | null) {
  const params = new URLSearchParams();
  const host = row.instance_domain ?? row.instanceDomain ?? "";
  const id = row.video_id ?? row.video_uuid ?? row.videoUuid ?? "";
  if (id) params.set("id", id);
  if (host) params.set("host", host);
  if (row.title) params.set("title", row.title);
  const channelLabel =
    row.channel_display_name ??
    row.channelDisplayName ??
    row.channel_name ??
    row.channelName ??
    "";
  if (channelLabel) params.set("channel", channelLabel);
  const channelHref = channelUrl(row);
  if (channelHref && channelHref !== "#") params.set("channelUrl", channelHref);
  const embed = embedUrl(row);
  if (embed) params.set("embed", embed);
  const original = videoUrl(row);
  if (original && original !== "#") params.set("url", original);
  if (apiParam && import.meta.env.DEV) params.set("api", apiParam);
  return `/video-page.html?${params.toString()}`;
}

/**
 * Render one video card as HTML.
 *
 * :param row: Video row from any Engine read route.
 * :param options: Page-supplied stats, footer extras and dev API override.
 * :returns: Card markup, with every interpolated value escaped.
 */
export function renderVideoCard(row: VideoRow, options: VideoCardOptions = {}) {
  const title = row.title ?? "Untitled video";
  const thumb = thumbnailUrl(row);
  const duration = formatDuration(row.duration ?? null);
  const stats = options.stats ?? null;
  const views = stats?.views ?? null;
  const likes = stats?.likes ?? null;
  const dislikes = stats?.dislikes ?? null;
  const channelLabel = channelName(row);
  const channelHref = channelUrl(row);
  const avatarUrl = channelAvatarUrl(row);
  const channelBadge = channelInitials(row);
  const publishedAt = publishedAtMs(row);
  const timeAgo = publishedAt ? formatTimeAgo(publishedAt) : null;
  const timeSuffix = timeAgo ? ` · ${timeAgo}` : "";
  const avatarMarkup = avatarUrl
    ? `<img src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" />`
    : `<span>${escapeHtml(channelBadge)}</span>`;
  const thumbMarkup = thumb
    ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
    : `<div class="thumb-fallback">No preview</div>`;
  const videoKey = resolveVideoKey(row);
  const keyAttribute = videoKey ? ` data-video-key="${escapeHtml(videoKey)}"` : "";
  const footerExtra = options.footerExtraHtml ?? "";
  const reaction = options.reaction ?? null;
  const likesClass = reaction === "liked" ? "stat likes active" : "stat likes";
  const dislikesClass = reaction === "disliked" ? "stat dislikes active" : "stat dislikes";
  const reactionLabel =
    reaction === "liked"
      ? `<span class="visually-hidden">You liked this</span>`
      : reaction === "disliked"
        ? `<span class="visually-hidden">You disliked this</span>`
        : "";
  const cardClass = reaction ? `video-card ${reaction}` : "video-card";
  // Outside the card's link: a button inside an <a> would also navigate.
  const actionsMarkup = options.actions && videoKey
    ? `
      <div class="card-actions">
        <button type="button" class="card-action" data-card-action="like" aria-pressed="${reaction === "liked"}" title="Like">${iconThumbUp()}<span class="visually-hidden">Like</span></button>
        <button type="button" class="card-action" data-card-action="dislike" aria-pressed="${reaction === "disliked"}" title="Dislike">${iconThumbDown()}<span class="visually-hidden">Dislike</span></button>
        <button type="button" class="card-action" data-card-action="channel">Block channel</button>
        <button type="button" class="card-action" data-card-action="account">Block account</button>
        <button type="button" class="card-action" data-card-action="follow-channel">${followLabel("channel", options.follow?.channel ?? false)}</button>
        <button type="button" class="card-action" data-card-action="follow-account">${followLabel("account", options.follow?.account ?? false)}</button>
        <span class="card-action-status" role="status"></span>
      </div>`
    : "";

  return `
    <article class="${cardClass}"${keyAttribute}>
      <a class="video-link" href="${escapeHtml(videoPageUrl(row, options.apiParam))}">
        <div class="video-thumb">
          ${thumbMarkup}
          <span class="duration">${duration}</span>
        </div>
        <div class="video-body">
          <h3 class="card-title">${escapeHtml(title)}</h3>
          <div class="video-footer">
            <div class="card-channel">
              <div class="card-avatar" aria-hidden="true">${avatarMarkup}</div>
              <div class="channel-text">
                <a class="channel-link" href="${escapeHtml(safeExternalUrl(channelHref))}" target="_blank" rel="noreferrer">
                  ${escapeHtml(channelLabel)}
                </a>
                <div class="video-meta"><span data-stat="views">${formatStatValue(views)}</span> views${escapeHtml(timeSuffix)}</div>
              </div>
            </div>
            <div class="video-stats">
              <span class="${likesClass}">${iconThumbUp()}<span data-stat="likes">${formatStatValue(likes)}</span></span>
              <span class="${dislikesClass}">${iconThumbDown()}<span data-stat="dislikes">${formatStatValue(dislikes)}</span></span>
              ${reactionLabel}
            </div>
            ${footerExtra}
          </div>
        </div>
      </a>${actionsMarkup}
    </article>
  `;
}
