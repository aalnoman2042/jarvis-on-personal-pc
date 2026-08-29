/* The wake word matcher, checked without a browser.
 *
 * `web/src/lib/wakeword.ts` imports nothing, which is what makes this possible:
 * tsc compiles that one file to a temp directory and node runs the result. No
 * test framework, no jsdom, no new dependency in package.json.
 *
 * The half that matters is the REFUSALS. A missed wake word is mildly annoying
 * and you say it again; a false one takes a sentence you said to somebody else
 * and hands it to something that can open applications and shut the machine
 * down. So the words it must not accept are pinned here, and anyone widening
 * the tolerance has to come through this file to do it.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = mkdtempSync(join(tmpdir(), "vondo-wake-"));

let passed = 0;
let failed = 0;

function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) {
    passed++;
    console.log(`  [ok  ] ${label}`);
  } else {
    failed++;
    console.log(`  [FAIL] ${label}: ${JSON.stringify(got)} != ${JSON.stringify(want)}`);
  }
}

// tsc's own entry point, run by this node. Not `npx`, which on Windows is a
// .cmd that spawnSync refuses outright (EINVAL) unless a shell is involved —
// and a shell is a thing worth not involving.
execFileSync(
  process.execPath,
  [join(ROOT, "web/node_modules/typescript/bin/tsc"),
   join(ROOT, "web/src/lib/wakeword.ts"),
   "--outDir", out, "--target", "es2020", "--module", "es2020"],
  { stdio: "pipe" },
);

const { wake, nearMiss, distance } =
  await import(pathToFileURL(join(out, "wakeword.js")).href);

console.log("\n=== 1. it wakes when it should ===");
check("plainly", wake("jarvis what is on today")?.command, "what is on today");
check("  with punctuation", wake("Jarvis, what's on today?")?.command,
      "what's on today");
check("  mid-sentence", wake("ok so jarvis open chrome")?.command, "open chrome");
check("  said on its own, opening the window",
      wake("jarvis"), { command: "", heard: "jarvis" });

console.log("\n=== 2. and when it is misheard, which is most of the time ===");
for (const heard of ["jervis", "javis", "jarvus", "harvis", "darvis", "jarves",
                     "jarviss", "charvis"]) {
  check(`  "${heard}"`, wake(`${heard} what is on today`)?.command,
        "what is on today");
}

console.log("\n=== 3. and NOT for real words somebody might actually say ===");
// These are the dangerous ones: ordinary English, and exactly what a recogniser
// offers when it is unsure. Waking on them is worse than having no wake word.
for (const word of ["service", "harvest", "services", "harvesting", "java",
                    "javascript", "carbon", "arrives", "marvels", "traverse",
                    "jarring", "starving"]) {
  check(`  "${word}" does not wake it`, wake(`the ${word} was fine`), null);
}

console.log("\n=== 4. the command is the rest of the same breath ===");
check("nothing after it means nothing to do",
      wake("hey jarvis")?.command, "");
check("only the FIRST match counts",
      wake("jarvis ask jarvis about jarvis")?.command, "ask jarvis about jarvis");
check("a short word is never the wake word", wake("jar of jam"), null);
check("silence is not a wake", wake(""), null);
check("  nor is punctuation", wake("... ?"), null);

console.log("\n=== 5. near misses are recorded, not acted on ===");
check("something close is worth keeping", nearMiss("the service was fine"),
      "service");
check("  and so is this one", nearMiss("a good harvest"), "harvest");
check("a word that woke it is not a near miss", nearMiss("jarvis hello"), "");
check("something unrelated is not either", nearMiss("the weather is nice"), "");
// The bug this pins: a capped early exit returning a fixed number meant every
// long word came back as "close", so ordinary speech logged as almost-Jarvis.
check("  and neither is a long word", nearMiss("extraordinarily complicated"), "");
check("  distance respects the cap it is given",
      distance("extraordinarily", "jarvis", 4) > 4, true);

rmSync(out, { recursive: true, force: true });
console.log(`\n${"=".repeat(52)}\n  ${passed} passed, ${failed} failed\n${"=".repeat(52)}`);
process.exit(failed ? 1 : 0);
