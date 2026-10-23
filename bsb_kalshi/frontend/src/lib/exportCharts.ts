import type { Figure } from '@/lib/figures'
import { themedLayout } from '@/lib/chartTheme'

/** Solid background for exported PNGs (on-screen charts are transparent over the card color). */
const EXPORT_BACKGROUND = '#15171c'
const EXPORT_WIDTH = 1400

/** Render a figure off-screen with Plotly's image export; returns base64 PNG without the data-URL prefix. */
export async function figureToPngBase64(figure: Figure): Promise<string> {
  const { default: Plotly } = await import('plotly.js-dist-min')
  const height = Math.max(figure.height, 360)
  const layout = {
    ...themedLayout(figure.layout),
    paper_bgcolor: EXPORT_BACKGROUND,
    plot_bgcolor: EXPORT_BACKGROUND,
    width: EXPORT_WIDTH,
    height,
  }
  const url = await Plotly.toImage({ data: figure.data, layout }, { format: 'png', width: EXPORT_WIDTH, height })
  return url.replace(/^data:image\/png;base64,/, '')
}
