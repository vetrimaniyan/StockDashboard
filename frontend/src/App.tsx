import { useCallback, useEffect, useMemo, useState } from 'react'
import { SignIn } from './components/SignIn'
import {
  ApiError,
  api,
  type DashboardResponse,
  type MetricDefinition,
  type PresetSummary,
  type ScreenResponse,
} from './api'
import { Backtest } from './components/Backtest'
import { Dashboard } from './components/Dashboard'
import { Screener } from './components/Screener'
import { StatusBar } from './components/StatusBar'
import { StockDetail } from './components/StockDetail'

type View = 'dashboard' | 'screener' | 'backtest'

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [presets, setPresets] = useState<PresetSummary[]>([])
  const [definitions, setDefinitions] = useState<MetricDefinition[]>([])
  const [activeScreen, setActiveScreen] = useState('Momentum Leaders')
  const [screen, setScreen] = useState<ScreenResponse | null>(null)
  const [screenLoading, setScreenLoading] = useState(false)
  const [symbol, setSymbol] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // null = not yet known. Any 401 flips this, so a session expiring
  // mid-use returns to sign-in rather than showing a broken dashboard.
  const [signedIn, setSignedIn] = useState<boolean | null>(null)

  const definitionMap = useMemo(
    () => new Map(definitions.map((d) => [d.name, d])),
    [definitions],
  )

  const handle = useCallback((e: ApiError) => {
    if (e.status === 401) {
      setSignedIn(false)
      setError(null)
      return
    }
    setError(e.message)
  }, [])

  const load = useCallback(() => {
    setError(null)
    Promise.all([api.dashboard(), api.presets(), api.metricDefinitions()])
      .then(([d, p, m]) => {
        setDashboard(d)
        setPresets(p)
        setDefinitions(m)
        setSignedIn(true)
      })
      .catch(handle)
  }, [handle])

  useEffect(load, [load])

  useEffect(() => {
    if (view !== 'screener') return
    setScreenLoading(true)
    api
      .presetScreen(activeScreen)
      .then(setScreen)
      .catch(handle)
      .finally(() => setScreenLoading(false))
  }, [view, activeScreen, handle])

  const openScreen = (name: string) => {
    setActiveScreen(name)
    setView('screener')
  }

  const status = dashboard?.status ?? screen?.status ?? null

  if (signedIn === false) {
    return <SignIn onSignedIn={load} />
  }

  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center gap-4 px-3 py-2 border-b border-[var(--border)] bg-[var(--panel)]">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold tracking-tight">Alpha-500</span>
          <span className="text-[var(--muted)]">NSE momentum &amp; swing screening</span>
        </div>

        <nav className="flex gap-1 ml-4">
          {(['dashboard', 'screener', 'backtest'] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1 rounded border capitalize ${
                view === v
                  ? 'border-[var(--accent)] bg-[var(--panel-2)]'
                  : 'border-transparent hover:border-[var(--border)]'
              }`}
            >
              {v}
            </button>
          ))}
        </nav>

        <span className="ml-auto text-[var(--muted)]">
          Decision support only — this application places no orders.
        </span>
        <button
          className="px-2 py-1 rounded border border-[var(--border)] hover:border-[var(--accent)]"
          onClick={load}
        >
          Refresh
        </button>
      </header>

      <StatusBar status={status} />

      {error && (
        <div className="px-3 py-2 bg-[rgba(239,95,107,0.12)] border-b border-[var(--down)] text-[var(--down)]">
          {error}
          <button className="ml-3 underline" onClick={load}>
            Retry
          </button>
        </div>
      )}

      <main className="flex-1 min-h-0">
        {view === 'dashboard' &&
          (dashboard ? (
            <Dashboard
              data={dashboard}
              onSelect={setSymbol}
              onOpenScreen={openScreen}
            />
          ) : (
            !error && <div className="p-8 text-[var(--muted)]">Loading dashboard…</div>
          ))}

        {view === 'backtest' && <Backtest presets={presets} />}

        {view === 'screener' && (
          <Screener
            presets={presets}
            active={activeScreen}
            screen={screen}
            loading={screenLoading}
            definitions={definitionMap}
            onSelectPreset={setActiveScreen}
            onSelectSymbol={setSymbol}
          />
        )}
      </main>

      {symbol && (
        <StockDetail
          symbol={symbol}
          definitions={definitionMap}
          onClose={() => setSymbol(null)}
        />
      )}
    </div>
  )
}
