import { describe, expect, it } from 'vitest'

import { formatSignalNotice } from '../lib/signalNotices.js'

describe('formatSignalNotice', () => {
  it('suppresses SIGINT because the terminal already shows Ctrl-C', () => {
    expect(formatSignalNotice('SIGINT')).toBeNull()
  })

  it('keeps service-level termination notices', () => {
    expect(formatSignalNotice('SIGTERM')).toBe('hermes-tui: received SIGTERM\n')
    expect(formatSignalNotice('SIGHUP')).toBe('hermes-tui: received SIGHUP\n')
  })
})
