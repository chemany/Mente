import assert from "node:assert/strict";
import {
  buildTaskQueryParams,
  parseTaskQueryState,
} from "../src/pages/tasks-url-state.ts";

{
  const parsed = parseTaskQueryState(
    new URLSearchParams(
      "scope=session&session_id=sess-42&source=cron&status=succeeded&task_type=cron&cursor=40&limit=50&task_id=task-9",
    ),
  );

  assert.deepEqual(parsed.filters, {
    scope: "session",
    sessionId: "sess-42",
    source: "cron",
    status: "succeeded",
    taskType: "cron",
    limit: 50,
  });
  assert.equal(parsed.offset, 40);
  assert.equal(parsed.taskId, "task-9");
}

{
  const parsed = parseTaskQueryState(
    new URLSearchParams("scope=recent&source=bad&status=nope&limit=999&offset=-4"),
  );

  assert.deepEqual(parsed.filters, {
    scope: "recent",
    sessionId: "",
    source: "all",
    status: "all",
    taskType: "",
    limit: 20,
  });
  assert.equal(parsed.offset, 0);
  assert.equal(parsed.taskId, null);
}

{
  const params = buildTaskQueryParams({
    filters: {
      scope: "session",
      sessionId: "sess-88",
      source: "gateway",
      status: "executing",
      taskType: "gateway_message",
      limit: 10,
    },
    offset: 20,
    taskId: "task-88",
  });

  assert.equal(
    params.toString(),
    "scope=session&session_id=sess-88&source=gateway&status=executing&task_type=gateway_message&limit=10&offset=20&task_id=task-88",
  );
}

console.log("tasks-url-state tests passed");
