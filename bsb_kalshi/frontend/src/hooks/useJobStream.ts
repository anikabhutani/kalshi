import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { jobEventsUrl, type JobEvent, type JobStatus } from '@/lib/api'

export interface LogLine {
  ts: string
  level: 'info' | 'warn' | 'error'
  message: string
}

export interface JobStreamState {
  status: JobStatus | null
  reason: string | null
  done: number
  total: number
  message: string
  logs: LogLine[]
}

const INITIAL: JobStreamState = { status: null, reason: null, done: 0, total: 0, message: '', logs: [] }

function reduce(state: JobStreamState, event: JobEvent): JobStreamState {
  switch (event.type) {
    case 'status':
      return { ...state, status: event.status, reason: event.reason ?? null }
    case 'progress':
      return { ...state, done: event.done, total: event.total, message: event.message }
    case 'log':
      return { ...state, logs: [...state.logs, { ts: event.ts, level: event.level, message: event.message }] }
  }
}

/** Subscribes to a job's SSE stream and refreshes dependent queries when it finishes. */
export function useJobStream(jobId: string | null): JobStreamState {
  const queryClient = useQueryClient()
  const [entry, setEntry] = useState<{ jobId: string | null; state: JobStreamState }>({
    jobId: null,
    state: INITIAL,
  })

  useEffect(() => {
    if (jobId === null) return undefined
    const source = new EventSource(jobEventsUrl(jobId))
    source.onmessage = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as JobEvent
      setEntry((prev) => ({ jobId, state: reduce(prev.jobId === jobId ? prev.state : INITIAL, event) }))
      if (event.type === 'status' && event.status !== 'running') {
        source.close()
        void queryClient.invalidateQueries({ queryKey: ['job', jobId] })
        void queryClient.invalidateQueries({ queryKey: ['requests'] })
        void queryClient.invalidateQueries({ queryKey: ['jobs'] })
        void queryClient.invalidateQueries({ queryKey: ['home'] })
        void queryClient.invalidateQueries({ queryKey: ['latest'] })
        void queryClient.invalidateQueries({ queryKey: ['catalog'] })
        void queryClient.invalidateQueries({ queryKey: ['t3'] })
      }
    }
    source.onerror = () => source.close()
    return () => source.close()
  }, [jobId, queryClient])

  return entry.jobId === jobId ? entry.state : INITIAL
}
