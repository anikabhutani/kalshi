import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Job } from '@/lib/api'
import { useJobStream, type JobStreamState } from '@/hooks/useJobStream'

export interface ModuleJob<R> {
  /** Job started in this session (null until the user runs one). */
  jobId: string | null
  start: (jobId: string) => void
  stream: JobStreamState
  running: boolean
  /** Latest job with results: this session's job once finished, else the last stored one. */
  job: Job<R> | null
  loading: boolean
}

/** Tracks a module's job: live progress for a new run, stored results otherwise. */
export function useModuleJob<R>(module: string, kind: string): ModuleJob<R> {
  const [jobId, setJobId] = useState<string | null>(null)
  const stream = useJobStream(jobId)
  const running = jobId !== null && (stream.status === null || stream.status === 'running')
  const finished = jobId !== null && stream.status !== null && stream.status !== 'running'

  const latest = useQuery({
    queryKey: ['latest', module, kind],
    queryFn: () => api.latestJob<R>(module, kind),
    meta: { silent: true },
  })
  const current = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.job<R>(jobId!),
    enabled: finished,
  })

  const job = jobId !== null ? (finished ? (current.data ?? null) : null) : (latest.data ?? null)
  return {
    jobId,
    start: setJobId,
    stream,
    running,
    job,
    loading: jobId === null ? latest.isLoading : finished && current.isLoading,
  }
}
