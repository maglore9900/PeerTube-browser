/**
 * Module `client/frontend/src/pages/video-page/index.ts`: provide runtime functionality.
 */

import "../../video.css";
import { createFeedPager, fetchSimilarVideosPayload, resolveApiBase, type FeedPager } from "../../data/videos";
import {
  cardReaction,
  fetchReaction,
  importLocalLikes,
  sendReaction,
  type Reaction,
  type ReactionAction,
  type ReactionVideo
} from "../../data/reactions";
import { safeExternalUrl } from "../../utils/safe-url";
import { ProfileKeyRejectedError, getProfileKey } from "../../data/profile";
import { blockVideoSource, type BlockKind } from "../../data/blocks";
import {
  followLookup,
  isFollowed,
  listFollows,
  setFollowed,
  toggleVideoSourceFollow,
  type FollowKind,
  type FollowSource
} from "../../data/follows";
import { keyRejectedNotice } from "../../components/key-rejected";
import { followLabel, observeTagRows, renderTagChips, tagSearchUrl } from "../../components/video-card";
import type { VideoRow } from "../../types/videos";
import { setupTranslate, withEmbedApi } from "./translate";

const titleEl = document.getElementById("video-title");
const channelEl = document.getElementById("video-channel");
const channelAvatarEl = document.getElementById("channel-avatar");
const channelSubscribersEl = document.getElementById("channel-subscribers");
const publishedEl = document.getElementById("video-published");
const instanceMetaEl = document.getElementById("instance-meta");
const instanceAvatarEl = document.getElementById("instance-avatar");
const instanceLinkEl = document.getElementById("instance-link") as HTMLAnchorElement | null;
const accountMetaEl = document.getElementById("account-meta");
const accountAvatarEl = document.getElementById("account-avatar");
const accountLinkEl = document.getElementById("account-link") as HTMLAnchorElement | null;
const viewsEl = document.getElementById("video-views");
const descriptionEl = document.getElementById("video-description");
const descriptionToggle = document.getElementById("description-toggle") as HTMLButtonElement | null;
const categoryItemEl = document.getElementById("video-category");
const categoryValueEl = document.getElementById("video-category-value");
const languageItemEl = document.getElementById("video-language");
const languageValueEl = document.getElementById("video-language-value");
const tagsEl = document.getElementById("video-tags");
const embedEl = document.getElementById("video-embed") as HTMLIFrameElement | null;
const originalLink = document.getElementById("original-link") as HTMLAnchorElement | null;
const similarLink = document.getElementById("similar-link") as HTMLAnchorElement | null;
const likeButton = document.getElementById("like-button") as HTMLButtonElement | null;
const dislikeButton = document.getElementById("dislike-button") as HTMLButtonElement | null;
const reactionStatusEl = document.getElementById("reaction-status");
const likeCount = document.getElementById("like-count");
const dislikeCount = document.getElementById("dislike-count");
const similarSection = document.getElementById("similar-section");
const similarCards = document.getElementById("similar-videos");
const similarSentinel = document.getElementById("similar-sentinel");
const similarLinkInline = document.getElementById("similar-link-inline") as HTMLAnchorElement | null;
const blockChannelButton = document.getElementById("block-channel") as HTMLButtonElement | null;
const blockAccountButton = document.getElementById("block-account") as HTMLButtonElement | null;
const followChannelButton = document.getElementById("follow-channel") as HTMLButtonElement | null;
const followAccountButton = document.getElementById("follow-account") as HTMLButtonElement | null;
const blockStatusEl = document.getElementById("block-status");
const commentsHeading = document.getElementById("comments-heading");
const commentsList = document.getElementById("comments-list");
const commentsStatus = document.getElementById("comments-status");
const commentsMoreButton = document.getElementById("comments-more") as HTMLButtonElement | null;
const statsNumberFormat = new Intl.NumberFormat("en-US");
// Matches the -webkit-line-clamp of .description-collapsed in video.css.
const DESCRIPTION_CLAMP_LINES = 4;
let currentMetadata: VideoMetadata | null = null;
let reaction: Reaction = { liked: false, disliked: false };
// The video's channel and account as the follow routes key them; a follow copies the Engine's key in.
const followSource: FollowSource = { instance_domain: "", channel_id: "", account_url: "" };
let followState = followLookup();

const params = new URLSearchParams(window.location.search);
if (similarCards) observeTagRows(similarCards);
const seedId = params.get("id");
const seedHost = params.get("host");
const apiBase = resolveApiBase({ apiBase: params.get("api") });
const fallback = {
  title: params.get("title") ?? "Video page",
  channel: params.get("channel") ?? "",
  channelUrl: params.get("channelUrl") ?? "",
  embed: params.get("embed") ?? "",
  url: params.get("url") ?? ""
};
const similarStatsCache = new Map<string, number | null>();
const similarStatsLoading = new Set<string>();
// Comments come straight from the source instance; these sit above the start calls because loadComments reads them before its first await.
const COMMENTS_BATCH = 20;
// rat-tail: PeerTube's VideoCommentPolicy.DISABLED as the plan expects it; R3's live check has not confirmed it yet, and only this value changes if it differs.
const COMMENTS_POLICY_DISABLED = 2;
const REPLIES_BATCH = 20;
// Deeper replies share the last indent so long chains stay readable on narrow screens; video.css has one rule per depth up to this.
const REPLY_DEPTH_CAP = 4;
const HTML_ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: "\u00a0" };
// loadVideo refreshes this link's href once metadata arrives, since the comments state can render first.
let commentsUnavailableLink: HTMLAnchorElement | null = null;
// Threads received so far, deleted ones included, so it is both the next batch's offset and the count held against the total.
let commentsReceived = 0;
// The similar list shows this many cards at first and adds this many per scroll to the bottom.
const SIMILAR_CHUNK = 8;
// Every row fetched so far; only the first similarRevealed of them are in the grid. Declared above the loadSimilarVideos() call, which resets this state before its first await.
let similarRows: VideoRow[] = [];
let similarRevealed = 0;
let similarLoading = false;
// One pager per load, so a retry starts with nothing shown and drops a replaced pager's result.
let similarPager: FeedPager | null = null;
let similarFetchingMore = false;
let similarScrollAttached = false;

if (similarLink && seedId) {
  const search = new URLSearchParams();
  search.set("id", seedId);
  if (seedHost) search.set("host", seedHost);
  similarLink.href = `/videos.html?${search.toString()}`;
}

if (descriptionEl && descriptionToggle) {
  descriptionToggle.addEventListener("click", () => {
    const collapsed = descriptionEl.classList.toggle("description-collapsed");
    descriptionToggle.textContent = collapsed ? "Show more" : "Show less";
    descriptionToggle.setAttribute("aria-expanded", String(!collapsed));
  });
  // The width decides how many lines the text wraps to, so every size change re-measures it.
  new ResizeObserver(() => updateDescriptionToggle()).observe(descriptionEl);
}

commentsMoreButton?.addEventListener("click", () => void loadMoreComments());

// A browser that holds a key hands its local likes to the profile before its first keyed read.
const localLikesImported = importLocalLikes(apiBase).catch((error) => {
  console.warn("[likes] import failed; the local likes are kept for the next load", error);
});

// One list fetch labels both follow buttons; without a key there is nothing to fetch and both read "Follow".
const followsLoaded = getProfileKey()
  ? listFollows(apiBase).then(followLookup, (error) => {
      console.warn("[follows] could not load the follow list; both buttons read Follow", error);
      return followLookup();
    })
  : Promise.resolve(followLookup());

void loadVideo();
void loadSimilarVideos();
void loadComments();

/**
 * Handle load video.
 */
