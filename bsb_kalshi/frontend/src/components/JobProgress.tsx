import { useEffect, useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Square } from 'lucide-react'
import { api, type JobStatus } from '@/lib/api'
import type { JobStreamState } from '@/hooks/useJobStream'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'

const STATUS_LABEL: Record<JobStatus, string> = {
  running: 'Running',
  succeeded: 'Finished',
  failed: 'Failed',
  cancelled: 'Stopped',
}

const STATUS_CLASS: Record<JobStatus, string> = {
  running: 'bg-primary/15 text-primary',
  succeeded: 'bg-primary/15 text-primary',
  failed: 'bg-destructive/15 text-destructive',
  cancelled: 'bg-warning/15 text-warning',
}

const LEVEL_CLASS = { info: 'text-muted-foreground', warn: 'text-warning', error: 'text-destructive' } as const

export function JobProgress({ jobId, stream }: { jobId: string; stream: JobStreamState }) {
  const logRef = useRef<HTMLDivElement>(null)
  const stop = useMutation({ mutationFn: () => api.stopJob(jobId) })
  const percent = stream.total > 0 ? Math.round((stream.done / stream.total) * 100) : stream.status === 'running' ? 0 : 100

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [stream.logs.length])

  return (
    <div className="grid gap-3 rounded-lg border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-3">
        {stream.status !== null && (
          <Badge className={STATUS_CLASS[stream.status]}>{STATUS_LABEL[stream.status]}</Badge>
        )}
        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{stream.message}</span>
        <span className="font-mono text-xs tabular-nums text-muted-foreground" title="Steps done / total steps">
          {stream.done}/{stream.total}
        </span>
        {stream.status === 'running' && (
          <Button size="sm" variant="outline" onClick={() => stop.mutate()} disabled={stop.isPending}>
            <Square /> Stop
          </Button>
        )}
      </div>
      <Progress value={percent} />
      {stream.reason !== null && <p className="text-sm text-destructive">{stream.reason}</p>}
      <div ref={logRef} className="max-h-40 overflow-y-auto rounded-md bg-background/60 p-2 font-mono text-[11px] leading-5">
        {stream.logs.length === 0 ? (
          <span className="text-muted-foreground">Waiting for the first progress update…</span>
        ) : (
          stream.logs.map((line, i) => (
            <div key={`${line.ts}-${i}`} className={LEVEL_CLASS[line.level]}>
              <span className="opacity-60">{new Date(line.ts).toLocaleTimeString()} </span>
              {line.message}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
