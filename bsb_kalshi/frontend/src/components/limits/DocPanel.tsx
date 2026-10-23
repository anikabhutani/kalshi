import { useState } from 'react'
import { ChevronDown, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { DataTable, type Column } from '@/components/DataTable'
import { JobProgress } from '@/components/JobProgress'
import { StatTile } from '@/components/StatTile'
import type { AccountLimitsResult, PaginationResult, RampResult, RateDoc } from '@/lib/api'
import type { ModuleJob } from '@/hooks/useModuleJob'
import { fmtNum } from '@/lib/format'

type TierRow = RateDoc['tiers'][number]

const TIER_COLUMNS: Column<TierRow>[] = [
  { key: 'tier', header: 'Account level', value: (t) => t.tier },
  { key: 'read', header: 'Reading budget (tokens/s)', value: (t) => t.read_budget, render: (t) => fmtNum(t.read_budget), className: 'text-right tabular-nums' },
  { key: 'write', header: 'Trading budget (tokens/s)', value: (t) => t.write_budget, render: (t) => fmtNum(t.write_budget), className: 'text-right tabular-nums' },
]

interface CompareRow {
  item: string
  documented: string
  api: string
  measured: string
}

const COMPARE_COLUMNS: Column<CompareRow>[] = [
  { key: 'item', header: 'What', value: (r) => r.item, className: 'min-w-48' },
  { key: 'doc', header: 'Kalshi’s docs say', value: (r) => r.documented, className: 'font-mono' },
  { key: 'api', header: 'Kalshi told us', value: (r) => r.api, className: 'font-mono' },
  { key: 'measured', header: 'We measured / set', value: (r) => r.measured, className: 'font-mono' },
]

function show(value: unknown): string {
  if (value === undefined || value === null || value === '') return '–'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function compareRows(doc: RateDoc, account: AccountLimitsResult | null, ramp: RampResult | null, pages: PaginationResult | null): CompareRow[] {
  const tierName = account?.limits?.usage_tier
  const tier = doc.tiers.find((t) => typeof tierName === 'string' && t.tier.toLowerCase() === tierName.toLowerCase())
  const clean = ramp?.steps.filter((s) => s.rate_limited === 0) ?? []
  const over = pages?.boundary.find((b) => b.case === 'Spec maximum + 1')
  return [
    {
      item: 'Cost of one request (tokens)',
      documented: show(doc.default_cost_tokens),
      api: show(account?.endpoint_costs?.default_cost),
      measured: '–',
    },
    { item: 'Our account level', documented: '–', api: show(tierName), measured: '–' },
    { item: 'Reading budget per second', documented: tier ? show(tier.read_budget) : '–', api: show(account?.limits?.read), measured: '–' },
    { item: 'Trading budget per second', documented: tier ? show(tier.write_budget) : '–', api: show(account?.limits?.write), measured: '–' },
    {
      item: 'This app’s own speed limit (Settings)',
      documented: '–',
      api: '–',
      measured: `${doc.client_limiter.rate_limit_rps} req/s, short bursts up to ${doc.client_limiter.rate_limit_burst}`,
    },
    {
      item: 'Fastest speed with no “slow down”',
      documented: '–',
      api: '–',
      measured: ramp === null ? 'not run' : clean.length > 0 ? `${Math.max(...clean.map((s) => s.target_rps))} req/s` : 'none',
    },
    {
      item: 'First “slow down” (429) in speed test',
      documented: '–',
      api: '–',
      measured:
        ramp === null
          ? 'not run'
          : ramp.first_429
            ? `${ramp.first_429.target_rps} req/s, request ${ramp.first_429.index + 1} of step ${ramp.first_429.step + 1}`
            : `none up to ${Math.max(0, ...ramp.rates)} req/s`,
    },
    {
      item: 'Does Kalshi say how much budget is left?',
      documented: '–',
      api: ramp === null ? 'not run' : (ramp.rate_header_names_seen ?? []).join(', ') || 'no',
      measured: '–',
    },
    {
      item: `Page size (${pages?.spec.path ?? 'page test'})`,
      documented: pages ? `normal ${show(pages.spec.size_default)}, max ${show(pages.spec.size_maximum)}` : '–',
      api: over ? `one over max → code ${show(over.status)}, ${show(over.items)} items` : '–',
      measured: '–',
    },
  ]
}

export function DocPanel({
  doc,
  account,
  onRunAccount,
  accountBusy,
  ramp,
  pages,
}: {
  doc: RateDoc
  account: ModuleJob<AccountLimitsResult>
  onRunAccount: () => void
  accountBusy: boolean
  ramp: RampResult | null
  pages: PaginationResult | null
}) {
  const [open, setOpen] = useState(false)
  const accountResult = account.job?.result ?? null
  return (
    <div className="grid gap-5">
      <div className="grid gap-3 sm:grid-cols-4">
        <StatTile label="Account levels in the docs" value={doc.tiers.length} />
        <StatTile label="Cost of one request" value={doc.default_cost_tokens !== null ? `${doc.default_cost_tokens} tokens` : '–'} />
        <StatTile label="This app’s speed limit" value={`${doc.client_limiter.rate_limit_rps} req/s`} hint={`short bursts up to ${doc.client_limiter.rate_limit_burst}`} />
        <StatTile label="Account key set up" value={doc.credentials_configured ? 'yes' : 'no'} tone={doc.credentials_configured ? 'primary' : 'warning'} />
      </div>
      <div className="grid gap-5 lg:grid-cols-[2fr_3fr]">
        <div className="grid content-start gap-2">
          <h3 className="text-xs font-semibold">Budget per account level (from Kalshi’s docs)</h3>
          <DataTable columns={TIER_COLUMNS} rows={doc.tiers} rowKey={(t) => t.tier} csvName="m5-documented-tiers.csv" empty="No tier table found." />
        </div>
        <div className="grid content-start gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold">Docs vs Kalshi vs our measurements</h3>
            <Button variant="outline" size="sm" onClick={onRunAccount} disabled={accountBusy || account.running}>
              <Play /> Read my account limits (2 requests)
            </Button>
          </div>
          {account.jobId !== null && <JobProgress jobId={account.jobId} stream={account.stream} />}
          <DataTable
            columns={COMPARE_COLUMNS}
            rows={compareRows(doc, accountResult, ramp, pages)}
            rowKey={(r) => r.item}
            csvName="m5-documented-vs-measured.csv"
            empty="–"
          />
          {accountResult?.calls.map((c) => (
            <p key={c.path} className="font-mono text-[11px] text-muted-foreground">
              GET {c.path} {c.auth ? '(with key)' : '(no key)'}: {c.status !== null ? `result code ${c.status}` : (c.note ?? c.error ?? '–')}
            </p>
          ))}
        </div>
      </div>
      <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border">
        <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-2.5 text-xs font-medium">
          Kalshi’s rate-limit docs, word for word
          <ChevronDown className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`} />
        </CollapsibleTrigger>
        <CollapsibleContent className="grid gap-4 border-t px-4 py-3">
          {doc.sections.map((s) => (
            <div key={s.heading} className="grid gap-1">
              <h4 className="text-xs font-semibold">{s.heading}</h4>
              <pre className="font-sans text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">{s.text}</pre>
            </div>
          ))}
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
