import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, NotebookPen } from 'lucide-react'
import { api, type QuestionId } from '@/lib/api'
import { QUESTION_PLAIN } from '@/lib/nav'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'

const AUTOSAVE_MS = 800

function Editor({ questionId, initial, savedAt }: { questionId: QuestionId; initial: string; savedAt: string | null }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState(initial)
  const [lastSaved, setLastSaved] = useState<string | null>(savedAt)
  const dirty = useRef(false)

  const save = useMutation({
    mutationFn: (value: string) => api.saveNote(questionId, value),
    onSuccess: (res) => {
      setLastSaved(res.updated_at)
      void queryClient.invalidateQueries({ queryKey: ['notes'] })
      void queryClient.invalidateQueries({ queryKey: ['home'] })
    },
  })
  const { mutate } = save

  useEffect(() => {
    if (!dirty.current) return undefined
    const timer = window.setTimeout(() => mutate(text), AUTOSAVE_MS)
    return () => window.clearTimeout(timer)
  }, [text, mutate])

  return (
    <div className="grid gap-2">
      <Textarea
        value={text}
        onChange={(e) => {
          dirty.current = true
          setText(e.target.value)
        }}
        placeholder={`Write your answer to ${questionId} here, in your own words. The app never writes in this box.`}
        className="min-h-36 font-[inherit] leading-relaxed"
      />
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {save.isPending ? (
          <>
            <Loader2 className="size-3 animate-spin" /> Saving…
          </>
        ) : lastSaved !== null ? (
          <>
            <Check className="size-3 text-primary" /> Saved {new Date(lastSaved).toLocaleTimeString()}
          </>
        ) : (
          'Autosaves as you type.'
        )}
      </div>
    </div>
  )
}

export function NotesBox({ questionId }: { questionId: QuestionId }) {
  const { data, isLoading } = useQuery({ queryKey: ['notes'], queryFn: api.notes, staleTime: Infinity })
  const entry = data?.[questionId]

  return (
    <section className="rounded-xl border bg-card p-5">
      <div className="mb-3 flex items-center gap-2">
        <NotebookPen className="size-4 text-primary" />
        <h2 className="text-sm font-semibold">
          My answer to {questionId}: {QUESTION_PLAIN[questionId].title}
        </h2>
      </div>
      {isLoading || entry === undefined ? (
        <Skeleton className="h-36 w-full" />
      ) : (
        <Editor questionId={questionId} initial={entry.text} savedAt={entry.updated_at} />
      )}
    </section>
  )
}
