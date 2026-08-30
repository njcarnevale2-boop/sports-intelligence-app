import test from "node:test";
import assert from "node:assert/strict";

import { fetchJson } from "./api.ts";

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
