import type { CatalogEndpoint } from '@/lib/api'
import type { Figure } from '@/lib/figures'
import { CLASSIFICATIONS, CLASSIFICATION_COLORS, observed } from '@/components/endpoints/classification'

const SPEC_ROWS = ['Spec: no auth', 'Spec: auth required'] as const

/** Spec auth claim x observed classification, for GET endpoints only. */
export function coverageMatrixFigure(endpoints: CatalogEndpoint[]): Figure {
  const gets = endpoints.filter((e) => e.method === 'GET')
  const z = SPEC_ROWS.map((_, row) =>
    CLASSIFICATIONS.map((c) => gets.filter((e) => Number(e.auth_required_spec) === row && observed(e) === c).length),
  )
  return {
    height: 240,
    data: [
      {
        type: 'heatmap',
        x: CLASSIFICATIONS,
        y: [...SPEC_ROWS],
        z,
        texttemplate: '%{z}',
        colorscale: [
          [0, 'rgba(52,211,153,0.04)'],
          [1, 'rgba(52,211,153,0.85)'],
        ],
        showscale: false,
        hovertemplate: '%{y}<br>Observed: %{x}<br>%{z} endpoints<extra></extra>',
        xgap: 3,
        ygap: 3,
      },
    ],
    layout: { xaxis: { title: { text: 'Observed classification' }, showgrid: false }, yaxis: { showgrid: false } },
  }
}

/** Count of GET endpoints per category, stacked by observed classification. */
export function classificationByCategoryFigure(endpoints: CatalogEndpoint[]): Figure {
  const gets = endpoints.filter((e) => e.method === 'GET')
  const categories = [...new Set(gets.map((e) => e.category))].sort()
  return {
    height: 320,
    data: CLASSIFICATIONS.map((c) => ({
      type: 'bar',
      name: c,
      x: categories,
      y: categories.map((cat) => gets.filter((e) => e.category === cat && observed(e) === c).length),
      marker: { color: CLASSIFICATION_COLORS[c] },
      hovertemplate: `%{x}<br>${c}: %{y}<extra></extra>`,
    })),
    layout: { barmode: 'stack', xaxis: { tickangle: -35 }, yaxis: { title: { text: 'GET endpoints' } } },
  }
}
