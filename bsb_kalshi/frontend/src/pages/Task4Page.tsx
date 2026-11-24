import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CheckCircle2, CircleDashed, CircleMinus, CircleX, Download, Play, Scale, TriangleAlert } from 'lucide-react'
import { t4Api, type T4Check, type T4Facts, type T4Results, type T4Season, type T4State } from '@/lib/api'
import { fmtNum, fmtUtc } from '@/lib/format'
import { navItem } from '@/lib/nav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Chart } from '@/components/charts/Chart'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { PageShell, Section } from '@/components/PageShell'
import { StatTile } from '@/components/StatTile'
import {
  BOOKS,
  MARKETS,
  MARKET_LABEL,
  TIME_BUCKETS,
  bookMarketFigure,
  favoritesFigure,
  kickoffFigure,
  priceGroupFigure,
  weekFigure,
} from '@/components/task4/figures'

const ITEM = navItem('/task4')

type StepState = 'done' | 'partial' | 'todo'

function StepIcon({ state }: { state: StepState }) {
  if (state === 'done') return <CheckCircle2 className="size-4 shrink-0 text-primary" />
  if (state === 'partial') return <CircleDashed className="size-4 shrink-0 text-warning" />
  return <CircleDashed className="size-4 shrink-0 text-muted-foreground" />
}

const money = (v: number | null | undefined) => (v == null ? '—' : `$${v.toFixed(2)}`)
const plural = (n: number, word: string) => `${fmtNum(n)} ${word}${n === 1 ? '' : 's'}`
const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' }) : '—'

/** "285 games (272 regular season + 13 playoff), Sep 4, 2025 – Feb 8, 2026" — all from the season's facts. */
function seasonLine(f: T4Facts): string {
  const split = f.playoff_games ? ` (${fmtNum(f.regular_season_games)} regular season + ${fmtNum(f.playoff_games)} playoff)` : ''
  return `${plural(f.games, 'game')}${split}, ${day(f.first_kickoff)} – ${day(f.last_kickoff)}`
}

/** Books that end up with fewer closing lines than games (stale last prices left out). */
function closingNote(f: T4Facts): string {
  const short = Object.entries(f.games_by_book_at_close).filter(([, n]) => n < f.games)
  const window = `Closing line = last price ${f.closing_minutes_min}–${f.closing_minutes_max} min before kickoff.`
  if (!short.length) return window
  return `${window} ${short.map(([b, n]) => `${b} ${n}`).join(', ')} of ${f.games} games: a last price older than an hour isn’t counted as a closing line.`
}

function kickoffNote(f: T4Facts): string {
  const parts = Object.entries(f.time_bucket_games)
    .map(([book, buckets]) => {
      const thin = TIME_BUCKETS.filter((b) => (buckets[b] ?? 0) < f.games).map((b) => `${b}: ${buckets[b] ?? 0}`)
      return thin.length ? `${book} ${thin.join(', ')}` : null
    })
    .filter(Boolean)
  return parts.length
    ? `Games with a moneyline price in each bucket, where fewer than ${f.games}: ${parts.join('; ')}.`
    : `All three sportsbooks have prices for all ${f.games} games in every bucket.`
}

function weekNote(f: T4Facts): string {
  const notes = []
  if (f.last_week_partial) notes.push(`Week ${f.last_week} has ${plural(f.last_week_games, 'game')} so far.`)
  if (f.playoff_games) notes.push(`After week 18: playoff rounds (${plural(f.playoff_games, 'game')}).`)
  return notes.join(' ')
}

/** One block per season, side by side on wide screens (or stacked when `stack`). */
function BySeason({ seasons, stack, children }: { seasons: T4Season[]; stack?: boolean; children: (s: T4Season) => ReactNode }) {
  return (
    <div className={stack ? 'grid gap-6' : 'grid gap-6 xl:grid-cols-2'}>
      {seasons.map((s) => (
        <div key={s.season} className="grid min-w-0 content-start gap-2">
          <div className="flex flex-wrap items-baseline gap-2">
            <Badge>{s.season} season</Badge>
            <span className="text-xs text-muted-foreground">{seasonLine(s.facts)}</span>
          </div>
          {children(s)}
        </div>
      ))}
    </div>
  )
}

