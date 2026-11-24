import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Download, FileDown, FolderOpen, ImageOff, Save } from 'lucide-react'
import { api, exportFileUrl, type ExportInfo, type ExportSummary, type QuestionId } from '@/lib/api'
import { figureToPngBase64 } from '@/lib/exportCharts'
import { fmtNum, fmtUtc } from '@/lib/format'
import { navItem, MODULE_LABELS } from '@/lib/nav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Chart } from '@/components/charts/Chart'
import { useGalleryCharts, type GalleryChart } from '@/components/evidence/useGalleryCharts'
import { EmptyState } from '@/components/EmptyState'
import { NotesBox } from '@/components/NotesBox'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { StatTile } from '@/components/StatTile'

const ITEM = navItem('/evidence')
const QUESTION_IDS: QuestionId[] = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6']

const todayUtc = () => new Date().toISOString().slice(0, 10)

function VersionConfirm({ summary }: { summary: ExportSummary }) {
  const queryClient = useQueryClient()
  const [version, setVersion] = useState(summary.api_version_confirmed ?? '')
  const [date, setDate] = useState(summary.date_checked ?? '')
  const save = useMutation({
    mutationFn: () => api.updateSettings({ api_version: version || null, date_checked: date || null }),
    onSuccess: () => {
      toast.success('Saved.')
      void queryClient.invalidateQueries({ queryKey: ['m8-summary'] })
      void queryClient.invalidateQueries({ queryKey: ['meta'] })
    },
  })
  const dirty = version !== (summary.api_version_confirmed ?? '') || date !== (summary.date_checked ?? '')
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <div className="grid gap-1.5">
        <Label htmlFor="m8-version">Kalshi docs version (confirm it)</Label>
        <div className="flex gap-2">
          <Input id="m8-version" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="not confirmed" className="w-40 font-mono" />
          <Button type="button" variant="outline" onClick={() => setVersion(summary.openapi_version)}>
            Use {summary.openapi_version}
          </Button>
        </div>
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="m8-date">Date the docs were checked</Label>
        <div className="flex gap-2">
          <Input id="m8-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-44 font-mono" />
          <Button type="button" variant="outline" onClick={() => setDate(todayUtc())}>
            Today
          </Button>
        </div>
      </div>
      <Button type="submit" disabled={!dirty || save.isPending}>
        <Save /> Save
      </Button>
      <p className="basis-full text-xs text-muted-foreground">
        Kalshi’s data docs are version <span className="font-mono">{summary.openapi_version}</span>, live stream docs version{' '}
        <span className="font-mono">{summary.asyncapi_version}</span>, server <span className="font-mono">{summary.base_url}</span>. If these
        aren’t confirmed, the report shows a blank to fill in.
      </p>
    </form>
  )
}

function Gallery({ charts, selected, onToggle }: { charts: GalleryChart[]; selected: Set<string>; onToggle: (name: string) => void }) {
  if (charts.length === 0) {
    return (
      <EmptyState icon={ImageOff} title="No charts yet">
        Run tests on the other pages; their charts will appear here.
      </EmptyState>
    )
  }
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      {charts.map((c) => (
        <div key={c.name} className="grid gap-2 rounded-lg border p-3">
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" className="accent-primary" checked={selected.has(c.name)} onChange={() => onToggle(c.name)} />
            <span className="font-medium">{c.title}</span>
            <Badge variant="outline">{MODULE_LABELS[c.module] ?? c.module}</Badge>
            <span className="ml-auto font-mono text-muted-foreground">charts/{c.name}.png</span>
          </label>
          <Chart data={c.figure.data} layout={c.figure.layout} height={Math.min(c.figure.height, 360)} filename={c.name} />
        </div>
      ))}
    </div>
  )
}

function ExportList({ exports }: { exports: ExportInfo[] }) {
  if (exports.length === 0) {
    return <EmptyState icon={FolderOpen} title="No reports built yet" />
  }
  return (
    <div className="grid gap-3">
      {exports.map((e) => (
        <details key={e.name} className="rounded-lg border px-4 py-2.5 text-xs" open={e === exports[0]}>
          <summary className="flex cursor-pointer flex-wrap items-center gap-2">
            <span className="font-mono text-foreground">{e.name}</span>
            <span className="text-muted-foreground">{fmtUtc(e.created_at)}</span>
            <Badge variant="secondary">{e.files.length} files</Badge>
            <a className="ml-auto inline-flex items-center gap-1 text-primary hover:underline" href={exportFileUrl(e.name, 'appendix.md')} download>
              <Download className="size-3.5" /> Download report (appendix.md)
            </a>
          </summary>
          <div className="mt-2 grid gap-1 border-t pt-2">
            <span className="font-mono text-muted-foreground">{e.path}</span>
            <ul className="grid gap-0.5 sm:grid-cols-2">
              {e.files.map((f) => (
                <li key={f.path} className="flex items-center gap-2">
                  <a className="font-mono text-primary hover:underline" href={exportFileUrl(e.name, f.path)} download>
                    {f.path}
                  </a>
                  <span className="text-muted-foreground">{fmtNum(f.bytes)} B</span>
                </li>
              ))}
            </ul>
          </div>
        </details>
      ))}
    </div>
  )
}

