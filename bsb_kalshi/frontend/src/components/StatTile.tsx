import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function StatTile({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: 'default' | 'primary' | 'warning' | 'destructive'
}) {
  return (
    <div className="rounded-lg border bg-surface px-3 py-2.5" title={hint}>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          'mt-0.5 font-mono text-lg tabular-nums',
          tone === 'primary' && 'text-primary',
          tone === 'warning' && 'text-warning',
          tone === 'destructive' && 'text-destructive',
        )}
      >
        {value}
      </div>
    </div>
  )
}
