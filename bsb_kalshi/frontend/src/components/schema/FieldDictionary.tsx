import { useMemo, useState } from 'react'
import { Database } from 'lucide-react'
import type { EntityDictionary, FieldRow, PullResult } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable, type Column } from '@/components/DataTable'
import { EmptyState } from '@/components/EmptyState'
import { NativeSelect } from '@/components/NativeSelect'

type Entity = keyof PullResult['entities']
const ENTITIES: Entity[] = ['series', 'event', 'market']
const ENTITY_LABEL: Record<Entity, string> = {
  series: 'League (series)',
  event: 'Game (event)',
  market: 'Bet (market)',
}

const FILTERS = {
  all: { label: 'All fields', test: () => true },
  timestamps: {
    label: 'Times and dates',
    test: (f: FieldRow) => f.timestamp_like || f.name_looks_like_timestamp || f.spec_format === 'date-time',
  },
  top: { label: 'Main fields only', test: (f: FieldRow) => f.in_spec !== null },
  notInSpec: { label: 'Not in the docs', test: (f: FieldRow) => f.in_spec === false },
  outsideEnum: { label: 'Unexpected values', test: (f: FieldRow) => f.values_outside_spec_enum.length > 0 },
} satisfies Record<string, { label: string; test: (f: FieldRow) => boolean }>

type FilterKey = keyof typeof FILTERS

const yesNo = (v: boolean | null) => (v === null ? null : v ? 'yes' : 'no')

const COLUMNS: Column<FieldRow>[] = [
  { key: 'path', header: 'Field name', value: (f) => f.path, className: 'font-mono' },
  { key: 'types', header: 'Kind of value', value: (f) => f.types.join(' | '), className: 'font-mono' },
  {
    key: 'example',
    header: 'Example',
    value: (f) => f.example,
    render: (f) => (
      <span className="block max-w-56 truncate font-mono" title={f.example ?? ''}>
        {f.example ?? '–'}
      </span>
    ),
  },
  { key: 'present', header: 'Filled in', value: (f) => f.present_in, render: (f) => `${f.present_in}/${f.samples}` },
  { key: 'nulls', header: 'Empty', value: (f) => f.null_count, className: 'font-mono tabular-nums' },
  {
    key: 'ts',
    header: 'Time format',
    value: (f) => f.timestamp_format,
    render: (f) =>
      f.timestamp_format !== null ? (
        <Badge className="bg-primary/15 text-primary">{f.timestamp_format}</Badge>
      ) : f.name_looks_like_timestamp ? (
        <span className="text-warning" title="Name looks like a timestamp but the value did not parse as one">
          name only
        </span>
      ) : (
        <span className="text-muted-foreground">–</span>
      ),
  },
  {
    key: 'distinct',
    header: 'Values seen',
    value: (f) => f.distinct_values.join(', ') + (f.distinct_values_truncated ? ', …' : ''),
    className: 'max-w-48 truncate font-mono',
  },
  { key: 'in_spec', header: 'In the docs?', value: (f) => yesNo(f.in_spec) },
  {
    key: 'spec_type',
    header: 'Docs say it is',
    value: (f) => [f.spec_type, f.spec_format].filter(Boolean).join(' / ') || null,
    className: 'font-mono',
  },
  { key: 'spec_nullable', header: 'Docs: can be empty?', value: (f) => yesNo(f.spec_nullable) },
  { key: 'spec_required', header: 'Docs: always present?', value: (f) => yesNo(f.spec_required) },
  {
    key: 'outside_enum',
    header: 'Values the docs don’t list',
    value: (f) => f.values_outside_spec_enum.join(', ') || null,
    className: 'font-mono text-warning',
  },
  { key: 'spec_enum', header: 'Spec enum', value: (f) => f.spec_enum?.map(String).join(', ') ?? null, csvOnly: true },
  { key: 'description', header: 'Spec description', value: (f) => f.spec_description, csvOnly: true },
]

function EntityTable({ entity, dict }: { entity: Entity; dict: EntityDictionary }) {
  const [filter, setFilter] = useState<FilterKey>('all')
  const rows = useMemo(() => dict.fields.filter(FILTERS[filter].test), [dict, filter])
  return (
    <div className="grid gap-3">
      <p className="text-xs text-muted-foreground">
        Based on {dict.samples} example row(s). Compared against the docs’ definition{' '}
        <span className="font-mono">{dict.spec_source}</span>; the “Docs” columns are filled for main fields only.
      </p>
      <DataTable
        columns={COLUMNS}
        rows={rows}
        rowKey={(f) => f.path}
        csvName={`m2-fields-${entity}.csv`}
        maxHeight="max-h-[36rem]"
        toolbar={
          <NativeSelect
            aria-label="Field filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value as FilterKey)}
            className="w-52"
          >
            {Object.entries(FILTERS).map(([key, f]) => (
              <option key={key} value={key}>
                {f.label}
              </option>
            ))}
          </NativeSelect>
        }
        empty={
          <EmptyState icon={Database} title="No fields match">
            Choose a different filter.
          </EmptyState>
        }
      />
      <div className="grid gap-1.5">
        <h4 className="text-xs font-medium">
          Fields the docs mention that Kalshi did not send ({dict.spec_fields_not_observed.length})
        </h4>
        <div className="flex flex-wrap gap-1.5">
          {dict.spec_fields_not_observed.length === 0 ? (
            <span className="text-xs text-muted-foreground">None.</span>
          ) : (
            dict.spec_fields_not_observed.map((name) => (
              <Badge key={name} variant="outline" className="font-mono">
                {name}
              </Badge>
            ))
          )}
        </div>
        {(dict.omitted_fields ?? []).length > 0 && (
          <p className="text-[11px] text-muted-foreground">
            Shown separately on purpose (they have their own tab): {dict.omitted_fields?.join(', ')}
          </p>
        )}
      </div>
    </div>
  )
}

/** Flattened field dictionary per entity, compared with the spec schema. */
export function FieldDictionary({ result }: { result: PullResult }) {
  const [entity, setEntity] = useState<Entity>('market')
  return (
    <div className="grid gap-4">
      <div className="flex gap-1.5">
        {ENTITIES.map((e) => (
          <Button
            key={e}
            size="sm"
            variant={e === entity ? 'secondary' : 'ghost'}
            onClick={() => setEntity(e)}
            className={cn(e === entity && 'text-primary')}
          >
            {ENTITY_LABEL[e]} ({result.entities[e].fields.length} fields)
          </Button>
        ))}
      </div>
      <EntityTable key={entity} entity={entity} dict={result.entities[entity]} />
    </div>
  )
}
