import { useQuery } from '@tanstack/react-query'
import { Play, ShieldCheck } from 'lucide-react'
import { api, type RequestEstimate } from '@/lib/api'
import { fmtDuration } from '@/lib/format'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

/** Pre-run safety dialog: shows the request estimate before a job sends many requests. */
export function RunConfirmDialog({
  open,
  onOpenChange,
  title,
  estimate,
  breakdown,
  notes,
  fixedDurationS,
  onConfirm,
  confirming,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  estimate: RequestEstimate | null
  breakdown: { label: string; value: number }[]
  notes?: string[]
  /** For jobs that run for a set time regardless of request count (e.g. the M6 recorder). */
  fixedDurationS?: number
  onConfirm: () => void
  confirming: boolean
}) {
  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const rps = meta?.settings.rate_limit_rps ?? null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-primary" /> {title}
          </DialogTitle>
          <DialogDescription>Before starting, here is how many requests this test may send to Kalshi.</DialogDescription>
        </DialogHeader>
        {estimate !== null && (
          <div className="grid gap-3">
            <dl className="grid gap-1.5 rounded-lg border bg-surface p-3 text-sm">
              {breakdown.map((row) => (
                <div key={row.label} className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">{row.label}</dt>
                  <dd className="font-mono tabular-nums">{row.value}</dd>
                </div>
              ))}
              <div className="mt-1 flex justify-between gap-4 border-t pt-2 font-medium">
                <dt>Requests it may send (at most)</dt>
                <dd className="font-mono tabular-nums">{estimate.total}</dd>
              </div>
              <div className="flex justify-between gap-4 text-xs text-muted-foreground">
                <dt>Absolute limit, including retries</dt>
                <dd className="font-mono tabular-nums">{estimate.cap}</dd>
              </div>
              {fixedDurationS !== undefined ? (
                <div className="flex justify-between gap-4 text-xs text-muted-foreground">
                  <dt>Runs for</dt>
                  <dd className="font-mono tabular-nums">{fmtDuration(fixedDurationS)}</dd>
                </div>
              ) : (
                rps !== null && (
                  <div className="flex justify-between gap-4 text-xs text-muted-foreground">
                    <dt>Takes at least (at {rps} requests per second)</dt>
                    <dd className="font-mono tabular-nums">{fmtDuration(estimate.total / rps)}</dd>
                  </div>
                )
              )}
            </dl>
            <ul className="grid gap-1 text-xs text-muted-foreground">
              <li>Read-only requests, sent one at a time under our speed limit.</li>
              <li>Stops by itself if Kalshi asks us to slow down. You can stop it at any time.</li>
              {notes?.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={onConfirm} disabled={confirming || estimate === null}>
            <Play /> Start test
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
