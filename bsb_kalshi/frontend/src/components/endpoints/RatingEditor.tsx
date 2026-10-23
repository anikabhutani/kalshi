import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2 } from 'lucide-react'
import { api, type CatalogEndpoint } from '@/lib/api'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/NativeSelect'

const AUTOSAVE_MS = 800

/** User-typed 1-5 usefulness rating and reason for one endpoint (autosaves). */
export function RatingEditor({ endpoint }: { endpoint: CatalogEndpoint }) {
  const queryClient = useQueryClient()
  const [rating, setRating] = useState<number | null>(endpoint.user.rating)
  const [reason, setReason] = useState(endpoint.user.reason)
  const dirty = useRef(false)
  const save = useMutation({
    mutationFn: () => api.saveRating(endpoint.id, rating, reason),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['catalog'] }),
  })
  const { mutate } = save

  useEffect(() => {
    if (!dirty.current) return undefined
    const timer = window.setTimeout(() => mutate(), AUTOSAVE_MS)
    return () => window.clearTimeout(timer)
  }, [rating, reason, mutate])

  return (
    <div className="flex min-w-72 items-center gap-1.5">
      <NativeSelect
        aria-label={`Rating for ${endpoint.id}`}
        value={rating ?? ''}
        onChange={(e) => {
          dirty.current = true
          setRating(e.target.value === '' ? null : Number(e.target.value))
        }}
        className="h-7 w-14 px-1.5 text-xs"
      >
        <option value="">–</option>
        {[1, 2, 3, 4, 5].map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </NativeSelect>
      <Input
        aria-label={`Reason for ${endpoint.id}`}
        value={reason}
        onChange={(e) => {
          dirty.current = true
          setReason(e.target.value)
        }}
        placeholder="Your reason…"
        className="h-7 text-xs"
      />
      <span className="w-3.5">
        {save.isPending ? (
          <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
        ) : save.isSuccess ? (
          <Check className="size-3.5 text-primary" />
        ) : null}
      </span>
    </div>
  )
}
