/**
 * Module `client/frontend/src/data/profile.ts`: the visitor's profile key.
 *
 * The key is issued by the Client backend, shown to the visitor once, and kept in
 * localStorage. It is the only proof of the profile: there is no account to recover it from.
 */

import { resolveClientApiBase } from "./api-base";

const STORAGE_KEY = "profileKey:v1";

/**
 * The server refused the stored key: it was rotated elsewhere, or the profile was deleted.
 */
export class ProfileKeyRejectedError extends Error {}

/**
 * Return the stored profile key, or null when this browser holds none.
 */
export function getProfileKey(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * Return the header that proves the profile, or no headers without one.
 */
export function profileHeaders(): Record<string, string> {
  const key = getProfileKey();
  return key ? { "x-profile-key": key } : {};
}

/**
 * Keep a key in this browser, e.g. one pasted from another device.
 */
export function storeProfileKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key.trim());
}

/**
 * Drop the stored key, e.g. after the server refused it.
 */
export function forgetProfileKey(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/**
 * Create a profile, keep its key, and return the key for the one-time display.
 */
export async function createProfile(apiBase: string): Promise<string> {
  const payload = await postProfile(apiBase, "/api/profile", {});
  const key = String(payload.key ?? "");
  if (!key) throw new Error("Profile creation returned no key");
  storeProfileKey(key);
  return key;
}

/**
 * Replace the profile's key, keep the new one, and return it for the one-time display.
 */
export async function rotateProfileKey(apiBase: string): Promise<string> {
  const payload = await postProfile(apiBase, "/api/profile/rotate", profileHeaders());
  const key = String(payload.key ?? "");
  if (!key) throw new Error("Key rotation returned no key");
  storeProfileKey(key);
  return key;
}

/**
 * Delete the profile on the server and forget its key here.
 */
export async function deleteProfile(apiBase: string): Promise<void> {
  await postProfile(apiBase, "/api/profile/delete", profileHeaders());
  localStorage.removeItem(STORAGE_KEY);
}

/**
 * POST to a profile route; return the parsed body, or throw the server's error.
 */
async function postProfile(
  apiBase: string,
  path: string,
  headers: Record<string, string>
): Promise<{ key?: string; error?: string }> {
  const response = await fetch(new URL(path, resolveClientApiBase(apiBase)), {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: "{}"
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as { key?: string; error?: string }) : {};
  if (!response.ok) {
    throw new Error(payload.error ?? `Profile request failed (${response.status})`);
  }
  return payload;
}