export function EvidencePage() {
  const queryClient = useQueryClient()
  const summary = useQuery({ queryKey: ['m8-summary'], queryFn: api.exportSummary })
  const exports = useQuery({ queryKey: ['m8-exports'], queryFn: api.exports })
  const { charts, loading } = useGalleryCharts()
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const selected = new Set(charts.map((c) => c.name).filter((n) => !excluded.has(n)))
  const toggle = (name: string) =>
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })

  const runExport = useMutation({
    mutationFn: async () => {
      const images = []
      for (const chart of charts.filter((c) => selected.has(c.name))) {
        images.push({ name: chart.name, png_base64: await figureToPngBase64(chart.figure) })
      }
      return api.createExport(images)
    },
    onSuccess: (info) => {
      toast.success(`Report built: ${info.name}`)
      void queryClient.invalidateQueries({ queryKey: ['m8-exports'] })
      void queryClient.invalidateQueries({ queryKey: ['m8-summary'] })
    },
  })

  const s = summary.data
  const totalRequests = s ? Object.values(s.requests_by_module).reduce((a, b) => a + b, 0) : 0
  const totalJobs = s ? Object.values(s.jobs_by_module).reduce((a, b) => a + b, 0) : 0

  return (
    <PageShell item={ITEM}>
      <Section
        title="Build the report"
        description="Creates one folder containing a written report (appendix.md), spreadsheets of every result (CSV files), and picture versions of the charts (PNG). It never includes the account key, and it never writes conclusions: the answers come only from the notes boxes below."
        actions={
          <Button size="lg" disabled={runExport.isPending || s === undefined} onClick={() => runExport.mutate()}>
            <FileDown /> {runExport.isPending ? 'Drawing charts…' : `Build report (${selected.size} charts)`}
          </Button>
        }
      >
        {s === undefined ? (
          <Skeleton className="h-28 w-full" />
        ) : (
          <div className="grid gap-5">
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <StatTile label="Requests saved" value={fmtNum(totalRequests)} />
              <StatTile label="Tests run" value={fmtNum(totalJobs)} />
              <StatTile label="Answers written" value={`${s.notes_written.length} / ${s.questions.length}`} tone={s.notes_written.length === s.questions.length ? 'primary' : 'warning'} />
              <StatTile label="Docs version confirmed" value={s.api_version_confirmed ?? 'no'} tone={s.api_version_confirmed ? 'primary' : 'warning'} />
              <StatTile label="Docs checked on" value={s.date_checked ?? 'no'} tone={s.date_checked ? 'primary' : 'warning'} />
              <StatTile label="Reports built so far" value={s.exports} />
            </div>
            <div className="flex flex-wrap gap-1.5 text-xs">
              {Object.entries(s.requests_by_module)
                .sort()
                .map(([module, n]) => (
                  <Badge key={module} variant="outline">
                    {MODULE_LABELS[module] ?? module}: {n} requests
                  </Badge>
                ))}
            </div>
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span className="text-muted-foreground">Latest result used from each test:</span>
              {Object.entries(s.latest_results).map(([key, job]) => (
                <Badge key={key} variant={job ? 'secondary' : 'outline'} className="font-mono">
                  {key}: {job ? `run ${job.id.slice(0, 8)}` : 'not run yet'}
                </Badge>
              ))}
            </div>
            <VersionConfirm key={`${s.api_version_confirmed}-${s.date_checked}`} summary={s} />
          </div>
        )}
      </Section>

      <Section title="Charts to include" description="The same charts shown on each page. Untick any you don’t want in the report.">
        {loading ? <Skeleton className="h-64 w-full" /> : <Gallery charts={charts} selected={selected} onToggle={toggle} />}
      </Section>

      <Section title="Reports built so far" description="Newest first. Click a file name to download it.">
        {exports.data === undefined ? <Skeleton className="h-20 w-full" /> : <ExportList exports={exports.data} />}
      </Section>

      <div className="grid gap-4">
        <h2 className="text-sm font-semibold">Answers to each question (copied word for word into the report)</h2>
        {QUESTION_IDS.map((q) => (
          <NotesBox key={q} questionId={q} />
        ))}
      </div>

      <RawRequestsDrawer />
    </PageShell>
  )
}
