import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import type { RequestEstimate } from '@/lib/api'

/** Jobs estimated above this many requests need confirmation in the safety dialog. */
export const CONFIRM_THRESHOLD = 10

/** Plan -> (confirm if large) -> run. The plan call never sends requests to Kalshi. */
export function useGuardedRun<P>({
  plan,
  run,
  onStarted,
}: {
  plan: (params: P) => Promise<RequestEstimate>
  run: (params: P) => Promise<{ job_id: string }>
  onStarted: (jobId: string) => void
}) {
  const [pending, setPending] = useState<{ params: P; estimate: RequestEstimate } | null>(null)
  const runMutation = useMutation({
    mutationFn: run,
    onSuccess: (res) => {
      setPending(null)
      onStarted(res.job_id)
    },
  })
  const planMutation = useMutation({
    mutationFn: async (params: P) => ({ params, estimate: await plan(params) }),
    onSuccess: (res) => (res.estimate.total > CONFIRM_THRESHOLD ? setPending(res) : runMutation.mutate(res.params)),
  })
  return {
    request: planMutation.mutate,
    busy: planMutation.isPending || runMutation.isPending,
    estimate: pending?.estimate ?? null,
    dialogOpen: pending !== null,
    closeDialog: () => setPending(null),
    confirm: () => {
      if (pending !== null) runMutation.mutate(pending.params)
    },
    confirming: runMutation.isPending,
  }
}
