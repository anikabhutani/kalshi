/** Plain Plotly charts for the Task 4 (sportsbook costs) page. */

import type { Data } from 'plotly.js-dist-min'
import type { T4Season } from '@/lib/api'
import { CHART_COLORS } from '@/lib/chartTheme'
import type { Figure } from '@/lib/figures'

export const BOOKS = ['DraftKings', 'FanDuel', 'Pinnacle'] as const
export const ALL_BOOKS = [...BOOKS, 'Kalshi'] as const
/** Only these two are priced against Pinnacle's fair line. */
const VS_PIN = ['DraftKings', 'FanDuel'] as const

/** Books that appear in the results (Kalshi only once Task 3 has data). */
export function booksIn(r: T4Season): string[] {
  const present = new Set(r.by_book_market.map((x) => x.bookmaker))
  return ALL_BOOKS.filter((b) => present.has(b))
}
export const MARKETS = ['h2h', 'spreads', 'totals'] as const
export const MARKET_LABEL: Record<string, string> = { h2h: 'Moneyline', spreads: 'Spread', totals: 'Total' }
export const PRICE_GROUPS = ['<25%', '25-40%', '40-60%', '60-75%', '>75%']
export const TIME_BUCKETS = ['7+ days', '3-7 days', '1-3 days', '1-24 h', 'under 1 h']
export const FL_GROUPS = ['favorite', 'underdog', 'longshot (<25%)']
const SHORT_ROUND: Record<string, string> = { 'Wild Card': 'WC', Divisional: 'DIV', Conference: 'CONF', 'Super Bowl': 'SB' }

const BOOK_COLOR: Record<string, string> = {
  DraftKings: CHART_COLORS.primary,
  FanDuel: CHART_COLORS.blue,
  Pinnacle: CHART_COLORS.amber,
  Kalshi: CHART_COLORS.violet,
}
const COST_AXIS = { title: { text: 'Cost per $10 bet ($)' }, tickprefix: '$', rangemode: 'tozero' as const }
const money = (v: number) => `$${v.toFixed(2)}`

function bars(
  books: readonly string[],
  categories: string[],
  value: (book: string, cat: string) => { y: number | null; n: number | null } | undefined,
  xTitle: string,
): Figure {
  const data: Data[] = books.map((book) => {
    const pts = categories.map((c) => value(book, c))
    return {
      type: 'bar',
      name: book,
      x: categories,
      y: pts.map((p) => p?.y ?? null),
      text: pts.map((p) => (p?.y == null ? '' : money(p.y))),
      customdata: pts.map((p) => p?.n ?? 0),
      textposition: 'outside',
      hovertemplate: `${book} · %{x}<br>%{text} per $10 · n=%{customdata}<extra></extra>`,
      marker: { color: BOOK_COLOR[book] },
    } as Data
  })
  return {
    data,
    layout: { barmode: 'group', yaxis: COST_AXIS, xaxis: { title: { text: xTitle }, type: 'category' } },
    height: 360,
  }
}

export function bookMarketFigure(r: T4Season): Figure {
  const m = new Map(r.by_book_market.map((x) => [`${x.bookmaker}|${x.market}`, x]))
  return bars(booksIn(r), MARKETS.map((k) => MARKET_LABEL[k] ?? k), (b, label) => {
    const key = MARKETS.find((k) => (MARKET_LABEL[k] ?? k) === label)
    const x = m.get(`${b}|${key}`)
    return x && { y: x.mean, n: x.n }
  }, 'Kind of bet')
}

/** Moneyline sides by no-vig win probability; vsPinnacle prices DK/FD against Pinnacle's fair line. */
export function priceGroupFigure(r: T4Season, vsPinnacle: boolean): Figure {
  const rows = r.by_price_group.filter((x) => x.market === 'h2h')
  const m = new Map(rows.map((x) => [`${x.bookmaker}|${x.price_group}`, x]))
  const books = vsPinnacle ? [...VS_PIN] : booksIn(r)
  const fig = bars(books, PRICE_GROUPS, (b, g) => {
    const x = m.get(`${b}|${g}`)
    if (!x) return undefined
    return vsPinnacle ? { y: x.mean_cost_vs_pinnacle, n: x.n_vs_pinnacle } : { y: x.mean, n: x.n }
  }, 'Fair win probability of the side bet (Shin)')
  fig.layout.yaxis = { ...COST_AXIS, rangemode: 'normal' }
  return fig
}

