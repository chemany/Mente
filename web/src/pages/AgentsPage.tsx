import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";
import {
  Bot,
  Database,
  FileText,
  HardDrive,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  AgentInventory,
  AgentInventoryListResponse,
  AgentRuntimeActionResponse,
} from "@/lib/api";
import {
  buildAgentsSummaryCards,
  pickNextAgentId,
} from "./agents-page-helpers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Toast } from "@/components/Toast";
import { useToast } from "@/hooks/useToast";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";
import { cn } from "@/lib/utils";

function SummaryCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: typeof Bot;
}) {
  return (
    <Card className="rounded-[calc(var(--theme-radius)+0.55rem)] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.78)_0%,rgba(247,250,248,0.92)_100%)]">
      <CardContent className="flex items-center justify-between gap-3 p-5">
        <div>
          <div className="font-mondwest text-[0.6rem] tracking-[0.14em] text-muted-foreground/70">
            {label}
          </div>
          <div className="mt-2 font-expanded text-2xl text-foreground">
            {value}
          </div>
        </div>
        <div className="flex h-11 w-11 items-center justify-center rounded-[calc(var(--theme-radius)+0.2rem)] border border-border/65 bg-white/70 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]">
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

function SmallMeta({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-[calc(var(--theme-radius)+0.35rem)] border border-border/65 bg-white/62 px-3.5 py-3.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]">
      <div className="font-mondwest text-[0.6rem] tracking-[0.14em] text-muted-foreground/70">
        {label}
      </div>
      <div className="mt-1 break-all font-courier text-xs text-foreground">
        {value}
      </div>
    </div>
  );
}

function FileSection({
  title,
  values,
  emptyLabel,
}: {
  title: string;
  values: string[];
  emptyLabel: string;
}) {
  return (
    <div className="rounded-[calc(var(--theme-radius)+0.35rem)] border border-border/65 bg-white/62 p-3.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]">
      <div className="font-mondwest text-[0.6rem] tracking-[0.14em] text-muted-foreground/70">
        {title}
      </div>
      {values.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">{emptyLabel}</p>
      ) : (
        <div className="mt-2 flex flex-col gap-2">
          {values.map((value) => (
            <div
              key={value}
              className="break-all rounded-[calc(var(--theme-radius)-0.05rem)] border border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.9)_0%,rgba(243,247,244,0.95)_100%)] px-2.5 py-2 font-courier text-[11px] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.88)]"
            >
              {value}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentListRow({
  agent,
  selected,
  onSelect,
  labels,
}: {
  agent: AgentInventory;
  selected: boolean;
  onSelect: () => void;
  labels: {
    sessions: string;
    lanes: string;
    taskProfiles: string;
  };
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-[calc(var(--theme-radius)+0.35rem)] border px-4 py-4 text-left transition-all duration-150",
        selected
          ? "border-foreground/18 bg-white/84 shadow-[0_18px_44px_-34px_rgba(17,24,39,0.28)]"
          : "border-border/65 bg-white/58 hover:bg-white/82 hover:shadow-[0_18px_44px_-34px_rgba(17,24,39,0.22)]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-expanded text-sm text-foreground">
              {agent.display_name}
            </span>
            <Badge variant="outline" className="text-[10px]">
              {agent.agent_id}
            </Badge>
          </div>
          <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {agent.soul_excerpt}
          </p>
        </div>
        <Badge variant="secondary" className="text-[10px] tabular-nums">
          {agent.runtime.session_count} {labels.sessions}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {agent.lanes.map((lane) => (
          <Badge key={`${agent.agent_id}:lane:${lane}`} variant="outline" className="text-[10px]">
            {labels.lanes}: {lane}
          </Badge>
        ))}
        {agent.task_profiles.map((profile) => (
          <Badge
            key={`${agent.agent_id}:task:${profile}`}
            variant="secondary"
            className="text-[10px]"
          >
            {labels.taskProfiles}: {profile}
          </Badge>
        ))}
      </div>
    </button>
  );
}

export default function AgentsPage() {
  const [inventory, setInventory] = useState<AgentInventoryListResponse | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentInventory | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<"reset" | "clear" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const { setAfterTitle, setEnd } = usePageHeader();

  const loadInventory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await api.getAgents();
      setInventory(resp);
      setSelectedAgentId((current) => pickNextAgentId(resp.agents, current));
    } catch (err) {
      setError(String(err));
      setInventory(null);
      setSelectedAgentId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (agentId: string) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const resp = await api.getAgentDetail(agentId);
      setDetail(resp);
    } catch (err) {
      setDetailError(String(err));
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInventory();
  }, [loadInventory]);

  useEffect(() => {
    if (!selectedAgentId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    void loadDetail(selectedAgentId);
  }, [loadDetail, selectedAgentId]);

  const summaryCards = useMemo(
    () =>
      inventory
        ? buildAgentsSummaryCards(inventory.summary)
        : buildAgentsSummaryCards({
            agent_count: 0,
            total_runtime_sessions: 0,
            agents_with_state_db: 0,
            agents_with_log_db: 0,
          }),
    [inventory],
  );

  useLayoutEffect(() => {
    setAfterTitle(
      <span className="flex items-center gap-2">
        {loading ? (
          <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        ) : null}
        <Badge variant="secondary" className="text-[10px] tabular-nums">
          {inventory?.summary.agent_count ?? 0}
        </Badge>
        <Badge variant="outline" className="text-[10px] tabular-nums">
          {inventory?.summary.total_runtime_sessions ?? 0} {t.agents.sessions}
        </Badge>
      </span>,
    );
    setEnd(
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => void loadInventory()}
        disabled={loading}
        className="h-7 text-xs"
      >
        <RefreshCw className="h-3 w-3" />
        {t.common.refresh}
      </Button>,
    );
    return () => {
      setAfterTitle(null);
      setEnd(null);
    };
  }, [inventory, loading, setAfterTitle, setEnd, t.agents.sessions, t.common.refresh, loadInventory]);

  const runRuntimeAction = useCallback(
    async (action: "reset" | "clear") => {
      if (!selectedAgentId) {
        return;
      }
      const confirmMessage =
        action === "reset" ? t.agents.confirmReset : t.agents.confirmClear;
      if (!window.confirm(confirmMessage)) {
        return;
      }
      setActionLoading(action);
      try {
        const result: AgentRuntimeActionResponse =
          action === "reset"
            ? await api.resetAgentRuntime(selectedAgentId)
            : await api.clearAgentRuntime(selectedAgentId);
        showToast(
          action === "reset"
            ? `${t.agents.runtimeResetSuccess}: ${result.removed_entries_count}`
            : `${t.agents.runtimeClearSuccess}: ${result.removed_entries_count}`,
          "success",
        );
        await loadInventory();
        await loadDetail(selectedAgentId);
      } catch (err) {
        showToast(String(err), "error");
      } finally {
        setActionLoading(null);
      }
    },
    [
      loadDetail,
      loadInventory,
      selectedAgentId,
      showToast,
      t.agents.confirmClear,
      t.agents.confirmReset,
      t.agents.runtimeClearSuccess,
      t.agents.runtimeResetSuccess,
    ],
  );

  const summaryLabels: Record<(typeof summaryCards)[number]["key"], string> = {
    agent_count: t.agents.registeredAgents,
    total_runtime_sessions: t.agents.runtimeSessions,
    agents_with_state_db: t.agents.agentsWithStateDb,
    agents_with_log_db: t.agents.agentsWithLogDb,
  };

  const summaryIcons: Record<(typeof summaryCards)[number]["key"], typeof Bot> = {
    agent_count: Bot,
    total_runtime_sessions: HardDrive,
    agents_with_state_db: Database,
    agents_with_log_db: FileText,
  };

  return (
    <div className="flex flex-col gap-5">
      <PluginSlot name="agents:top" />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {summaryCards.map((card) => (
          <SummaryCard
            key={card.key}
            label={summaryLabels[card.key]}
            value={card.value}
            icon={summaryIcons[card.key]}
          />
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[23rem_minmax(0,1fr)]">
        <Card className="rounded-[calc(var(--theme-radius)+0.65rem)] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.78)_0%,rgba(247,250,248,0.94)_100%)]">
          <CardHeader>
            <CardTitle>{t.agents.agentRegistry}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {loading ? (
              <div className="text-sm text-muted-foreground">{t.common.loading}</div>
            ) : error ? (
              <div className="text-sm text-destructive">
                {t.agents.failedToLoad}: {error}
              </div>
            ) : inventory && inventory.agents.length > 0 ? (
              inventory.agents.map((agent) => (
                <AgentListRow
                  key={agent.agent_id}
                  agent={agent}
                  selected={selectedAgentId === agent.agent_id}
                  onSelect={() => setSelectedAgentId(agent.agent_id)}
                  labels={{
                    sessions: t.agents.sessions,
                    lanes: t.agents.lanes,
                    taskProfiles: t.agents.taskProfiles,
                  }}
                />
              ))
            ) : (
              <div className="text-sm text-muted-foreground">{t.agents.noAgents}</div>
            )}
          </CardContent>
        </Card>

        <div className="min-w-0 flex flex-col gap-4">
          <Card className="rounded-[calc(var(--theme-radius)+0.65rem)] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.78)_0%,rgba(247,250,248,0.94)_100%)]">
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <div>
                <CardTitle>{t.agents.agentDetail}</CardTitle>
                {detail ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      {detail.agent_id}
                    </Badge>
                    <Badge variant="secondary" className="text-[10px]">
                      {detail.display_name}
                    </Badge>
                  </div>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void runRuntimeAction("reset")}
                  disabled={!detail || actionLoading !== null}
                  className="h-8"
                >
                  <RotateCcw className="h-3 w-3" />
                  {actionLoading === "reset"
                    ? t.agents.resettingRuntime
                    : t.agents.resetRuntime}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  onClick={() => void runRuntimeAction("clear")}
                  disabled={!detail || actionLoading !== null}
                  className="h-8"
                >
                  <Trash2 className="h-3 w-3" />
                  {actionLoading === "clear"
                    ? t.agents.clearingRuntime
                    : t.agents.clearRuntime}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {detailLoading ? (
                <div className="text-sm text-muted-foreground">{t.common.loading}</div>
              ) : detailError ? (
                <div className="text-sm text-destructive">
                  {t.agents.failedToLoadDetail}: {detailError}
                </div>
              ) : !detail ? (
                <div className="text-sm text-muted-foreground">
                  {t.agents.noAgentSelected}
                </div>
              ) : (
                <>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    <SmallMeta
                      label={t.agents.runtimeSessions}
                      value={detail.runtime.session_count}
                    />
                    <SmallMeta
                      label={t.agents.lanes}
                      value={detail.lanes.join(", ") || t.common.none}
                    />
                    <SmallMeta
                      label={t.agents.taskProfiles}
                      value={detail.task_profiles.join(", ") || t.common.none}
                    />
                    <SmallMeta
                      label={t.agents.runtimeHome}
                      value={detail.runtime.runtime_home}
                    />
                  </div>

                  <div className="grid gap-3 xl:grid-cols-3">
                    <SmallMeta label={t.agents.agentDir} value={detail.agent_dir} />
                    <SmallMeta label={t.agents.soulPath} value={detail.soul_path} />
                    <SmallMeta
                      label={t.agents.runtimeHome}
                      value={detail.runtime.runtime_home}
                    />
                  </div>

                  <div className="grid gap-3 xl:grid-cols-2">
                    <FileSection
                      title={t.agents.sessionFiles}
                      values={detail.runtime.session_files}
                      emptyLabel={t.common.none}
                    />
                    <FileSection
                      title={t.agents.stateFiles}
                      values={detail.runtime.state_files}
                      emptyLabel={t.common.none}
                    />
                    <FileSection
                      title={t.agents.logFiles}
                      values={detail.runtime.log_files}
                      emptyLabel={t.common.none}
                    />
                    <FileSection
                      title={t.agents.otherFiles}
                      values={detail.runtime.other_files}
                      emptyLabel={t.common.none}
                    />
                  </div>

                  <div className="rounded-[calc(var(--theme-radius)+0.45rem)] border border-border/65 bg-[linear-gradient(180deg,rgba(255,255,255,0.74)_0%,rgba(244,248,245,0.9)_100%)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.78)]">
                    <div className="font-mondwest text-[0.6rem] tracking-[0.14em] text-muted-foreground/70">
                      {t.agents.fullSoul}
                    </div>
                    <pre className="mt-3 overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-6 text-foreground">
                      {detail.soul_text?.trim() || t.agents.noSoul}
                    </pre>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <PluginSlot name="agents:bottom" />
      <Toast toast={toast} />
    </div>
  );
}
