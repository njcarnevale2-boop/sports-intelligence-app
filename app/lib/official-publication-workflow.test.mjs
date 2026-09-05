import test from "node:test";
import assert from "node:assert/strict";

import {
  applyOfficialPreview,
  beginOfficialPublish,
  buildOfficialPublishRequestBody,
  canPublishOfficialFromWorkflow,
  createOfficialPublishWorkflowState,
  markOfficialPublishSucceeded,
  toOfficialPublishFailureMessage,
} from "./official-publication-workflow.ts";

test("publish is disabled before preview", () => {
  const state = createOfficialPublishWorkflowState();
  assert.equal(canPublishOfficialFromWorkflow(state), false);
  assert.equal(buildOfficialPublishRequestBody(state), null);
});

test("preview snapshotId is passed exactly to publish body", () => {
  const state = applyOfficialPreview(createOfficialPublishWorkflowState(), {
    snapshotId: "snap-live-1",
  });

  assert.equal(canPublishOfficialFromWorkflow(state), true);
  assert.deepEqual(buildOfficialPublishRequestBody(state), { snapshotId: "snap-live-1" });
});

test("new preview replaces prior snapshotId", () => {
  const first = applyOfficialPreview(createOfficialPublishWorkflowState(), {
    snapshotId: "snap-old",
  });
  const second = applyOfficialPreview(first, {
    snapshotId: "snap-new",
  });

  assert.deepEqual(buildOfficialPublishRequestBody(second), { snapshotId: "snap-new" });
});

test("missing snapshotId cannot publish", () => {
  const state = applyOfficialPreview(createOfficialPublishWorkflowState(), {
    snapshotId: null,
  });

  assert.equal(canPublishOfficialFromWorkflow(state), false);

  const started = beginOfficialPublish(state);
  assert.equal(started.allowed, false);
  if (!started.allowed) {
    assert.match(started.reason, /Preview Official SIA 3 first/);
  }
});

test("stale or snapshot mismatch does not auto-override", () => {
  const message = toOfficialPublishFailureMessage("Snapshot is stale; refresh preview and publish again");
  assert.match(message, /Preview Official SIA 3 again/);

  const state = applyOfficialPreview(createOfficialPublishWorkflowState(), {
    snapshotId: "snap-live-2",
  });

  assert.deepEqual(buildOfficialPublishRequestBody(state), { snapshotId: "snap-live-2" });
  assert.equal("overrideStaleOdds" in buildOfficialPublishRequestBody(state), false);
  assert.equal("overrideMissingSnapshotLinkage" in buildOfficialPublishRequestBody(state), false);
});

test("double-click/in-flight publication is blocked", () => {
  const state = applyOfficialPreview(createOfficialPublishWorkflowState(), {
    snapshotId: "snap-live-3",
  });

  const first = beginOfficialPublish(state);
  assert.equal(first.allowed, true);

  const second = beginOfficialPublish(first.state);
  assert.equal(second.allowed, false);
  if (!second.allowed) {
    assert.match(second.reason, /in flight/i);
  }
});

test("successful publication does not permit second publication from same preview", () => {
  const state = applyOfficialPreview(createOfficialPublishWorkflowState(), {
    snapshotId: "snap-live-4",
  });

  const started = beginOfficialPublish(state);
  assert.equal(started.allowed, true);

  const published = markOfficialPublishSucceeded(started.state);
  assert.equal(canPublishOfficialFromWorkflow(published), false);

  const blocked = beginOfficialPublish(published);
  assert.equal(blocked.allowed, false);
  if (!blocked.allowed) {
    assert.match(blocked.reason, /already been published/i);
  }
});
