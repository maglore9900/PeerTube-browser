/**
 * Module `client/frontend/src/data/blocks.ts`: the profile's channel and account blocks.
 *
 * A block is made from a video the visitor is looking at: the Client backend looks the
 * video up and blocks its channel or its account, so the browser never names either.
 */

import { resolveClientApiBase } from "./api-base";
import { profileHeaders } from "./profile";

export type BlockKind = "channel" | "account";

export interface Block {
  kind: BlockKind;
  instance_domain: string;
  channel_id: string;
  account_url: string;
  label: string;
  created_at?: number;
}

/**
 * Return the profile's blocks, newest first.
 */
export async function listBlocks(apiBase: string): Promise<Block[]> {
  const payload = await request(apiBase, "GET", "/api/profile/blocks");
  return Array.isArray(payload.blocks) ? (payload.blocks as Block[]) : [];
}

/**
 * Block the channel or the account of the video identified by uuid and host.
 */
export async function blockVideoSource(
  apiBase: string,
  kind: BlockKind,
  uuid: string,
  host: string
): Promise<Block> {
  const payload = await request(apiBase, "POST", "/api/profile/blocks", { kind, uuid, host });
  return payload.block as Block;
}

/**
 * Remove one block, as `listBlocks` returned it.
 */
export async function unblock(apiBase: string, block: Block): Promise<void> {
  const { kind, instance_domain, channel_id, account_url } = block;
  await request(apiBase, "POST", "/api/profile/blocks/remove", { kind, instance_domain, channel_id, account_url });
}

async function request(
  apiBase: string,
  method: "GET" | "POST",
  path: string,
  body?: Record<string, string>
): Promise<{ blocks?: unknown; block?: unknown; error?: string }> {
  const response = await fetch(new URL(path, resolveClientApiBase(apiBase)), {
    method,
    headers: { "content-type": "application/json", ...profileHeaders() },
    body: body ? JSON.stringify(body) : undefined
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as { blocks?: unknown; block?: unknown; error?: string }) : {};
  if (!response.ok) {
    throw new Error(payload.error ?? `Block request failed (${response.status})`);
  }
  return payload;
}