async function loadVideo() {
  const metadata = await fetchVideoMetadata();
  currentMetadata = metadata;
  const channelUrl = metadata?.channelUrl || fallback.channelUrl;
  const channel = [
    metadata?.channelName,
    fallback.channel,
    labelFromUrl(channelUrl)
  ]
    .map((value) => value?.trim())
    .find((value) => value);
  const title = metadata?.title ?? fallback.title;
  const avatarUrl = metadata?.channelAvatarUrl ?? "";
  const subscribersCount = metadata?.subscribersCount ?? null;
  const embed = metadata?.embedUrl ?? fallback.embed;
  const views = metadata?.views ?? null;
  const likes = metadata?.likes ?? null;
  const dislikes = metadata?.dislikes ?? null;
  const description = metadata?.description ?? "";
  const category = metadata?.category ?? "";
  const language = metadata?.language ?? "";
  const tags = metadata?.tags ?? [];
  const publishedAt = metadata?.publishedAt ?? null;
  const timeAgo = publishedAt ? formatTimeAgo(publishedAt) : null;
  const instanceName = metadata?.instanceName ?? seedHost ?? "";
  const instanceUrl = metadata?.instanceUrl ?? (seedHost ? `https://${seedHost}` : "");
  const instanceAvatarUrl = metadata?.instanceAvatarUrl ?? "";
  const accountName = metadata?.accountName ?? "";
  const accountUrl = metadata?.accountUrl ?? "";
  const accountAvatarUrl = metadata?.accountAvatarUrl ?? "";

  document.title = `${title || "Video"} - PeerTube - Browser`;

  if (titleEl) titleEl.textContent = title || "Video page";
  const channelRowEl = channelEl?.closest(".channel-row") as HTMLElement | null;
  if (channelEl) {
    if (channel) {
      channelEl.innerHTML = channelUrl
        ? `<a href="${escapeHtml(safeExternalUrl(channelUrl))}" target="_blank" rel="noreferrer">${escapeHtml(channel)}</a>`
        : escapeHtml(channel);
    } else {
      channelEl.textContent = "";
    }
  }
  if (channelAvatarEl) {
    const avatarMarkup = renderChannelAvatar(avatarUrl, channel || "");
    channelAvatarEl.innerHTML = avatarMarkup;
    channelAvatarEl.hidden = !avatarMarkup;
  }
  if (channelSubscribersEl) {
    if (Number.isFinite(subscribersCount ?? NaN)) {
      channelSubscribersEl.textContent = `${numberFormat().format(subscribersCount ?? 0)} subscribers`;
    } else {
      channelSubscribersEl.textContent = "";
    }
  }
  if (instanceMetaEl) {
    instanceMetaEl.hidden = !instanceName;
  }
  if (instanceLinkEl) {
    instanceLinkEl.textContent = instanceName;
    if (instanceUrl) {
      instanceLinkEl.href = safeExternalUrl(instanceUrl);
    } else {
      instanceLinkEl.removeAttribute("href");
    }
  }
  if (instanceAvatarEl) {
    const initials = escapeHtml(instanceInitials(instanceName));
    if (instanceAvatarUrl) {
      instanceAvatarEl.classList.remove("fallback");
      instanceAvatarEl.innerHTML = `
        <img src="${escapeHtml(instanceAvatarUrl)}" alt="" loading="lazy" />
        <span>${initials}</span>
      `;
      bindAvatarFallback(instanceAvatarEl);
    } else {
      instanceAvatarEl.classList.add("fallback");
      instanceAvatarEl.innerHTML = `<span>${initials}</span>`;
    }
  }
  if (accountMetaEl) {
    accountMetaEl.hidden = !accountName;
  }
  if (accountLinkEl) {
    accountLinkEl.textContent = accountName;
    if (accountUrl) {
      accountLinkEl.href = safeExternalUrl(accountUrl);
    } else {
      accountLinkEl.removeAttribute("href");
    }
  }
  if (accountAvatarEl) {
    const initials = escapeHtml(instanceInitials(accountName));
    if (accountAvatarUrl) {
      accountAvatarEl.classList.remove("fallback");
      accountAvatarEl.innerHTML = `
        <img src="${escapeHtml(accountAvatarUrl)}" alt="" loading="lazy" />
        <span>${initials}</span>
      `;
      bindAvatarFallback(accountAvatarEl);
    } else {
      accountAvatarEl.classList.add("fallback");
      accountAvatarEl.innerHTML = `<span>${initials}</span>`;
    }
  }
  if (publishedEl) {
    publishedEl.textContent = timeAgo ? `${timeAgo}` : "";
  }
  if (channelRowEl) {
    const hasMeta = Boolean(channel || subscribersCount || timeAgo);
    channelRowEl.hidden = !hasMeta;
  }
  enableBlockButtons(metadata?.videoUuid || resolveVideoSource()?.id || "", resolveVideoSource()?.host || "");
  void enableFollowButtons(metadata?.videoUuid || resolveVideoSource()?.id || "", resolveVideoSource()?.host || "", metadata);
  void loadReaction();
  if (viewsEl) {
    const value = Number.isFinite(views ?? NaN) ? numberFormat().format(views ?? 0) : "0";
    const icon = iconEye();
    viewsEl.innerHTML = `${icon}<span class="metric-value">${value}</span>`;
  }
  if (likeCount) {
    likeCount.textContent = numberFormat().format(likes ?? 0);
  }
  if (dislikeCount) {
    dislikeCount.textContent = numberFormat().format(dislikes ?? 0);
  }
  if (descriptionEl) {
    descriptionEl.textContent = description ? description : "No description available.";
    updateDescriptionToggle();
  }
  renderTaxonomyItem(categoryItemEl, categoryValueEl, category);
  renderTaxonomyItem(languageItemEl, languageValueEl, language);
  if (tagsEl) {
    if (tags.length) {
      // Tags come from remote instances, so each chip is built from text, never from markup; a tag the search cannot take stays a plain chip.
      tagsEl.replaceChildren(
        ...tags.map((tag) => {
          const href = tagSearchUrl(tag, params.get("api"));
          const chip = document.createElement(href ? "a" : "span");
          chip.className = "tag-chip";
          chip.textContent = tag;
          if (href) (chip as HTMLAnchorElement).href = href;
          return chip;
        })
      );
    } else {
      tagsEl.textContent = "No tags";
    }
  }
  if (embedEl) {
    // The embed URL can come straight from the `?embed=` query parameter when
    // metadata resolution fails, so a scheme check is what stops a
    // `javascript:` URL from executing in this origin via iframe navigation.
    const apiEmbed = embed && /^https:\/\//i.test(embed.trim()) ? withEmbedApi(embed) : null;
    if (apiEmbed) {
      embedEl.src = apiEmbed;
      // After the api=1 src is set, never before; setupTranslate binds once per page and never throws, so applyOriginalHref below always runs.
      setupTranslate(embedEl, apiBase, { id: metadata?.videoUuid || resolveVideoSource()?.id || "", host: resolveVideoSource()?.host || "" });
    } else {
      embedEl.removeAttribute("src");
    }
  }
  applyOriginalHref(originalLink);
  applyOriginalHref(commentsUnavailableLink);
}

/**
 * Show the description toggle exactly while the real description's text is taller than the clamp,
 * collapsed or not; the placeholder never gets one.
 */
function updateDescriptionToggle() {
  if (!descriptionEl || !descriptionToggle) return;
  if (!currentMetadata?.description) {
    descriptionToggle.hidden = true;
    return;
  }
  const style = getComputedStyle(descriptionEl);
  // scrollHeight counts clipped lines too; the computed padding differs between the collapsed and expanded states, so it is read rather than assumed.
  const textHeight = descriptionEl.scrollHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  // Rounding to whole lines absorbs scrollHeight's integer rounding, so exactly four lines never reads as taller.
  descriptionToggle.hidden = Math.round(textHeight / parseFloat(style.lineHeight)) <= DESCRIPTION_CLAMP_LINES;
}

