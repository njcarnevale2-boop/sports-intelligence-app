import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function readWorkspaceFile(relativePath) {
  return readFileSync(resolve(__dirname, "..", relativePath), "utf8");
}

test("home page uses current-bet and model-cushion semantics", () => {
  const page = readWorkspaceFile("page.tsx");

  assert.match(page, /BET RANGE/);
  assert.match(page, /MODEL CUSHION/);
  assert.match(page, /MODEL ADVANTAGE/);
  assert.match(page, /currently observed executable quote/i);
  assert.match(page, /Current Line/);
  assert.doesNotMatch(page, /SIA VS MARKET/);
  assert.doesNotMatch(page, /PROBABILITY EDGE/);
  assert.doesNotMatch(page, /CONFIDENCE\"/);
  assert.doesNotMatch(page, /\{[^\n]*confidence[^\n]*\/100/);
  assert.doesNotMatch(page, /RECOMMENDED TO/);
  assert.doesNotMatch(page, /CURRENT LINE STATUS" value=/);

  const statusHeaderCount = (page.match(/Current Line/g) ?? []).length;
  assert.equal(statusHeaderCount, 2);
  assert.doesNotMatch(page, /SIA \d+\.?\d*% vs market \d+\.?\d*%/i);
  assert.doesNotMatch(page, /\+\d+\.?\d*%/);
  assert.doesNotMatch(page, /playable threshold|official bet through|recommended through/i);
});

test("advanced surfaces label model boundaries as theoretical", () => {
  const gameIntel = readWorkspaceFile("games/[eventId]/page.tsx");
  const opportunity = readWorkspaceFile("opportunities/[id]/page.tsx");

  assert.match(gameIntel, /Theoretical Model Boundary/);
  assert.match(gameIntel, /Research estimate only/);
  assert.doesNotMatch(gameIntel, /Official Bet Through/);

  assert.match(opportunity, /Theoretical Model Boundary/);
  assert.match(opportunity, /Theoretical EV boundary/);
  assert.doesNotMatch(opportunity, /Recommended To/);
});
