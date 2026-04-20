import type { EventRecordV2, WorkflowStateViewV2 } from "./schema-v2.js";

export type WorkflowSlotVersionV2 = {
  event_id: string;
  event_fingerprint: string;
  occurred_at: string;
};

export type WorkflowPatchV2 = {
  task_ref: string;
  set: Partial<
    Pick<
      WorkflowStateViewV2,
      | "current_owner_ref"
      | "current_stage"
      | "current_approval_ref"
      | "approval_status"
      | "current_blocker_ref"
      | "next_action_json"
    >
  >;
  slots: Array<
    | "current_owner_ref"
    | "current_stage"
    | "current_approval_ref"
    | "approval_status"
    | "current_blocker_ref"
    | "next_action_json"
  >;
  event: EventRecordV2;
};

function isTaskRef(value: string | null | undefined): value is string {
  return typeof value === "string" && value.startsWith("task:");
}

function asRecordJson(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function taskRefForEvent(event: EventRecordV2): string | null {
  if (isTaskRef(event.subject_ref)) {
    return event.subject_ref;
  }
  if (isTaskRef(event.object_ref)) {
    return event.object_ref;
  }
  try {
    const refs = JSON.parse(event.related_refs_json) as unknown;
    if (Array.isArray(refs)) {
      const match = refs.find(
        (ref): ref is string => typeof ref === "string" && ref.startsWith("task:"),
      );
      if (match) {
        return match;
      }
    }
  } catch {
    // ignore malformed related refs and fall back to payload inspection
  }
  const payload = asRecordJson(event.payload_json);
  return isTaskRef(payload.task_ref) ? payload.task_ref : null;
}

export function deriveWorkflowPatchesV2(events: EventRecordV2[]): WorkflowPatchV2[] {
  const patches: WorkflowPatchV2[] = [];
  for (const event of events) {
    const taskRef = taskRefForEvent(event);
    if (!taskRef) {
      continue;
    }
    const payload = asRecordJson(event.payload_json);
    switch (event.event_type) {
      case "owner_changed":
        patches.push({
          task_ref: taskRef,
          set: {
            current_owner_ref:
              typeof payload.new_owner_ref === "string" ? payload.new_owner_ref : event.object_ref,
          },
          slots: ["current_owner_ref"],
          event,
        });
        break;
      case "stage_changed":
        patches.push({
          task_ref: taskRef,
          set: {
            current_stage: typeof payload.new_stage === "string" ? payload.new_stage : null,
          },
          slots: ["current_stage"],
          event,
        });
        break;
      case "approval_status_updated": {
        const approvalRef =
          typeof payload.approval_ref === "string"
            ? payload.approval_ref
            : typeof event.object_ref === "string" && event.object_ref.startsWith("approval:")
              ? event.object_ref
              : null;
        patches.push({
          task_ref: taskRef,
          set: {
            current_approval_ref: approvalRef,
            approval_status:
              typeof payload.approval_status === "string" ? payload.approval_status : null,
          },
          slots: ["current_approval_ref", "approval_status"],
          event,
        });
        break;
      }
      case "blocked": {
        const blockerRef =
          typeof payload.blocker_ref === "string" ? payload.blocker_ref : event.object_ref;
        const set: WorkflowPatchV2["set"] = {
          current_blocker_ref: blockerRef ?? null,
          current_stage: "blocked",
        };
        const slots: WorkflowPatchV2["slots"] = ["current_blocker_ref", "current_stage"];
        if (typeof blockerRef === "string" && blockerRef.startsWith("approval:")) {
          set.current_approval_ref = blockerRef;
          slots.push("current_approval_ref");
        }
        patches.push({ task_ref: taskRef, set, slots, event });
        break;
      }
      case "unblocked":
        patches.push({
          task_ref: taskRef,
          set: {
            current_blocker_ref: null,
            current_stage:
              typeof payload.resume_stage === "string" ? payload.resume_stage : "in_progress",
          },
          slots: ["current_blocker_ref", "current_stage"],
          event,
        });
        break;
      case "next_action_set":
        patches.push({
          task_ref: taskRef,
          set: {
            next_action_json: JSON.stringify({
              assignee_ref: typeof payload.assignee_ref === "string" ? payload.assignee_ref : null,
              action_text: typeof payload.action_text === "string" ? payload.action_text : null,
            }),
          },
          slots: ["next_action_json"],
          event,
        });
        break;
      default:
        break;
    }
  }
  return patches;
}
