import { useQuery } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'
import { api } from '@/lib/api'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function RateMeter() {
  const { data } = useQuery({
    queryKey: ['ratelimit'],
    queryFn: api.rateLimit,
    refetchInterval: 1_000,
    staleTime: 0,
    meta: { silent: true },
  })

  const fraction = data ? Math.max(0, Math.min(1, data.tokens / data.capacity)) : 0
  const cooling = (data?.cooldown_remaining_s ?? 0) > 0

  return (
    <Tooltip>
      <TooltipTrigger
        render={<div className="hidden items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs md:flex" />}
      >
        <Gauge className={cn('size-3.5', cooling ? 'text-warning' : 'text-muted-foreground')} />
        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
          <div
            className={cn('h-full rounded-full transition-all', cooling ? 'bg-warning' : 'bg-primary')}
            style={{ width: `${fraction * 100}%` }}
          />
        </div>
        <span className="font-mono tabular-nums text-muted-foreground">
          {data ? `${data.requests_last_60s.toFixed(0)}/min` : '–'}
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="flex-col items-start">
        {data ? (
          <>
            <span>Our own speed limit: at most {data.rate_per_s} requests per second to Kalshi.</span>
            <span>Requests sent in the last minute: {data.requests_last_60s}</span>
            <span>Tests running now: {data.running_jobs}</span>
            {cooling && (
              <span>Paused for {data.cooldown_remaining_s.toFixed(0)} s because Kalshi asked us to slow down</span>
            )}
          </>
        ) : (
          <span>Speed-limit status unavailable.</span>
        )}
      </TooltipContent>
    </Tooltip>
  )
}
