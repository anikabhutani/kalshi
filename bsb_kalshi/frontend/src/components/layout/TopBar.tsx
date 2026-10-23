import { useQuery } from '@tanstack/react-query'
import { CalendarCheck, FileCode2 } from 'lucide-react'
import { api } from '@/lib/api'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { RateMeter } from '@/components/layout/RateMeter'
import { SettingsDialog } from '@/components/layout/SettingsDialog'
import { StatusPill } from '@/components/layout/StatusPill'
import { StopAllButton } from '@/components/layout/StopAllButton'
import { cn } from '@/lib/utils'

export function TopBar() {
  const { data: meta } = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const confirmed = meta?.settings.api_version ?? null
  const specVersion = meta?.openapi.version
  const mismatch = confirmed !== null && specVersion !== undefined && confirmed !== specVersion

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur md:px-6">
      <StatusPill />
      <Tooltip>
        <TooltipTrigger
          render={<div className="hidden items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs sm:flex" />}
        >
          <FileCode2 className="size-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">Kalshi API version</span>
          <span className={cn('font-mono', confirmed === null ? 'text-warning' : mismatch ? 'text-destructive' : 'text-foreground')}>
            {confirmed ?? specVersion ?? '…'}
          </span>
          {confirmed === null && <span className="text-warning">not confirmed</span>}
        </TooltipTrigger>
        <TooltipContent side="bottom">
          Version of Kalshi’s documentation this tool follows: {specVersion ?? '…'}. Confirmed by you:{' '}
          {confirmed ?? 'not yet'} (set it in Settings).
        </TooltipContent>
      </Tooltip>
      <div className="hidden items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs lg:flex">
        <CalendarCheck className="size-3.5 text-muted-foreground" />
        <span className="text-muted-foreground">Docs checked on</span>
        <span className={cn('font-mono', meta?.settings.date_checked ? 'text-foreground' : 'text-warning')}>
          {meta?.settings.date_checked ?? 'not set'}
        </span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <RateMeter />
        <SettingsDialog meta={meta} />
        <StopAllButton />
      </div>
    </header>
  )
}
