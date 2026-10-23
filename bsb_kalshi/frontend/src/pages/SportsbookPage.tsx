import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { navItem } from '@/lib/nav'
import { Skeleton } from '@/components/ui/skeleton'
import { PageShell, Section } from '@/components/PageShell'
import { RawRequestsDrawer } from '@/components/RawRequestsDrawer'
import { DatasetsPanel } from '@/components/sportsbook/DatasetsPanel'
import { OverlayPanel } from '@/components/sportsbook/OverlayPanel'

const ITEM = navItem('/sportsbook')

export function SportsbookPage() {
  const datasets = useQuery({ queryKey: ['m7-datasets'], queryFn: api.datasets })
  const labJobs = useQuery({ queryKey: ['m7-lab-jobs'], queryFn: api.labJobs })
  const labRuns = (labJobs.data ?? []).filter((j) => j.status !== 'running' && j.status !== 'failed')
  const loading = datasets.isLoading || labJobs.isLoading

  return (
    <PageShell item={ITEM}>
      <Section
        title="Step 1: Add sportsbook odds"
        description="Upload a spreadsheet of sportsbook odds (e.g. from DraftKings or FanDuel). The app turns odds like +150 or −200 into a percentage chance. Sportsbooks build in a profit margin (the “vig”), so their two sides add up to more than 100%; the app also removes that margin (“no-vig”) for a fair comparison. Formulas: American odds 100/(A+100) or −A/(−A+100); decimal odds 1/D."
      >
        {loading ? <Skeleton className="h-48 w-full" /> : <DatasetsPanel datasets={datasets.data ?? []} labJobs={labRuns} />}
      </Section>

      <Section
        title="Step 2: Compare with Kalshi"
        description="Puts the sportsbook’s chance and Kalshi’s price on the same chart. A Kalshi price of 62¢ means a 62% chance. Kalshi prices come from a price test you already ran on the “Price history & timing” page, so this step sends no new requests."
      >
        {loading ? <Skeleton className="h-64 w-full" /> : <OverlayPanel datasets={datasets.data ?? []} labJobs={labRuns} />}
      </Section>

      <RawRequestsDrawer module="M7" />
    </PageShell>
  )
}
