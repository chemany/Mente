import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

{
  const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  assert.ok(
    appSource.includes('className="font-sans flex h-dvh'),
    "app shell should use a readable sans-serif base font instead of the old display font",
  );
  assert.ok(
    !appSource.includes("uppercase text-midground"),
    "app shell should not force all interface copy into uppercase",
  );
  assert.ok(
    appSource.includes("blend-lighter font-bold text-[0.95rem]"),
    "app chrome titles should opt into the theme-controlled blend helper",
  );
}

{
  const pageHeaderSource = readFileSync(new URL("../src/contexts/PageHeaderProvider.tsx", import.meta.url), "utf8");
  assert.ok(
    pageHeaderSource.includes("blend-lighter font-expanded"),
    "page headers should use the theme-controlled blend helper",
  );
}

{
  const sidebarFooterSource = readFileSync(new URL("../src/components/SidebarFooter.tsx", import.meta.url), "utf8");
  assert.ok(
    sidebarFooterSource.includes("blend-lighter font-mondwest"),
    "sidebar footer branding should use the theme-controlled blend helper",
  );
}

{
  const chatPageSource = readFileSync(new URL("../src/pages/ChatPage.tsx", import.meta.url), "utf8");
  assert.ok(
    chatPageSource.includes("blend-lighter font-bold text-[1.125rem]"),
    "chat sheet titles should use the theme-controlled blend helper",
  );
}

{
  const cssSource = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
  assert.ok(
    cssSource.includes("mix-blend-mode: var(--theme-text-blend-mode, plus-lighter);"),
    "blend-lighter helper should be theme-controlled for readability on light themes",
  );
  assert.ok(
    cssSource.includes(".font-mondwest") && cssSource.includes("font-family: var(--theme-font-sans)"),
    "legacy display utility should be remapped to the theme sans stack",
  );
  assert.ok(
    cssSource.includes(".font-expanded") && cssSource.includes("font-family: var(--theme-font-display)"),
    "legacy expanded utility should be remapped to the theme display stack",
  );
  assert.ok(
    cssSource.includes(".font-courier") && cssSource.includes("font-family: var(--theme-font-mono)"),
    "legacy courier utility should be remapped to the theme mono stack",
  );
}

console.log("readability-chrome tests passed");
