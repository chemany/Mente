import type { AgentInventory, AgentsSummary } from "@/lib/api";

export interface AgentsSummaryCard {
  key:
    | "agent_count"
    | "total_runtime_sessions"
    | "agents_with_state_db"
    | "agents_with_log_db";
  value: number;
}

export function buildAgentsSummaryCards(
  summary: AgentsSummary,
): AgentsSummaryCard[] {
  return [
    { key: "agent_count", value: summary.agent_count },
    {
      key: "total_runtime_sessions",
      value: summary.total_runtime_sessions,
    },
    { key: "agents_with_state_db", value: summary.agents_with_state_db },
    { key: "agents_with_log_db", value: summary.agents_with_log_db },
  ];
}

export function pickNextAgentId(
  agents: AgentInventory[],
  currentAgentId: string | null,
): string | null {
  if (agents.length === 0) {
    return null;
  }
  if (currentAgentId && agents.some((agent) => agent.agent_id === currentAgentId)) {
    return currentAgentId;
  }
  return agents[0]?.agent_id ?? null;
}
