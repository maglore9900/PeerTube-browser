/**
 * Module `engine/crawler/src/host-filters.ts`: provide runtime functionality.
 */
import fs from "node:fs";
/**
 * Handle load hosts from file.
 */
export function loadHostsFromFile(filePath) {
    const hosts = new Set();
    if (!filePath)
        return hosts;
    const raw = fs.readFileSync(filePath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#"))
            continue;
        const host = normalizeHostToken(trimmed);
        if (host)
            hosts.add(host);
    }
    return hosts;
}
/**
 * Handle filter hosts.
 */
export function filterHosts(hosts, excluded) {
    if (excluded.size === 0)
        return hosts;
    return hosts.filter((host) => !excluded.has(host.toLowerCase()));
}
/**
 * Maximum stored length for short remote text fields (display names, titles).
 *
 * Remote instances choose these strings freely. An over-long repetitive value is not a
 * display problem but a cost one: it makes every later `LIKE` scan over the column
 * disproportionately expensive for whoever searches.
 */
export const MAX_TEXT_FIELD_LENGTH = 200;
/**
 * Return `value` as a trimmed string capped at `maxLength`, or null when unusable.
 *
 * @param value Candidate text from a remote PeerTube API response.
 * @param maxLength Maximum number of characters to keep.
 * @returns The bounded string, or null when the value is not a non-empty string.
 */
export function toBoundedString(value, maxLength = MAX_TEXT_FIELD_LENGTH) {
    if (typeof value !== "string")
        return null;
    const trimmed = value.trim();
    if (!trimmed)
        return null;
    return trimmed.length > maxLength ? trimmed.slice(0, maxLength) : trimmed;
}
/**
 * Return `value` only when it is an absolute http(s) URL, otherwise null.
 *
 * Remote instances control these strings and the frontend puts them in `href`/`src`
 * attributes. Rejecting other schemes at ingest keeps `javascript:` and `data:` URLs
 * out of the database entirely, rather than relying on every render path to re-check.
 *
 * @param value Candidate URL from a remote PeerTube API response.
 * @returns The URL when its scheme is http or https, otherwise null.
 */
export function toHttpUrlOrNull(value) {
    if (typeof value !== "string")
        return null;
    const raw = value.trim();
    if (!raw)
        return null;
    try {
        const parsed = new URL(raw);
        return parsed.protocol === "http:" || parsed.protocol === "https:" ? raw : null;
    }
    catch {
        return null;
    }
}
/**
 * Handle normalize host token.
 */
export function normalizeHostToken(value) {
    const raw = value.trim().toLowerCase();
    if (!raw)
        return null;
    try {
        if (raw.startsWith("http://") || raw.startsWith("https://")) {
            const host = new URL(raw).hostname.toLowerCase();
            return host || null;
        }
        if (raw.includes("/")) {
            const host = new URL(`https://${raw}`).hostname.toLowerCase();
            return host || null;
        }
        return raw.replace(/^\.+|\.+$/g, "") || null;
    }
    catch {
        return null;
    }
}
