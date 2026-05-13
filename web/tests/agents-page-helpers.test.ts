import assert from "node:assert/strict";
import { en } from "../src/i18n/en.ts";
import { resolvePageTitle } from "../src/lib/resolve-page-title.ts";
import type { AgentInventory } from "../src/lib/api.ts";
import {
  buildAgentsSummaryCards,
  pickNextAgentId,
} from "../src/pages/agents-page-helpers.ts";

const sampleAgents: AgentInventory[] = [
  {
    agent_id: "director",
    display_name: "Director",
    agent_dir: "/tmp/agents/director",
    soul_path: "/tmp/agents/director/soul.md",
    lanes: ["general"],
    task_profiles: ["chat"],
    soul_excerpt: "Owns dispatch and replies.",
    runtime: {
      runtime_home: "/tmp/runtime/director",
      session_count: 2,
      session_files: ["session-a.jsonl", "session-b.jsonl"],
      state_files: ["state.db"],
      log_files: [],
      other_files: ["lock"],
    },
  },
  {
    agent_id: "engineering",
    display_name: "Engineering",
    agent_dir: "/tmp/agents/engineering",
    soul_path: "/tmp/agents/engineering/soul.md",
    lanes: ["build", "fix"],
    task_profiles: ["coding", "review"],
    soul_excerpt: "Owns implementation execution.",
    runtime: {
      runtime_home: "/tmp/runtime/engineering",
      session_count: 4,
      session_files: ["session-c.jsonl"],
      state_files: [],
      log_files: ["agent.log"],
      other_files: [],
    },
  },
];

{
  const cards = buildAgentsSummaryCards({
    agent_count: 2,
    total_runtime_sessions: 6,
    agents_with_state_db: 1,
    agents_with_log_db: 1,
  });

  assert.deepEqual(cards, [
    { key: "agent_count", value: 2 },
    { key: "total_runtime_sessions", value: 6 },
    { key: "agents_with_state_db", value: 1 },
    { key: "agents_with_log_db", value: 1 },
  ]);
}

{
  assert.equal(pickNextAgentId(sampleAgents, null), "director");
  assert.equal(pickNextAgentId(sampleAgents, "engineering"), "engineering");
  assert.equal(pickNextAgentId(sampleAgents, "missing"), "director");
  assert.equal(pickNextAgentId([], "director"), null);
}

{
  assert.equal(resolvePageTitle("/agents", en, []), en.app.nav.agents);
}

console.log("agents-page-helpers tests passed");
