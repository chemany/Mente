import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

{
  const cardSource = readFileSync(
    new URL("../src/components/ui/card.tsx", import.meta.url),
    "utf8",
  );
  assert.ok(
    cardSource.includes("rounded-[var(--theme-radius)]"),
    "shared cards should use the theme radius instead of hard rectangular edges",
  );
  assert.ok(
    cardSource.includes("shadow-[0_20px_50px_-32px_rgba(17,24,39,0.28)]"),
    "shared cards should provide a soft shadow instead of relying on rigid borders alone",
  );
}

{
  const backdropSource = readFileSync(
    new URL("../src/components/Backdrop.tsx", import.meta.url),
    "utf8",
  );
  assert.ok(
    backdropSource.includes(
      'mixBlendMode: "var(--component-backdrop-base-mix-blend-mode, normal)"',
    ),
    "light dashboard backdrop should default to normal blending instead of the old dark difference blend",
  );
  assert.ok(
    backdropSource.includes(
      'background: "var(--component-backdrop-base-background, var(--background-base))"',
    ),
    "backdrop base layer should be theme-configurable so empty canvas regions do not fall back to black",
  );
}

{
  const agentsPageSource = readFileSync(
    new URL("../src/pages/AgentsPage.tsx", import.meta.url),
    "utf8",
  );
  assert.ok(
    !agentsPageSource.includes("bg-black/10"),
    "agents page runtime file chips should not reintroduce black patches on the light dashboard",
  );
  assert.ok(
    agentsPageSource.includes("rounded-[calc(var(--theme-radius)+0.55rem)]"),
    "agents page summary cards and data blocks should use softer rounded corners",
  );
  assert.ok(
    agentsPageSource.includes('<div className="min-w-0 flex flex-col gap-4">'),
    "agents detail column should opt into min-w-0 so long paths do not force the grid wider than the viewport",
  );
}

{
  const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  assert.ok(
    appSource.includes("rounded-[calc(var(--theme-radius)+0.9rem)]"),
    "main dashboard shell should wrap content in a softer rounded surface",
  );
  assert.ok(
    !appSource.includes("lg:mr-4"),
    "main dashboard shell should not reserve an empty right margin band on desktop",
  );
  assert.ok(
    appSource.includes('"min-h-0 min-w-0 w-full flex flex-1 flex-col overflow-hidden"'),
    "main content shell should be an explicit column flex container so routed pages keep a real layout box",
  );
  assert.ok(
    appSource.includes('"w-full min-w-0 min-h-0 flex flex-1 flex-col"'),
    "routes container should always claim flex-1 instead of only docs/chat routes",
  );
  assert.ok(
    appSource.includes("<RouteCrashBoundary"),
    "dashboard routes should be wrapped in a crash boundary so frontend errors do not collapse into a blank pane",
  );
}

{
  const boundarySource = readFileSync(
    new URL("../src/components/RouteCrashBoundary.tsx", import.meta.url),
    "utf8",
  );
  assert.ok(
    boundarySource.includes("Dashboard route crashed"),
    "route crash boundary should render a visible fallback instead of leaving the main pane empty",
  );
}

{
  const backdropSource = readFileSync(
    new URL("../src/components/Backdrop.tsx", import.meta.url),
    "utf8",
  );
  assert.ok(
    backdropSource.includes("z-[0]") &&
      backdropSource.includes("z-[1]") &&
      backdropSource.includes("z-[2]") &&
      backdropSource.includes("z-[3]"),
    "backdrop layers should stay behind the application chrome instead of painting over routed content",
  );
}

console.log("agents-page-chrome tests passed");
