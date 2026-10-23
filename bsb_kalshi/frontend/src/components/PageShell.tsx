import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { QUESTION_PLAIN, type NavItem } from '@/lib/nav'

export function PageShell({ item, children }: { item: NavItem; children: ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-8">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <item.icon className="size-5 text-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">{item.label}</h1>
          {item.module !== null && (
            <Badge variant="outline" className="font-mono" title="Module number used in the report">
              {item.module}
            </Badge>
          )}
          {item.questions.length > 0 && item.questions.length < 6 &&
            item.questions.map((q) => (
              <Badge key={q} variant="secondary" title={QUESTION_PLAIN[q].prompt}>
                Answers {q}: {QUESTION_PLAIN[q].title}
              </Badge>
            ))}
          {item.questions.length === 6 && <Badge variant="secondary">Covers all six questions</Badge>}
        </div>
        <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
          <span className="font-medium text-foreground">What this page does: </span>
          {item.description}
        </p>
      </header>
      {children}
    </div>
  )
}

export function Section({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border bg-card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {description !== undefined && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </div>
      <div className="p-5">{children}</div>
    </section>
  )
}
