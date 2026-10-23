import { useMemo } from 'react'
import type { CatalogEndpoint } from '@/lib/api'
import { Chart } from '@/components/charts/Chart'
import { classificationByCategoryFigure, coverageMatrixFigure } from '@/components/endpoints/coverageFigures'

/** Spec auth claim x observed classification, for GET endpoints only. */
export function CoverageMatrix({ endpoints }: { endpoints: CatalogEndpoint[] }) {
  const figure = useMemo(() => coverageMatrixFigure(endpoints), [endpoints])
  return <Chart data={figure.data} layout={figure.layout} height={figure.height} filename="m1-coverage-matrix" />
}

/** Count of endpoints per category, stacked by observed classification. */
export function ClassificationByCategory({ endpoints }: { endpoints: CatalogEndpoint[] }) {
  const figure = useMemo(() => classificationByCategoryFigure(endpoints), [endpoints])
  return <Chart data={figure.data} layout={figure.layout} height={figure.height} filename="m1-classification-by-category" />
}
