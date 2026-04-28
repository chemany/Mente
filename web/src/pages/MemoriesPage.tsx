import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Database,
  RefreshCw,
  Search,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  DebugMemoriesResponse,
  DebugMemory,
  TaskPagination,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { FilterGroup, Segmented } from "@/components/ui/segmented";
import { Select, SelectOption } from "@/components/ui/select";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";
import { cn } from "@/lib/utils";
import {
  buildMemoryQueryParams,
  DEFAULT_MEMORY_FILTERS,
  memoryFiltersEqual,
  parseMemoryQueryState,
  type MemoryFilters,
  type MemoryFilterScopeValue,
  type MemoryScopeValue,
  type MemorySourceValue,
} from "./memories-url-state";

const LIMIT_OPTIONS = [10, 20, 50] as const;

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatTimestamp(value: number): string {
  if (!Number.isFinite(value)) {
    return "unknown";
  }
  return new Date(value * 1000).toISOString();
}

function SmallMeta({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="border border-border bg-background/30 px-3 py-2">
      <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
        {label}
      </div>
      <div className="mt-1 font-courier text-xs text-foreground">{value}</div>
    </div>
  );
}

function MemoryRow({
  memory,
  expanded,
  onToggle,
  detailLabel,
  labels,
}: {
  memory: DebugMemory;
  expanded: boolean;
  onToggle: () => void;
  detailLabel: string;
  labels: {
    sessionId: string;
    taskId: string;
    memoryId: string;
    score: string;
    createdAt: string;
    metadata: string;
    fact: string;
  };
}) {
  return (
    <Card
      className={cn(
        "overflow-hidden border-border bg-background/25 transition-colors",
        expanded && "border-foreground/30 bg-background/35",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-col gap-3 px-4 py-4 text-left transition-colors hover:bg-foreground/5"
      >
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{memory.source}</Badge>
              <Badge variant="secondary">{memory.task_type}</Badge>
              <Badge variant="outline">{memory.scope}</Badge>
              {memory.kind && memory.kind !== "fact" ? (
                <Badge variant="outline">{memory.kind}</Badge>
              ) : null}
              <span className="font-courier text-[11px] text-muted-foreground">
                {memory.memory_id}
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-foreground">
              {memory.fact}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
            <div className="min-w-0 text-right">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase">
                {labels.createdAt}
              </div>
              <div className="mt-1 max-w-[18rem] truncate font-courier text-[11px] text-foreground">
                {formatTimestamp(memory.created_at)}
              </div>
            </div>
            {expanded ? (
              <ChevronUp className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0" />
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          <span>
            {labels.score}: {memory.score}
          </span>
          <span className="truncate">
            {labels.sessionId}: {memory.session_id ?? "none"}
          </span>
          <span className="truncate">
            {labels.taskId}: {memory.task_id}
          </span>
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-border bg-black/15 px-4 py-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <SmallMeta label={labels.memoryId} value={memory.memory_id} />
            <SmallMeta label={labels.taskId} value={memory.task_id} />
            <SmallMeta label={labels.sessionId} value={memory.session_id ?? "none"} />
            <SmallMeta label={labels.score} value={memory.score} />
            <SmallMeta label={labels.createdAt} value={formatTimestamp(memory.created_at)} />
          </div>

          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            <div className="border border-border bg-background/20 p-3">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
                {labels.fact}
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {memory.fact}
              </p>
            </div>
            <div className="border border-border bg-background/20 p-3">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
                {labels.metadata}
              </div>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-5 text-foreground">
                {formatJson(memory.metadata)}
              </pre>
            </div>
          </div>

          <div className="mt-4 border border-border bg-background/20 p-3">
            <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
              {detailLabel}
            </div>
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-5 text-foreground">
              {formatJson(memory)}
            </pre>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

export default function MemoriesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQueryState = parseMemoryQueryState(searchParams);
  const [draftFilters, setDraftFilters] = useState<MemoryFilters>(
    initialQueryState.filters,
  );
  const [appliedFilters, setAppliedFilters] = useState<MemoryFilters>(
    initialQueryState.filters,
  );
  const [offset, setOffset] = useState(initialQueryState.offset);
  const [data, setData] = useState<DebugMemoriesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedMemoryId, setExpandedMemoryId] = useState<string | null>(
    initialQueryState.memoryId,
  );
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  const sessionScopeMissing =
    appliedFilters.scope === "session" && !appliedFilters.sessionId.trim();

  const loadMemories = useCallback(() => {
    if (sessionScopeMissing) {
      setLoading(false);
      setError(null);
      setData(null);
      return;
    }

    setLoading(true);
    setError(null);
    api
      .getDebugMemories({
        scope: appliedFilters.scope,
        session_id:
          appliedFilters.scope === "session"
            ? appliedFilters.sessionId.trim()
            : undefined,
        source:
          appliedFilters.source === "all" ? undefined : appliedFilters.source,
        task_type: appliedFilters.taskType.trim() || undefined,
        memory_scope:
          appliedFilters.memoryScope === "all"
            ? undefined
            : appliedFilters.memoryScope,
        limit: appliedFilters.limit,
        offset,
      })
      .then(setData)
      .catch((err) => {
        setError(String(err));
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [appliedFilters, offset, sessionScopeMissing]);

  useEffect(() => {
    const nextState = parseMemoryQueryState(searchParams);
    queueMicrotask(() => {
      setDraftFilters((current) =>
        memoryFiltersEqual(current, nextState.filters) ? current : nextState.filters,
      );
      setAppliedFilters((current) =>
        memoryFiltersEqual(current, nextState.filters) ? current : nextState.filters,
      );
      setOffset((current) =>
        current === nextState.offset ? current : nextState.offset,
      );
      setExpandedMemoryId((current) =>
        current === nextState.memoryId ? current : nextState.memoryId,
      );
    });
  }, [searchParams]);

  useEffect(() => {
    const nextParams = buildMemoryQueryParams({
      filters: appliedFilters,
      offset,
      memoryId: expandedMemoryId,
    });
    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [appliedFilters, expandedMemoryId, offset, searchParams, setSearchParams]);

  useLayoutEffect(() => {
    setAfterTitle(
      <span className="flex items-center gap-2">
        {loading ? (
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        ) : null}
        <Badge variant="secondary" className="text-[10px]">
          {data?.count ?? 0}
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          {appliedFilters.scope}
        </Badge>
      </span>,
    );
    setEnd(
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={loadMemories}
        disabled={loading}
        className="h-7 text-xs"
      >
        <RefreshCw className="mr-1 h-3 w-3" />
        {t.common.refresh}
      </Button>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [
    appliedFilters.scope,
    data?.count,
    loading,
    loadMemories,
    setAfterTitle,
    setEnd,
    t.common.refresh,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(loadMemories, 0);
    return () => window.clearTimeout(timer);
  }, [loadMemories]);

  const pagination: TaskPagination | null = data?.pagination ?? null;

  return (
    <div className="flex flex-col gap-4">
      <PluginSlot name="memories:top" />

      <Card className="border-border bg-background/20">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Database className="h-4 w-4" />
            {t.memories.filters}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <FilterGroup label={t.memories.scope}>
              <Segmented
                value={draftFilters.scope}
                onChange={(value) =>
                  setDraftFilters((current) => ({
                    ...current,
                    scope: value as MemoryScopeValue,
                  }))
                }
                options={[
                  { value: "recent", label: t.memories.scopeRecent },
                  { value: "session", label: t.memories.scopeSession },
                ]}
              />
            </FilterGroup>

            <FilterGroup label={t.memories.source}>
              <Select
                value={draftFilters.source}
                onValueChange={(value) =>
                  setDraftFilters((current) => ({
                    ...current,
                    source: value as MemorySourceValue,
                  }))
                }
                className="w-36"
              >
                <SelectOption value="all">{t.memories.allSources}</SelectOption>
                <SelectOption value="gateway">gateway</SelectOption>
                <SelectOption value="cron">cron</SelectOption>
              </Select>
            </FilterGroup>

            <FilterGroup label={t.memories.memoryScope}>
              <Select
                value={draftFilters.memoryScope}
                onValueChange={(value) =>
                  setDraftFilters((current) => ({
                    ...current,
                    memoryScope: value as MemoryFilterScopeValue,
                  }))
                }
                className="w-40"
              >
                <SelectOption value="all">{t.memories.allScopes}</SelectOption>
                <SelectOption value="session">session</SelectOption>
                <SelectOption value="task_type">task_type</SelectOption>
                <SelectOption value="global">global</SelectOption>
              </Select>
            </FilterGroup>

            <FilterGroup label={t.memories.limit}>
              <Segmented
                value={String(draftFilters.limit)}
                onChange={(value) =>
                  setDraftFilters((current) => ({
                    ...current,
                    limit: Number(value),
                  }))
                }
                options={LIMIT_OPTIONS.map((value) => ({
                  value: String(value),
                  label: String(value),
                }))}
              />
            </FilterGroup>
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_1fr_auto]">
            <div className="space-y-1">
              <label
                htmlFor="memories-session-id"
                className="font-mondwest text-[0.65rem] tracking-[0.12em] uppercase text-muted-foreground/70"
              >
                {t.memories.sessionId}
              </label>
              <Input
                id="memories-session-id"
                value={draftFilters.sessionId}
                onChange={(event) =>
                  setDraftFilters((current) => ({
                    ...current,
                    sessionId: event.target.value,
                  }))
                }
                placeholder={t.memories.sessionPlaceholder}
                className="h-9 text-xs"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="memories-task-type"
                className="font-mondwest text-[0.65rem] tracking-[0.12em] uppercase text-muted-foreground/70"
              >
                {t.memories.taskType}
              </label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="memories-task-type"
                  value={draftFilters.taskType}
                  onChange={(event) =>
                    setDraftFilters((current) => ({
                      ...current,
                      taskType: event.target.value,
                    }))
                  }
                  placeholder={t.memories.taskTypePlaceholder}
                  className="h-9 pl-8 text-xs"
                />
              </div>
            </div>

            <div className="flex items-end gap-2">
              <Button
                type="button"
                size="sm"
                className="h-9"
                onClick={() => {
                  setOffset(0);
                  setExpandedMemoryId(null);
                  setAppliedFilters(draftFilters);
                }}
              >
                {t.memories.applyFilters}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-9"
                onClick={() => {
                  setDraftFilters(DEFAULT_MEMORY_FILTERS);
                  setAppliedFilters(DEFAULT_MEMORY_FILTERS);
                  setOffset(0);
                  setExpandedMemoryId(null);
                }}
              >
                {t.memories.resetFilters}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-4">
        <SmallMeta label={t.memories.returned} value={data?.count ?? 0} />
        <SmallMeta label={t.memories.offset} value={pagination?.offset ?? offset} />
        <SmallMeta
          label={t.memories.nextCursor}
          value={pagination?.next_cursor ?? "none"}
        />
        <SmallMeta
          label={t.memories.queryScope}
          value={
            appliedFilters.scope === "session" && appliedFilters.sessionId.trim()
              ? `session:${appliedFilters.sessionId.trim()}`
              : appliedFilters.scope
          }
        />
      </div>

      {sessionScopeMissing ? (
        <Card className="border-warning/30 bg-warning/10">
          <CardContent className="py-6">
            <p className="text-sm text-warning">{t.memories.sessionRequired}</p>
          </CardContent>
        </Card>
      ) : null}

      {error ? (
        <Card className="border-destructive/30 bg-destructive/10">
          <CardContent className="py-6">
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      ) : null}

      {loading && !data ? (
        <div className="flex items-center justify-center py-20">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : null}

      {!loading && !error && !sessionScopeMissing && data?.memories.length === 0 ? (
        <Card className="border-border bg-background/20">
          <CardContent className="py-12 text-center">
            <p className="text-sm text-muted-foreground">{t.memories.noMemories}</p>
          </CardContent>
        </Card>
      ) : null}

      {data?.memories.length ? (
        <div className="flex flex-col gap-3">
          {data.memories.map((memory) => (
            <MemoryRow
              key={memory.memory_id}
              memory={memory}
              expanded={expandedMemoryId === memory.memory_id}
              onToggle={() =>
                setExpandedMemoryId((current) =>
                  current === memory.memory_id ? null : memory.memory_id,
                )
              }
              detailLabel={t.memories.rawMemory}
              labels={{
                sessionId: t.memories.sessionId,
                taskId: t.memories.taskId,
                memoryId: t.memories.memoryId,
                score: t.memories.score,
                createdAt: t.memories.createdAt,
                metadata: t.memories.metadata,
                fact: t.memories.fact,
              }}
            />
          ))}
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-3 border-t border-border/60 pt-2">
        <div className="text-xs text-muted-foreground">
          {pagination
            ? `${t.memories.returned}: ${pagination.returned} · ${t.memories.offset}: ${pagination.offset}`
            : `${t.memories.returned}: 0 · ${t.memories.offset}: ${offset}`}
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 w-7 p-0"
            disabled={offset === 0 || loading}
            onClick={() =>
              setOffset((current) =>
                Math.max(0, current - appliedFilters.limit),
              )
            }
            aria-label={t.memories.previousPage}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Badge variant="outline" className="text-[10px]">
            {t.memories.offset}: {pagination?.offset ?? offset}
          </Badge>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 w-7 p-0"
            disabled={!pagination?.has_more || loading}
            onClick={() => setOffset(pagination?.next_offset ?? offset)}
            aria-label={t.memories.nextPage}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <PluginSlot name="memories:bottom" />
    </div>
  );
}
