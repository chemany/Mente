export type MemoryScopeValue = "recent" | "session";
export type MemorySourceValue = "all" | "gateway" | "cron";
export type MemoryFilterScopeValue = "all" | "session" | "task_type" | "global";

export interface MemoryFilters {
  scope: MemoryScopeValue;
  sessionId: string;
  source: MemorySourceValue;
  taskType: string;
  memoryScope: MemoryFilterScopeValue;
  limit: number;
}

export interface MemoryQueryState {
  filters: MemoryFilters;
  offset: number;
  memoryId: string | null;
}

export const DEFAULT_MEMORY_FILTERS: MemoryFilters = {
  scope: "recent",
  sessionId: "",
  source: "all",
  taskType: "",
  memoryScope: "all",
  limit: 20,
};

const VALID_SOURCES = new Set<MemorySourceValue>(["all", "gateway", "cron"]);
const VALID_MEMORY_SCOPES = new Set<MemoryFilterScopeValue>([
  "all",
  "session",
  "task_type",
  "global",
]);
const VALID_LIMITS = new Set([10, 20, 50]);

function parseOffset(rawValue: string | null): number {
  if (!rawValue) return 0;
  const parsed = Number.parseInt(rawValue, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

export function parseMemoryQueryState(searchParams: URLSearchParams): MemoryQueryState {
  const scope =
    searchParams.get("scope") === "session"
      ? "session"
      : DEFAULT_MEMORY_FILTERS.scope;
  const source = searchParams.get("source") ?? DEFAULT_MEMORY_FILTERS.source;
  const memoryScope = searchParams.get("memory_scope") ?? DEFAULT_MEMORY_FILTERS.memoryScope;
  const rawLimit = Number.parseInt(searchParams.get("limit") ?? "", 10);
  const memoryId = (searchParams.get("memory_id") || "").trim() || null;

  return {
    filters: {
      scope,
      sessionId: (searchParams.get("session_id") || "").trim(),
      source: VALID_SOURCES.has(source as MemorySourceValue)
        ? (source as MemorySourceValue)
        : DEFAULT_MEMORY_FILTERS.source,
      taskType: (searchParams.get("task_type") || "").trim(),
      memoryScope: VALID_MEMORY_SCOPES.has(memoryScope as MemoryFilterScopeValue)
        ? (memoryScope as MemoryFilterScopeValue)
        : DEFAULT_MEMORY_FILTERS.memoryScope,
      limit: VALID_LIMITS.has(rawLimit) ? rawLimit : DEFAULT_MEMORY_FILTERS.limit,
    },
    offset: parseOffset(searchParams.get("offset") ?? searchParams.get("cursor")),
    memoryId,
  };
}

export function buildMemoryQueryParams(state: MemoryQueryState): URLSearchParams {
  const params = new URLSearchParams();
  const { filters, offset, memoryId } = state;

  if (filters.scope !== DEFAULT_MEMORY_FILTERS.scope) {
    params.set("scope", filters.scope);
  }
  if (filters.scope === "session" && filters.sessionId.trim()) {
    params.set("session_id", filters.sessionId.trim());
  }
  if (filters.source !== DEFAULT_MEMORY_FILTERS.source) {
    params.set("source", filters.source);
  }
  if (filters.taskType.trim()) {
    params.set("task_type", filters.taskType.trim());
  }
  if (filters.memoryScope !== DEFAULT_MEMORY_FILTERS.memoryScope) {
    params.set("memory_scope", filters.memoryScope);
  }
  if (filters.limit !== DEFAULT_MEMORY_FILTERS.limit) {
    params.set("limit", String(filters.limit));
  }
  if (offset > 0) {
    params.set("offset", String(offset));
  }
  if (memoryId) {
    params.set("memory_id", memoryId);
  }

  return params;
}

export function memoryFiltersEqual(left: MemoryFilters, right: MemoryFilters): boolean {
  return (
    left.scope === right.scope &&
    left.sessionId === right.sessionId &&
    left.source === right.source &&
    left.taskType === right.taskType &&
    left.memoryScope === right.memoryScope &&
    left.limit === right.limit
  );
}
