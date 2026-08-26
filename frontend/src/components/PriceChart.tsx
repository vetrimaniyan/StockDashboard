/** Candlestick chart with volume and moving averages (FR-8.4). */

import { useEffect, useRef } from 'react'
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { Candle } from '../api'

function sma(values: number[], window: number): Array<number | null> {
  const out: Array<number | null> = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= window) sum -= values[i - window]
    if (i >= window - 1) out[i] = sum / window
  }
  return out
}

const toTime = (iso: string) => (Date.parse(iso) / 1000) as UTCTimestamp

export function PriceChart({
  candles,
  high52w,
  low52w,
}: {
  candles: Candle[]
  high52w?: number | null
  low52w?: number | null
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#8fa3ba',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(38,50,66,0.5)' },
        horzLines: { color: 'rgba(38,50,66,0.5)' },
      },
      rightPriceScale: { borderColor: '#263242', scaleMargins: { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: '#263242', rightOffset: 4 },
      crosshair: { mode: 1 },
      autoSize: true,
    })
    chartRef.current = chart

    const priceSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#35c97f',
      downColor: '#ef5f6b',
      borderUpColor: '#35c97f',
      borderDownColor: '#ef5f6b',
      wickUpColor: '#35c97f',
      wickDownColor: '#ef5f6b',
    })
    priceSeries.setData(
      candles.map((c) => ({
        time: toTime(c.trade_date),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    )

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } })
    volumeSeries.setData(
      candles.map((c) => ({
        time: toTime(c.trade_date),
        value: c.volume,
        color: c.close >= c.open ? 'rgba(53,201,127,0.35)' : 'rgba(239,95,107,0.35)',
      })),
    )

    const closes = candles.map((c) => c.close)
    const overlays: Array<[number, string]> = [
      [20, '#5b9dff'],
      [50, '#f0b429'],
      [200, '#b78cf0'],
    ]
    for (const [window, color] of overlays) {
      if (closes.length < window) continue
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      const values = sma(closes, window)
      series.setData(
        candles
          .map((c, i) => ({ time: toTime(c.trade_date), value: values[i] }))
          .filter((p): p is { time: UTCTimestamp; value: number } => p.value !== null),
      )
    }

    for (const [value, title, color] of [
      [high52w, '52w high', '#35c97f'],
      [low52w, '52w low', '#ef5f6b'],
    ] as Array<[number | null | undefined, string, string]>) {
      if (value == null) continue
      priceSeries.createPriceLine({
        price: value,
        color,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title,
      })
    }

    chart.timeScale().fitContent()
    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [candles, high52w, low52w])

  if (candles.length === 0) {
    return (
      <div className="h-full grid place-items-center text-[var(--muted)]">
        No price history stored for this symbol.
      </div>
    )
  }

  return <div ref={containerRef} className="w-full h-full" />
}
