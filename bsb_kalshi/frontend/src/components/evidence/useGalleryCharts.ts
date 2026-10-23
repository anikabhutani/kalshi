import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type DepthResult, type LabResult, type PaginationResult, type RampResult, type RecorderResult } from '@/lib/api'
import {
  archiveMatrixFigure,
  depthTimelineFigure,
  headerValuesFigure,
  latencyVsRateFigure,
  paginationFigure,
  rampTimelineFigure,
  type Figure,
} from '@/lib/figures'
import { classificationByCategoryFigure, coverageMatrixFigure } from '@/components/endpoints/coverageFigures'
import { cumulativeUpdatesFigure, eventTimelineFigure, latencyHistogramFigure, priceComparisonFigure } from '@/components/restws/recorderFigures'
import { priceLayout, priceTraces } from '@/components/timestamps/priceFigure'

export interface GalleryChart {
  /** File name stem for charts/<name>.png. */
  name: string
  title: string
  module: string
  jobId: string | null
  figure: Figure
}

function latest<R>(module: string, kind: string) {
  return { queryKey: ['latest', module, kind], queryFn: () => api.latestJob<R>(module, kind), meta: { silent: true } }
}

/** Every chart that can be drawn from stored results, built with the same figure code as the module pages. */
export function useGalleryCharts(): { charts: GalleryChart[]; loading: boolean } {
  const catalog = useQuery({ queryKey: ['catalog'], queryFn: api.catalog })
  const lab = useQuery(latest<LabResult>('M3', 'price_sources'))
  const depth = useQuery(latest<DepthResult>('M4', 'depth_archive'))
  const ramp = useQuery(latest<RampResult>('M5', 'ramp'))
  const pages = useQuery(latest<PaginationResult>('M5', 'pagination'))
  const recorder = useQuery(latest<RecorderResult>('M6', 'recorder'))

  const charts = useMemo(() => {
    const out: GalleryChart[] = []
    const add = (name: string, title: string, module: string, jobId: string | null, figure: Figure | null) => {
      if (figure !== null) out.push({ name, title, module, jobId, figure })
    }
    const endpoints = catalog.data?.endpoints ?? []
    if (catalog.data?.probe_job) {
      const id = catalog.data.probe_job.id
      add('m1-coverage-matrix', 'Spec auth claim vs observed classification', 'M1', id, coverageMatrixFigure(endpoints))
      add('m1-classification-by-category', 'Observed classification by category', 'M1', id, classificationByCategoryFigure(endpoints))
    }
    const labJob = lab.data
    if (labJob?.result) {
      add('m3-price-sources', `Price sources: ${labJob.result.params.market_ticker}`, 'M3', labJob.id, {
        data: priceTraces(labJob.result),
        layout: priceLayout(null),
        height: 520,
      })
    }
    const depthJob = depth.data
    if (depthJob?.result) {
      add('m4-availability', 'Data availability by endpoint', 'M4', depthJob.id, depthTimelineFigure(depthJob.result))
      add('m4-archive-matrix', 'Archive matrix', 'M4', depthJob.id, archiveMatrixFigure(depthJob.result))
    }
    const rampJob = ramp.data
    if (rampJob?.result) {
      add('m5-latency-vs-rate', 'Latency vs request rate', 'M5', rampJob.id, latencyVsRateFigure(rampJob.result))
      add('m5-ramp-timeline', 'Ramp latency over time', 'M5', rampJob.id, rampTimelineFigure(rampJob.result))
      add('m5-header-values', 'Rate-limit header values over time', 'M5', rampJob.id, headerValuesFigure(rampJob.result))
    }
    const pageJob = pages.data
    if (pageJob?.result) {
      add('m5-pagination', `Pagination: ${pageJob.result.spec.path}`, 'M5', pageJob.id, paginationFigure(pageJob.result))
    }
    const recJob = recorder.data
    if (recJob?.result) {
      const r = recJob.result
      add('m6-event-timeline', `Event timeline WS vs REST: ${r.params.market_ticker}`, 'M6', recJob.id, eventTimelineFigure(r))
      add('m6-prices', 'YES bid/ask/last: WS vs REST', 'M6', recJob.id, priceComparisonFigure(r))
      add('m6-latency-histogram', 'WS update latency histogram', 'M6', recJob.id, latencyHistogramFigure(r))
      add('m6-cumulative-updates', 'Cumulative updates over time', 'M6', recJob.id, cumulativeUpdatesFigure(r))
    }
    return out
  }, [catalog.data, lab.data, depth.data, ramp.data, pages.data, recorder.data])

  const loading = [catalog, lab, depth, ramp, pages, recorder].some((q) => q.isLoading)
  return { charts, loading }
}
