import type { CatalogEndpoint, ProbeClassification } from '@/lib/api'
import { CHART_COLORS } from '@/lib/chartTheme'

export const CLASSIFICATIONS: ProbeClassification[] = [
  'public',
  'key required',
  'denied even with key',
  'inconclusive',
  'error',
  'not probed',
]

export const CLASSIFICATION_COLORS: Record<ProbeClassification, string> = {
  public: CHART_COLORS.primary,
  'key required': CHART_COLORS.blue,
  'denied even with key': CHART_COLORS.red,
  inconclusive: CHART_COLORS.amber,
  error: CHART_COLORS.pink,
  'not probed': CHART_COLORS.muted,
}

export const CLASSIFICATION_BADGE: Record<ProbeClassification, string> = {
  public: 'bg-primary/15 text-primary',
  'key required': 'bg-sky-400/15 text-sky-300',
  'denied even with key': 'bg-destructive/15 text-destructive',
  inconclusive: 'bg-warning/15 text-warning',
  error: 'bg-pink-400/15 text-pink-300',
  'not probed': 'bg-muted text-muted-foreground',
}

export function observed(endpoint: CatalogEndpoint): ProbeClassification {
  return endpoint.probe?.classification ?? 'not probed'
}