/**
 * Handle load similar videos.
 */
async function loadSimilarVideos() {
  if (!similarSection || !similarCards) return;
  if (!seedId) {
    similarSection.setAttribute("hidden", "true");
    return;
  }
  if (similarLinkInline) {
    const search = new URLSearchParams();
    search.set("id", seedId);
    if (seedHost) search.set("host", seedHost);
    similarLinkInline.href = `/videos.html?${search.toString()}`;
  }
  similarRows = [];
  similarRevealed = 0;
  similarLoading = true;
  similarCards.innerHTML = `<div class="loading">Loading...</div>`;
  const current = createFeedPager((exclude) =>
    fetchSimilarVideosPayload({ id: seedId, host: seedHost, limit: "48", apiBase }, exclude)
  );
  similarPager = current;
  try {
    await localLikesImported;
    const payload = await current.next();
    if (current !== similarPager) return;
    similarLoading = false;
    const rows = payload.rows ?? [];
    if (!rows.length) {
      similarCards.innerHTML = `<div class="error">No similar videos found.</div>`;
      return;
    }
    similarRows = rows.slice();
    const first = similarRows.slice(0, SIMILAR_CHUNK);
    similarRevealed = first.length;
    similarCards.innerHTML = first.map((row) => renderSimilarCard(row)).join("");
    queueSimilarStats(first);
    // Only after a non-empty first batch, so a page with nothing to page never touches the observer or layout.
    setupSimilarScroll();
    fillSimilarViewport();
  } catch (error) {
    if (current !== similarPager) return;
    similarLoading = false;
    if (error instanceof ProfileKeyRejectedError) {
      similarCards.replaceChildren(keyRejectedNotice(() => void loadSimilarVideos()));
      return;
    }
    const message = error instanceof Error ? error.message : "Failed to load similar videos";
    similarCards.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
  }
}

type CommentItem = {
  id: number | null;
  text: string;
  createdAt: number | null;
  isDeleted: boolean;
  totalReplies: number;
  displayName: string;
  name: string;
  host: string;
};

type ReplyRow = { comment: CommentItem; depth: number };

/**
 * Load the video's first batch of comment threads from its source instance; no other block waits on it.
 */
async function loadComments() {
  if (!commentsList || !commentsStatus) return;
  if (commentsMoreButton) commentsMoreButton.hidden = true;
  const source = resolveVideoSource();
  if (!source?.host || !source.id) {
    renderCommentsUnavailable(source?.host ?? "");
    return;
  }
  try {
    const page = await fetchCommentThreads(source, 0);
    // PeerTube answers a video with comments disabled with an empty list, so only an empty first batch asks the video itself.
    if (page.total === 0 && (await fetchCommentsDisabled(source))) {
      renderCommentsUnavailable(source.host);
      return;
    }
    if (commentsHeading) commentsHeading.textContent = `Comments (${numberFormat().format(page.total)})`;
    appendCommentThreads(page);
    commentsStatus.textContent = page.total === 0 ? "No comments yet." : "";
  } catch (error) {
    console.warn("[comments] could not load comment threads", error);
    renderCommentsUnavailable(source.host);
  }
}

/**
 * Fetch the next batch from the received count. The button is disabled while the batch is in flight, so a double click sends one request.
 */
async function loadMoreComments() {
  const source = resolveVideoSource();
  if (!commentsMoreButton || !source?.host || !source.id) return;
  commentsMoreButton.disabled = true;
  try {
    appendCommentThreads(await fetchCommentThreads(source, commentsReceived));
  } catch (error) {
    // The button stays shown and is re-enabled below, so the same batch can be retried.
    console.warn("[comments] could not load more comment threads", error);
  } finally {
    commentsMoreButton.disabled = false;
  }
}

/**
 * Append one batch and show "Load more comments" only while the received count is below the total.
 */
function appendCommentThreads(page: { total: number; threads: CommentItem[] }) {
  if (!commentsList) return;
  for (const thread of page.threads) {
    // A deleted thread is only worth showing as context for its replies.
    if (thread.isDeleted && thread.totalReplies === 0) continue;
    commentsList.append(renderCommentThread(thread));
  }
  commentsReceived += page.threads.length;
  // An empty batch below the total would leave the offset where it is, so the button could never advance.
  if (commentsMoreButton) commentsMoreButton.hidden = commentsReceived >= page.total || page.threads.length === 0;
}

/**
 * Replace the comments status with "unavailable" and a link to the original video. The host is remote input, so it goes in as text.
 */
function renderCommentsUnavailable(host: string) {
  if (!commentsStatus) return;
  const link = document.createElement("a");
  link.className = "ghost-link";
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "Open the original video";
  applyOriginalHref(link);
  commentsUnavailableLink = link;
  commentsStatus.replaceChildren(host ? `Comments are unavailable on ${host}. ` : "Comments are unavailable. ", link);
}

/**
 * Fetch one batch of threads, newest first. Throws on a network error, a non-OK status or unparsable JSON; tolerates any shape inside.
 */
async function fetchCommentThreads(source: { host: string; id: string }, start: number) {
  const data = asRecord(await fetchVideoJson(source, `/comment-threads?start=${start}&count=${COMMENTS_BATCH}&sort=-createdAt`, "Comment threads"));
  const rows = Array.isArray(data.data) ? data.data : [];
  return { total: Math.max(0, normalizeNumber(data.total) ?? 0), threads: rows.map((row) => parseComment(row)) };
}

/**
 * Fetch one thread's whole reply tree; PeerTube does not paginate it. Throws on a network error, a non-OK status or unparsable JSON.
 */
async function fetchCommentThread(source: { host: string; id: string }, threadId: number) {
  return fetchVideoJson(source, `/comment-threads/${threadId}`, "Comment thread");
}

/**
 * Whether the video has comments disabled. Any failure reads as "not disabled", so the section falls back to "No comments yet.".
 */
async function fetchCommentsDisabled(source: { host: string; id: string }) {
  try {
    const data = asRecord(await fetchVideoJson(source, "", "Video"));
    return data.commentsEnabled === false || normalizeNumber(asRecord(data.commentsPolicy).id) === COMMENTS_POLICY_DISABLED;
  } catch (error) {
    console.warn("[comments] could not check whether comments are disabled", error);
    return false;
  }
}

/**
 * GET a JSON body at `path` under the video on its source instance, the one request shape the comments block uses. Throws on a network error, a non-OK status or unparsable JSON.
 */
async function fetchVideoJson(source: { host: string; id: string }, path: string, label: string) {
  const url = `https://${source.host}/api/v1/videos/${encodeURIComponent(source.id)}${path}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${label} request failed: ${response.status}`);
  return (await response.json()) as unknown;
}

/**
 * Read one comment through tolerant accessors: a missing or mistyped field becomes an empty or default value, never an exception.
 */