function SeasonPicker({ seasons, value, onChange }: { seasons: T4Season[]; value: number; onChange: (s: number) => void }) {
  return (
    <div className="flex gap-1">
      {seasons.map((s) => (
        <Button key={s.season} size="sm" variant={value === s.season ? 'default' : 'outline'} onClick={() => onChange(s.season)}>
          {s.season}
        </Button>
      ))}
    </div>
  )
}

function Brief({ state, results }: { state: T4State; results: T4Results | null }) {
  const seasons = results?.seasons ?? []
  const qc = (s: T4Season, check: string) => s.qc_summary.filter((q) => q.check === check).reduce((n, q) => n + q.issues, 0)
  const per = (fn: (s: T4Season) => string) => seasons.map((s) => `${s.season}: ${fn(s)}`).join(' · ')
  const failed = seasons.flatMap((s) => s.checks.filter((c) => c.status === 'fail'))
  const steps: { text: string; state: StepState; detail: string }[] = [
    {
      text: 'List every NFL game and which books posted each market (2025 and 2026 seasons)',
      state: results ? 'done' : 'todo',
      detail: results ? per((s) => seasonLine(s.facts)) : 'Run below.',
    },
    {
      text: 'Write sportsbook_backfill.py and run it for all NFL games; save raw',
      state: state.games_saved > 0 ? 'done' : 'todo',
      detail:
        state.games_saved > 0
          ? `backend/app/task4/sportsbook_backfill.py. ${fmtNum(state.games_complete)} games saved raw in ${state.raw_dir} (${Object.entries(state.games_by_season)
              .map(([s, n]) => `${s}: ${n}`)
              .join(', ')}). Source: odds export file; The Odds API source is a placeholder (no key).`
          : 'Not run yet.',
    },
    {
      text: 'Compute vig and cost per $10 for every game, book, market and snapshot time',
      state: results ? 'done' : 'todo',
      detail:
        'Cost per $10 = expected loss on a $10 bet at the fair (no-vig) price, found with Shin’s method, which lets the margin fall more on longshots, as research shows books do. Every snapshot is in costs_all_snapshots.csv; the simpler proportional method is kept as a check column.',
    },
    {
      text: 'Quality check our own data: missing Pinnacle lines, stale lines, bad odds',
      state: results ? 'done' : 'todo',
      detail: results
        ? per(
            (s) =>
              `${fmtNum(qc(s, 'missing_pinnacle_line'))} snapshots missing Pinnacle, ${fmtNum(qc(s, 'stale_closing_line'))} stale closing lines, ${fmtNum(
                s.qc_summary.filter((q) => q.check.startsWith('bad_odds')).reduce((n, q) => n + q.issues, 0),
              )} bad odds, ${fmtNum(qc(s, 'post_kickoff_snapshot_excluded'))} in-game snapshots excluded`,
          )
        : 'Runs after the backfill.',
    },
    {
      text: 'Results: cost per $10 by price group, market type, book and week; vig as kickoff gets closer; favorites vs longshots',
      state: results ? 'done' : 'todo',
      detail: results ? `Calculated ${fmtUtc(results.generated_at, false)}, separately for each season.` : 'Runs after the backfill.',
    },
    {
      text: 'Plain charts of those results, one per season',
      state: results ? 'done' : 'todo',
      detail: 'Below (2025 and 2026 side by side), and as PNGs in data/task4/charts/2025 and /2026.',
    },
    {
      text: 'Make the script pick up new games each day',
      state: 'partial',
      detail:
        'Reruns skip saved games. scripts/task4_daily.sh runs both steps; schedule it with cron. With a file source it only finds new games when the export file is replaced with a newer one.',
    },
  ]
  return (
    <Section title="Task 4: sportsbook vig and cost per $10 for every NFL game" description="The request, step by step, with where each step stands.">
      <ol className="grid gap-2.5">
        {steps.map((s, i) => (
          <li key={s.text} className="flex gap-2.5 text-sm">
            <StepIcon state={s.state} />
            <div className="grid gap-0.5">
              <span>
                <span className="mr-1.5 font-mono text-xs text-muted-foreground">{i + 1}.</span>
                {s.text}
              </span>
              <span className="text-xs text-muted-foreground">{s.detail}</span>
            </div>
          </li>
        ))}
      </ol>
      {failed.length > 0 && (
        <p className="mt-3 text-sm text-destructive">
          {plural(failed.length, 'self-check')} failed; see “Self-checks” below before using these numbers.
        </p>
      )}
    </Section>
  )
}

