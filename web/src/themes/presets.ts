import type { DashboardTheme } from "./types";

/**
 * Built-in dashboard themes.
 *
 * Each theme defines its own palette, typography, and layout so switching
 * themes produces visible changes beyond just color — fonts, density, and
 * corner-radius all shift to match the theme's personality.
 *
 * Theme names must stay in sync with the backend's
 * `_BUILTIN_DASHBOARD_THEMES` list in `hermes_cli/web_server.py`.
 */

// ---------------------------------------------------------------------------
// Shared typography / layout presets
// ---------------------------------------------------------------------------

/** Default system stack — neutral, safe fallback for every platform. */
const SYSTEM_SANS =
  'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const SYSTEM_MONO =
  'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace';

// ---------------------------------------------------------------------------
// Themes
// ---------------------------------------------------------------------------

export const defaultTheme: DashboardTheme = {
  name: "default",
  label: "Workspace Mist",
  description: "Fresh paper-and-seafoam workspace with calm contrast",
  palette: {
    background: { hex: "#f4f7f4", alpha: 1 },
    midground: { hex: "#111111", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0.6 },
    warmGlow: "rgba(176, 214, 194, 0.28)",
    noiseOpacity: 0.24,
  },
  typography: {
    fontSans:
      `"Source Sans 3", "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", ${SYSTEM_SANS}`,
    fontMono: `"IBM Plex Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    fontDisplay:
      `"Source Sans 3", "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", ${SYSTEM_SANS}`,
    baseSize: "15px",
    lineHeight: "1.6",
    letterSpacing: "0",
  },
  layout: {
    radius: "0.85rem",
    density: "spacious",
  },
  colorOverrides: {
    card: "#ffffff",
    cardForeground: "#111111",
    popover: "#fbfcfb",
    popoverForeground: "#111111",
    secondary: "#e9f0ec",
    secondaryForeground: "#1b1e20",
    muted: "#edf3ef",
    mutedForeground: "#3f4649",
    accent: "#dce8e2",
    accentForeground: "#111111",
    border: "#8f9d98",
    input: "#8f9d98",
    ring: "#2d6a5f",
    success: "#2f7d63",
    warning: "#d08a2f",
    destructive: "#be4b49",
  },
  customCSS: `
    :root {
      --theme-text-blend-mode: normal;
    }
  `,
  componentStyles: {
    card: {
      borderRadius: "calc(var(--theme-radius) + 0.35rem)",
      background:
        "linear-gradient(180deg, rgba(255, 255, 255, 0.94) 0%, rgba(247, 250, 248, 0.84) 100%)",
      boxShadow:
        "0 20px 60px -36px rgba(31, 79, 70, 0.28), 0 0 0 1px rgba(31, 79, 70, 0.06) inset",
    },
    header: {
      background:
        "linear-gradient(180deg, rgba(244, 247, 244, 0.94) 0%, rgba(236, 243, 239, 0.88) 100%)",
    },
    sidebar: {
      background:
        "linear-gradient(180deg, rgba(244, 247, 244, 0.97) 0%, rgba(235, 242, 238, 0.93) 100%)",
    },
    backdrop: {
      baseBackground:
        "linear-gradient(180deg, rgba(248, 251, 248, 1) 0%, rgba(239, 245, 241, 1) 54%, rgba(232, 239, 234, 1) 100%)",
      baseMixBlendMode: "normal",
      glowOpacity: "0.18",
      noiseBlendMode: "soft-light",
      noiseOpacity: "0.18",
      fillerBlendMode: "soft-light",
      fillerOpacity: "0.014",
      backgroundPosition: "center top",
    },
  },
};

export const midnightTheme: DashboardTheme = {
  name: "midnight",
  label: "Midnight",
  description: "Deep blue-violet with cool accents",
  palette: {
    background: { hex: "#0a0a1f", alpha: 1 },
    midground: { hex: "#d4c8ff", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(167, 139, 250, 0.32)",
    noiseOpacity: 0.8,
  },
  typography: {
    fontSans: `"Inter", ${SYSTEM_SANS}`,
    fontMono: `"JetBrains Mono", ${SYSTEM_MONO}`,
    baseSize: "14px",
    lineHeight: "1.6",
    letterSpacing: "-0.005em",
  },
  layout: {
    radius: "0.75rem",
    density: "comfortable",
  },
};

export const emberTheme: DashboardTheme = {
  name: "ember",
  label: "Ember",
  description: "Warm crimson and bronze — forge vibes",
  palette: {
    background: { hex: "#1a0a06", alpha: 1 },
    midground: { hex: "#ffd8b0", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(249, 115, 22, 0.38)",
    noiseOpacity: 1,
  },
  typography: {
    fontSans: `"Spectral", Georgia, "Times New Roman", serif`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
    baseSize: "15px",
    lineHeight: "1.6",
    letterSpacing: "0",
  },
  layout: {
    radius: "0.25rem",
    density: "comfortable",
  },
  colorOverrides: {
    destructive: "#c92d0f",
    warning: "#f97316",
  },
};

export const monoTheme: DashboardTheme = {
  name: "mono",
  label: "Mono",
  description: "Clean grayscale — minimal and focused",
  palette: {
    background: { hex: "#0e0e0e", alpha: 1 },
    midground: { hex: "#eaeaea", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(255, 255, 255, 0.1)",
    noiseOpacity: 0.6,
  },
  typography: {
    fontSans: `"IBM Plex Sans", ${SYSTEM_SANS}`,
    fontMono: `"IBM Plex Mono", ${SYSTEM_MONO}`,
    baseSize: "13px",
    lineHeight: "1.5",
    letterSpacing: "0",
  },
  layout: {
    radius: "0",
    density: "compact",
  },
};

export const cyberpunkTheme: DashboardTheme = {
  name: "cyberpunk",
  label: "Cyberpunk",
  description: "Neon green on black — matrix terminal",
  palette: {
    background: { hex: "#040608", alpha: 1 },
    midground: { hex: "#9bffcf", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(0, 255, 136, 0.22)",
    noiseOpacity: 1.2,
  },
  typography: {
    fontSans: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    fontMono: `"Share Tech Mono", "JetBrains Mono", ${SYSTEM_MONO}`,
    baseSize: "14px",
    lineHeight: "1.5",
    letterSpacing: "0.02em",
  },
  layout: {
    radius: "0",
    density: "compact",
  },
  colorOverrides: {
    success: "#00ff88",
    warning: "#ffd700",
    destructive: "#ff0055",
  },
};

export const roseTheme: DashboardTheme = {
  name: "rose",
  label: "Rosé",
  description: "Soft pink and warm ivory — easy on the eyes",
  palette: {
    background: { hex: "#1a0f15", alpha: 1 },
    midground: { hex: "#ffd4e1", alpha: 1 },
    foreground: { hex: "#ffffff", alpha: 0 },
    warmGlow: "rgba(249, 168, 212, 0.3)",
    noiseOpacity: 0.9,
  },
  typography: {
    fontSans: `"Fraunces", Georgia, serif`,
    fontMono: `"DM Mono", ${SYSTEM_MONO}`,
    baseSize: "16px",
    lineHeight: "1.7",
    letterSpacing: "0",
  },
  layout: {
    radius: "1rem",
    density: "spacious",
  },
};

export const BUILTIN_THEMES: Record<string, DashboardTheme> = {
  default: defaultTheme,
  midnight: midnightTheme,
  ember: emberTheme,
  mono: monoTheme,
  cyberpunk: cyberpunkTheme,
  rose: roseTheme,
};
