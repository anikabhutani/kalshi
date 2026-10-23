import { useMemo, useState, type ReactNode } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

export type CellValue = string | number | boolean | null | undefined

export interface Column<T> {
  key: string
  header: string
  value: (row: T) => CellValue
  render?: (row: T) => ReactNode
  className?: string
  /** Included in the CSV export but not rendered. */
  csvOnly?: boolean
  /** Rendered (e.g. row actions) but not sortable and left out of the CSV export. */
  displayOnly?: boolean
}

function compare(a: CellValue, b: CellValue): number {
  if (a === b) return 0
  if (a === null || a === undefined) return 1
  if (b === null || b === undefined) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

function csvEscape(value: CellValue): string {
  const s = value === null || value === undefined ? '' : String(value)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function downloadCsv<T>(filename: string, columns: Column<T>[], rows: T[]): void {
  const lines = [
    columns.map((c) => csvEscape(c.header)).join(','),
    ...rows.map((r) => columns.map((c) => csvEscape(c.value(r))).join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  csvName,
  empty,
  maxHeight = 'max-h-[28rem]',
  renderLimit = 1000,
  toolbar,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  csvName: string
  empty: ReactNode
  maxHeight?: string
  /** Rows beyond this are not rendered (still filtered, sorted and exported). */
  renderLimit?: number
  toolbar?: ReactNode
}) {
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const filtered = needle
      ? rows.filter((r) => columns.some((c) => String(c.value(r) ?? '').toLowerCase().includes(needle)))
      : rows
    if (sort === null) return filtered
    const column = columns.find((c) => c.key === sort.key)
    if (column === undefined) return filtered
    return [...filtered].sort((a, b) => compare(column.value(a), column.value(b)) * sort.dir)
  }, [rows, columns, filter, sort])

  const shown = useMemo(() => columns.filter((c) => c.csvOnly !== true), [columns])
  const exported = useMemo(() => columns.filter((c) => c.displayOnly !== true), [columns])

  const toggleSort = (key: string) =>
    setSort((prev) => (prev?.key !== key ? { key, dir: 1 } : prev.dir === 1 ? { key, dir: -1 } : null))

  if (rows.length === 0) return <>{empty}</>

  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2">
        <div className="relative max-w-xs flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter rows…" className="pl-8" />
        </div>
        {toolbar}
        <span className="text-xs text-muted-foreground">
          {visible.length} of {rows.length}
          {visible.length > renderLimit && ` · first ${renderLimit} shown, CSV has all`}
        </span>
        <Button variant="outline" size="sm" className="ml-auto" onClick={() => downloadCsv(csvName, exported, visible)}>
          <Download /> CSV
        </Button>
      </div>
      <div className={cn('overflow-auto rounded-lg border', maxHeight)}>
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-surface">
            <TableRow>
              {shown.map((c) => (
                <TableHead key={c.key} className={c.className}>
                  {c.displayOnly === true ? (
                    <span className="sr-only">{c.header}</span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => toggleSort(c.key)}
                      className="inline-flex items-center gap-1 text-xs font-medium hover:text-foreground"
                    >
                      {c.header}
                      {sort?.key !== c.key ? (
                        <ArrowUpDown className="size-3 opacity-40" />
                      ) : sort.dir === 1 ? (
                        <ArrowUp className="size-3" />
                      ) : (
                        <ArrowDown className="size-3" />
                      )}
                    </button>
                  )}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.slice(0, renderLimit).map((row) => (
              <TableRow key={rowKey(row)}>
                {shown.map((c) => (
                  <TableCell key={c.key} className={cn('text-xs', c.className)}>
                    {c.render ? c.render(row) : String(c.value(row) ?? '–')}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
