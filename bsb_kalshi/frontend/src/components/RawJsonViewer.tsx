import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

const MAX_CHARS = 200_000

/** Shows stored raw response bodies (data/raw) for chosen evidence-log requests. */
export function RawJsonViewer({ sources }: { sources: { label: string; requestId: number | null }[] }) {
  const available = sources.filter((s): s is { label: string; requestId: number } => s.requestId !== null)
  const [selected, setSelected] = useState<number | null>(available[0]?.requestId ?? null)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['raw', selected],
    queryFn: () => api.rawBody(selected!),
    enabled: selected !== null,
    staleTime: Infinity,
  })
  const text = data === undefined ? '' : JSON.stringify(data, null, 2)

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-1.5">
        {available.map((s) => (
          <Button
            key={s.requestId}
            size="sm"
            variant={s.requestId === selected ? 'secondary' : 'ghost'}
            onClick={() => setSelected(s.requestId)}
          >
            {s.label} <span className="font-mono text-muted-foreground">#{s.requestId}</span>
          </Button>
        ))}
      </div>
      {selected === null ? null : isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <p className="text-xs text-muted-foreground">No raw body stored for request #{selected}.</p>
      ) : (
        <pre className="max-h-[32rem] overflow-auto rounded-lg border bg-background/60 p-3 font-mono text-[11px] leading-5">
          {text.length > MAX_CHARS ? `${text.slice(0, MAX_CHARS)}\n… (truncated for display)` : text}
        </pre>
      )}
    </div>
  )
}
