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
  DebugTask,
  DebugTasksResponse,
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
  buildTaskQueryParams,
  DEFAULT_TASK_FILTERS,
  parseTaskQueryState,
  taskFiltersEqual,
  type TaskFilters,
  type TaskScopeValue,
  type TaskSourceValue,
  type TaskStatusValue,
} from "./tasks-url-state";

const LIMIT_OPTIONS = [10, 20, 50] as const;

const STATUS_VARIANTS: Record<string, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  ingested: "outline",
  classified: "outline",
  planned: "secondary",
  context_prepared: "secondary",
  executing: "warning",
  verified: "secondary",
  persisted: "secondary",
  succeeded: "success",
  failed: "destructive",
  blocked: "warning",
};

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
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

function ArraySection({
  title,
  values,
}: {
  title: string;
  values: string[];
}) {
  return (
    <div className="border border-border bg-background/20 p-3">
      <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
        {title}
      </div>
      {values.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">None</p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {values.map((value) => (
            <Badge key={value} variant="outline" className="text-[10px]">
              {value}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function TaskRow({
  task,
  expanded,
  onToggle,
  detailLabel,
}: {
  task: DebugTask;
  expanded: boolean;
  onToggle: () => void;
  detailLabel: string;
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
              <Badge variant={STATUS_VARIANTS[task.status] ?? "outline"}>
                {task.status}
              </Badge>
              <Badge variant="outline">{task.source}</Badge>
              <Badge variant="secondary">{task.task_type}</Badge>
              <span className="font-courier text-[11px] text-muted-foreground">
                {task.task_id}
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-foreground">
              {task.objective}
            </p>
            <p className="mt-2 max-h-10 overflow-hidden text-xs leading-relaxed text-muted-foreground">
              {task.user_request}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
            <div className="min-w-0 text-right">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase">
                Session
              </div>
              <div className="mt-1 max-w-[18rem] truncate font-courier text-[11px] text-foreground">
                {task.session_id}
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
          <span>{task.allowed_tools.length} tools</span>
          <span>{task.constraints.length} constraints</span>
          <span>{task.skill_refs.length} skills</span>
          <span>{task.artifacts_in.length} artifacts</span>
          {task.workspace ? <span className="truncate">workspace: {task.workspace}</span> : null}
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-border bg-black/15 px-4 py-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <SmallMeta label="Task ID" value={task.task_id} />
            <SmallMeta label="Session" value={task.session_id} />
            <SmallMeta label="Execution" value={task.execution_mode ?? "default"} />
            <SmallMeta label="Resume Token" value={task.resume_token ?? "none"} />
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="border border-border bg-background/20 p-3">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
                Objective
              </div>
              <p className="mt-2 text-sm leading-relaxed text-foreground">
                {task.objective}
              </p>
            </div>
            <div className="border border-border bg-background/20 p-3">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
                User Request
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {task.user_request}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <ArraySection title="Constraints" values={task.constraints} />
            <ArraySection title="Allowed Tools" values={task.allowed_tools} />
            <ArraySection title="Skill Refs" values={task.skill_refs} />
            <ArraySection title="Memory Facts" values={task.memory_facts} />
            <ArraySection title="Artifacts In" values={task.artifacts_in} />
            <ArraySection
              title="Acceptance Criteria"
              values={task.acceptance_criteria}
            />
          </div>

          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            <div className="border border-border bg-background/20 p-3">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
                Metadata
              </div>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-5 text-foreground">
                {formatJson(task.metadata)}
              </pre>
            </div>
            <div className="border border-border bg-background/20 p-3">
              <div className="font-mondwest text-[0.6rem] tracking-[0.14em] uppercase text-muted-foreground/70">
                {detailLabel}
              </div>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-5 text-foreground">
                {formatJson(task)}
              </pre>
            </div>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

export default function TasksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQueryState = parseTaskQueryState(searchParams);
  const [draftFilters, setDraftFilters] = useState<TaskFilters>(
    initialQueryState.filters,
  );
  const [appliedFilters, setAppliedFilters] = useState<TaskFilters>(
    initialQueryState.filters,
  );
  const [offset, setOffset] = useState(initialQueryState.offset);
  const [data, setData] = useState<DebugTasksResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(
    initialQueryState.taskId,
  );
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  const sessionScopeMissing =
    appliedFilters.scope === "session" && !appliedFilters.sessionId.trim();

  const loadTasks = useCallback(() => {
    if (sessionScopeMissing) {
      setLoading(false);
      setError(null);
      setData(null);
      return;
    }

    setLoading(true);
    setError(null);
    api
      .getDebugTasks({
        scope: appliedFilters.scope,
        session_id:
          appliedFilters.scope === "session"
            ? appliedFilters.sessionId.trim()
            : undefined,
        source:
          appliedFilters.source === "all" ? undefined : appliedFilters.source,
        status:
          appliedFilters.status === "all" ? undefined : appliedFilters.status,
        task_type: appliedFilters.taskType.trim() || undefined,
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
    const nextState = parseTaskQueryState(searchParams);

    setDraftFilters((current) =>
      taskFiltersEqual(current, nextState.filters) ? current : nextState.filters,
    );
    setAppliedFilters((current) =>
      taskFiltersEqual(current, nextState.filters) ? current : nextState.filters,
    );
    setOffset((current) =>
      current === nextState.offset ? current : nextState.offset,
    );
    setExpandedTaskId((current) =>
      current === nextState.taskId ? current : nextState.taskId,
    );
  }, [searchParams]);

  useEffect(() => {
    const nextParams = buildTaskQueryParams({
      filters: appliedFilters,
      offset,
      taskId: expandedTaskId,
    });
    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [appliedFilters, expandedTaskId, offset, searchParams, setSearchParams]);

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
        onClick={loadTasks}
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
    loadTasks,
    setAfterTitle,
    setEnd,
    t.common.refresh,
  ]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const pagination: TaskPagination | null = data?.pagination ?? null;

  return (
    <div className="flex flex-col gap-4">
      <PluginSlot name="tasks:top" />

      <Card className="border-border bg-background/20">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Database className="h-4 w-4" />
            {t.tasks.filters}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <FilterGroup label={t.tasks.scope}>
              <Segmented
                value={draftFilters.scope}
                onChange={(value) =>
                  setDraftFilters((current) => ({
                    ...current,
                    scope: value as TaskScopeValue,
                  }))
                }
                options={[
                  { value: "recent", label: t.tasks.scopeRecent },
                  { value: "session", label: t.tasks.scopeSession },
                ]}
              />
            </FilterGroup>

            <FilterGroup label={t.tasks.source}>
              <Select
                value={draftFilters.source}
                onValueChange={(value) =>
                  setDraftFilters((current) => ({
                    ...current,
                    source: value as TaskSourceValue,
                  }))
                }
                className="w-36"
              >
                <SelectOption value="all">{t.tasks.allSources}</SelectOption>
                <SelectOption value="gateway">gateway</SelectOption>
                <SelectOption value="cron">cron</SelectOption>
              </Select>
            </FilterGroup>

            <FilterGroup label={t.tasks.status}>
              <Select
                value={draftFilters.status}
                onValueChange={(value) =>
                  setDraftFilters((current) => ({
                    ...current,
                    status: value as TaskStatusValue,
                  }))
                }
                className="w-44"
              >
                <SelectOption value="all">{t.tasks.allStatuses}</SelectOption>
                <SelectOption value="ingested">ingested</SelectOption>
                <SelectOption value="classified">classified</SelectOption>
                <SelectOption value="planned">planned</SelectOption>
                <SelectOption value="context_prepared">context_prepared</SelectOption>
                <SelectOption value="executing">executing</SelectOption>
                <SelectOption value="verified">verified</SelectOption>
                <SelectOption value="persisted">persisted</SelectOption>
                <SelectOption value="succeeded">succeeded</SelectOption>
                <SelectOption value="failed">failed</SelectOption>
                <SelectOption value="blocked">blocked</SelectOption>
              </Select>
            </FilterGroup>

            <FilterGroup label={t.tasks.limit}>
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
                htmlFor="tasks-session-id"
                className="font-mondwest text-[0.65rem] tracking-[0.12em] uppercase text-muted-foreground/70"
              >
                {t.tasks.sessionId}
              </label>
              <Input
                id="tasks-session-id"
                value={draftFilters.sessionId}
                onChange={(event) =>
                  setDraftFilters((current) => ({
                    ...current,
                    sessionId: event.target.value,
                  }))
                }
                placeholder={t.tasks.sessionPlaceholder}
                className="h-9 text-xs"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="tasks-task-type"
                className="font-mondwest text-[0.65rem] tracking-[0.12em] uppercase text-muted-foreground/70"
              >
                {t.tasks.taskType}
              </label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="tasks-task-type"
                  value={draftFilters.taskType}
                  onChange={(event) =>
                    setDraftFilters((current) => ({
                      ...current,
                      taskType: event.target.value,
                    }))
                  }
                  placeholder={t.tasks.taskTypePlaceholder}
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
                  setExpandedTaskId(null);
                  setAppliedFilters(draftFilters);
                }}
              >
                {t.tasks.applyFilters}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-9"
                onClick={() => {
                  setDraftFilters(DEFAULT_TASK_FILTERS);
                  setAppliedFilters(DEFAULT_TASK_FILTERS);
                  setOffset(0);
                  setExpandedTaskId(null);
                }}
              >
                {t.tasks.resetFilters}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-4">
        <SmallMeta label={t.tasks.returned} value={data?.count ?? 0} />
        <SmallMeta label={t.tasks.offset} value={pagination?.offset ?? offset} />
        <SmallMeta
          label={t.tasks.nextCursor}
          value={pagination?.next_cursor ?? "none"}
        />
        <SmallMeta
          label={t.tasks.queryScope}
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
            <p className="text-sm text-warning">{t.tasks.sessionRequired}</p>
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

      {!loading && !error && !sessionScopeMissing && data?.tasks.length === 0 ? (
        <Card className="border-border bg-background/20">
          <CardContent className="py-12 text-center">
            <p className="text-sm text-muted-foreground">{t.tasks.noTasks}</p>
          </CardContent>
        </Card>
      ) : null}

      {data?.tasks.length ? (
        <div className="flex flex-col gap-3">
          {data.tasks.map((task) => (
            <TaskRow
              key={task.task_id}
              task={task}
              expanded={expandedTaskId === task.task_id}
              onToggle={() =>
                setExpandedTaskId((current) =>
                  current === task.task_id ? null : task.task_id,
                )
              }
              detailLabel={t.tasks.rawTask}
            />
          ))}
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-3 border-t border-border/60 pt-2">
        <div className="text-xs text-muted-foreground">
          {pagination
            ? `${t.tasks.returned}: ${pagination.returned} · ${t.tasks.offset}: ${pagination.offset}`
            : `${t.tasks.returned}: 0 · ${t.tasks.offset}: ${offset}`}
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
            aria-label={t.tasks.previousPage}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Badge variant="outline" className="text-[10px]">
            {t.tasks.offset}: {pagination?.offset ?? offset}
          </Badge>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 w-7 p-0"
            disabled={!pagination?.has_more || loading}
            onClick={() => setOffset(pagination?.next_offset ?? offset)}
            aria-label={t.tasks.nextPage}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <PluginSlot name="tasks:bottom" />
    </div>
  );
}
