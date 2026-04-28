import assert from "node:assert/strict";
import {
  buildMemoryQueryParams,
  parseMemoryQueryState,
} from "../src/pages/memories-url-state.ts";

{
  const parsed = parseMemoryQueryState(
    new URLSearchParams(
      "scope=session&session_id=sess-42&source=gateway&task_type=conversation&memory_scope=session&cursor=10&limit=50&memory_id=mem-9",
    ),
  );

  assert.deepEqual(parsed.filters, {
    scope: "session",
    sessionId: "sess-42",
    source: "gateway",
    taskType: "conversation",
    memoryScope: "session",
    limit: 50,
  });
  assert.equal(parsed.offset, 10);
  assert.equal(parsed.memoryId, "mem-9");
}

{
  const parsed = parseMemoryQueryState(
    new URLSearchParams("scope=recent&source=bad&memory_scope=nope&limit=999&offset=-4"),
  );

  assert.deepEqual(parsed.filters, {
    scope: "recent",
    sessionId: "",
    source: "all",
    taskType: "",
    memoryScope: "all",
    limit: 20,
  });
  assert.equal(parsed.offset, 0);
  assert.equal(parsed.memoryId, null);
}

{
  const params = buildMemoryQueryParams({
    filters: {
      scope: "session",
      sessionId: "sess-88",
      source: "gateway",
      taskType: "conversation",
      memoryScope: "session",
      limit: 10,
    },
    offset: 20,
    memoryId: "mem-88",
  });

  assert.equal(
    params.toString(),
    "scope=session&session_id=sess-88&source=gateway&task_type=conversation&memory_scope=session&limit=10&offset=20&memory_id=mem-88",
  );
}

console.log("memories-url-state tests passed");
