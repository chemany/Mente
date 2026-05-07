export interface ThemeColors {
  gold: string
  amber: string
  bronze: string
  cornsilk: string
  dim: string
  completionBg: string
  completionCurrentBg: string

  label: string
  ok: string
  error: string
  warn: string

  prompt: string
  sessionLabel: string
  sessionBorder: string

  statusBg: string
  statusFg: string
  statusGood: string
  statusWarn: string
  statusBad: string
  statusCritical: string
  selectionBg: string

  diffAdded: string
  diffRemoved: string
  diffAddedWord: string
  diffRemovedWord: string

  shellDollar: string
}

export interface ThemeBrand {
  name: string
  icon: string
  prompt: string
  welcome: string
  goodbye: string
  tool: string
  helpHeader: string
}

export interface Theme {
  color: ThemeColors
  brand: ThemeBrand
  bannerLogo: string
  bannerHero: string
}

// ── Color math ───────────────────────────────────────────────────────

function parseHex(h: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(h)

  if (!m) {
    return null
  }

  const n = parseInt(m[1]!, 16)

  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

function mix(a: string, b: string, t: number) {
  const pa = parseHex(a)
  const pb = parseHex(b)

  if (!pa || !pb) {
    return a
  }

  const lerp = (i: 0 | 1 | 2) => Math.round(pa[i] + (pb[i] - pa[i]) * t)

  return '#' + ((1 << 24) | (lerp(0) << 16) | (lerp(1) << 8) | lerp(2)).toString(16).slice(1)
}

// ── Defaults ─────────────────────────────────────────────────────────

const BRAND: ThemeBrand = {
  name: 'Mente',
  icon: '⚕',
  prompt: '❯',
  welcome: 'Type your message or /help for commands.',
  goodbye: 'Goodbye! ⚕',
  tool: '┊',
  helpHeader: '(^_^)? Commands'
}

export const DARK_THEME: Theme = {
  color: {
    gold: '#FFFFFF',
    amber: '#F0F0F0',
    bronze: '#8A8A8A',
    cornsilk: '#FFFFFF',
    dim: '#B5B5B5',
    completionBg: '#111111',
    completionCurrentBg: '#2B2B2B',

    label: '#F0F0F0',
    ok: '#58C7A2',
    error: '#EF6B73',
    warn: '#F2A65A',

    prompt: '#FFFFFF',
    sessionLabel: '#FFFFFF',
    sessionBorder: '#B5B5B5',

    statusBg: '#000000',
    statusFg: '#FFFFFF',
    statusGood: '#58C7A2',
    statusWarn: '#F2A65A',
    statusBad: '#F28C5B',
    statusCritical: '#EF6B73',
    selectionBg: '#2B2B2B',

    diffAdded: 'rgb(220,255,220)',
    diffRemoved: 'rgb(255,220,220)',
    diffAddedWord: 'rgb(36,138,61)',
    diffRemovedWord: 'rgb(207,34,46)',
    shellDollar: '#55C6FF'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: ''
}

// Light-terminal palette: darker golds/ambers that stay legible on white
// backgrounds. Same shape as DARK_THEME so `fromSkin` still layers on top
// cleanly (#11300).
export const LIGHT_THEME: Theme = {
  color: {
    gold: '#000000',
    amber: '#111111',
    bronze: '#6E6E6E',
    cornsilk: '#000000',
    dim: '#555555',
    completionBg: '#FFFFFF',
    completionCurrentBg: '#E9E9E9',

    label: '#111111',
    ok: '#2E8B6E',
    error: '#C95A68',
    warn: '#C47A3A',

    prompt: '#000000',
    sessionLabel: '#000000',
    sessionBorder: '#555555',

    statusBg: '#FFFFFF',
    statusFg: '#000000',
    statusGood: '#2E8B6E',
    statusWarn: '#C47A3A',
    statusBad: '#D98955',
    statusCritical: '#B94B60',
    selectionBg: '#E9E9E9',

    diffAdded: 'rgb(200,240,200)',
    diffRemoved: 'rgb(240,200,200)',
    diffAddedWord: 'rgb(27,94,32)',
    diffRemovedWord: 'rgb(183,28,28)',
    shellDollar: '#1C7ED6'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: ''
}

// Pick light vs dark. Explicit `HERMES_TUI_LIGHT` wins; otherwise sniff
// `COLORFGBG` (set by XFCE Terminal, rxvt, Terminal.app, etc.) — last field is the
// background ANSI index; 7/15 are the "white" slots most light themes emit (#11300).
export function detectLightMode(env: NodeJS.ProcessEnv = process.env): boolean {
  const explicit = (env.HERMES_TUI_LIGHT ?? '').trim().toLowerCase()

  if (/^(?:1|true|yes|on)$/.test(explicit)) {
    return true
  }

  if (/^(?:0|false|no|off)$/.test(explicit)) {
    return false
  }

  const bg = Number((env.COLORFGBG ?? '').trim().split(';').at(-1))

  return bg === 7 || bg === 15
}

export const DEFAULT_THEME: Theme = detectLightMode() ? LIGHT_THEME : DARK_THEME

// ── Skin → Theme ─────────────────────────────────────────────────────

export function fromSkin(
  colors: Record<string, string>,
  branding: Record<string, string>,
  bannerLogo = '',
  bannerHero = '',
  toolPrefix = '',
  helpHeader = ''
): Theme {
  const d = DEFAULT_THEME
  const c = (k: string) => colors[k]

  const amber = c('ui_accent') ?? c('banner_accent') ?? d.color.amber
  const accent = c('banner_accent') ?? c('banner_title') ?? d.color.amber
  const dim = c('banner_dim') ?? d.color.dim
  const hasCompletionOverride =
    c('completion_menu_bg') !== undefined ||
    c('completion_menu_current_bg') !== undefined ||
    c('banner_accent') !== undefined ||
    c('banner_title') !== undefined ||
    c('ui_accent') !== undefined

  return {
    color: {
      gold: c('banner_title') ?? d.color.gold,
      amber,
      bronze: c('banner_border') ?? d.color.bronze,
      cornsilk: c('banner_text') ?? d.color.cornsilk,
      dim,
      completionBg: c('completion_menu_bg') ?? d.color.completionBg,
      completionCurrentBg:
        c('completion_menu_current_bg') ??
        (hasCompletionOverride
          ? mix(c('completion_menu_bg') ?? d.color.completionBg, accent, 0.25)
          : d.color.completionCurrentBg),

      label: c('ui_label') ?? d.color.label,
      ok: c('ui_ok') ?? d.color.ok,
      error: c('ui_error') ?? d.color.error,
      warn: c('ui_warn') ?? d.color.warn,

      prompt: c('prompt') ?? c('banner_text') ?? d.color.prompt,
      sessionLabel: c('session_label') ?? c('banner_dim') ?? d.color.sessionLabel,
      sessionBorder: c('session_border') ?? c('banner_dim') ?? d.color.sessionBorder,

      statusBg: c('status_bar_bg') ?? d.color.statusBg,
      statusFg: c('status_bar_text') ?? d.color.statusFg,
      statusGood: c('status_bar_good') ?? c('ui_ok') ?? d.color.statusGood,
      statusWarn: c('status_bar_warn') ?? c('ui_warn') ?? d.color.statusWarn,
      statusBad: c('status_bar_bad') ?? d.color.statusBad,
      statusCritical: c('status_bar_critical') ?? d.color.statusCritical,
      selectionBg: c('selection_bg') ?? d.color.selectionBg,

      diffAdded: d.color.diffAdded,
      diffRemoved: d.color.diffRemoved,
      diffAddedWord: d.color.diffAddedWord,
      diffRemovedWord: d.color.diffRemovedWord,
      shellDollar: c('shell_dollar') ?? d.color.shellDollar
    },

    brand: {
      name: branding.agent_name ?? d.brand.name,
      icon: d.brand.icon,
      prompt: branding.prompt_symbol ?? d.brand.prompt,
      welcome: branding.welcome ?? d.brand.welcome,
      goodbye: branding.goodbye ?? d.brand.goodbye,
      tool: toolPrefix || d.brand.tool,
      helpHeader: branding.help_header ?? (helpHeader || d.brand.helpHeader)
    },

    bannerLogo,
    bannerHero
  }
}
