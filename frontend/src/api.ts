/** Typed client for the Alpha-500 API. */

export interface DataStatus {
  data_as_of: string | null
  latest_session: string | null
  is_stale: boolean
  reason: string | null
  last_run_status: string | null
  last_run_at: string | null
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
  round_trip_cost_pct: number | null
  breakeven_move_pct: number | null
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
}