export function favoritesFigure(r: T4Season, vsPinnacle: boolean): Figure {
  const m = new Map(r.favorites_longshots.map((x) => [`${x.bookmaker}|${x.group}`, x]))
  const books = vsPinnacle ? [...VS_PIN] : booksIn(r)
  const fig = bars(books, FL_GROUPS, (b, g) => {
    const x = m.get(`${b}|${g}`)
    if (!x) return undefined
    return vsPinnacle ? { y: x.mean_cost_vs_pinnacle, n: x.n_vs_pinnacle } : { y: x.mean_cost_per_10, n: x.n }
  }, 'Moneyline side')
  fig.layout.yaxis = { ...COST_AXIS, rangemode: 'normal' }
  return fig
}

function lines(
  books: string[],
  market: string,
  x: (string | number)[],
  value: (book: string, x: string | number) => { y: number; n: number } | undefined,
  xTitle: string,
): Figure {
  const data: Data[] = books.map((book) => {
    const pts = x.map((v) => value(book, v))
    return {
      type: 'scatter',
      mode: 'lines+markers',
      name: book,
      x: x.map(String),
      y: pts.map((p) => p?.y ?? null),
      customdata: pts.map((p) => p?.n ?? 0),
      hovertemplate: `${book} · %{x}<br>$%{y:.3f} per $10 · n=%{customdata}<extra></extra>`,
      line: { color: BOOK_COLOR[book] },
      marker: { color: BOOK_COLOR[book] },
    } as Data
  })
  return {
    data,
    layout: {
      yaxis: { ...COST_AXIS, rangemode: 'normal' },
      xaxis: { title: { text: xTitle }, type: 'category' },
      title: { text: MARKET_LABEL[market], font: { size: 13 } },
      margin: { t: 36, b: 110 },
      legend: { orientation: 'h', x: 0, y: -0.42, yanchor: 'top' },
    },
    height: 360,
  }
}

/** Regular-season weeks by number, then playoff rounds by name (from the backend's week_label). */
export function weekFigure(r: T4Season, market: string): Figure {
  const weeks = [...new Set(r.by_week.map((w) => w.week))].sort((a, b) => a - b)
  const label = new Map(r.by_week.map((w) => [w.week, SHORT_ROUND[w.week_label] ?? w.week_label ?? String(w.week)]))
  const m = new Map(r.by_week.filter((w) => w.market === market).map((w) => [`${w.bookmaker}|${w.week}`, w]))
  const fig = lines(booksIn(r), market, weeks.map((w) => label.get(w) ?? String(w)), (b, lab) => {
    const week = weeks.find((w) => (label.get(w) ?? String(w)) === lab)
    const x = m.get(`${b}|${week}`)
    return x && { y: x.mean, n: x.n }
  }, weeks.some((w) => w > 18) ? 'NFL week (WC, DIV, CONF, SB = playoff rounds)' : 'NFL week')
  // every week labelled: Plotly otherwise hides every other label once they get crowded
  fig.layout.xaxis = { ...fig.layout.xaxis, dtick: 1, tickangle: weeks.length > 10 ? -90 : 0, tickfont: { size: weeks.length > 10 ? 9 : 11 } }
  return fig
}

export function kickoffFigure(r: T4Season, market: string): Figure {
  const m = new Map(
    r.by_time_to_kickoff.filter((t) => t.market === market).map((t) => [`${t.bookmaker}|${t.time_bucket}`, t]),
  )
  return lines(booksIn(r), market, TIME_BUCKETS, (b, bucket) => {
    const x = m.get(`${b}|${bucket}`)
    return x && { y: x.mean_cost_per_10, n: x.games }
  }, 'Time before kickoff')
}
