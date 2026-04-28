export type TaskScopeValue = "recent" | "session";
export type TaskSourceValue = "all" | "gateway" | "cron";
export type TaskStatusValue =
  | "all"
  | "ingested"
  | "classified"
  | "planned"
  | "context_prepared"
  | "executing"
  | "verified"
  | "persisted"
  | "succeeded"
  | "failed"
  | "blocked";

export interface TaskFilters {
  scope: TaskScopeValue;
  sessionId: string;
  source: TaskSourceValue;
  status: TaskStatusValue;
  taskType: string;
  limit: number;
}

export interface TaskQueryState {
  filters: TaskFilters;
  offset: number;
  taskId: string | null;
}

export const DEFAULT_TASK_FILTERS: TaskFilters = {
  scope: "recent",
  sessionId: "",
  source: "all",
  status: "all",
  taskType: "",
  limit: 20,
};

const VALID_SOURCES = new Set<TaskSourceValue>(["all", "gateway", "cron"]);
const VALID_STATUSES = new Set<TaskStatusValue>([
  "all",
  "ingested",
  "classified",
  "planned",
  "context_prepared",
  "executing",
  "verified",
  "persisted",
  "succeeded",
  "failed",
  "blocked",
]);
const VALID_LIMITS = new Set([10, 20, 50]);

function parseOffset(rawValue: string | null): number {
  if (!rawValue) return 0;
  const parsed = Number.parseInt(rawValue, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

export function parseTaskQueryState(searchParams: URLSearchParams): TaskQueryState {
  const scope =
    searchParams.get("scope") === "session"
      ? "session"
      : DEFAULT_TASK_FILTERS.scope;
  const source = searchParams.get("source") ?? DEFAULT_TASK_FILTERS.source;
  const status = searchParams.get("status") ?? DEFAULT_TASK_FILTERS.status;
  const rawLimit = Number.parseInt(searchParams.get("limit") ?? "", 10);
  const taskId = (searchParams.get("task_id") || "").trim() || null;

  return {
    filters: {
      scope,
      sessionId: (searchParams.get("session_id") || "").trim(),
      source: VALID_SOURCES.has(source as TaskSourceValue)
        ? (source as TaskSourceValue)
        : DEFAULT_TASK_FILTERS.source,
      status: VALID_STATUSES.has(status as TaskStatusValue)
        ? (status as TaskStatusValue)
        : DEFAULT_TASK_FILTERS.status,
      taskType: (searchParams.get("task_type") || "").trim(),
      limit: VALID_LIMITS.has(rawLimit) ? rawLimit : DEFAULT_TASK_FILTERS.limit,
    },
    offset: parseOffset(searchParams.get("offset") ?? searchParams.get("cursor")),
    taskId,
  };
}

export function buildTaskQueryParams(state: TaskQueryState): URLSearchParams {
  const params = new URLSearchParams();
  const { filters, offset, taskId } = state;

  if (filters.scope !== DEFAULT_TASK_FILTERS.scope) {
    params.set("scope", filters.scope);
  }
  if (filters.scope === "session" && filters.sessionId.trim()) {
    params.set("session_id", filters.sessionId.trim());
  }
  if (filters.source !== DEFAULT_TASK_FILTERS.source) {
    params.set("source", filters.source);
  }
  if (filters.status !== DEFAULT_TASK_FILTERS.status) {
    params.set("status", filters.status);
  }
  if (filters.taskType.trim()) {
    params.set("task_type", filters.taskType.trim());
  }
  if (filters.limit !== DEFAULT_TASK_FILTERS.limit) {
    params.set("limit", String(filters.limit));
  }
  if (offset > 0) {
    params.set("offset", String(offset));
  }
  if (taskId) {
    params.set("task_id", taskId);
  }

  return params;
}

export function taskFiltersEqual(left: TaskFilters, right: TaskFilters): boolean {
  return (
    left.scope === right.scope &&
    left.sessionId === right.sessionId &&
    left.source === right.source &&
    left.status === right.status &&
    left.taskType === right.taskType &&
    left.limit === right.limit
  );
}
