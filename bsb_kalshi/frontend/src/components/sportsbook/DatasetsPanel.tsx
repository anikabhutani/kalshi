import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, FlaskConical, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { api, type DatasetSummary, type DatasetUpload, type Job } from '@/lib/api'
import { fmtUtc } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DataTable, type Column } from '@/components/DataTable'
import { NativeSelect } from '@/components/NativeSelect'
import { labRunLabel } from '@/components/sportsbook/labRuns'

const MAX_UPLOAD_BYTES = 2_000_000

export function DummyBadge() {
  return <Badge className="bg-warning/15 font-semibold tracking-wide text-warning">DUMMY DATA</Badge>
}

function UploadReport({ upload }: { upload: DatasetUpload }) {
  return (
    <div className="grid gap-1 rounded-lg border bg-surface p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{upload.name}</span>
        {upload.is_dummy && <DummyBadge />}
        <span className="text-muted-foreground">
          {upload.rows} valid row(s), {upload.error_count} line(s) skipped
        </span>
      </div>
      {upload.notes.map((n) => (
        <div key={n} className="text-muted-foreground">
          {n}
        </div>
      ))}
      {upload.errors.length > 0 && (
        <ul className="max-h-40 overflow-auto font-mono text-warning">
          {upload.errors.map((e) => (
            <li key={e.line}>
              line {e.line}: {e.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function DatasetsPanel({ datasets, labJobs }: { datasets: DatasetSummary[]; labJobs: Job<null>[] }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [labJobId, setLabJobId] = useState('')
  const [lastUpload, setLastUpload] = useState<DatasetUpload | null>(null)
  const selectedLab = labJobId || labJobs[0]?.id || ''

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['m7-datasets'] })
  const upload = useMutation({
    mutationFn: async () => {
      if (file === null) throw new Error('Choose a CSV file first.')
      if (file.size > MAX_UPLOAD_BYTES) throw new Error('The file is larger than 2 MB.')
      return api.uploadDataset(name.trim() || file.name, await file.text())
    },
    onSuccess: (res) => {
      setLastUpload(res)
      toast.success(`Stored ${res.rows} row(s).`)
      void refresh()
    },
  })
  const dummy = useMutation({
    mutationFn: () => api.dummyDataset(selectedLab),
    onSuccess: (res) => {
      setLastUpload(res)
      void refresh()
    },
  })
  const remove = useMutation({ mutationFn: api.deleteDataset, onSuccess: () => void refresh() })

  const columns: Column<DatasetSummary>[] = [
    {
      key: 'name',
      header: 'Odds file',
      value: (d) => d.name,
      render: (d) => (
        <span className="flex flex-wrap items-center gap-2">
          {d.name} {d.is_dummy && <DummyBadge />}
        </span>
      ),
    },
    { key: 'rows', header: 'Rows', value: (d) => d.rows, className: 'text-right tabular-nums' },
    { key: 'skipped', header: 'Lines skipped', value: (d) => d.error_count, className: 'text-right tabular-nums' },
    { key: 'books', header: 'Sportsbooks', value: (d) => d.books.join(', '), className: 'whitespace-normal' },
    { key: 'markets', header: 'Outcomes', value: (d) => d.markets.join(', '), className: 'whitespace-normal' },
    { key: 'first', header: 'Earliest', value: (d) => fmtUtc(d.first_ts), className: 'font-mono' },
    { key: 'last', header: 'Latest', value: (d) => fmtUtc(d.last_ts), className: 'font-mono' },
    {
      key: 'actions',
      header: 'Actions',
      displayOnly: true,
      value: () => null,
      render: (d) => (
        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${d.name}`} disabled={remove.isPending} onClick={() => remove.mutate(d.id)}>
          <Trash2 />
        </Button>
      ),
    },
  ]

  return (
    <div className="grid gap-5">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="grid content-start gap-3 rounded-lg border p-4">
          <h3 className="text-xs font-semibold">Upload a spreadsheet (CSV)</h3>
          <p className="text-xs text-muted-foreground">
            Easiest: download the template, fill it in, and upload it. Each row is one outcome at one moment from one sportsbook, with the
            odds in either American (+150) or decimal (2.50) form. Columns:{' '}
            <span className="font-mono">timestamp_utc, book, event, market, odds_american, odds_decimal</span>. When a game has exactly two
            outcomes at the same moment, the margin is removed automatically.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <a href="/api/m7/template" download className={cn(buttonVariants({ variant: 'outline', size: 'lg' }))}>
              <Download /> Download template
            </a>
            <div className="grid gap-1.5">
              <Label htmlFor="m7-file">File</Label>
              <Input id="m7-file" type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="w-64" />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="m7-name">Name (optional)</Label>
              <Input id="m7-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="defaults to file name" className="w-48" />
            </div>
            <Button size="lg" disabled={file === null || upload.isPending} onClick={() => upload.mutate()}>
              <Upload /> Upload
            </Button>
          </div>
        </div>
        <div className="grid content-start gap-3 rounded-lg border border-warning/30 bg-warning/5 p-4">
          <h3 className="flex items-center gap-2 text-xs font-semibold">
            Generate test data <DummyBadge />
          </h3>
          <p className="text-xs text-muted-foreground">
            Creates fake odds from two made-up sportsbooks, just to show how the comparison works. The numbers are random and do not come
            from Kalshi or any real sportsbook. Everything is clearly labelled “DUMMY”.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="m7-lab-dummy">Match the time range of this price test</Label>
              <NativeSelect id="m7-lab-dummy" value={selectedLab} onChange={(e) => setLabJobId(e.target.value)} className="w-80" disabled={labJobs.length === 0}>
                {labJobs.length === 0 && <option value="">None yet: run a price test on “Price history & timing” first</option>}
                {labJobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {labRunLabel(j)}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <Button variant="outline" size="lg" disabled={selectedLab === '' || dummy.isPending} onClick={() => dummy.mutate()}>
              <FlaskConical /> Generate DUMMY DATA
            </Button>
          </div>
        </div>
      </div>
      {lastUpload !== null && <UploadReport upload={lastUpload} />}
      <DataTable
        columns={columns}
        rows={datasets}
        rowKey={(d) => d.id}
        csvName="m7-datasets.csv"
        empty={<p className="text-xs text-muted-foreground">No odds files yet. Upload one or generate test data.</p>}
      />
    </div>
  )
}
