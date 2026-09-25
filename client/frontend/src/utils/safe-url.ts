/**
 * Module `client/frontend/src/utils/safe-url.ts`: scheme validation for URL values
 * that originate outside the application (crawled instance data, URL parameters).
 */

/**
 * Return `value` only when it is an absolute `http`/`https` URL, otherwise `"#"`.
 *
 * Escaping alone does not make a URL sink safe: `escapeHtml` leaves a
 * `javascript:` scheme intact, and a navigation to such a URL executes script in
 * the application origin. Every `href`/`src` assignment fed by remote or
 * user-controlled data must pass through here.
 *
 * @param value Candidate URL from crawled data, API responses, or query parameters.
 * @returns The original URL when the scheme is allowed, `"#"` otherwise.
 */
export function safeExternalUrl(value: string | null | undefined): string {
  if (!value) return "#";
  return /^https?:\/\//i.test(value.trim()) ? value : "#";
}
