/** Typed client for the Alpha-500 API. */

export interface DataStatus {
  data_as_of: string | null
  latest_session: string | null
  is_stale: boolean
  reason: string | null
  last_run_status: string | null
  last_run_at: string | null
  engine_stale: boolean
}

export interface MarketRegime {
  regime: string
  index_close: number | null
  sma_50: number | null
  sma_200: number | null
  net_new_highs: number | null
  advisory: string | null
}

export interface Breadth {
  new_highs: number
  new_lows: number
  net_new_highs: number
  advances: number
  declines: number
  universe: number
}

export interface SectorPerformance {
  sector: string
  median_ret_1w: number | null
  count: number
}

export interface PresetSummary {
  name: string
  description: string
  is_exit_screen: boolean
  is_universe: boolean
}

export interface UniverseChange {
  tradingsymbol: string
  change_type: string
  change_date: string
}

export type ScreenRow = Record<string, unknown> & {
  tradingsymbol: string
  name?: string | null
  sector?: string | null
}

export interface DashboardResponse {
  status: DataStatus
  regime: MarketRegime
  breadth: Breadth
  exit_signals: ScreenRow[]
  momentum_leaders: ScreenRow[]
  pullback_reversals: ScreenRow[]
  sector_heatmap: SectorPerformance[]
  universe_changes: UniverseChange[]
  presets: PresetSummary[]
}

export interface ScreenResponse {
  screen_name: string
  version: number
  definition: Record<string, unknown>
  data_as_of: string | null
  status: DataStatus
  row_count: number
  rows: ScreenRow[]
}

export interface MetricDefinition {
  name: string
  label: string
  formula: string
  description: string
  group: string
  unit: string
}

export interface Candle {
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  delivery_pct: number | null
}

export interface RiskSuggestion {
  atr_stop_price: number | null
  atr_stop_distance_pct: number | null
  structural_stop_price: number | null
  wider_stop: string | null
  quantity: number | null
  position_value: number | null
  exceeds_max_weight: boolean
  breakeven_move_pct: number | null
  round_trip_cost_pct: number | null
  net_gain_at_target_pct: number | null
  cost_exceeds_atr_target: boolean
}

export interface StockDetail {
  tradingsymbol: string
  name: string | null
  sector: string | null
  industry: string | null
  status: DataStatus
  metrics: Record<string, unknown>
  candles: Candle[]
  corporate_actions: Array<Record<string, unknown>>
  upcoming_ex_dates: Array<Record<string, unknown>>
  risk: RiskSuggestion
}

export class ApiError extends Error {
  status: number
  retriable: boolean

  constructor(message: string, status: number, retriable = false) {
    super(message)
    this.status = status
    this.retriable = retriable
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    // Carries the session cookie. The token itself is never held in JS: it is
    // exchanged once for an httpOnly cookie, so no script on the page — ours
    // or anyone else's — can read it back out.
    credentials: 'include',
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText
    let retriable = false
    try {
      const body = await response.json()
      detail = body.detail ?? detail
      retriable = Boolean(body.retry)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status, retriable)
  }
  return (await response.json()) as T
}

