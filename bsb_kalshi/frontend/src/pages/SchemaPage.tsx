import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Database, Download } from 'lucide-react'
import { api, type LinkRow, type PullResult } from '@/lib/api'
import { navItem } from '@/lib/nav'
import { fmtUtc } from '@/lib/format'
import { useModuleJob } from '@/hooks/useModuleJob'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { NotesBox } from '@/components/NotesBox'
import { PageShell, Section } from '@/components/PageShell'
import { RawJsonViewer } from '@/components/RawJsonViewer'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { StatTile } from '@/components/StatTile'
import { FieldDictionary } from '@/components/schema/FieldDictionary'
import { GamePicker } from '@/components/schema/GamePicker'
import { RelationshipTree } from '@/components/schema/RelationshipTree'

const ITEM = navItem('/schema')

const LINK_COLUMNS: Column<LinkRow>[] = [
  { key: 'child', header: 'Field in the lower level', value: (l) => l.child, className: 'font-mono' },
  { key: 'parent', header: 'Points to (upper level)', value: (l) => l.parent, className: 'font-mono' },
  { key: 'matching', header: 'Rows that matched', value: (l) => l.matching, className: 'font-mono tabular-nums' },
  { key: 'records', header: 'Rows checked', value: (l) => l.records, className: 'font-mono tabular-nums' },
]

function Results({ result }: { result: PullResult }) {
  const { entities, nested_vs_list: nested } = result
  const timestampFields = Object.values(entities).reduce(
    (sum, e) => sum + e.fields.filter((f) => f.timestamp_like).length,
    0,
  )
  return (
    <>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Facts about the league" value={entities.series.fields.length} />
        <StatTile label="Facts about the game" value={entities.event.fields.length} />
        <StatTile label="Facts about each bet" value={entities.market.fields.length} />
        <StatTile label="Bets in this game" value={result.tree.markets.length} />
        <StatTile label="Fields that hold a time" value={timestampFields} tone="primary" />
        <StatTile label="Bets came from" value={<span className="text-sm">{result.markets_source}</span>} />
      </div>

      <Section
        title="How it fits together"
        description="Kalshi nests data like folders: a league (series) holds games (events), and each game holds yes/no bets (markets). The table shows which field links each level to the one above it, checked on every row."
      >
        <div className="grid gap-5 xl:grid-cols-[3fr_2fr]">
          <RelationshipTree result={result} />
          <div className="grid content-start gap-4">
            <DataTable
              columns={LINK_COLUMNS}
              rows={result.links}
              rowKey={(l) => l.child}
              csvName="m2-links.csv"
              empty={<p className="text-xs text-muted-foreground">No linking fields found.</p>}
            />
            <dl className="grid gap-1.5 rounded-lg border bg-surface p-3 text-xs">
              <div className="mb-1 font-medium">Two ways to get a game’s bets: do they agree?</div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Bets included with the game</dt>
                <dd className="font-mono">{nested.nested_count}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Bets from the separate bets list</dt>
                <dd className="font-mono">{nested.list_count}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Only with the game</dt>
                <dd className="font-mono">{nested.only_in_nested.join(', ') || '–'}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Only in the bets list</dt>
                <dd className="font-mono">{nested.only_in_list.join(', ') || '–'}</dd>
              </div>
            </dl>
          </div>
        </div>
      </Section>

      <Section
        title="Every piece of information Kalshi sent"
        description="A dictionary of every field in the data we got back, with what kind of value it holds (number, text, time…) and a real example."
      >
        <FieldDictionary result={result} />
      </Section>

      <Section title="Original data, exactly as received" description="The untouched replies from Kalshi, kept as proof.">
        <RawJsonViewer
          sources={[
            { label: 'League (series)', requestId: entities.series.request_id },
            { label: 'Game with its bets (event)', requestId: entities.event.request_id },
            { label: 'Bets list (markets)', requestId: entities.market.request_id },
          ]}
        />
      </Section>
    </>
  )
}

export function SchemaPage() {
  const [seriesTicker, setSeriesTicker] = useState('')
  const [eventTicker, setEventTicker] = useState('')
  const job = useModuleJob<PullResult>('M2', 'pull_game')
  const pull = useMutation({
    mutationFn: () => api.pullGame(seriesTicker, eventTicker),
    onSuccess: (res) => job.start(res.job_id),
  })

  return (
    <PageShell item={ITEM}>
      <Section
        title="Pick a game"
        description="Choose a league and a game from Kalshi’s live lists. Pressing “Get game data” downloads that one game (3–4 requests) so we can see exactly how Kalshi structures it."
        actions={
          <Button
            size="lg"
            onClick={() => pull.mutate()}
            disabled={seriesTicker === '' || eventTicker === '' || pull.isPending || job.running}
          >
            <Download /> Get game data
          </Button>
        }
      >
        <div className="grid gap-4">
          <GamePicker
            seriesTicker={seriesTicker}
            eventTicker={eventTicker}
            onSeries={setSeriesTicker}
            onEvent={setEventTicker}
          />
          {job.jobId !== null && <JobProgress jobId={job.jobId} stream={job.stream} />}
        </div>
      </Section>

      {job.loading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : job.job?.result ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            Showing game <span className="font-mono text-foreground">{job.job.result.event_ticker}</span>
            <span>downloaded {fmtUtc(job.job.finished_at)}</span>
            <Badge variant="outline" className="font-mono">
              run {job.job.id.slice(0, 8)}
            </Badge>
          </div>
          <Results key={job.job.id} result={job.job.result} />
        </>
      ) : (
        !job.running && (
          <EmptyState icon={Database} title="No game downloaded yet">
            Pick a league and a game above, then press “Get game data”.
          </EmptyState>
        )
      )}

      <RawRequestsDrawer module="M2" />
      <NotesBox questionId="Q1" />
    </PageShell>
  )
}
