/**
 * Module `client/frontend/src/about-analytics.ts`: send the About page's analytics events (one page view, one event per tracked outbound click).
 */

import { resolveClientApiBase } from "./data/api-base";

type AnalyticsEvent =
  | { type: "page_view"; page_path: string; timestamp: number }
  | { type: "outbound_click"; track_id: string; href: string; page_path: string; timestamp: number };

/**
 * Handle send analytics event. Never throws and never rejects: analytics must not surface to the visitor.
 */
function sendAnalyticsEvent(event: AnalyticsEvent): void {
  try {
    // No argument, so `?api=` is never read; `new URL` so a base ending in `/` gives no `//api`.
    const url = new URL("/api/analytics/event", resolveClientApiBase()).toString();
    const body = JSON.stringify(event);
    try {
      // Called on `navigator` itself: a detached reference throws "Illegal invocation".
      if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function"
        && navigator.sendBeacon(url, new Blob([body], { type: "application/json" }))) {
        return;
      }
    } catch {
      // A refused cross-origin beacon can throw; fetch gets one more try.
    }
    fetch(url, { method: "POST", body, headers: { "Content-Type": "application/json" }, keepalive: true }).catch(() => undefined);
  } catch {
    // A bad base, a missing fetch or an over-64 KiB keepalive body throws synchronously; analytics stays silent.
  }
}

/**
 * Handle document click: one outbound_click per click that resolves to an `a[data-track-id]`.
 */
function handleDocumentClick(event: Event): void {
  const target = event.target as Element | null;
  // A Text node or the document itself has no `closest`.
  if (!target || typeof target.closest !== "function") {
    return;
  }
  const link = target.closest("a[data-track-id]");
  if (!link) {
    return;
  }
  // An SVG <a>'s `href` is an SVGAnimatedString, which the server would reject, so nothing is sent.
  const href = (link as HTMLAnchorElement).href;
  if (typeof href !== "string") {
    return;
  }
  sendAnalyticsEvent({
    type: "outbound_click",
    track_id: link.getAttribute("data-track-id") ?? "",
    href,
    page_path: window.location.pathname,
    timestamp: Date.now()
  });
}

sendAnalyticsEvent({ type: "page_view", page_path: window.location.pathname, timestamp: Date.now() });
document.addEventListener("click", handleDocumentClick);