function parseComment(value: unknown): CommentItem {
  const data = asRecord(value);
  const account = asRecord(data.account);
  // createdAt is an ISO string, which normalizeTimestampMs would turn into null.
  const createdAt = typeof data.createdAt === "string" ? Date.parse(data.createdAt) : NaN;
  return {
    id: normalizeNumber(data.id),
    text: typeof data.text === "string" ? data.text : "",
    createdAt: Number.isFinite(createdAt) ? createdAt : null,
    isDeleted: data.isDeleted === true,
    totalReplies: Math.max(0, normalizeNumber(data.totalReplies) ?? 0),
    displayName: getString(account, ["displayName"]),
    name: getString(account, ["name"]),
    host: getString(account, ["host"])
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function renderCommentThread(thread: CommentItem) {
  const item = document.createElement("article");
  item.className = "comment-thread";
  item.append(renderComment(thread));
  if (thread.totalReplies > 0 && thread.id !== null) item.append(...renderReplies(thread.id, thread.totalReplies));
  return item;
}

/**
 * The reply toggle and its container for one thread. The tree is fetched on the first expand only; the toggle is disabled while that request is in flight, so a double click sends one request.
 */
function renderReplies(threadId: number, total: number) {
  const label = `Show ${numberFormat().format(total)} ${total === 1 ? "reply" : "replies"}`;
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "ghost-button comment-replies-toggle";
  toggle.textContent = label;
  toggle.setAttribute("aria-expanded", "false");
  const container = document.createElement("div");
  container.className = "comment-replies";
  container.hidden = true;
  const list = document.createElement("div");
  list.className = "comment-replies-list";
  const more = document.createElement("button");
  more.type = "button";
  more.className = "ghost-button comment-replies-more";
  more.textContent = "Show more replies";
  more.hidden = true;
  container.append(list, more);
  let rows: ReplyRow[] | null = null;
  let shown = 0;
  const showMoreReplies = () => {
    if (!rows) return;
    const next = rows.slice(shown, shown + REPLIES_BATCH);
    list.append(...next.map((row) => renderReplyRow(row)));
    shown += next.length;
    more.hidden = shown >= rows.length;
  };
  const setExpanded = (expanded: boolean) => {
    container.hidden = !expanded;
    toggle.textContent = expanded ? "Hide replies" : label;
    toggle.setAttribute("aria-expanded", String(expanded));
  };
  toggle.addEventListener("click", async () => {
    // Once fetched, the rows stay in the container, so collapsing and re-expanding only flips its visibility.
    if (rows) {
      setExpanded(container.hidden);
      return;
    }
    const source = resolveVideoSource();
    if (!source?.host || !source.id) return;
    toggle.disabled = true;
    try {
      rows = flattenReplies(await fetchCommentThread(source, threadId));
      showMoreReplies();
      setExpanded(true);
    } catch (error) {
      // The label is unchanged and the toggle is re-enabled below, so the next click retries.
      console.warn("[comments] could not load replies", error);
    } finally {
      toggle.disabled = false;
    }
  });
  more.addEventListener("click", showMoreReplies);
  return [toggle, container];
}

/**
 * Flatten a thread detail `{ comment, children: [{ comment, children }] }` into pre-order rows with their depth, starting at 1. A deleted reply with no children is dropped.
 */
function flattenReplies(tree: unknown) {
  const rows: ReplyRow[] = [];
  const walk = (children: unknown, depth: number) => {
    if (!Array.isArray(children)) return;
    for (const child of children) {
      const node = asRecord(child);
      const kids = Array.isArray(node.children) ? node.children : [];
      const comment = parseComment(node.comment);
      if (!(comment.isDeleted && kids.length === 0)) rows.push({ comment, depth });
      walk(kids, depth + 1);
    }
  };
  walk(asRecord(tree).children, 1);
  return rows;
}

function renderReplyRow(row: ReplyRow) {
  const el = renderComment(row.comment);
  el.classList.add("comment-reply", `comment-depth-${Math.min(row.depth, REPLY_DEPTH_CAP)}`);
  return el;
}

/**
 * Build one comment from text only: remote content never reaches an HTML sink.
 */
function renderComment(comment: CommentItem) {
  const el = document.createElement("div");
  el.className = "comment";
  if (comment.isDeleted) {
    const deleted = document.createElement("p");
    deleted.className = "comment-deleted";
    deleted.textContent = "Comment deleted";
    el.append(deleted);
    return el;
  }
  const meta = document.createElement("div");
  meta.className = "comment-meta";
  const author = document.createElement("span");
  author.className = "comment-author";
  author.textContent = comment.displayName || comment.name || "Unknown author";
  meta.append(author);
  if (comment.name) {
    const handle = document.createElement("span");
    handle.className = "comment-handle";
    handle.textContent = comment.host ? `@${comment.name}@${comment.host}` : `@${comment.name}`;
    meta.append(handle);
  }
  if (comment.createdAt !== null) {
    const time = document.createElement("span");
    time.className = "comment-time";
    time.textContent = formatTimeAgo(comment.createdAt);
    meta.append(time);
  }
  const body = document.createElement("p");
  body.className = "comment-body";
  body.textContent = commentPlainText(comment.text);
  el.append(meta, body);
  return el;
}

/**
 * Reduce federated HTML (Mastodon `<p>`, `<br>`, `<a>`, `<span>`) to plain text; text with no tag-shaped `<` is returned untouched, so PeerTube Markdown shows raw.
 * Entities are decoded last, so an encoded `&lt;script&gt;` ends as the literal text "<script>", which is only ever set as text.
 */
function commentPlainText(text: string) {
  if (!/<[a-z/]/i.test(text)) return text;
  return text
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>\s*<p[^>]*>/gi, "\n\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&(#\d+|#x[0-9a-f]+|[a-z]+);/gi, (match, name: string) => decodeEntity(match, name))
    .trim();
}

function decodeEntity(match: string, name: string) {
  if (name[0] === "#") {
    const hex = name[1] === "x" || name[1] === "X";
    const code = hex ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
    return Number.isInteger(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : match;
  }
  return HTML_ENTITIES[name.toLowerCase()] ?? match;
}

/**
 * Append the next chunk of fetched rows to the grid; with none left, ask the pager for more.
 */
function revealSimilarChunk() {
  if (similarLoading || !similarCards) return false;
  const nextCount = Math.min(similarRows.length, similarRevealed + SIMILAR_CHUNK);
  if (nextCount <= similarRevealed) {
    void loadMoreSimilar();
    return false;
  }
  const slice = similarRows.slice(similarRevealed, nextCount);
  similarRevealed = nextCount;
  // Appending leaves the cards already shown, and the stats already filled into them, in place.
  similarCards.insertAdjacentHTML("beforeend", slice.map((row) => renderSimilarCard(row)).join(""));
  queueSimilarStats(slice);
  return true;
}

/**
 * Fetch the next up-next batch once the revealed rows reach the end of the ones fetched.
 */
async function loadMoreSimilar() {
  const current = similarPager;
  if (!current || similarLoading || similarFetchingMore || current.exhausted) return;
  similarFetchingMore = true;
  let appended = false;
  try {
    const payload = await current.next();
    if (current !== similarPager || !payload.rows?.length) return;
    similarRows.push(...payload.rows);
    appended = true;
  } catch (error) {
    console.warn("[similar] loading more failed; paging stops for this page view", error);
  } finally {
    similarFetchingMore = false;
  }
  // The sentinel may still be in view, so the observer will not fire again: reveal until it scrolls.
  if (appended) {
    revealSimilarChunk();
    fillSimilarViewport();
  }
}

/**
 * While the page is too short to scroll, keep revealing chunks until it can.
 */
function fillSimilarViewport() {
  if (similarLoading) return;
  let safety = 0;
  // Unlike the home page's loop this does not stop when the fetched rows run out: the reveal that finds none left asks for the next batch, which a short page would otherwise never request.
  while (document.documentElement.scrollHeight <= window.innerHeight + 120 && safety < 50) {
    if (!revealSimilarChunk()) break;
    safety += 1;
  }
}

/**
 * Reveal the next chunk once the page is scrolled near its bottom.
 */
function maybeRevealSimilarOnScroll() {
  if (similarLoading) return;
  const nearBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 240;
  if (nearBottom) revealSimilarChunk();
}

/**
 * Watch the sentinel after the grid, with scroll and resize as a fallback; attached once per page view.
 */
function setupSimilarScroll() {
  if (similarScrollAttached) return;
  similarScrollAttached = true;
  if (similarSentinel) {
    new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        revealSimilarChunk();
      },
      { rootMargin: "200px" }
    ).observe(similarSentinel);
  }
  window.addEventListener("scroll", maybeRevealSimilarOnScroll, { passive: true });
  window.addEventListener("resize", () => {
    maybeRevealSimilarOnScroll();
    fillSimilarViewport();
  });
}

/**
 * Enable "Block channel" and "Block account" once the video's uuid and host are known.
 * The Client backend looks the video up, so the page sends nothing else.
 */
function enableBlockButtons(uuid: string, host: string) {
  if (!uuid || !host) return;
  const buttons: [HTMLButtonElement | null, BlockKind][] = [
    [blockChannelButton, "channel"],
    [blockAccountButton, "account"]
  ];
  for (const [button, kind] of buttons) {
    if (!button || button.dataset.wired) continue;
    button.dataset.wired = "true";
    button.disabled = false;
    button.addEventListener("click", async () => {
      if (!getProfileKey()) {
        setBlockStatus("Blocking needs a profile. Create one from the Profile button on the home page.");
        return;
      }
      button.disabled = true;
      try {
        const block = await blockVideoSource(apiBase, kind, uuid, host);
        // The Client drops the follow on the key it blocks.
        setFollowed(followState, kind, block, false);
        renderFollowButtons();
        // Blocking also dislikes the video, so the feed steers away from videos like it.
        try {
          renderReaction(await sendReaction(apiBase, "dislike", { uuid, host }));
        } catch (error) {
          setBlockStatus(`Blocked ${block.label || kind}, but the dislike failed: ${error instanceof Error ? error.message : error}`);
          return;
        }
        setBlockStatus(`Blocked ${block.label || kind} and disliked this video. Its videos no longer appear in your feeds or search.`);
      } catch (error) {
        setBlockStatus(error instanceof Error ? error.message : "Block failed");
      } finally {
        button.disabled = false;
      }
    });
  }
}

/**
 * Label "Follow channel" and "Follow account" from the follow list, then let them toggle. They stay disabled until the
 * list is known, so a click never acts on a state the page has not shown. A follow names the video, as a block does.
 */
async function enableFollowButtons(uuid: string, host: string, metadata: VideoMetadata | null) {
  if (!uuid || !host) return;
  // The instance fallback carries no Engine channel id, so its channel reads "Follow channel" until a follow returns the Engine's key.
  Object.assign(followSource, { instance_domain: host, channel_id: metadata?.channelId ?? "", account_url: metadata?.accountUrl ?? "" });
  followState = await followsLoaded;
  renderFollowButtons();
  const buttons: [HTMLButtonElement | null, FollowKind][] = [
    [followChannelButton, "channel"],
    [followAccountButton, "account"]
  ];
  for (const [button, kind] of buttons) {
    if (!button || button.dataset.wired) continue;
    button.dataset.wired = "true";
    button.disabled = false;
    button.addEventListener("click", async () => {
      if (!getProfileKey()) {
        setBlockStatus("Following needs a profile. Create one from the Profile button on the home page.");
        return;
      }
      button.disabled = true;
      try {
        const follow = await toggleVideoSourceFollow(apiBase, followState, kind, uuid, host, followSource);
        if (follow) {
          Object.assign(followSource, kind === "channel" ? { instance_domain: follow.instance_domain, channel_id: follow.channel_id } : { account_url: follow.account_url });
        }
        renderFollowButtons();
        setBlockStatus(follow ? `Following ${follow.label || kind}.` : `Unfollowed this ${kind}.`);
      } catch (error) {
        setBlockStatus(error instanceof Error ? error.message : "Follow failed");
      } finally {
        button.disabled = false;
      }
    });
  }
}

function renderFollowButtons() {
  if (followChannelButton) followChannelButton.textContent = followLabel("channel", isFollowed(followState, "channel", followSource));
  if (followAccountButton) followAccountButton.textContent = followLabel("account", isFollowed(followState, "account", followSource));
}

/**
 * Show one taxonomy item with its value, or hide it when the video has none.
 */
function renderTaxonomyItem(itemEl: HTMLElement | null, valueEl: HTMLElement | null, value: string) {
  if (itemEl) itemEl.hidden = !value;
  if (valueEl) valueEl.textContent = value;
}

/**
 * Point a link at the original video, the one URL "Open original" and the comments fallback share so the two never drift.
 * With no original URL the link has no href; `safeExternalUrl("")` would turn it into "#".
 */
function applyOriginalHref(link: HTMLAnchorElement | null) {
  if (!link) return;
  const original = currentMetadata?.originalUrl ?? fallback.url;
  if (original) {
    link.href = safeExternalUrl(original);
  } else {
    link.removeAttribute("href");
  }
}

function setBlockStatus(text: string) {
  if (blockStatusEl) blockStatusEl.textContent = text;
}

/**
 * Show the visitor's reaction to this video, then let the buttons change it. The buttons stay
 * disabled until the reaction is known, so a click never acts on a state the page has not shown.
 */
async function loadReaction() {
  const video = reactionVideo();
  if (!video || !likeButton || !dislikeButton) return;
  try {
    await localLikesImported;
    renderReaction(await fetchReaction(apiBase, video));
  } catch (error) {
    setReactionStatus(error instanceof Error ? error.message : "Could not read your reaction");
  }
  if (likeButton.dataset.wired) return;
  likeButton.dataset.wired = "true";
  likeButton.disabled = false;
  dislikeButton.disabled = false;
  likeButton.addEventListener("click", () => {
    void react(likeButton, reaction.liked ? "undo_like" : "like", video);
  });
  dislikeButton.addEventListener("click", () => {
    if (!getProfileKey()) {
      setReactionStatus("Disliking needs a profile. Create one from the Profile button on the home page.");
      return;
    }
    void react(dislikeButton, reaction.disliked ? "undo_dislike" : "dislike", video);
  });
}

/**
 * Send one reaction from a button; on failure both buttons keep the state they showed.
 */
async function react(button: HTMLButtonElement, action: ReactionAction, video: ReactionVideo) {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  setReactionStatus("");
  try {
    renderReaction(await sendReaction(apiBase, action, video));
  } catch (error) {
    setReactionStatus(error instanceof Error ? error.message : "Reaction failed");
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

function renderReaction(state: Reaction) {
  reaction = state;
  setReactionButton(likeButton, state.liked, "Like", "Liked");
  setReactionButton(dislikeButton, state.disliked, "Dislike", "Disliked");
}

function setReactionButton(button: HTMLButtonElement | null, active: boolean, idle: string, activeLabel: string) {
  if (!button) return;
  button.classList.toggle("active", active);
  button.setAttribute("aria-pressed", String(active));
  const label = button.querySelector(".reaction-label");
  if (label) label.textContent = active ? activeLabel : idle;
}

function setReactionStatus(text: string) {
  if (reactionStatusEl) reactionStatusEl.textContent = text;
}

/**
 * The video's uuid and host, which the reaction routes and the local likes key on.
 */
function reactionVideo(): ReactionVideo | null {
  if (!seedId) return null;
  const uuid = resolveLikeUuid(seedId, currentMetadata);
  const host = resolveLikeHost(seedHost, currentMetadata);
  return uuid && host ? { uuid, host } : null;
}

/**
 * Handle channel name.
 */
function channelName(row: VideoRow | null) {
  return (
    row?.channel_display_name ??
    row?.channelDisplayName ??
    row?.channel_name ??
    row?.channelName ??
    row?.account_name ??
    row?.accountName ??
    ""
  );
}

/**
 * Handle channel initials.
 */
function channelInitials(label: string) {
  const trimmed = label.trim();
  if (!trimmed) return "•";
  const cleaned = trimmed.replace(/[_\-]+/g, " ").replace(/\s+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

/**
 * Attach the avatar load-failure fallback to images inside `container`.
 *
 * Replaces an inline `onerror=` attribute: an inline handler only runs under a CSP
 * with `script-src 'unsafe-inline'`, which would also let injected markup execute and
 * defeat the purpose of having a policy at all.
 *
 * @param container Element holding the avatar image and its initials fallback.
 */
function bindAvatarFallback(container: HTMLElement) {
  container.querySelectorAll("img").forEach((image) => {
    image.addEventListener(
      "error",
      () => {
        image.parentElement?.classList.add("fallback");
        image.remove();
      },
      { once: true }
    );
  });
}

/**
 * Handle render channel avatar.
 */
function renderChannelAvatar(avatarUrl: string, label: string) {
  if (avatarUrl) {
    return `<img src="${escapeHtml(avatarUrl)}" alt="" loading="lazy" />`;
  }
  if (!label) return "";
  return `<span>${escapeHtml(channelInitials(label))}</span>`;
}

/**
 * Handle channel url for.
 */
function channelUrlFor(row: VideoRow | null) {
  if (!row) return "";
  if (row.channel_url) return row.channel_url;
  if (row.channelUrl) return row.channelUrl;
  if (row.account_url) return row.account_url;
  if (row.accountUrl) return row.accountUrl;
  const name = row.channel_name ?? row.channelName;
  const host = row.instance_domain ?? row.instanceDomain;
  if (name && host) {
    return `https://${host}/video-channels/${encodeURIComponent(name)}`;
  }
  return "";
}

/**
 * Handle label from url.
 */
function labelFromUrl(value: string) {
  if (!value) return "";
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean);
    return decodeURIComponent(parts[parts.length - 1] ?? "");
  } catch {
    return "";
  }
}

type VideoMetadata = {
  videoUuid?: string;
  title?: string;
  channelName?: string;
  /** The Engine's channel id; only `/api/video` carries it, the instance fallback leaves it unset. */
  channelId?: string;
  channelUrl?: string;
  channelAvatarUrl?: string;
  subscribersCount?: number | null;
  instanceName?: string;
  instanceUrl?: string;
  instanceAvatarUrl?: string;
  accountName?: string;
  accountUrl?: string;
  accountAvatarUrl?: string;
  embedUrl?: string;
  originalUrl?: string;
  views?: number | null;
  likes?: number | null;
  dislikes?: number | null;
  description?: string;
  category?: string;
  language?: string;
  tags?: string[];
  publishedAt?: number | null;
};

/**
 * Handle fetch video metadata.
 */
async function fetchVideoMetadata(): Promise<VideoMetadata | null> {
  const source = resolveVideoSource();
  if (!source?.host || !source.id) return null;
  const serverMeta = await fetchVideoMetadataFromServer(source);
  if (serverMeta) return serverMeta;
  return fetchVideoMetadataFromInstance(source);
}

/**
 * Handle fetch video metadata from server.
 */
async function fetchVideoMetadataFromServer(source: { host: string; id: string; url: string }) {
  try {
    const url = new URL("/api/video", apiBase);
    url.searchParams.set("id", source.id);
    url.searchParams.set("host", source.host);
    const response = await fetch(url.toString(), { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    const instanceMeta = await fetchInstanceMetadata(source.host);
    const publishedAt = normalizeTimestampMs(data.publishedAt);
    return {
      videoUuid: (data.videoUuid as string | undefined) ?? "",
      title: (data.title as string | undefined) ?? fallback.title,
      channelName: (data.channelName as string | undefined) ?? fallback.channel,
      channelId: (data.channelId as string | undefined) ?? "",
      channelUrl: (data.channelUrl as string | undefined) ?? fallback.channelUrl,
      channelAvatarUrl: (data.channelAvatarUrl as string | undefined) ?? "",
      subscribersCount: normalizeNumber(data.subscribersCount) ?? null,
      instanceName:
        (data.instanceName as string | undefined) ?? instanceMeta?.name ?? source.host,
      instanceUrl:
        (data.instanceUrl as string | undefined) ??
        instanceMeta?.url ??
        `https://${source.host}`,
      instanceAvatarUrl: instanceMeta?.avatarUrl ?? "",
      accountName: (data.accountName as string | undefined) ?? "",
      accountUrl: (data.accountUrl as string | undefined) ?? "",
      accountAvatarUrl: (data.accountAvatarUrl as string | undefined) ?? "",
      embedUrl: (data.embedUrl as string | undefined) ?? fallback.embed,
      originalUrl: (data.originalUrl as string | undefined) ?? source.url ?? fallback.url,
      views: normalizeNumber(data.views),
      likes: normalizeNumber(data.likes),
      dislikes: normalizeNumber(data.dislikes),
      description: (data.description as string | undefined) ?? "",
      category: (data.category as string | undefined) ?? "",
      language: (data.language as string | undefined) ?? "",
      tags: Array.isArray(data.tags) ? data.tags.filter((tag): tag is string => typeof tag === "string") : [],
      publishedAt
    };
  } catch {
    return null;
  }
}

/**
 * Handle fetch video metadata from instance.
 */
async function fetchVideoMetadataFromInstance(source: { host: string; id: string; url: string }) {
  try {
    const url = `https://${source.host}/api/v1/videos/${encodeURIComponent(source.id)}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    const channel = (data.channel ?? {}) as Record<string, unknown>;
    const account = (data.account ?? {}) as Record<string, unknown>;
    const channelName =
      (channel.displayName as string | undefined) ??
      (channel.display_name as string | undefined) ??
      (channel.name as string | undefined) ??
      "";
    const channelId = channel.name as string | undefined;
    const channelUrl =
      (channel.url as string | undefined) ??
      (channelId ? `https://${source.host}/video-channels/${encodeURIComponent(channelId)}` : "");
    const channelAvatarUrl =
      resolvePeerTubeAvatarUrl(source.host, channel) ??
      resolvePeerTubeAvatarUrl(source.host, data as Record<string, unknown>) ??
      "";
    const accountName =
      (account.displayName as string | undefined) ??
      (account.display_name as string | undefined) ??
      (account.name as string | undefined) ??
      "";
    const accountUrl = (account.url as string | undefined) ?? "";
    const accountAvatarUrl =
      resolvePeerTubeAvatarUrl(source.host, account) ??
      resolvePeerTubeAvatarUrl(source.host, data as Record<string, unknown>) ??
      "";
    const embedPath = (data.embedPath ?? data.embed_path) as string | undefined;
    const embedUrl = embedPath ? resolveApiAssetUrl(source.host, embedPath) : "";
    const originalUrl =
      (data.url as string | undefined) ??
      (data.videoUrl as string | undefined) ??
      source.url ??
      "";
    const publishedAt = normalizeTimestampMs(data.publishedAt ?? data.published_at);
    const channelMeta = channelId ? await fetchChannelMetadata(source.host, channelId) : null;
    const instanceMeta = await fetchInstanceMetadata(source.host);

    return {
      title: (data.name as string | undefined) ?? (data.title as string | undefined) ?? "",
      channelName: channelName || channelMeta?.displayName || channelMeta?.channelName || "",
      channelUrl: channelMeta?.channelUrl || channelUrl,
      channelAvatarUrl: channelAvatarUrl || channelMeta?.avatarUrl || "",
      subscribersCount: channelMeta?.followersCount ?? null,
      instanceName: instanceMeta?.name ?? source.host,
      instanceUrl: instanceMeta?.url ?? `https://${source.host}`,
      instanceAvatarUrl: instanceMeta?.avatarUrl ?? "",
      accountName,
      accountUrl,
      accountAvatarUrl,
      embedUrl,
      originalUrl,
      views: normalizeNumber(data.views ?? data.viewsCount),
      likes: normalizeNumber(data.likes ?? data.likesCount),
      dislikes: normalizeNumber(data.dislikes ?? data.dislikesCount),
      description: (data.description as string | undefined) ?? "",
      publishedAt
    };
  } catch {
    return null;
  }
}

/**
 * Handle fetch channel metadata.
 */
async function fetchChannelMetadata(host: string, channelId: string) {
  try {
    const url = `https://${host}/api/v1/video-channels/${encodeURIComponent(channelId)}`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    return {
      followersCount: normalizeNumber(
        data.followersCount ?? data.followers_count ?? data.followers
      ),
      avatarUrl: resolvePeerTubeAvatarUrl(host, data) ?? "",
      displayName: (data.displayName as string | undefined) ?? (data.display_name as string | undefined) ?? "",
      channelName: (data.name as string | undefined) ?? channelId,
      channelUrl:
        (data.url as string | undefined) ??
        `https://${host}/video-channels/${encodeURIComponent(channelId)}`
    };
  } catch {
    return null;
  }
}

/**
 * Handle fetch instance metadata.
 */
async function fetchInstanceMetadata(host: string) {
  try {
    const url = `https://${host}/api/v1/config`;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const data = (await response.json()) as Record<string, unknown>;
    const customization = data.customization as Record<string, unknown> | undefined;
    const instance = (data.instance ?? customization?.instance ?? {}) as Record<string, unknown>;
    const branding = (data.branding ?? customization?.branding ?? {}) as Record<string, unknown>;
    const name =
      (getString(instance, ["name", "title", "displayName"]) as string) ??
      (getString(data, ["name", "title"]) as string) ??
      host;
    const avatarUrl =
      resolveAssetCandidate(host, branding.smallLogo) ||
      resolveAssetCandidate(host, branding.logo) ||
      resolveAssetCandidate(host, branding.favicon) ||
      resolveAssetCandidate(host, branding.icon) ||
      resolveAssetCandidate(host, (branding as Record<string, unknown>).small_logo) ||
      resolveAssetCandidate(host, (branding as Record<string, unknown>).logo_url) ||
      resolveAssetCandidate(host, (branding as Record<string, unknown>).favicon_url) ||
      resolveAssetCandidate(host, instance.logo) ||
      resolveAssetCandidate(host, instance.avatars) ||
      resolveAssetCandidate(host, instance.avatar) ||
      `https://${host}/favicon.ico`;
    return {
      name,
      url: `https://${host}`,
      avatarUrl
    };
  } catch {
    return null;
  }
}

/**
 * Handle resolve video source.
 */
function resolveVideoSource() {
  const urlCandidates = [fallback.url, fallback.embed].filter(Boolean);
  const parsed = urlCandidates.map((item) => parseVideoUrl(item)).find((item) => item?.host);
  const host = seedHost ?? parsed?.host ?? "";
  const id = seedId ?? parsed?.id ?? "";
  const url = fallback.url || parsed?.url || "";
  if (!host && !id) return null;
  return { host, id, url };
}

/**
 * Handle parse video url.
 */
function parseVideoUrl(value: string) {
  if (!value) return null;
  try {
    const url = new URL(value);
    const match = url.pathname.match(/\/(?:videos\/watch|videos\/embed|w)\/([^/?#]+)/);
    return {
      host: url.host,
      id: match ? match[1] : "",
      url: value
    };
  } catch {
    return null;
  }
}

/**
 * Handle get string.
 */
function getString(source: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "";
}

/**
 * Handle resolve asset candidate.
 */
function resolveAssetCandidate(host: string, value: unknown) {
  if (!value) return "";
  if (typeof value === "string") return resolveApiAssetUrl(host, value);
  if (Array.isArray(value)) {
    for (const item of value) {
      const resolved = resolveAssetCandidate(host, item);
      if (resolved) return resolved;
    }
    return "";
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const path = (obj.path ?? obj.url ?? obj.fileUrl) as string | undefined;
    if (path) return resolveApiAssetUrl(host, path);
  }
  return "";
}

/**
 * Handle resolve peer tube avatar url.
 */
function resolvePeerTubeAvatarUrl(host: string, source: Record<string, unknown>) {
  const avatar = (source.avatar ?? source.channelAvatar ?? source.accountAvatar) as
    | Record<string, unknown>
    | undefined;
  const avatars = (source.avatars ?? source.channelAvatars ?? source.accountAvatars) as
    | Array<Record<string, unknown>>
    | undefined;
  const path =
    (avatar?.path as string | undefined) ??
    (avatar?.url as string | undefined) ??
    (avatars?.[0]?.path as string | undefined) ??
    (avatars?.[0]?.url as string | undefined) ??
    "";
  return path ? resolveApiAssetUrl(host, path) : "";
}

/**
 * Handle resolve api asset url.
 */
function resolveApiAssetUrl(host: string, value: string) {
  if (!value) return "";
  if (value.startsWith("http")) return value;
  return `https://${host}${value.startsWith("/") ? value : `/${value}`}`;
}

/**
 * Handle instance initials.
 */
function instanceInitials(label: string) {
  const trimmed = label.trim();
  if (!trimmed) return "•";
  const cleaned = trimmed.replace(/[_\-]+/g, " ").replace(/\s+/g, " ").trim();
  const parts = cleaned.split(" ").filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

/**
 * Handle normalize timestamp ms.
 */
function normalizeTimestampMs(value: unknown) {
  if (value == null) return null;
  const raw = Number(value);
  if (!Number.isFinite(raw)) return null;
  if (raw < 1e12) return raw * 1000;
  return raw;
}

/**
 * Handle published at ms.
 */
function publishedAtMs(row: VideoRow) {
  const value = row.published_at ?? row.publishedAt ?? null;
  return normalizeTimestampMs(value);
}

/**
 * Handle normalize number.
 */
function normalizeNumber(value: unknown) {
  if (value == null) return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

/**
 * Handle format time ago.
 */
function formatTimeAgo(timestampMs: number) {
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
 * Handle format stat value.
 */
function formatStatValue(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--";
  return statsNumberFormat.format(value);
}

/**
 * Handle normalize stat value.
 */
function normalizeStatValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

/**
 * Handle resolve similar key.
 */
function resolveSimilarKey(row: VideoRow) {
  const host = row.instance_domain ?? row.instanceDomain ?? "";
  const id = row.video_uuid ?? row.videoUuid ?? row.video_id ?? "";
  if (!host || !id) return null;
  return `${host}::${id}`;
}

/**
 * Handle resolve similar stats.
 */
function resolveSimilarStats(row: VideoRow) {
  const key = resolveSimilarKey(row);
  if (!key) return null;
  if (similarStatsCache.has(key)) {
    return similarStatsCache.get(key) ?? null;
  }
  return normalizeStatValue(row.views ?? row.views_count ?? row.viewsCount) ?? null;
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
 * Handle queue similar stats.
 */
function queueSimilarStats(rows: VideoRow[]) {
  if (!rows.length) return;
  const groups = new Map<string, { key: string; id: string }[]>();

  for (const row of rows) {
    const host = row.instance_domain ?? row.instanceDomain ?? "";
    const id = String(row.video_uuid ?? row.videoUuid ?? row.video_id ?? "");
    if (!host || !id) continue;
    const key = `${host}::${id}`;
    if (hasServerStats(row)) {
      if (!similarStatsCache.has(key)) {
        const views = normalizeStatValue(row.views ?? row.views_count ?? row.viewsCount);
        similarStatsCache.set(key, views ?? null);
      }
      continue;
    }
    if (similarStatsCache.has(key)) continue;
    if (similarStatsLoading.has(key)) continue;
    similarStatsLoading.add(key);
    const batch = groups.get(host) ?? [];
    batch.push({ key, id });
    groups.set(host, batch);
  }

  for (const [host, entries] of groups) {
    void fetchSimilarStatsForHost(host, entries);
  }
}

/**
 * Handle fetch similar stats for host.
 */
async function fetchSimilarStatsForHost(host: string, entries: { key: string; id: string }[]) {
  const ids = entries.map((entry) => entry.id);
  try {
    const statsById = await fetchBatchViews(host, ids);
    const missing: { key: string; id: string }[] = [];
    for (const entry of entries) {
      if (!statsById.has(entry.id)) {
        missing.push(entry);
        continue;
      }
      const views = statsById.get(entry.id) ?? null;
      similarStatsCache.set(entry.key, views);
      similarStatsLoading.delete(entry.key);
      applySimilarStatsToDom(entry.key, views);
    }
    if (missing.length) {
      await fetchViewsIndividually(host, missing);
    }
  } catch {
    await fetchViewsIndividually(host, entries);
  }
}

/**
 * Handle fetch views individually.
 */
async function fetchViewsIndividually(host: string, entries: { key: string; id: string }[]) {
  await Promise.all(
    entries.map(async (entry) => {
      try {
        const views = await fetchSingleViews(host, entry.id);
        similarStatsCache.set(entry.key, views);
        applySimilarStatsToDom(entry.key, views);
      } finally {
        similarStatsLoading.delete(entry.key);
      }
    })
  );
}

/**
 * Handle fetch batch views.
 */
async function fetchBatchViews(host: string, ids: string[]) {
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
  const stats = new Map<string, number | null>();
  for (const item of data) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const uuid = record.uuid ?? record.video_uuid ?? record.videoUuid;
    const id = record.id ?? record.video_id ?? record.videoId;
    const views = normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
    if (uuid) stats.set(String(uuid), views);
    if (id) stats.set(String(id), views);
  }
  return stats;
}

/**
 * Handle fetch single views.
 */
async function fetchSingleViews(host: string, id: string) {
  const url = `https://${host}/api/v1/videos/${encodeURIComponent(id)}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) return null;
  const record = (await response.json()) as Record<string, unknown>;
  return normalizeStatValue(record.views ?? record.viewsCount ?? record.views_count);
}

/**
 * Handle apply similar stats to dom.
 */
function applySimilarStatsToDom(key: string, views: number | null) {
  if (!similarCards) return;
  const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(key) : key;
  const card = similarCards.querySelector<HTMLElement>(`[data-video-key="${escaped}"]`);
  if (!card) return;
  const viewsEl = card.querySelector<HTMLElement>('[data-stat="views"]');
  if (viewsEl) viewsEl.textContent = formatStatValue(views);
}

/**
 * Handle embed url for.
 */
function embedUrlFor(row: VideoRow | null) {
  if (!row) return "";
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
 * Handle video url for.
 */
function videoUrlFor(row: VideoRow | null) {
  if (!row) return "";
  if (row.video_url) return row.video_url;
  if (row.videoUrl) return row.videoUrl;
  const uuid = row.video_uuid;
  const host = row.instance_domain ?? row.instanceDomain;
  if (uuid && host) {
    return `https://${host}/videos/watch/${encodeURIComponent(uuid)}`;
  }
  return "";
}

/**
 * Handle video page url.
 */
function videoPageUrl(row: VideoRow) {
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
  const channelHref = channelUrlFor(row);
  if (channelHref) params.set("channelUrl", channelHref);
  const embed = embedUrlFor(row);
  if (embed) params.set("embed", embed);
  const original = videoUrlFor(row);
  if (original) params.set("url", original);
  return `/video-page.html?${params.toString()}`;
}

/**
 * Handle thumbnail url.
 */
function thumbnailUrl(row: VideoRow) {
  return row.thumbnail_url ?? row.thumbnailUrl ?? row.preview_path ?? row.previewPath ?? null;
}

/**
 * Handle render similar card.
 */
function renderSimilarCard(row: VideoRow) {
  const title = row.title ?? "Untitled video";
  const thumb = thumbnailUrl(row);
  const duration = formatDuration(row.duration ?? null);
  const channel = channelName(row) ?? "Unknown channel";
  const key = resolveSimilarKey(row);
  const views = resolveSimilarStats(row);
  const publishedAt = publishedAtMs(row);
  const timeAgo = publishedAt ? formatTimeAgo(publishedAt) : null;
  const timeSuffix = timeAgo ? ` · ${timeAgo}` : "";
  const thumbMarkup = thumb
    ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
    : "";
  const keyAttribute = key ? ` data-video-key="${escapeHtml(key)}"` : "";
  const reaction = cardReaction(row);
  const reactionMarkup =
    reaction === "liked"
      ? `<span class="similar-reaction">${iconThumbUp()}Liked</span>`
      : reaction === "disliked"
        ? `<span class="similar-reaction">${iconThumbDown()}Disliked</span>`
        : "";
  return `
    <div class="similar-card-item"${keyAttribute}>
      <a class="similar-card-link" href="${escapeHtml(videoPageUrl(row))}">
        <div class="similar-thumb">
          ${thumbMarkup}
          <span class="duration">${escapeHtml(duration)}</span>
        </div>
        <h4 class="similar-title">${escapeHtml(title)}</h4>
        <p class="similar-channel">${escapeHtml(channel)}</p>
        <p class="similar-meta"><span data-stat="views">${formatStatValue(views)}</span> views${escapeHtml(timeSuffix)}</p>
        ${reactionMarkup}
      </a>
      ${renderTagChips(row.tags, params.get("api"))}
    </div>
  `;
}

/**
 * Handle format duration.
 */
function formatDuration(value: number | null) {
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
 * Handle resolve like uuid.
 */
function resolveLikeUuid(id: string, metadata: VideoMetadata | null) {
  const candidate = metadata?.videoUuid ?? "";
  if (candidate) return candidate;
  return looksLikeUuid(id) ? id : "";
}

/**
 * Handle resolve like host.
 */
function resolveLikeHost(hostParam: string | null, metadata: VideoMetadata | null) {
  const host = hostParam?.trim();
  if (host) return host;
  const metaHost = metadata?.instanceName?.trim();
  if (metaHost) return metaHost;
  return "";
}

/**
 * Handle looks like uuid.
 */
function looksLikeUuid(value: string) {
  return /^[0-9a-fA-F-]{32,36}$/.test(value);
}

/**
 * Handle number format.
 */
function numberFormat() {
  return new Intl.NumberFormat("en-US");
}

/**
 * Handle icon eye.
 */
function iconEye() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="3.2" />
    </svg>
  `;
}

/**
 * Handle icon thumb up.
 */
function iconThumbUp() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 11v9M7 20h7.3a2 2 0 0 0 1.95-1.55l1.7-7A2 2 0 0 0 16 9H12V5a2 2 0 0 0-2-2l-3 6" />
      <rect x="3" y="11" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

/**
 * Handle icon thumb down.
 */
function iconThumbDown() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M7 13V4M7 4h7.3a2 2 0 0 1 1.95 1.55l1.7 7A2 2 0 0 1 16 15h-4v4a2 2 0 0 1-2 2l-3-6" />
      <rect x="3" y="4" width="4" height="9" rx="1.2" />
    </svg>
  `;
}

/**
 * Handle apply action icons.
 */
function applyActionIcons() {
  likeButton?.insertAdjacentHTML("afterbegin", iconThumbUp());
  dislikeButton?.insertAdjacentHTML("afterbegin", iconThumbDown());
}

applyActionIcons();

/**
 * Handle escape html.
 */
function escapeHtml(value: string) {
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
