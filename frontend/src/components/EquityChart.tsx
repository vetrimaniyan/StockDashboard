/** Equity curves for a backtest: gross of tax, net of tax, and the benchmark. */

import { useEffect, useRef } from 'react'
import { LineSeries, createChart, type IChartApi, type UTCTimestamp } from 'lightweight-charts'
import type { BacktestResponse } from '../api'

function toTime(iso: string): UTCTimestamp {
  return (Date.parse(iso) / 1000) as UTCTimestamp
}

export function EquityChart({ result }: { result: BacktestResponse }) {
  const holder = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!holder.current) return
    const css = getComputedStyle(document.documentElement)
    const text = css.getPropertyValue('--text').trim() || '#e6e6e6'
    const border = css.getPropertyValue('--border').trim() || '#2a2a2a'
    const up = css.getPropertyValue('--up').trim() || '#4ea36a'
    const down = css.getPropertyValue('--down').trim() || '#ef5f6b'
    const muted = css.getPropertyValue('--muted').trim() || '#8a8a8a'

    const chart = createChart(holder.current, {
      autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: text },
      grid: {
        vertLines: { color: border, style: 1 },
        horzLines: { color: border, style: 1 },
      },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border, timeVisible: false },
      crosshair: { mode: 0 },
    })
    chartRef.current = chart

    const gross = chart.addSeries(LineSeries, {
      color: up,
      lineWidth: 2,
      title: 'gross of tax',
      priceLineVisible: false,
    })
    const net = chart.addSeries(LineSeries, {
      color: down,
      lineWidth: 2,
      title: 'net of tax',
      priceLineVisible: false,
    })

    gross.setData(
      result.equity_curve.map((p) => ({ time: toTime(p.date), value: p.gross })),
    )
    net.setData(
      result.equity_curve.map((p) => ({ time: toTime(p.date), value: p.net })),
    )

    // Rebase the index to the same starting capital so the comparison is a
    // like-for-like growth path rather than two different scales.
    if (result.benchmark && result.benchmark.curve.length && result.equity_curve.length) {
      const base = result.equity_curve[0].net
      const first = result.benchmark.curve[0].close
      const bench = chart.addSeries(LineSeries, {
        color: muted,
        lineWidth: 1,
        lineStyle: 2,
        title: `${result.benchmark.index_name} buy & hold`,
        priceLineVisible: false,
      })
      bench.setData(
        result.benchmark.curve.map((p) => ({
          time: toTime(p.date),
          value: (p.close / first) * base,
        })),
      )
    }

    chart.timeScale().fitContent()
    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [result])

  return <div ref={holder} className="h-[320px] w-full" />
}
