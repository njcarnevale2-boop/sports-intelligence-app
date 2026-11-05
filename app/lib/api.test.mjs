import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { buildApiUrl, fetchJson } from "./api.ts";

test("buildApiUrl keeps backend calls on the website origin", () => {
  assert.equal(buildApiUrl("api/games?week=8"), "/api/games?week=8");
});

test("Home requires current projections and explicit publication for Official cards", () => {
  const source = readFileSync(new URL("../page.tsx", import.meta.url), "utf8");
  assert.match(source, /const officialPublished = String\(board\?\.officialPublicationStatus \|\| ""\)\.toUpperCase\(\) === "PUBLISHED"/);
  assert.match(source, /const items = projectionCurrent && officialPublished \? board\?\.decisionBoard \|\| \[\] : \[\]/);
  assert.match(source, /const approved = projectionCurrent && officialPublished && decision\?\.status === "APPROVED"/);
});

test("Games loads the canonical week before the filtered slate and keeps missing projections pending", () => {
  const source = readFileSync(new URL("../games/page.tsx", import.meta.url), "utf8");
  assert.match(source, /\/api\/decision-board\?weekOnly=true/);
  assert.match(source, /q\.set\("week", String\(week\)\)/);
  assert.doesNotMatch(source, /fetchJson<GamesResponse>\(\s*["`]\/api\/games["`]/);
  assert.match(source, /if \(!projectionCurrent\) return "PROJECTION PENDING"/);
});

test("fetchJson keeps the timeout active while reading a successful JSON body", async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  withWindow();
  let abortRequest;
  let timeoutClearedBeforeBody = false;
  let bodyFinished = false;
  globalThis.window.setTimeout = (callback) => {
    abortRequest = callback;
    return 1;
  };
  globalThis.window.clearTimeout = () => {
    timeoutClearedBeforeBody = !bodyFinished;
  };
  globalThis.fetch = async (_input, init) => ({
    status: 200,
    ok: true,
    headers: new Headers({ "content-type": "application/json" }),
    json: () => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => {
        bodyFinished = true;
        reject(new DOMException("Body aborted", "AbortError"));
      });
      queueMicrotask(abortRequest);
    }),
  });
  try {
    await assert.rejects(() => fetchJson("/api/games"), /Request timed out/);
    assert.equal(timeoutClearedBeforeBody, false);
  } finally {
    restoreGlobals(originalWindow, originalFetch);
  }
});

function withWindow() {
  const storage = new Map();
  globalThis.window = {
    setTimeout,
    clearTimeout,
    location: { pathname: "/" },
    localStorage: {
      getItem: (key) => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    },
  };
}

function restoreGlobals(originalWindow, originalFetch) {
  globalThis.window = originalWindow;
  globalThis.fetch = originalFetch;
}

test("fetchJson preserves safe backend detail for 400 errors", async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;

  withWindow();
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "Model spread context is unavailable for this game." }), {
      status: 400,
      headers: { "content-type": "application/json" },
    });

  try {
    await assert.rejects(
      () => fetchJson("/api/move-the-line"),
      /Model spread context is unavailable for this game\./,
    );
  } finally {
    restoreGlobals(originalWindow, originalFetch);
  }
});

test("fetchJson falls back when backend detail is unsafe", async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;

  withWindow();
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ detail: "Traceback (most recent call last):\nFile \"/Users/dev/app.py\"" }),
      {
        status: 400,
        headers: { "content-type": "application/json" },
      },
    );

  try {
    await assert.rejects(
      () => fetchJson("/api/move-the-line"),
      /Request failed \(400\)/,
    );
  } finally {
    restoreGlobals(originalWindow, originalFetch);
  }
});

test("fetchJson falls back when backend detail is missing", async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;

  withWindow();
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ errorCode: "MOVE_LINE_400" }), {
      status: 400,
      headers: { "content-type": "application/json" },
    });

  try {
    await assert.rejects(
      () => fetchJson("/api/move-the-line"),
      /Request failed \(400\)/,
    );
  } finally {
    restoreGlobals(originalWindow, originalFetch);
  }
});

test("fetchJson returns successful JSON payload unchanged", async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;

  withWindow();
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ ok: true, value: 7 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  try {
    const payload = await fetchJson("/api/test-success");
    assert.deepEqual(payload, { ok: true, value: 7 });
  } finally {
    restoreGlobals(originalWindow, originalFetch);
  }
});
