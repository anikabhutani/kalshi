import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type ConnectionState } from '@/lib/api'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const STATE_STYLE: Record<ConnectionState | 'backend_down' | 'loading', { label: string; dot: string; text: string }> = {
  ok: { label: 'Connected to Kalshi', dot: 'bg-primary', text: 'text-primary' },
  unauthorized: { label: 'Account key rejected', dot: 'bg-destructive', text: 'text-destructive' },
  forbidden: { label: 'Key lacks access', dot: 'bg-destructive', text: 'text-destructive' },
  rate_limited: { label: 'Kalshi asked us to slow down', dot: 'bg-warning', text: 'text-warning' },
  offline: { label: 'No internet / Kalshi unreachable', dot: 'bg-muted-foreground', text: 'text-muted-foreground' },
  error: { label: 'Connection problem', dot: 'bg-destructive', text: 'text-destructive' },
  not_configured: { label: 'No account key set up', dot: 'bg-warning', text: 'text-warning' },
  backend_down: { label: 'App server not running', dot: 'bg-destructive', text: 'text-destructive' },
  loading: { label: 'Checking connection…', dot: 'bg-muted-foreground animate-pulse', text: 'text-muted-foreground' },
}

export function StatusPill() {
  const queryClient = useQueryClient()
  const { data, isError, isFetching } = useQuery({
    queryKey: ['status'],
    queryFn: () => api.status(),
    refetchInterval: 60_000,
    meta: { silent: true },
  })

  const key = isError ? 'backend_down' : data === undefined || isFetching ? 'loading' : data.state
  const style = STATE_STYLE[key]

  const refresh = () =>
    queryClient.fetchQuery({ queryKey: ['status'], queryFn: () => api.status(true), staleTime: 0 })

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            onClick={() => void refresh()}
            className="flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs font-medium hover:bg-accent"
          />
        }
      >
        <span className={cn('size-2 rounded-full', style.dot)} />
        <span className={style.text}>{style.label}</span>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-sm flex-col items-start">
        {data !== undefined && !isError ? (
          <>
            <span>{data.message}</span>
            <span className="font-mono opacity-70">
              GET {data.path}
              {data.http_status !== null && ` → ${data.http_status}`}
              {data.latency_ms !== null && ` · ${data.latency_ms.toFixed(0)} ms`}
            </span>
            <span className="opacity-70">Click to re-check now.</span>
          </>
        ) : (
          <span>The app’s server is not responding. Start it with “make dev”.</span>
        )}
      </TooltipContent>
    </Tooltip>
  )
}