function RunSection({ state }: { state: T4State }) {
  const queryClient = useQueryClient()
  const [path, setPath] = useState(state.source_path ?? '')
  const run = useMutation({
    mutationFn: () => t4Api.run(path.trim() || null),
    onSuccess: (r) => {
      void queryClient.invalidateQueries({ queryKey: ['t4'] })
      const failed = r.seasons.reduce((n, s) => n + s.checks_failed, 0)
      const msg = `Done in ${r.seconds} s: ${r.backfill.saved_complete + r.backfill.saved_partial} new games saved, ${r.backfill.skipped_complete} already saved.`
      if (failed) toast.error(`${msg} ${failed} self-check(s) failed — see Self-checks.`)
      else toast.success(`${msg} All self-checks passed.`)
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Run failed.'),
  })
  return (
    <Section
      title="1. Load odds and calculate"
      description="Reads the odds export (odds_data.zip or history_americanfootball_nfl.csv) from this computer, saves games that have been played and aren't saved yet, then recalculates both seasons and runs the self-checks. No requests go to Kalshi."
    >
      <div className="grid gap-4">
        <div className="flex flex-wrap items-end gap-2">
          <div className="grid min-w-72 flex-1 gap-1">
            <Label htmlFor="t4-path" className="text-xs">Path to the odds export on this computer</Label>
            <Input id="t4-path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="~/Downloads/odds_data.zip" className="font-mono text-xs" />
          </div>
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            <Play className={run.isPending ? 'animate-pulse' : undefined} /> {run.isPending ? 'Running…' : 'Run backfill and calculate'}
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <StatTile
            label="Games saved"
            value={fmtNum(state.games_saved)}
            tone="primary"
            hint={Object.entries(state.games_by_season).map(([s, n]) => `${s}: ${n}`).join(', ')}
          />
          <StatTile label="Complete / partial" value={`${state.games_complete} / ${state.games_partial}`} hint="Complete = has a snapshot in the last hour before kickoff" />
          <StatTile label="Newest snapshot in source" value={state.source_as_of ? fmtUtc(state.source_as_of, false) : '—'} />
          <StatTile label="Last run" value={state.last_run ? fmtUtc(state.last_run, false) : '—'} />
        </div>
        <p className="text-xs text-muted-foreground">
          Daily: <code className="font-mono">scripts/task4_daily.sh</code> (or <code className="font-mono">make sportsbook</code>). API source: {state.api_source}.
        </p>
      </div>
    </Section>
  )
}

const STATUS: Record<T4Check['status'], { icon: ReactNode; label: string; className: string }> = {
  pass: { icon: <CheckCircle2 className="size-4 text-primary" />, label: 'pass', className: 'text-primary' },
  warn: { icon: <TriangleAlert className="size-4 text-warning" />, label: 'warning', className: 'text-warning' },
  fail: { icon: <CircleX className="size-4 text-destructive" />, label: 'FAILED', className: 'text-destructive' },
  skip: { icon: <CircleMinus className="size-4 text-muted-foreground" />, label: 'skipped', className: 'text-muted-foreground' },
}

function ChecksSection({ results }: { results: T4Results }) {
  const ids = results.seasons[0]?.checks.map((c) => c.id) ?? []
  const tally = (s: T4Season) =>
    (['pass', 'warn', 'skip', 'fail'] as const)
      .map((st) => [st, s.checks.filter((c) => c.status === st).length] as const)
      .filter(([, n]) => n)
      .map(([st, n]) => `${n} ${STATUS[st].label}`)
      .join(', ')
  return (
    <Section
      title="Self-checks"
      description="Run automatically after every calculation, for each season. Each one recomputes a result a second way, independently of the main calculation, and names the earlier mistake it guards against. A failed check means a number on this page can’t be trusted."
      actions={
        <div className="flex flex-wrap gap-2">
          {results.seasons.map((s) => (
            <Badge key={s.season} variant="outline">
              {s.season}: {tally(s)}
            </Badge>
          ))}
        </div>
      }
    >
      <div className="grid gap-3">
        {ids.map((id) => {
          const rows = results.seasons.map((s) => ({ season: s.season, check: s.checks.find((c) => c.id === id) }))
          const first = rows.find((r) => r.check)?.check
          if (!first) return null
          return (
            <div key={id} className="rounded-lg border bg-surface px-3 py-2.5">
              <div className="text-sm font-medium">{first.title}</div>
              <div className="mb-1.5 text-xs text-muted-foreground">Guards against: {first.guards}</div>
              <div className="grid gap-1">
                {rows.map(({ season, check }) =>
                  check ? (
                    <div key={season} className="flex items-start gap-2 text-xs">
                      {STATUS[check.status].icon}
                      <span className="w-10 shrink-0 font-mono">{season}</span>
                      <span className={`w-16 shrink-0 ${STATUS[check.status].className}`}>{STATUS[check.status].label}</span>
                      <span className="text-muted-foreground">{check.detail}</span>
                    </div>
                  ) : null,
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

type Game = T4Season['games'][number]

function GamesSection({ results }: { results: T4Results }) {
  const [season, setSeason] = useState(results.seasons.at(-1)?.season ?? 0)
  const s = results.seasons.find((x) => x.season === season) ?? results.seasons[0]
  if (!s) return null
  const columns: Column<Game>[] = [
    { key: 'week', header: 'Week', value: (g) => g.week, render: (g) => String(g.week_label ?? g.week) },
    { key: 'kickoff', header: 'Kickoff (ET)', value: (g) => g.commence_time, render: (g) => String(g.kickoff_et) },
    { key: 'game', header: 'Game', value: (g) => `${g.away_team} at ${g.home_team}` },
    ...BOOKS.map((b) => ({
      key: b,
      header: b,
      value: (g: Game) => MARKETS.filter((m) => g[`${b} ${m}`] === 'yes').map((m) => MARKET_LABEL[m]).join(', ') || 'none',
    })),
  ]
  return (
    <Section
      title="2. Every NFL game and which books posted each market"
      description={`Played games only. A book counts as posting a market if it had a line before kickoff. ${s.season}: ${seasonLine(s.facts)}.`}
      actions={<SeasonPicker seasons={results.seasons} value={s.season} onChange={setSeason} />}
    >
      <DataTable key={s.season} columns={columns} rows={s.games} rowKey={(g) => g.event_id} csvName={`task4-games-${s.season}.csv`} empty="No games" />
    </Section>
  )
}

const CHECK_LABEL: Record<string, string> = {
  missing_pinnacle_line: 'Pinnacle line missing at a snapshot where DraftKings or FanDuel had one',
  missing_pinnacle_closing_line: 'No Pinnacle line in the last hour before kickoff',
  stale_closing_line: 'Last price before kickoff more than an hour old (left out of closing-line results)',
  stale_line_last_update: 'Stale: book last updated the line more than 60 min before the snapshot',
  stale_line_pinnacle_off_market: 'Possibly stale: Pinnacle far from DraftKings and FanDuel (5 pts moneyline, 1.5 pts spread/total)',
  post_kickoff_snapshot_excluded: 'Snapshot taken after kickoff (live line, excluded)',
  bad_odds_invalid_american: 'Bad odds: missing or between −100 and +100',
  bad_odds_decimal_mismatch: 'Bad odds: decimal and American disagree',
  bad_odds_implied_prob_mismatch: 'Bad odds: implied probability in the file is wrong',
  bad_odds_unknown_outcome: 'Bad odds: outcome name matches neither team',
  bad_odds_negative_vig: 'Bad odds: negative vig (prices sum below 100%)',
  bad_odds_vig_above_12pct: 'Bad odds: vig above 12%',
  bad_odds_spread_points_not_opposite: 'Bad odds: spread points not opposite',
  bad_odds_total_points_differ: 'Bad odds: over and under have different totals',
}

function QualitySection({ results }: { results: T4Results }) {
  const [season, setSeason] = useState(results.seasons.at(-1)?.season ?? 0)
  const s = results.seasons.find((x) => x.season === season) ?? results.seasons[0]
  if (!s) return null
  type Row = T4Season['qc_summary'][number]
  const columns: Column<Row>[] = [
    { key: 'check', header: 'Check', value: (r) => CHECK_LABEL[r.check] ?? r.check },
    { key: 'book', header: 'Book', value: (r) => r.bookmaker },
    {
      key: 'issues',
      header: 'Issues',
      value: (r) => r.issues,
      render: (r) => <span className={r.issues > 0 ? 'text-warning' : 'text-muted-foreground'}>{fmtNum(r.issues)}</span>,
    },
    { key: 'games', header: 'Games', value: (r) => r.games },
  ]
  return (
    <Section
      title="3. Quality check of the odds data"
      description="Bad odds are dropped from the results. The books’ last-update times are always within a minute of the snapshot, so they can’t prove a line is stale; the Pinnacle-vs-market and stale-closing-line checks are the useful ones."
      actions={
        <div className="flex flex-wrap items-center gap-3">
          <SeasonPicker seasons={results.seasons} value={s.season} onChange={setSeason} />
          <a className="inline-flex items-center gap-1 text-xs text-primary hover:underline" href={t4Api.exportUrl(s.season, 'qc_issues.csv')}>
            <Download className="size-3.5" /> every issue (CSV)
          </a>
        </div>
      }
    >
      <DataTable key={s.season} columns={columns} rows={s.qc_summary} rowKey={(r) => `${r.check}|${r.bookmaker}`} csvName={`task4-qc-${s.season}.csv`} empty="No checks" />
    </Section>
  )
}

function KalshiSection({ results }: { results: T4Results }) {
  type Row = T4Season['kalshi_all_strikes'][number]
  const columns: Column<Row>[] = [
    { key: 'market', header: 'Bet', value: (r) => MARKET_LABEL[r.market] ?? r.market },
    { key: 'rows', header: 'Kalshi markets averaged', value: (r) => r.rows },
    { key: 'n', header: 'Games', value: (r) => r.n },
    { key: 'mean', header: 'Mean cost / $10', value: (r) => r.mean, render: (r) => money(r.mean) },
    { key: 'median', header: 'Median', value: (r) => r.median, render: (r) => money(r.median) },
  ]
  return (
    <Section
      title="Kalshi in these charts"
      description="Kalshi prices come from the Kalshi API through Task 3 (its downloaded candles and cost calculation); the sportsbooks come from the odds file. To compare like with like, Kalshi is shown at the 15-minute quote, 10 contracts, and for spreads and totals only the strike nearest 50¢ (sportsbooks post one main line near 50/50, Kalshi lists a ladder). Kalshi cost = half the bid-ask gap + Kalshi’s fee, against its mid price. It appears only in the ‘own fair price’ views, and only for seasons Task 3 has downloaded."
    >
      <BySeason seasons={results.seasons}>
        {(s) =>
          s.kalshi_info.available ? (
            <div className="grid gap-2">
              <div className="flex flex-wrap gap-2 text-xs">
                {Object.entries(s.kalshi_info.games_by_market ?? {}).map(([m, n]) => (
                  <Badge key={m} variant={n < s.facts.games ? 'secondary' : 'outline'}>
                    {MARKET_LABEL[m] ?? m}: {n} of {s.facts.games} games
                  </Badge>
                ))}
              </div>
              <DataTable columns={columns} rows={s.kalshi_all_strikes} rowKey={(r) => `${r.market}|${r.rows}`} csvName={`task4-kalshi-${s.season}.csv`} empty="No Kalshi rows" />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{s.kalshi_info.note ?? 'No Kalshi data for this season.'}</p>
          )
        }
      </BySeason>
    </Section>
  )
}

function BookMarketTable({ s }: { s: T4Season }) {
  type BM = T4Season['by_book_market'][number]
  const columns: Column<BM>[] = [
    { key: 'book', header: 'Book', value: (r) => r.bookmaker },
    { key: 'market', header: 'Bet', value: (r) => MARKET_LABEL[r.market] ?? r.market },
    { key: 'n', header: 'Games', value: (r) => r.n },
    { key: 'mean', header: 'Mean cost / $10', value: (r) => r.mean, render: (r) => money(r.mean) },
    { key: 'median', header: 'Median', value: (r) => r.median, render: (r) => money(r.median) },
    { key: 'min', header: 'Min', value: (r) => r.min, render: (r) => money(r.min) },
    { key: 'max', header: 'Max', value: (r) => r.max, render: (r) => money(r.max) },
    { key: 'vig', header: 'Mean vig', value: (r) => r.mean_overround, render: (r) => (r.mean_overround == null ? '—' : `${(r.mean_overround * 100).toFixed(2)}%`) },
  ]
  return <DataTable key={s.season} columns={columns} rows={s.by_book_market} rowKey={(r) => `${r.bookmaker}|${r.market}`} csvName={`task4-by-book-market-${s.season}.csv`} empty="No results" />
}

function ResultsSection({ results }: { results: T4Results }) {
  const [vsPin, setVsPin] = useState(false)
  const [tableSeason, setTableSeason] = useState(results.seasons.at(-1)?.season ?? 0)
  const seasons = results.seasons
  const figs = useMemo(
    () =>
      new Map(
        seasons.map((s) => [
          s.season,
          { bookMarket: bookMarketFigure(s), price: priceGroupFigure(s, vsPin), fav: favoritesFigure(s, vsPin) },
        ]),
      ),
    [seasons, vsPin],
  )
  const tableS = seasons.find((s) => s.season === tableSeason) ?? seasons[0]
  const longshotRange = seasons.map((s) => `${s.season}: ${s.facts.longshot_sides_min}–${s.facts.longshot_sides_max}`).join(', ')
  const toggle = (
    <div className="flex gap-1">
      <Button size="sm" variant={vsPin ? 'outline' : 'default'} onClick={() => setVsPin(false)}>vs book’s own fair price</Button>
      <Button size="sm" variant={vsPin ? 'default' : 'outline'} onClick={() => setVsPin(true)}>vs Pinnacle’s fair price</Button>
    </div>
  )
  return (
    <>
      <Section
        title="4. Cost per $10 by book and kind of bet (closing line)"
        description="Mean over each season’s games at the closing line. Kalshi, when Task 3 has data: 15-minute quote, main line, 10 contracts."
      >
        <BySeason seasons={seasons}>
          {(s) => (
            <>
              <Chart {...figs.get(s.season)!.bookMarket} filename={`task4-${s.season}-cost-by-book-market`} />
              <p className="text-xs text-muted-foreground">{closingNote(s.facts)}</p>
              <div className="flex flex-wrap gap-3 text-xs">
                <a className="inline-flex items-center gap-1 text-primary hover:underline" href={t4Api.exportUrl(s.season, 'costs_all_snapshots.csv')}>
                  <Download className="size-3.5" /> every snapshot (CSV)
                </a>
                <a className="inline-flex items-center gap-1 text-primary hover:underline" href={t4Api.exportUrl(s.season, 'summary.md')}>
                  <Download className="size-3.5" /> summary
                </a>
              </div>
            </>
          )}
        </BySeason>
        {tableS && (
          <div className="mt-6 grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">Table, {tableS.season} season</span>
              <SeasonPicker seasons={seasons} value={tableS.season} onChange={setTableSeason} />
            </div>
            <BookMarketTable s={tableS} />
          </div>
        )}
      </Section>

      <Section
        title="5. Moneyline cost per $10 by price group"
        description={`Groups by the side’s fair win probability (Shin’s method). ‘vs Pinnacle’ prices DraftKings and FanDuel against Pinnacle’s fair line instead of their own, as an outside check (Kalshi has no Pinnacle match and is grouped by its mid price). Longshot groups (under 25%) hold ${longshotRange} bets per sportsbook; small groups swing widely. Hover a bar for its count.`}
        actions={toggle}
      >
        <BySeason seasons={seasons}>
          {(s) => <Chart {...figs.get(s.season)!.price} filename={`task4-${s.season}-cost-by-price-group`} />}
        </BySeason>
      </Section>

      <Section title="6. Favorites vs underdogs vs longshots (moneyline, closing)" description="Longshots (under 25%) are also counted as underdogs. Hover a bar for its count." actions={toggle}>
        <BySeason seasons={seasons}>
          {(s) => <Chart {...figs.get(s.season)!.fav} filename={`task4-${s.season}-favorites-longshots`} />}
        </BySeason>
      </Section>

      <Section
        title="7. How cost changes as kickoff gets closer"
        description="Mean cost per $10 by time before kickoff; each game counts once per bucket. Kalshi (Task 3) has quotes only at 24 h, 3 h, 1 h and 15 min before kickoff."
      >
        <BySeason seasons={seasons} stack>
          {(s) => (
            <>
              <div className="grid gap-4 xl:grid-cols-3">
                {MARKETS.map((m) => (
                  <Chart key={m} {...kickoffFigure(s, m)} filename={`task4-${s.season}-kickoff-${m}`} />
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{kickoffNote(s.facts)}</p>
            </>
          )}
        </BySeason>
      </Section>

      <Section
        title="8. Cost per $10 by NFL week (closing line)"
        description="Weeks run Tuesday to Monday, Eastern. Moneyline moves week to week mostly with the mix of lopsided games (longshots cost more), not because prices changed; spreads and totals are flat."
      >
        <BySeason seasons={seasons} stack>
          {(s) => (
            <>
              <div className="grid gap-4 xl:grid-cols-3">
                {MARKETS.map((m) => (
                  <Chart key={m} {...weekFigure(s, m)} filename={`task4-${s.season}-week-${m}`} />
                ))}
              </div>
              {weekNote(s.facts) && <p className="text-xs text-muted-foreground">{weekNote(s.facts)}</p>}
            </>
          )}
        </BySeason>
      </Section>
    </>
  )
}

export function Task4Page() {
  const state = useQuery({ queryKey: ['t4', 'state'], queryFn: t4Api.state })
  const results = useQuery({ queryKey: ['t4', 'results'], queryFn: t4Api.results })
  const data = results.data && results.data.seasons?.length ? results.data : null
  return (
    <PageShell item={ITEM}>
      {state.isLoading || state.data === undefined ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : (
        <>
          <Brief state={state.data} results={data} />
          <RunSection state={state.data} />
          {results.isLoading ? (
            <Skeleton className="h-96 w-full rounded-xl" />
          ) : data ? (
            <>
              <ChecksSection results={data} />
              <GamesSection results={data} />
              <QualitySection results={data} />
              <KalshiSection results={data} />
              <ResultsSection results={data} />
              <p className="text-xs text-muted-foreground">
                <Badge variant="outline" className="mr-2">numbers only</Badge>
                This page shows what the data says; the conclusions in the write-up are yours.
              </p>
            </>
          ) : (
            <EmptyState icon={Scale} title="No results yet">
              Enter the path to the odds export and run it.
            </EmptyState>
          )}
        </>
      )}
    </PageShell>
  )
}
