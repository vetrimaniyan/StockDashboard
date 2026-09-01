/** Candlestick chart with volume and moving averages (FR-8.4). */

import { useEffect, useRef } from 'react'
import {
  BaselineSeries,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
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

/** The FR-17 leg, as the chart needs it. All optional: most symbols have none. */
export interface FibOverlay {
  legLowDate?: string | null
  legLowPrice?: number | null
  legHighDate?: string | null
  legHighPrice?: number | null
  /** The session the leg became usable — NOT the session the high printed. */
  confirmedDate?: string | null
  level382?: number | null
  level500?: number | null
  level618?: number | null
  level786?: number | null
  stop?: number | null
}

export function PriceChart({
  candles,
  high52w,
  low52w,
  fib,
}: {
  candles: Candle[]
  high52w?: number | null
  low52w?: number | null
  fib?: FibOverlay | null
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

    // --- FR-17.10 retracement overlay ------------------------------------
    if (fib?.legLowDate && fib.legHighDate && fib.legLowPrice && fib.legHighPrice) {
      const zoneLow = fib.level618
      const zoneHigh = fib.level500

      // Shade the 50-61.8% band. A baseline series fills between its line and
      // its base value, which is the only native way to shade a price band.
      if (zoneLow != null && zoneHigh != null) {
        const band = chart.addSeries(BaselineSeries, {
          baseValue: { type: 'price', price: zoneLow },
          topFillColor1: 'rgba(91,157,255,0.16)',
          topFillColor2: 'rgba(91,157,255,0.16)',
          topLineColor: 'rgba(91,157,255,0)',
          bottomFillColor1: 'rgba(0,0,0,0)',
          bottomFillColor2: 'rgba(0,0,0,0)',
          bottomLineColor: 'rgba(0,0,0,0)',
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        band.setData(
          candles.map((c) => ({ time: toTime(c.trade_date), value: zoneHigh })),
        )
      }

      // The impulse leg itself: A to B, two points.
      const legSeries = chart.addSeries(LineSeries, {
        color: '#f0b429',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      legSeries.setData([
        { time: toTime(fib.legLowDate), value: fib.legLowPrice },
        { time: toTime(fib.legHighDate), value: fib.legHighPrice },
      ])

      // FR-17.10: the confirmation marker is required. Without it the chart
      // implies the level was knowable on the session the high printed, which
      // is exactly the look-ahead the metric is built to avoid.
      const markers: Array<{
        time: UTCTimestamp
        position: 'aboveBar' | 'belowBar'
        color: string
        shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square'
        text: string
      }> = [
        {
          time: toTime(fib.legLowDate),
          position: 'belowBar' as const,
          color: '#5b9dff',
          shape: 'arrowUp' as const,
          text: `A ${fib.legLowPrice.toFixed(2)}`,
        },
        {
          time: toTime(fib.legHighDate),
          position: 'aboveBar' as const,
          color: '#f0b429',
          shape: 'arrowDown' as const,
          text: `B ${fib.legHighPrice.toFixed(2)}`,
        },
      ]
      if (fib.confirmedDate && fib.confirmedDate !== fib.legHighDate) {
        markers.push({
          time: toTime(fib.confirmedDate),
          position: 'aboveBar' as const,
          color: '#8fa3ba',
          shape: 'circle' as const,
          text: 'leg usable from here',
        })
      }
      markers.sort((a, b) => (a.time as number) - (b.time as number))
      createSeriesMarkers(priceSeries, markers)

      const levels: Array<[number | null | undefined, string, string]> = [
        [fib.level382, '38.2%', '#8fa3ba'],
        [fib.level500, '50%', '#5b9dff'],
        [fib.level618, '61.8%', '#5b9dff'],
        [fib.level786, '78.6%', '#8fa3ba'],
      ]
      for (const [value, ratio, color] of levels) {
        if (value == null) continue
        priceSeries.createPriceLine({
          price: value,
          color,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `${ratio} ${value.toFixed(2)}`,
        })
      }
      if (fib.stop != null) {
        priceSeries.createPriceLine({
          price: fib.stop,
          color: '#ef5f6b',
          lineWidth: 2,
          lineStyle: 0,
          axisLabelVisible: true,
          title: `stop ${fib.stop.toFixed(2)}`,
        })
      }
    }

    chart.timeScale().fitContent()
    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [candles, high52w, low52w, fib])

  if (candles.length === 0) {
    return (
      <div className="h-full grid place-items-center text-[var(--muted)]">
        No price history stored for this symbol.
      </div>
    )
  }

  return <div ref={containerRef} className="w-full h-full" />
}
