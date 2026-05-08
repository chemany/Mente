export const buildBannerSubtitle = (icon: string, brandName = 'Mente'): string => {
  const label = brandName.trim() === 'Mente' ? 'Mente Agent' : brandName.trim() || 'Mente Agent'
  return `${icon} ${label} · thought in hand`
}

export const buildSessionModelLabel = (model: string): string => model

export const buildTerminalTitle = ({
  cwd,
  marker,
  model
}: {
  cwd?: string | null
  marker: string
  model?: string | null
}): string => {
  const trimmedModel = model?.trim() || ''

  if (!trimmedModel) {
    return 'Mente'
  }

  const trimmedCwd = cwd?.trim() || ''
  return trimmedCwd ? `${marker} ${trimmedModel} · ${trimmedCwd}` : `${marker} ${trimmedModel}`
}

export const buildHistorySpeakerLabel = (role: 'assistant' | 'user', index: number): string =>
  role === 'user' ? `You #${index + 1}` : `Mente #${index + 1}`
