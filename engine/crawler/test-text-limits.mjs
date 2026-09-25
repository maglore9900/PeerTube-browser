/**
 * Check for task 76: toBoundedString caps stored remote text at MAX_TEXT_FIELD_LENGTH.
 *
 * Run: node engine/crawler/test-text-limits.mjs
 */

import { MAX_TEXT_FIELD_LENGTH, toBoundedString } from "./dist/host-filters.js";

let failures = 0;

/** Record one assertion outcome. */
function check(name, condition, detail = "") {
  if (condition) {
    console.log(`  PASS ${name}`);
  } else {
    console.log(`  FAIL ${name} ${detail}`);
    failures += 1;
  }
}

console.log(`MAX_TEXT_FIELD_LENGTH = ${MAX_TEXT_FIELD_LENGTH}`);

const ordinary = "PeerTube News";
check("ordinary name unchanged", toBoundedString(ordinary) === ordinary);

const unicode = "中文字幕 会员制餐厅 BLACK HOLE";
check("unicode name unchanged", toBoundedString(unicode) === unicode);

check("whitespace trimmed", toBoundedString("  Daily News  ") === "Daily News");

const hostile = "a".repeat(5000);
const bounded = toBoundedString(hostile);
check(
  "hostile 5000-char name truncated",
  bounded.length === MAX_TEXT_FIELD_LENGTH,
  `got ${bounded.length}`
);

const exact = "b".repeat(MAX_TEXT_FIELD_LENGTH);
check("exactly-at-limit name kept whole", toBoundedString(exact).length === MAX_TEXT_FIELD_LENGTH);

const justOver = "c".repeat(MAX_TEXT_FIELD_LENGTH + 1);
check("one-over-limit truncated", toBoundedString(justOver).length === MAX_TEXT_FIELD_LENGTH);

check("empty string -> null", toBoundedString("") === null);
check("whitespace-only -> null", toBoundedString("   ") === null);
check("null -> null", toBoundedString(null) === null);
check("undefined -> null", toBoundedString(undefined) === null);
check("number -> null", toBoundedString(42) === null);
check("custom limit honoured", toBoundedString("abcdef", 3) === "abc");

if (failures > 0) {
  console.log(`\nFAILED: ${failures} check(s)`);
  process.exit(1);
}
console.log("\nAll checks passed.");
