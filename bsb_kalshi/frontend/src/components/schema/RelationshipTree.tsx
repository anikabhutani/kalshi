import { Link } from 'react-router-dom'
import { ArrowDown, Clock } from 'lucide-react'
import type { LinkRow, PullResult } from '@/lib/api'
import { fmtUtc } from '@/lib/format'
import { Badge } from '@/components/ui/badge'

function Connector({ links }: { links: LinkRow[] }) {
  return (
    <div className="flex items-center gap-3 py-1.5 pl-6">
      <ArrowDown className="size-4 text-muted-foreground" />
      <div className="flex flex-wrap gap-1.5">
        {links.length === 0 ? (
          <span className="text-xs text-muted-foreground">No field links this level to the one above.</span>
        ) : (
          links.map((l) => (
            <Badge key={l.child} variant="outline" className="font-mono text-primary">
              {l.child} = {l.parent}
              <span className="text-muted-foreground">
                {' '}
                ({l.matching}/{l.records})
              </span>
            </Badge>
          ))
        )}
      </div>
    </div>
  )
}

function Node({ kind, id, title }: { kind: string; id: string; title: string | null }) {
  return (
    <div className="rounded-lg border bg-surface px-4 py-3">
      <div className="text-[11px] tracking-wide text-muted-foreground uppercase">{kind}</div>
      <div className="font-mono text-sm">{id}</div>
      {title && <div className="text-xs text-muted-foreground">{title}</div>}
    </div>
  )
}

/** Series -> event -> markets, with the fields observed to link each level to its parent. */
export function RelationshipTree({ result }: { result: PullResult }) {
  const { tree, links } = result
  const eventLinks = links.filter((l) => l.parent.startsWith('series.'))
  const marketLinks = links.filter((l) => l.parent.startsWith('event.'))
  return (
    <div className="grid gap-0">
      <Node kind="League (series)" id={tree.series.ticker} title={tree.series.title} />
      <Connector links={eventLinks} />
      <Node
        kind="Game (event)"
        id={tree.event.event_ticker}
        title={[tree.event.title, tree.event.sub_title].filter(Boolean).join(' · ')}
      />
      <Connector links={marketLinks} />
      <div className="rounded-lg border bg-surface p-3">
        <div className="mb-2 text-[11px] tracking-wide text-muted-foreground uppercase">
          Yes/no bets in this game (markets): {tree.markets.length}
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {tree.markets.map((m) => (
            <div key={m.ticker} className="flex items-start justify-between gap-3 rounded-md border bg-card px-3 py-2">
              <div className="min-w-0">
                <div className="truncate font-mono text-xs">{m.ticker}</div>
                <div className="text-xs text-muted-foreground">
                  {m.yes_sub_title ?? '–'} · <span className="font-mono">{m.status ?? '–'}</span>
                </div>
                <div className="text-[11px] text-muted-foreground/80">
                  {fmtUtc(m.open_time, false)} → {fmtUtc(m.close_time, false)}
                </div>
              </div>
              <Link
                to={`/timestamps?market=${encodeURIComponent(m.ticker)}&series=${encodeURIComponent(tree.series.ticker)}`}
                className="inline-flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
              >
                <Clock className="size-3" /> See price history
              </Link>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
