import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, CircleCheck, CircleDashed, FlaskConical, Play } from 'lucide-react'
import { api, type SanityCheckRow, type SanityResult } from '@/lib/api'
import { MODULE_LABELS, NAV_ITEMS, QUESTION_PLAIN } from '@/lib/nav'
import { useJobStream } from '@/hooks/useJobStream'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { cn } from '@/lib/utils'

const HOME = NAV_ITEMS[0]!

const STEPS: { title: string; body: string }[] = [
  {
    title: '1. Ask Kalshi for data',
    body: 'Each page runs a small test that requests real data from Kalshi, such as prices, trades, or game lists. It only reads; it never bets or touches money.',
  },
  {
    title: '2. Keep a receipt',
    body: 'Every request is saved with the time, what was asked, and what came back, so every number in the report can be traced to its source.',
  },
  {
    title: '3. Measure and chart',
    body: 'The app counts, times, and compares what came back, then draws tables and charts. It does not draw conclusions.',
  },
  {
    title: '4. Write the answer',
    body: 'Each question has a notes box at the bottom of its page where the answer is written in plain words, backed by the numbers above it.',
  },
]

const GLOSSARY: { term: string; meaning: string }[] = [
  { term: 'API', meaning: 'The doorway Kalshi provides for programs to request data, instead of a person clicking around the website.' },
  { term: 'Endpoint', meaning: 'One specific address in the API, like a menu item. For example, “list of markets” or “price history”.' },
  { term: 'Request', meaning: 'One question sent to Kalshi, such as “give me the price history for this game”.' },
  { term: 'Market / contract', meaning: 'A single yes/no bet on Kalshi, e.g. “Will Seattle win?”. Its price (1¢–99¢) acts like a probability.' },
  { term: 'Event / series', meaning: 'An event is one game that holds several markets. A series is the league-level group, e.g. all NFL games.' },
  { term: 'Candlestick (candle)', meaning: 'A summary of prices over a time slot (e.g. one minute): the opening, highest, lowest and closing price.' },
  { term: 'Checking (REST / polling)', meaning: 'Asking Kalshi “what is the price now?” over and over every few seconds.' },
  { term: 'Live stream (WebSocket)', meaning: 'An open connection where Kalshi pushes every change to us the moment it happens.' },
  { term: 'Account key', meaning: 'A private login credential for programs. It stays on this computer and is never shown or saved in exports.' },
  { term: 'Rate limit', meaning: 'Kalshi’s cap on how many requests we may send per second. Going over gets a “slow down” reply (code 429).' },
  { term: 'Archive (historical)', meaning: 'Older data that Kalshi moves out of the live system into a separate store.' },
  { term: 'UTC', meaning: 'A worldwide standard clock (London winter time). All times here use it so nothing gets mixed up.' },
]

function HowItWorks() {
  return (
    <Section title="How it works" description="The same four steps happen on every page.">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {STEPS.map((s) => (
          <div key={s.title} className="rounded-lg border bg-surface p-4">
            <h3 className="text-sm font-semibold">{s.title}</h3>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{s.body}</p>
          </div>
        ))}
      </div>
    </Section>
  )
}

function Glossary() {
  return (
    <Section title="Plain-English glossary" description="Terms you will see around the app.">
      <dl className="grid gap-x-6 gap-y-3 md:grid-cols-2">
        {GLOSSARY.map((g) => (
          <div key={g.term} className="text-sm">
            <dt className="font-medium">{g.term}</dt>
            <dd className="text-xs leading-relaxed text-muted-foreground">{g.meaning}</dd>
          </div>
        ))}
      </dl>
    </Section>
  )
}

