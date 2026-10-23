import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-dist-min'
import type { Config, Data, Layout } from 'plotly.js-dist-min'

const PlotlyComponent = createPlotlyComponent(Plotly)

export default function PlotImpl({
  data,
  layout,
  config,
  height,
}: {
  data: Data[]
  layout: Partial<Layout>
  config: Partial<Config>
  height: number
}) {
  return (
    <PlotlyComponent
      data={data}
      layout={layout}
      config={config}
      useResizeHandler
      style={{ width: '100%', height }}
    />
  )
}
