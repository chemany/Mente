import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { en } from "../src/i18n/en.ts";
import { zh } from "../src/i18n/zh.ts";

{
  assert.equal(en.app.brand, "Mente");
  assert.equal(en.app.brandShort, "MN");
  assert.equal(en.app.footer.org, "chemany / Mente");
  assert.equal(en.status.updateHermes, "Update Mente");
  assert.equal(en.status.updatingHermes, "Updating Mente...");
}

{
  assert.equal(zh.app.brand, "Mente");
  assert.equal(zh.app.brandShort, "MN");
  assert.equal(zh.app.footer.org, "chemany / Mente");
  assert.equal(zh.status.updateHermes, "更新 Mente");
  assert.equal(zh.status.updatingHermes, "正在更新 Mente...");
}

{
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /<title>Mente Dashboard<\/title>/);
}

{
  const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  assert.ok(
    !appSource.includes("Hermes\n                <br />\n                Agent"),
    "sidebar branding should not hardcode Hermes Agent anymore",
  );
}

{
  const chatSource = readFileSync(new URL("../src/pages/ChatPage.tsx", import.meta.url), "utf8");
  assert.ok(
    chatSource.includes("Open this page through `mente dashboard`, not directly."),
    "chat page missing-token banner should reference mente dashboard",
  );
}

{
  const configSource = readFileSync(new URL("../src/pages/ConfigPage.tsx", import.meta.url), "utf8");
  assert.ok(
    configSource.includes('a.download = "mente-config.json";'),
    "config export filename should use mente branding",
  );
}

{
  const envSource = readFileSync(new URL("../src/pages/EnvPage.tsx", import.meta.url), "utf8");
  assert.ok(
    envSource.includes("<code>~/.mente/.env</code>"),
    "env page should show the Mente env path",
  );
  assert.ok(
    !envSource.includes("<code>~/.hermes/.env</code>"),
    "env page should not show the legacy Hermes env path",
  );
}

{
  const sidebarFooterSource = readFileSync(new URL("../src/components/SidebarFooter.tsx", import.meta.url), "utf8");
  assert.ok(
    sidebarFooterSource.includes('href="https://github.com/chemany/Mente"'),
    "sidebar footer should link to the Mente GitHub repository",
  );
  assert.ok(
    !sidebarFooterSource.includes('href="https://nousresearch.com"'),
    "sidebar footer should not link to Nous Research anymore",
  );
}

{
  const docsSource = readFileSync(new URL("../src/pages/DocsPage.tsx", import.meta.url), "utf8");
  assert.ok(
    docsSource.includes('https://chemany.github.io/Mente/docs/'),
    "docs page should point at the Mente docs site",
  );
  assert.ok(
    !docsSource.includes("hermes-agent.nousresearch.com/docs/"),
    "docs page should not point at the old Hermes docs site",
  );
}

console.log("branding-copy tests passed");
