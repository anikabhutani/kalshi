import { useMemo, useState } from 'react'
import type { LabResult } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/NativeSelect'
import { Chart } from '@/components/charts/Chart'
import { priceLayout, priceTraces } from '@/components/timestamps/priceFigure'
import { candleLabel, candleSources } from '@/components/timestamps/sources'

/** Candle closes (or OHLC), bid/ask, trades and the orderbook mid on one time axis, plus volume. */
export function PriceChart({ result, markerTs }: { result: LabResult; markerTs: number | null }) {
  const candles = candleSources(result)
  const [interval, setIntervalMin] = useState(candles[0]?.interval_min ?? 1)
  const [style, setStyle] = useState<'line' | 'candles'>('line')
  const [showBidAsk, setShowBidAsk] = useState(true)
  const [showTrades, setShowTrades] = useState(true)

  const data = useMemo(
    () => priceTraces(result, { interval, style, showBidAsk, showTrades }),
    [result, interval, style, showBidAsk, showTrades],
  )
  const layout = useMemo(() => priceLayout(markerTs), [markerTs])

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <div className="flex gap-1">
          {(['line', 'candles'] as const).map((s) => (
            <Button key={s} size="xs" variant={style === s ? 'secondary' : 'ghost'} onClick={() => setStyle(s)} className="capitalize">
              {s}
            </Button>
          ))}
        </div>
        <NativeSelect
          aria-label="Candle interval"
          value={interval}
          onChange={(e) => setIntervalMin(Number(e.target.value))}
          className="h-7 w-36 text-xs"
        >
          {candles.map((c) => (
            <option key={c.interval_min} value={c.interval_min}>
              {candleLabel(c.interval_min)}
            </option>
          ))}
        </NativeSelect>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={showBidAsk} onChange={(e) => setShowBidAsk(e.target.checked)} className="accent-primary" />
          Bid/ask
        </label>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={showTrades} onChange={(e) => setShowTrades(e.target.checked)} className="accent-primary" />
          Trades
        </label>
        <span className="text-muted-foreground">
          Candle points sit at end_period_ts (period end). Line steps hold the last close; gaps are periods with no trade.
        </span>
      </div>
      <Chart data={data} layout={layout} height={520} filename="m3-price-sources" />
    </div>
  )
}