function QuestionCards() {
  const { data, isLoading } = useQuery({ queryKey: ['home'], queryFn: api.home })
  if (isLoading || data === undefined) {
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-52 rounded-xl" />
        ))}
      </div>
    )
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {data.map((q) => (
        <article key={q.id} className="flex flex-col gap-4 rounded-xl border bg-card p-5 transition-colors hover:border-primary/30">
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 font-mono text-sm font-semibold text-primary">
              {q.id}
            </span>
            <div className="min-w-0">
              <h3 className="font-semibold leading-tight">{QUESTION_PLAIN[q.id].title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{QUESTION_PLAIN[q.id].prompt}</p>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] text-muted-foreground">Pages that help answer it:</span>
            <div className="flex flex-wrap gap-1.5">
              {q.modules.map((m) => (
                <Badge key={m} variant="outline">
                  {MODULE_LABELS[m] ?? m}
                </Badge>
              ))}
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-2 rounded-lg bg-surface p-3 text-center">
            <div>
              <dt className="text-[11px] text-muted-foreground">Tests run</dt>
              <dd className="font-mono text-lg tabular-nums">{q.jobs_run}</dd>
            </div>
            <div>
              <dt className="text-[11px] text-muted-foreground">Requests saved</dt>
              <dd className="font-mono text-lg tabular-nums">{q.evidence_count}</dd>
            </div>
            <div>
              <dt className="text-[11px] text-muted-foreground">Answer written</dt>
              <dd className="flex h-7 items-center justify-center">
                {q.has_notes ? (
                  <CircleCheck className="size-5 text-primary" />
                ) : (
                  <CircleDashed className="size-5 text-muted-foreground" />
                )}
              </dd>
            </div>
          </dl>
          <Link to={q.page} className={cn(buttonVariants({ variant: 'outline' }), 'mt-auto justify-between')}>
            Open page <ArrowRight />
          </Link>
        </article>
      ))}
    </div>
  )
}

const SANITY_COLUMNS: Column<SanityCheckRow>[] = [
  { key: 'label', header: 'Check', value: (r) => r.label },
  { key: 'path', header: 'Address asked', value: (r) => `GET ${r.path}`, className: 'font-mono' },
  { key: 'auth', header: 'Used account key?', value: (r) => (r.auth ? 'yes' : 'no') },
  { key: 'status', header: 'Result code (200 = OK)', value: (r) => r.status_code, className: 'font-mono' },
  { key: 'latency', header: 'Response time (ms)', value: (r) => r.latency_ms, className: 'font-mono tabular-nums' },
  { key: 'server', header: 'Kalshi’s clock', value: (r) => r.server_date, className: 'font-mono' },
  { key: 'local', header: 'Our clock', value: (r) => r.local_received_at, className: 'font-mono' },
  { key: 'offset', header: 'Clock difference (s)', value: (r) => r.clock_offset_s, className: 'font-mono tabular-nums' },
  { key: 'error', header: 'Problem', value: (r) => r.error, className: 'text-destructive' },
]

function SanityCheck() {
  const [jobId, setJobId] = useState<string | null>(null)
  const stream = useJobStream(jobId)
  const run = useMutation({ mutationFn: api.runSanityCheck, onSuccess: (res) => setJobId(res.job_id) })
  const finished = stream.status !== null && stream.status !== 'running'
  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.job<SanityResult>(jobId!),
    enabled: jobId !== null && finished,
  })

  return (
    <Section
      title="Quick connection test"
      description="Sends just two requests to make sure everything works: one that anyone can make, and one that uses our account key. Both are saved as receipts."
      actions={
        <Button size="lg" onClick={() => run.mutate()} disabled={run.isPending || stream.status === 'running'}>
          <Play /> Run test
        </Button>
      }
    >
      <div className="grid gap-4">
        {jobId === null ? (
          <EmptyState icon={FlaskConical} title="Not run yet">
            Press “Run test” to check that Kalshi is reachable and that our account key is accepted.
          </EmptyState>
        ) : (
          <JobProgress jobId={jobId} stream={stream} />
        )}
        {job?.result && (
          <DataTable
            columns={SANITY_COLUMNS}
            rows={job.result.checks}
            rowKey={(r) => r.label}
            csvName="sanity-check.csv"
            empty={null}
          />
        )}
        {jobId !== null && <RawRequestsDrawer jobId={jobId} />}
      </div>
    </Section>
  )
}

export function HomePage() {
  return (
    <PageShell item={HOME}>
      <HowItWorks />
      <QuestionCards />
      <SanityCheck />
      <Glossary />
    </PageShell>
  )
}
