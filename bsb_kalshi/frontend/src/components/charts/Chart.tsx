import { lazy, Suspense, useMemo } from 'react'
import type { Data, Layout } from 'plotly.js-dist-min'
import { Skeleton } from '@/components/ui/skeleton'
import { chartConfig, themedLayout } from '@/lib/chartTheme'

const PlotImpl = lazy(() => import('@/components/charts/PlotImpl'))

/** Interactive Plotly chart (zoom, hover, PNG download) in the app's dark theme. */
export function Chart({
  data,
  layout = {},
  height = 360,
  filename,
}: {
  data: Data[]
  layout?: Partial<Layout>
  height?: number
  filename: string
}) {
  const themed = useMemo(() => themedLayout(layout), [layout])
  const config = useMemo(() => chartConfig(filename), [filename])
  return (
    <Suspense fallback={<Skeleton className="w-full rounded-lg" style={{ height }} />}>
      <PlotImpl data={data} layout={themed} config={config} height={height} />
    </Suspense>
  )
}
