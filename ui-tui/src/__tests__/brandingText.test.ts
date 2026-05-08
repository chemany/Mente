import { describe, expect, it } from 'vitest'

import { buildBannerSubtitle, buildSessionModelLabel, buildTerminalTitle } from '../lib/brandingText.js'

describe('brandingText', () => {
  it('uses Mente-only banner copy', () => {
    expect(buildBannerSubtitle('⚕')).toBe('⚕ Mente Agent · thought in hand')
  })

  it('omits vendor branding from the session model label', () => {
    expect(buildSessionModelLabel('gpt-5.4')).toBe('gpt-5.4')
  })

  it('uses Mente as the empty terminal title fallback', () => {
    expect(buildTerminalTitle({ cwd: '', marker: '✓', model: '' })).toBe('Mente')
  })

  it('builds the terminal title from marker, model, and cwd', () => {
    expect(buildTerminalTitle({ cwd: '/root/code/Mente', marker: '⏳', model: 'gpt-5.4' })).toBe(
      '⏳ gpt-5.4 · /root/code/Mente'
    )
  })
})
