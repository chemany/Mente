import { describe, expect, it } from 'vitest'

import { DARK_THEME, DEFAULT_THEME, detectLightMode, fromSkin, LIGHT_THEME } from '../theme.js'

describe('DEFAULT_THEME', () => {
  it('has brand defaults', () => {
    expect(DEFAULT_THEME.brand.name).toBe('Mente')
    expect(DEFAULT_THEME.brand.prompt).toBe('❯')
    expect(DEFAULT_THEME.brand.tool).toBe('┊')
  })

  it('has high-contrast dark defaults', () => {
    expect(DEFAULT_THEME.color.gold).toBe('#FFFFFF')
    expect(DEFAULT_THEME.color.cornsilk).toBe('#FFFFFF')
    expect(DEFAULT_THEME.color.statusBg).toBe('#000000')
    expect(DEFAULT_THEME.color.statusFg).toBe('#FFFFFF')
    expect(DEFAULT_THEME.color.error).toBe('#EF6B73')
  })
})

describe('LIGHT_THEME', () => {
  it('uses high-contrast light defaults', () => {
    expect(LIGHT_THEME.color.gold).toBe('#000000')
    expect(LIGHT_THEME.color.cornsilk).toBe('#000000')
    expect(LIGHT_THEME.color.statusBg).toBe('#FFFFFF')
    expect(LIGHT_THEME.color.statusFg).toBe('#000000')
  })

  it('keeps the same shape as DARK_THEME', () => {
    expect(Object.keys(LIGHT_THEME.color).sort()).toEqual(Object.keys(DARK_THEME.color).sort())
    expect(LIGHT_THEME.brand).toEqual(DARK_THEME.brand)
  })
})

describe('DEFAULT_THEME aliasing', () => {
  it('defaults to DARK_THEME when nothing signals light', () => {
    expect(DEFAULT_THEME).toBe(DARK_THEME)
  })
})

describe('detectLightMode', () => {
  it('returns false on empty env', () => {
    expect(detectLightMode({})).toBe(false)
  })

  it('honors HERMES_TUI_LIGHT on/off', () => {
    expect(detectLightMode({ HERMES_TUI_LIGHT: '1' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_LIGHT: 'true' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_LIGHT: 'on' })).toBe(true)
    expect(detectLightMode({ HERMES_TUI_LIGHT: '0' })).toBe(false)
    expect(detectLightMode({ HERMES_TUI_LIGHT: 'off' })).toBe(false)
  })

  it('sniffs COLORFGBG bg slots 7 and 15 as light (#11300)', () => {
    expect(detectLightMode({ COLORFGBG: '0;15' })).toBe(true)
    expect(detectLightMode({ COLORFGBG: '0;default;15' })).toBe(true)
    expect(detectLightMode({ COLORFGBG: '0;7' })).toBe(true)
    expect(detectLightMode({ COLORFGBG: '15;0' })).toBe(false)
    expect(detectLightMode({ COLORFGBG: '7;default;0' })).toBe(false)
  })

  it('lets HERMES_TUI_LIGHT=0 override a light COLORFGBG', () => {
    expect(detectLightMode({ COLORFGBG: '0;15', HERMES_TUI_LIGHT: '0' })).toBe(false)
  })
})

describe('fromSkin', () => {
  it('overrides banner colors', () => {
    expect(fromSkin({ banner_title: '#FF0000' }, {}).color.gold).toBe('#FF0000')
  })

  it('preserves unset colors', () => {
    expect(fromSkin({ banner_title: '#FF0000' }, {}).color.amber).toBe(DEFAULT_THEME.color.amber)
  })

  it('overrides branding', () => {
    const { brand } = fromSkin({}, { agent_name: 'TestBot', prompt_symbol: '$' })
    expect(brand.name).toBe('TestBot')
    expect(brand.prompt).toBe('$')
  })

  it('defaults for empty skin', () => {
    expect(fromSkin({}, {}).color).toEqual(DEFAULT_THEME.color)
    expect(fromSkin({}, {}).brand.icon).toBe(DEFAULT_THEME.brand.icon)
  })

  it('passes banner logo/hero', () => {
    expect(fromSkin({}, {}, 'LOGO', 'HERO').bannerLogo).toBe('LOGO')
    expect(fromSkin({}, {}, 'LOGO', 'HERO').bannerHero).toBe('HERO')
  })

  it('maps ui_ color keys + cascades to status', () => {
    const { color } = fromSkin({ ui_ok: '#008000' }, {})
    expect(color.ok).toBe('#008000')
    expect(color.statusGood).toBe('#008000')
  })

  it('maps status and completion skin colors directly', () => {
    const { color } = fromSkin(
      {
        status_bar_bg: '#10161C',
        status_bar_text: '#C5D6D8',
        completion_menu_bg: '#131C22',
        completion_menu_current_bg: '#1F3239'
      },
      {}
    )

    expect(color.statusBg).toBe('#10161C')
    expect(color.statusFg).toBe('#C5D6D8')
    expect(color.completionBg).toBe('#131C22')
    expect(color.completionCurrentBg).toBe('#1F3239')
  })
})
