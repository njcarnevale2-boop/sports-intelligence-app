export type OfficialPreviewLike = {
  snapshotId?: unknown;
};

export type OfficialPublishWorkflowState = {
  previewSnapshotId: string | null;
  publishInFlight: boolean;
  publishedSnapshotId: string | null;
};

export function createOfficialPublishWorkflowState(): OfficialPublishWorkflowState {
  return {
    previewSnapshotId: null,
    publishInFlight: false,
    publishedSnapshotId: null,
  };
}

function _valid_snapshot_id(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function applyOfficialPreview(
  state: OfficialPublishWorkflowState,
  preview: OfficialPreviewLike,
): OfficialPublishWorkflowState {
  const nextSnapshotId = _valid_snapshot_id(preview?.snapshotId) ? preview.snapshotId : null;
  return {
    ...state,
    previewSnapshotId: nextSnapshotId,
    publishInFlight: false,
  };
}

export function clearOfficialPreview(
  state: OfficialPublishWorkflowState,
): OfficialPublishWorkflowState {
  return {
    ...state,
    previewSnapshotId: null,
    publishInFlight: false,
  };
}

export function canPublishOfficialFromWorkflow(
  state: OfficialPublishWorkflowState,
): boolean {
  if (state.publishInFlight) {
    return false;
  }
  if (!state.previewSnapshotId) {
    return false;
  }
  if (state.publishedSnapshotId && state.publishedSnapshotId === state.previewSnapshotId) {
    return false;
  }
  return true;
}

export function beginOfficialPublish(
  state: OfficialPublishWorkflowState,
): { allowed: true; state: OfficialPublishWorkflowState } | { allowed: false; reason: string; state: OfficialPublishWorkflowState } {
  if (state.publishInFlight) {
    return {
      allowed: false,
      reason: "Publication already in flight.",
      state,
    };
  }

  if (!state.previewSnapshotId) {
    return {
      allowed: false,
      reason: "Preview Official SIA 3 first so a valid snapshot can be published.",
      state,
    };
  }

  if (state.publishedSnapshotId && state.publishedSnapshotId === state.previewSnapshotId) {
    return {
      allowed: false,
      reason: "This preview has already been published. Run Preview Official SIA 3 again before publishing.",
      state,
    };
  }

  return {
    allowed: true,
    state: {
      ...state,
      publishInFlight: true,
    },
  };
}

export function markOfficialPublishSucceeded(
  state: OfficialPublishWorkflowState,
): OfficialPublishWorkflowState {
  return {
    ...state,
    publishInFlight: false,
    publishedSnapshotId: state.previewSnapshotId,
  };
}

export function markOfficialPublishFailed(
  state: OfficialPublishWorkflowState,
): OfficialPublishWorkflowState {
  return {
    ...state,
    publishInFlight: false,
  };
}

export function buildOfficialPublishRequestBody(
  state: OfficialPublishWorkflowState,
): { snapshotId: string } | null {
  if (!state.previewSnapshotId) {
    return null;
  }
  return {
    snapshotId: state.previewSnapshotId,
  };
}

export function toOfficialPublishFailureMessage(raw: string): string {
  const text = String(raw || "");
  const lower = text.toLowerCase();
  const snapshotMismatch =
    lower.includes("snapshot")
    && (lower.includes("stale") || lower.includes("refresh preview") || lower.includes("no opportunity snapshot"));

  if (snapshotMismatch) {
    return "Publish blocked: preview snapshot is no longer current. Run Preview Official SIA 3 again, then publish.";
  }

  return text || "Publish failed";
}