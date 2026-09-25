/**
 * Check for task 73: toHttpUrlOrNull rejects non-http(s) URLs at crawl ingest.
 *
 * Run: node engine/crawler/test-url-safety.mjs
 */

import { toHttpUrlOrNull } from "./dist/host-filters.js";

const cases = [
  ["https://peertube.example/video-channels/news", "https://peertube.example/video-channels/news"],
  ["http://peertube.example/c/news", "http://peertube.example/c/news"],
  ["  https://peertube.example/x  ", "https://peertube.example/x"],
  ["javascript:alert(document.domain)", null],
  ["JavaScript:alert(1)", null],
  ["data:text/html,<script>alert(1)</script>", null],
  ["vbscript:msgbox(1)", null],
  ["file:///etc/passwd", null],
  ["//evil.example/x", null],
  ["not a url", null],
  ["", null],
  [null, null],
  [undefined, null],
  [42, null]
];

let failures = 0;
for (const [input, expected] of cases) {
  const actual = toHttpUrlOrNull(input);
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`  ${ok ? "PASS" : "FAIL"} ${JSON.stringify(input)} -> ${JSON.stringify(actual)}`);
}

if (failures > 0) {
  console.log(`\nFAILED: ${failures} case(s)`);
  process.exit(1);
}
console.log("\nAll cases passed.");
