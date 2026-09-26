/**
 * Module `client/frontend/src/components/key-rejected.ts`: the notice shown when the server
 * refuses this browser's profile key, with the control that forgets it.
 */

import { forgetProfileKey } from "../data/profile";

/**
 * Build the notice. `onForget` runs after the key is dropped, e.g. to reload what failed.
 */
export function keyRejectedNotice(onForget: () => void): HTMLElement {
  const notice = document.createElement("div");
  notice.className = "error key-rejected";
  const text = document.createElement("p");
  text.textContent =
    "Your profile key is no longer valid: it was rotated or its profile was deleted in another browser. Forget it here to browse without it, or paste the current key in the Profile window.";
  const forget = document.createElement("button");
  forget.type = "button";
  forget.className = "ghost-button";
  forget.textContent = "Forget key";
  forget.addEventListener("click", () => {
    forgetProfileKey();
    onForget();
  });
  notice.append(text, forget);
  return notice;
}
