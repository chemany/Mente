export function formatSignalNotice(signal: NodeJS.Signals): string | null {
  if (signal === 'SIGINT') {
    return null
  }

  return `hermes-tui: received ${signal}\n`
}
