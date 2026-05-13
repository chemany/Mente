import assert from "node:assert/strict";
import { defaultTheme } from "../src/themes/presets.ts";

{
  assert.equal(defaultTheme.name, "default");
  assert.equal(defaultTheme.label, "Workspace Mist");
  assert.match(
    defaultTheme.description,
    /fresh|light|calm|workspace/i,
    "default theme should describe a fresh light workspace aesthetic",
  );

  assert.equal(
    defaultTheme.palette.background.hex,
    "#f4f7f4",
    "default theme background should be a light paper tone",
  );
  assert.ok(
    defaultTheme.palette.noiseOpacity <= 0.35,
    "default theme should use a softer noise layer than the old dark theme",
  );
  assert.equal(defaultTheme.layout.density, "spacious");
  assert.equal(
    defaultTheme.palette.midground.hex,
    "#111111",
    "default theme should use near-black ink for strong contrast on light surfaces",
  );
  assert.equal(
    defaultTheme.colorOverrides?.mutedForeground,
    "#3f4649",
    "default theme should provide a darker muted foreground for readable secondary text",
  );
  assert.equal(
    defaultTheme.colorOverrides?.border,
    "#8f9d98",
    "default theme should provide a stronger border color on light backgrounds",
  );
  assert.match(
    defaultTheme.typography.fontSans,
    /Source Sans 3/,
    "default theme should use a more comfortable English sans-serif body font",
  );
  assert.match(
    defaultTheme.typography.fontSans,
    /Noto Sans SC/,
    "default theme should use a proper Chinese sans-serif body font",
  );
  assert.match(
    defaultTheme.typography.fontDisplay ?? "",
    /Source Sans 3/,
    "default theme display font should stay aligned with the more readable sans direction",
  );
  assert.match(
    defaultTheme.customCSS ?? "",
    /--theme-text-blend-mode:\s*normal/,
    "default theme should disable glow-style text blending on the light theme",
  );
}

console.log("default-theme tests passed");
