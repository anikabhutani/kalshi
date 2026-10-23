import { useMemo, useState, type ReactNode } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { api, type EventItem, type SeriesItem } from '@/lib/api'
import { fmtUtc } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { NativeSelect } from '@/components/NativeSelect'

function PickList<T>({
  items,
  loading,
  selected,
  itemKey,
  onSelect,
  render,
  emptyText,
}: {
  items: T[]
  loading: boolean
  selected: string
  itemKey: (item: T) => string
  onSelect: (item: T) => void
  render: (item: T) => ReactNode
  emptyText: string
}) {
  if (loading) return <Skeleton className="h-64 w-full" />
  if (items.length === 0) return <p className="rounded-lg border p-4 text-xs text-muted-foreground">{emptyText}</p>
  return (
    <ul className="max-h-64 overflow-y-auto rounded-lg border">
      {items.map((item) => (
        <li key={itemKey(item)}>
          <button
            type="button"
            onClick={() => onSelect(item)}
            className={cn(
              'w-full border-b px-3 py-2 text-left text-xs last:border-b-0 hover:bg-accent/40',
              itemKey(item) === selected && 'bg-primary/10 text-primary',
            )}
          >
            {render(item)}
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Category -> tag -> series -> event browser. Categories and tags come from the API. */
export function GamePicker({
  seriesTicker,
  eventTicker,
  onSeries,
  onEvent,
}: {
  seriesTicker: string
  eventTicker: string
  onSeries: (ticker: string) => void
  onEvent: (ticker: string) => void
}) {
  const [category, setCategory] = useState<string | null>(null)
  const [tag, setTag] = useState('')
  const [seriesFilter, setSeriesFilter] = useState('')
  const [status, setStatus] = useState('')
  const [eventFilter, setEventFilter] = useState('')

  const { data: cats, isLoading: catsLoading } = useQuery({ queryKey: ['m2-categories'], queryFn: api.categories })
  const activeCategory = category ?? cats?.suggested_category ?? cats?.categories[0]?.name ?? null
  const tags = cats?.categories.find((c) => c.name === activeCategory)?.tags ?? []

  const series = useQuery({
    queryKey: ['m2-series', activeCategory, tag],
    queryFn: () => api.series(activeCategory!, tag || null),
    enabled: activeCategory !== null,
  })
  const visibleSeries = useMemo(() => {
    const needle = seriesFilter.trim().toLowerCase()
    const rows = series.data ?? []
    return needle ? rows.filter((s) => `${s.ticker} ${s.title}`.toLowerCase().includes(needle)) : rows
  }, [series.data, seriesFilter])

  const events = useInfiniteQuery({
    queryKey: ['m2-events', seriesTicker, status],
    queryFn: ({ pageParam }) => api.events(seriesTicker, status || null, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.cursor,
    enabled: seriesTicker !== '',
  })
  const visibleEvents = useMemo(() => {
    const needle = eventFilter.trim().toLowerCase()
    const rows = events.data?.pages.flatMap((p) => p.events) ?? []
    return needle
      ? rows.filter((e) => `${e.event_ticker} ${e.title ?? ''} ${e.sub_title ?? ''}`.toLowerCase().includes(needle))
      : rows
  }, [events.data, eventFilter])

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="grid content-start gap-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="m2-category">Category</Label>
            <NativeSelect
              id="m2-category"
              value={activeCategory ?? ''}
              disabled={catsLoading}
              onChange={(e) => {
                setCategory(e.target.value)
                setTag('')
              }}
            >
              {cats?.categories.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="m2-tag">Sport</Label>
            <NativeSelect id="m2-tag" value={tag} onChange={(e) => setTag(e.target.value)} disabled={tags.length === 0}>
              <option value="">All</option>
              {tags.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </NativeSelect>
          </div>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={seriesFilter}
            onChange={(e) => setSeriesFilter(e.target.value)}
            placeholder={`Search ${series.data?.length ?? 0} leagues / series…`}
            className="pl-8"
          />
        </div>
        <PickList<SeriesItem>
          items={visibleSeries}
          loading={catsLoading || series.isLoading}
          selected={seriesTicker}
          itemKey={(s) => s.ticker}
          onSelect={(s) => {
            onSeries(s.ticker)
            onEvent('')
          }}
          render={(s) => (
            <>
              <span className="font-mono">{s.ticker}</span>
              <span className="ml-2 text-muted-foreground">{s.title}</span>
              {s.frequency !== null && <span className="ml-2 text-muted-foreground/70">· {s.frequency}</span>}
            </>
          )}
          emptyText="Nothing found for this category and sport."
        />
        {cats !== undefined && cats.sport_ordering.length > 0 && (
          <p className="text-[11px] text-muted-foreground">
            Sports Kalshi lists: {cats.sport_ordering.join(', ')}
          </p>
        )}
      </div>

      <div className="grid content-start gap-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="m2-status">Game status</Label>
            <NativeSelect id="m2-status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any</option>
              {cats?.event_statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="m2-event-filter">Search games</Label>
            <Input
              id="m2-event-filter"
              value={eventFilter}
              onChange={(e) => setEventFilter(e.target.value)}
              placeholder="Team, date, code…"
            />
          </div>
        </div>
        <PickList<EventItem>
          items={visibleEvents}
          loading={events.isLoading && seriesTicker !== ''}
          selected={eventTicker}
          itemKey={(e) => e.event_ticker}
          onSelect={(e) => onEvent(e.event_ticker)}
          render={(e) => (
            <>
              <div className="font-mono">{e.event_ticker}</div>
              <div className="text-muted-foreground">
                {e.title}
                {e.sub_title && ` · ${e.sub_title}`}
                {e.strike_date && ` · settles ${fmtUtc(e.strike_date, false)}`}
              </div>
            </>
          )}
          emptyText={seriesTicker === '' ? 'Pick a league / series on the left first.' : 'No games found for this choice.'}
        />
        {events.hasNextPage && (
          <Button variant="outline" size="sm" onClick={() => void events.fetchNextPage()} disabled={events.isFetchingNextPage}>
            Load more games (1 request)
          </Button>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="m2-series-ticker">League code (series)</Label>
            <Input
              id="m2-series-ticker"
              value={seriesTicker}
              onChange={(e) => onSeries(e.target.value.trim())}
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="m2-event-ticker">Game code (event)</Label>
            <Input
              id="m2-event-ticker"
              value={eventTicker}
              onChange={(e) => onEvent(e.target.value.trim())}
              className="font-mono"
            />
          </div>
        </div>
      </div>
    </div>
  )
}