export const api = {
  /** Reachable without a credential; says only whether one is wanted. */
  health: () => request<{ status: string; auth_required: boolean }>('/api/health'),
  signIn: (token: string) =>
    request<{ status: string; label: string }>('/api/session', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  signOut: () => request<{ status: string }>('/api/session/end', { method: 'POST' }),
  status: () => request<DataStatus>('/api/status'),
  dashboard: () => request<DashboardResponse>('/api/dashboard'),
  presets: () => request<PresetSummary[]>('/api/presets'),
  metricDefinitions: () => request<MetricDefinition[]>('/api/metrics/definitions'),
  presetScreen: (name: string) =>
    request<ScreenResponse>(`/api/screen/${encodeURIComponent(name)}`),
  customScreen: (definition: Record<string, unknown>) =>
    request<ScreenResponse>('/api/screen', {
      method: 'POST',
      body: JSON.stringify(definition),
    }),
  stock: (symbol: string) =>
    request<StockDetail>(`/api/stock/${encodeURIComponent(symbol)}`),
  indexValuation: () => request<IndexValuationResponse>('/api/indices/valuation'),
  backtestAvailability: () =>
    request<BacktestAvailability>('/api/backtest/availability'),
  backtest: (params: BacktestParams) =>
    request<BacktestResponse>('/api/backtest', {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  exportScreen: (
    fmt: 'xlsx' | 'csv' | 'html',
    payload: { screen_name: string; definition: Record<string, unknown>; columns?: string[] },
  ) =>
    request<{ path: string; filename: string; row_count: number; data_as_of: string }>(
      `/api/export/${fmt}`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
}

export interface IndexValuation {
  index_name: string
  as_of: string | null
  close: number | null
  pe: number | null
  pb: number | null
  div_yield: number | null
  median_pe_7y: number | null
  median_pe_10y: number | null
  sessions_7y: number
  sessions_10y: number
  pe_vs_7y_pct: number | null
  pe_vs_10y_pct: number | null
}

export interface IndexValuationResponse {
  indices: IndexValuation[]
  history_from: string | null
  history_to: string | null
  observations: number
  note: string
}

export interface BacktestAvailability {
  ready: boolean
  sessions: number
  start: string | null
  end: string | null
  reason: string | null
}

export interface BacktestPerformance {
  final_equity: number
  total_return_pct: number
  cagr_pct: number
  max_drawdown_pct: number
  max_drawdown_days: number
  sharpe: number | null
  sortino: number | null
  volatility_pct: number | null
}

export interface BacktestTradeStats {
  trades: number
  winners: number
  losers: number
  hit_rate_pct: number | null
  avg_win_pct: number | null
  avg_loss_pct: number | null
  win_loss_ratio: number | null
  avg_holding_days: number | null
  median_holding_days: number | null
  exposure_pct: number | null
  total_costs: number
  total_tds: number
}

export interface BacktestTrade {
  symbol: string
  entry_date: string
  entry_price: number
  quantity: number
  exit_date: string | null
  exit_price: number | null
  exit_reason: string | null
  holding_days: number
  gross_pnl: number
  costs: number
  tds: number
  net_pnl: number
  net_return_pct: number
}

export interface SweepPointResult {
  value: number
  metric: number
  trades: number
  max_drawdown_pct: number
  sharpe: number | null
}

export interface SweepResult {
  best_value: number | null
  best_metric: number
  is_narrow_peak: boolean
  plateau_width: number
  warning: string | null
  points: SweepPointResult[]
}

export interface WalkForwardWindow {
  train_start: string
  train_end: string
  test_start: string
  test_end: string
  chosen_value: number
  in_sample_cagr: number
  out_of_sample_cagr: number
  out_of_sample_trades: number
  narrow_peak: boolean
}

export interface WalkForwardResult {
  windows: WalkForwardWindow[]
  in_sample_cagr: number | null
  out_of_sample_cagr: number | null
  degradation_pct: number | null
  warning: string | null
}

export interface BacktestBenchmark {
  index_name: string
  cagr_pct: number
  total_return_pct: number
  max_drawdown_pct: number
  curve: { date: string; close: number }[]
}

export interface BacktestResponse {
  gross_of_tax: BacktestPerformance
  net_of_tax: BacktestPerformance
  trades: BacktestTradeStats
  sessions: number
  start: string | null
  end: string | null
  warnings: string[]
  trades_detail: BacktestTrade[]
  equity_curve: { date: string; gross: number; net: number }[]
  benchmark: BacktestBenchmark | null
  config: Record<string, unknown>
  sweep?: SweepResult
  walk_forward?: WalkForwardResult
}

export interface BacktestParams {
  screen_name: string
  stop_atr_multiple: number
  trailing_stop: boolean
  use_exit_screen: boolean
  max_positions: number
  initial_capital: number
  sweep?: number[]
  walk_forward?: boolean
}
