import { useMutation, useQuery } from '@tanstack/react-query'
import { api, type AccountLimitsResult, type PaginationResult, type RampResult } from '@/lib/api'
import { navItem } from '@/lib/nav'
import { useModuleJob } from '@/hooks/useModuleJob'
import { Skeleton } from '@/components/ui/skeleton'
import { DocPanel } from '@/components/limits/DocPanel'
import { PaginationPanel } from '@/components/limits/PaginationPanel'
import { RampPanel } from '@/components/limits/RampPanel'
import { NotesBox } from '@/components/NotesBox'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'

const ITEM = navItem('/limits')

export function LimitsPage() {
  const doc = useQuery({ queryKey: ['m5-doc'], queryFn: api.rateDoc })
  const account = useModuleJob<AccountLimitsResult>('M5', 'account_limits')
  const ramp = useModuleJob<RampResult>('M5', 'ramp')
  const pages = useModuleJob<PaginationResult>('M5', 'pagination')
  const runAccount = useMutation({ mutationFn: api.runAccountLimits, onSuccess: (res) => account.start(res.job_id) })

  return (
    <PageShell item={ITEM}>
      {doc.data === undefined ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : (
        <>
          <Section
            title="What the rules say vs what we saw"
            description="Kalshi caps how much data each account can request per second, using a budget of “tokens” (most requests cost 10). This puts three things side by side: what Kalshi’s docs say, what Kalshi reports for our account, and what this app measured."
          >
            <DocPanel
              doc={doc.data}
              account={account}
              onRunAccount={() => runAccount.mutate()}
              accountBusy={runAccount.isPending}
              ramp={ramp.job?.result ?? null}
              pages={pages.job?.result ?? null}
            />
          </Section>
          <Section
            title="Speed test: how fast can we go?"
            description="Sends requests to one address, slowly at first and then a bit faster at each step, and records how quickly Kalshi answers. It stops the moment Kalshi says “slow down” (code 429)."
          >
            <RampPanel doc={doc.data} job={ramp} />
          </Section>
          <Section
            title="How big results are split into pages"
            description="Kalshi returns long lists a page at a time, like search results. This tests the normal page size, the largest allowed, and one over the limit, then flips through several pages to check for repeats and how Kalshi signals the last page."
          >
            <PaginationPanel doc={doc.data} job={pages} />
          </Section>
        </>
      )}
      <RawRequestsDrawer module="M5" />
      <NotesBox questionId="Q4" />
    </PageShell>
  )
}
