/**
 * Module `client/frontend/src/pages/likes/index.ts`: the page listing the visitor's liked videos.
 *
 * With a profile key the likes are the profile's; without one they are this browser's local
 * likes. Each card can un-like its video, and goes only once the Client accepted that.
 */

import "../../videos.css";
import { channelName, escapeHtml, thumbnailUrl, videoPageUrl } from "../../components/video-card";
import { importLocalLikes, sendReaction } from "../../data/reactions";
import { fetchUserProfileLikes } from "../../data/user-profile";
import type { VideoRow } from "../../types/videos";

function requireElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing likes page element: ${id}`);
  return element;
}

const grid = requireElement("likes-grid");
const status = requireElement("likes-status");

const apiParam = new URLSearchParams(window.location.search).get("api") ?? "";

grid.addEventListener("click", (event) => {
  const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>(".like-remove");
  if (button) void removeLike(button);
});

void loadLikes();

async function loadLikes() {
  status.textContent = "Loading...";
  try {
    // A browser that holds a key hands its local likes to the profile before reading them back.
    await importLocalLikes(apiParam).catch((error) => {
      console.warn("[likes] import failed; the local likes are kept for the next load", error);
    });
    const likes = await fetchUserProfileLikes(apiParam);
    status.textContent = "";
    grid.innerHTML = renderLikes(likes);
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "Could not load your likes";
  }
}

/**
 * Render the liked videos as cards, every remote value escaped.
 */
function renderLikes(likes: VideoRow[]) {
  if (!likes.length) {
    return `<div class="empty">No likes yet.</div>`;
  }
  return likes
    .map((row) => {
      const title = row.title ?? "Untitled";
      const thumb = thumbnailUrl(row);
      const host = row.instance_domain ?? row.instanceDomain ?? "";
      const channel = channelName(row);
      const meta = host ? `${channel} · ${host}` : channel;
      const thumbMarkup = thumb
        ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(title)}" loading="lazy" />`
        : `<div class="thumb-fallback">No preview</div>`;
      const uuid = row.video_uuid ?? row.videoUuid ?? "";
      return `
        <article class="like-card">
          <a class="like-link" href="${escapeHtml(videoPageUrl(row))}">
            <div class="like-thumb">${thumbMarkup}</div>
            <h3 class="like-title">${escapeHtml(title)}</h3>
            <div class="like-meta">${escapeHtml(meta)}</div>
          </a>
          <button class="ghost-button like-remove" type="button" data-uuid="${escapeHtml(uuid)}" data-host="${escapeHtml(host)}">Unlike</button>
          <p class="like-error" role="status"></p>
        </article>
      `;
    })
    .join("");
}

/**
 * Un-like one video from its card; the card goes only once the Client accepted it.
 */
async function removeLike(button: HTMLButtonElement) {
  const card = button.closest<HTMLElement>(".like-card");
  const errorEl = card?.querySelector<HTMLElement>(".like-error");
  const uuid = button.dataset.uuid ?? "";
  const host = button.dataset.host ?? "";
  if (!card || !uuid || !host) return;
  button.disabled = true;
  if (errorEl) errorEl.textContent = "";
  try {
    await sendReaction(apiParam, "undo_like", { uuid, host });
    card.remove();
    if (!grid.querySelector(".like-card")) grid.innerHTML = renderLikes([]);
  } catch (error) {
    if (errorEl) errorEl.textContent = error instanceof Error ? error.message : "Unlike failed";
    button.disabled = false;
  }
}
