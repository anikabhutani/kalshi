/** Typed client for the Kalshi Recon backend (never talks to Kalshi directly). */

export type ConnectionState =
  | 'not_configured'
  | 'ok'
  | 'unauthorized'
  | 'forbidden'
  | 'rate_limited'
  | 'offline'
  | 'error'

export interface ConnectionStatus {
  state: ConnectionState
  http_status: number | null
  latency_ms: number | null
  path: string
  checked_at: string
  message: string
}

export interface RuntimeSettings {
  api_version: string | null
  date_checked: string | null
  base_url: string
  rate_limit_rps: number
  rate_limit_burst: number
  max_requests_per_job: number
  auth_check_path: string
}

export interface ServerEntry {
  url: string
  description: string
}

export interface Meta {
  openapi: {
    title: string
    version: string
    servers: ServerEntry[]
    endpoint_count: number
    get_endpoint_count: number
  }
  asyncapi: {
    title: string
    version: string
    servers: (ServerEntry & { name: string; pathname: string })[]
    channels: string[]
  }
  credentials_configured: boolean
  settings: RuntimeSettings
  auth_check_choices: string[]
}

export interface RateLimitSnapshot {
  tokens: number
  capacity: number
  rate_per_s: number
  cooldown_remaining_s: number
  requests_last_60s: number
  running_jobs: number
}

export interface RequestRow {
  id: number
  job_id: string | null
  module: string
  timestamp_utc: string
  method: string
  url: string
  path_template: string | null
  params: Record<string, unknown>
  auth_used: boolean
  status_code: number | null
  latency_ms: number | null
  response_bytes: number | null
  response_headers: Record<string, string>
  response_body_sample: string | null
  raw_path: string | null
  error: string | null
}

export type JobStatus = 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface Job<R = unknown> {
  id: string
  module: string
  kind: string
  status: JobStatus
  params: Record<string, unknown>
  result: R | null
  error_reason: string | null
  request_count: number
  max_requests: number
  started_at: string
  finished_at: string | null
}

export type JobEvent =
  | { type: 'status'; status: JobStatus; reason?: string | null; ts: string }
  | { type: 'progress'; done: number; total: number; message: string; ts: string }
  | { type: 'log'; level: 'info' | 'warn' | 'error'; message: string; ts: string }

export type QuestionId = 'Q1' | 'Q2' | 'Q3' | 'Q4' | 'Q5' | 'Q6'

export interface QuestionProgress {
  id: QuestionId
  title: string
  prompt: string
  modules: string[]
  page: string
  jobs_run: number
  evidence_count: number
  has_notes: boolean
}

export interface NoteEntry {
  text: string
  updated_at: string | null
}

export interface SanityCheckRow {
  label: string
  path: string
  auth: boolean
  status_code: number | null
  latency_ms?: number
  server_date?: string | null
  local_received_at?: string
  clock_offset_s?: number | null
  request_id?: number
  error: string | null
}

export interface SanityResult {
  checks: SanityCheckRow[]
}

export interface RequestEstimate {
  total: number
  cap: number
  [part: string]: number
}

/* ---------- M1: endpoint catalog and auth probe ---------- */

export type ProbeClassification =
  | 'public'
  | 'key required'
  | 'denied even with key'
  | 'inconclusive'
  | 'error'
  | 'not probed'

export interface ProbeCall {
  status: number | null
  latency_ms: number
  request_id: number
  error: string | null
}

export interface ProbeResult {
  endpoint_id: string
  concrete_path?: string
  params?: Record<string, string | number>
  no_auth?: ProbeCall
  auth?: ProbeCall | null
  classification: ProbeClassification
  mismatch?: boolean | null
  note: string
}

export interface CatalogEndpoint {
  id: string
  method: string
  path: string
  category: string
  tags: string[]
  summary: string
  auth_required_spec: boolean
  params: string[]
  path_params: string[]
  required_query_params: string[]
  pagination_params: string[]
  time_range_params: string[]
  timestamp_fields: string[]
  historical_signals: string[]
  account_specific: boolean
  probe: ProbeResult | null
  user: { rating: number | null; reason: string }
}

export interface Catalog {
  spec_version: string
  endpoints: CatalogEndpoint[]
  probe_job: {
    id: string
    status: JobStatus
    finished_at: string | null
    partial: boolean
    discovered_ids: Record<string, string>
  } | null
}

export interface ProbePlan {
  targets: number
  skipped: number
  needed_ids: string[]
  credentials_configured: boolean
  estimate: RequestEstimate
}

/* ---------- M2: schema explorer ---------- */

export interface CategoriesResponse {
  categories: { name: string; tags: string[] }[]
  suggested_category: string | null
  sport_ordering: string[]
  event_statuses: string[]
}

export interface SeriesItem {
  ticker: string
  title: string
  frequency: string | null
  category: string | null
  tags: string[]
}

export interface EventItem {
  event_ticker: string
  title: string | null
  sub_title: string | null
  strike_date: string | null
  last_updated_ts: string | null
}

export interface EventsPage {
  events: EventItem[]
  cursor: string | null
}

export interface FieldRow {
  path: string
  types: string[]
  example: string | null
  present_in: number
  samples: number
  null_count: number
  nullable_observed: boolean
  timestamp_like: boolean
  timestamp_format: string | null
  name_looks_like_timestamp: boolean
  distinct_values: (string | number | boolean)[]
  distinct_values_truncated: boolean
  in_spec: boolean | null
  spec_type: string | null
  spec_format: string | null
  spec_nullable: boolean | null
  spec_required: boolean | null
  spec_enum: unknown[] | null
  values_outside_spec_enum: (string | number | boolean)[]
  spec_description: string | null
}

export interface EntityDictionary {
  samples: number
  spec_source: string
  request_id: number | null
  fields: FieldRow[]
  spec_fields_not_observed: string[]
  /** Absent in pulls stored before this field existed. */
  omitted_fields?: string[]
}

export interface LinkRow {
  child: string
  parent: string
  records: number
  matching: number
}

export interface TreeMarket {
  ticker: string
  event_ticker: string
  yes_sub_title: string | null
  status: string | null
  open_time: string | null
  close_time: string | null
}

export interface PullResult {
  series_ticker: string
  event_ticker: string
  markets_source: string
  entities: { series: EntityDictionary; event: EntityDictionary; market: EntityDictionary }
  tree: {
    series: { ticker: string; title: string }
    event: { event_ticker: string; series_ticker: string; title: string; sub_title: string }
    markets: TreeMarket[]
  }
  links: LinkRow[]
  nested_vs_list: { nested_count: number; list_count: number; only_in_nested: string[]; only_in_list: string[] }
}

/* ---------- M3: timestamp lab ---------- */

export interface MarketSummary {
  ticker: string
  event_ticker: string
  title: string | null
  yes_sub_title: string | null
  status: string | null
  open_time: string | null
  close_time: string | null
  expected_expiration_time: string | null
  occurrence_datetime: string | null
  settlement_ts: string | null
}

export interface LoadedMarket {
  market: MarketSummary
  series_ticker: string | null
  source: 'live' | 'historical'
  archived: boolean
  cutoff: Record<string, string>
  suggested_window: { start_ts: number; end_ts: number }
}

export interface LabParams {
  market_ticker: string
  series_ticker: string | null
  start_ts: number
  end_ts: number
  trade_page_cap: number
  trade_bucket_s: number
  archived: boolean
}

export interface GapRun {
  start_s: number
  end_s: number
  slots: number
}

export interface GapStats {
  interval_s: number
  origin_s: number | null
  expected_slots: number
  filled_slots: number
  empty_slots: number
  empty_pct: number | null
  longest_empty_run_slots: number
  longest_empty_run_s: number
  median_empty_run_s: number | null
  runs: GapRun[]
  runs_truncated: boolean
}

interface SeriesMetrics {
  records: number
  first_ts: string | null
  last_ts: string | null
  covered_s: number
  finest_granularity_s: number | null
  median_delta_s: number | null
  max_delta_s: number | null
  timestamp_field: string
}

export interface CandleMetrics extends SeriesMetrics {
  alignment_offset_s: number | null
  candles_without_trade: number
  missing_periods: GapStats
  periods_without_trade: GapStats
  timestamp_format: string | null
}

export interface TradeMetrics extends SeriesMetrics {
  truncated_by_page_cap: boolean
  bucket_s: number
  empty_buckets: GapStats
  timestamp_formats: string[]
}

export interface CandleRow {
  ts: number
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  mean: number | null
  bid_close: number | null
  ask_close: number | null
  volume: number | null
  open_interest: number | null
}

export interface TradeRow {
  ts: number
  price: number | null
  count: number | null
  side: string | null
  block: boolean
  source: 'live' | 'historical'
}

export interface CandleSource {
  kind: 'candles'
  interval_min: number
  endpoint: string
  request_ids: number[]
  rows: CandleRow[]
  metrics: CandleMetrics
}

export interface TradeSource {
  kind: 'trades'
  endpoints: string[]
  request_ids: number[]
  rows: TradeRow[]
  metrics: TradeMetrics
}

export interface OrderbookSource {
  kind: 'orderbook'
  endpoint: string
  status: number | null
  yes_levels: number
  no_levels: number
  best_yes_bid: number | null
  best_no_bid: number | null
  implied_yes_ask: number | null
  mid: number | null
  snapshot_ts: number
  server_date: string | null
  has_timestamp_field: boolean
  request_id: number
}

export type LabSource = CandleSource | TradeSource | OrderbookSource

export interface ClockRow {
  request_id: number
  path: string
  sent_at: string
  server_date: string | null
  offset_s: number | null
  latency_ms: number
  status: number | null
}

export interface ClockSummary {
  requests: number
  offset_median_s: number | null
  offset_min_s: number | null
  offset_max_s: number | null
  latency_median_ms: number | null
  latency_p95_ms: number | null
  latency_max_ms: number | null
  date_header_resolution_s: number
}

export interface MetadataTimestamp {
  field: string
  value: unknown
  detected_format: string | null
  spec_format: string | null
  spec_description: string | null
  utc: string | null
  epoch_s: number | null
}

export interface LabResult {
  params: LabParams
  sources: Record<string, LabSource>
  errors: { source: string; message: string; request_id: number }[]
  clock: { rows: ClockRow[]; summary?: ClockSummary }
  cutoff?: Record<string, string>
  market?: MarketSummary
  market_source?: string
  archived?: boolean
  metadata_timestamps?: MetadataTimestamp[]
  candle_endpoint?: string
  partial?: boolean
}

export interface PriceAtRow {
  source: string
  field: string
  price: number | null
  price_ts: string | null
  staleness_s: number | null
  before_first_record: boolean
  after_last_record: boolean
  records: number
  note: string
}

/* ---------- M4: depth and archive ---------- */

export interface DepthTarget {
  id: string
  label: string
  path: string
  mode: 'bisect' | 'walk'
  list_key: string
  ts_field: string
  ts_format: string | null
  bound_param: string | null
  bound_description: string | null
  fixed_params: Record<string, string>
  series_param: string | null
  ticker_param: string | null
  page_limit: number | null
  available: boolean
  reason: string | null
}

export interface DepthParams {
  targets: string[]
  series_ticker: string | null
  market_ticker: string | null
  search_from: string
  resolution: 'hour' | 'day'
  walk_page_cap: number
  archive_matrix: boolean
  request_cap: number
}

export interface DepthTargetsResponse {
  targets: DepthTarget[]
  cutoff_description: string | null
  defaults: DepthParams
}

export interface DepthProbe {
  bound: number | null
  status: number | null
  records: number
  record_ts: number | null
  request_id: number | null
  error: string | null
}

export interface WalkPage {
  index: number
  status: number | null
  records: number
  min_ts: number | null
  max_ts: number | null
  cursor_returned: boolean
  request_id: number
}

export interface DepthTargetResult extends DepthTarget {
  filters_applied: Record<string, string>
  stop_reason?: string | null
  oldest_ts?: number | null
  newest_ts?: number | null
  oldest_utc?: string | null
  newest_utc?: string | null
  probes?: DepthProbe[]
  lower_bound?: number
  upper_bound?: number
  resolution_s?: number
  bracket_lo?: number | null
  bracket_hi?: number | null
  beyond_lower_bound?: boolean
  no_records?: boolean
  pages?: WalkPage[]
  records_seen?: number
  end_reached?: boolean
}

export interface MatrixCell {
  check: string
  endpoint: string
  status: number | null
  records: number | null
  request_id: number | null
  note: string | null
}

export interface MatrixSample {
  label: string
  ticker: string
  cells: MatrixCell[]
  event_ticker?: string | null
  status?: string | null
  close_time?: string | null
  settlement_ts?: string | null
  cutoff_side?: string
  series_ticker?: string | null
}

export interface CutoffValue {
  raw: unknown
  epoch_s: number | null
  utc: string | null
}

export interface DepthResult {
  params: DepthParams
  estimate: RequestEstimate
  run_at: string
  cutoff: Record<string, CutoffValue>
  targets: DepthTargetResult[]
  matrix: {
    discovery: { label: string; path: string; status: number | null; ticker: string | null; request_id: number }[]
    samples: MatrixSample[]
    stop_reason: string | null
  } | null
  notes: string[]
  partial?: boolean
}

/* ---------- M5: limits ---------- */

export interface PaginationChoice {
  path: string
  size_param: string
  size_default: number | null
  size_minimum: number | null
  size_maximum: number | null
  size_description: string | null
  cursor_description: string | null
  filter_params: string[]
  list_keys: string[]
}

export interface RateDoc {
  tiers: { tier: string; read_budget: number | null; write_budget: number | null }[]
  default_cost_tokens: number | null
  sections: { heading: string; text: string }[]
  client_limiter: { rate_limit_rps: number; rate_limit_burst: number }
  ramp_choices: string[]
  pagination_choices: PaginationChoice[]
  credentials_configured: boolean
}

export interface AccountLimitsResult {
  limits: Record<string, unknown> | null
  endpoint_costs: Record<string, unknown> | null
  calls: { path: string; auth: boolean; status: number | null; request_id?: number; error?: string | null; note?: string }[]
}

export interface RampParams {
  path: string
  auth: boolean
  start_rps: number
  step_rps: number
  max_rps: number
  requests_per_step: number
}

export interface RampRequestRow {
  step: number
  target_rps: number
  index: number
  t_s: number
  latency_ms: number | null
  status: number | null
  rate_headers?: Record<string, string>
  request_id?: number
  error?: string | null
}

export interface RampStep {
  target_rps: number
  requests: number
  achieved_rps: number | null
  latency_median_ms: number | null
  latency_p95_ms: number | null
  latency_max_ms: number | null
  status_counts: Record<string, number>
  rate_limited: number
}

export interface RampResult {
  params: RampParams
  rates: number[]
  limiter: { rate_limit_rps: number; rate_limit_burst: number }
  other_running_jobs_at_start: number
  started_at: string
  requests: RampRequestRow[]
  steps: RampStep[]
  first_429?: { step: number; target_rps: number; index: number; t_s: number; message: string } | null
  stopped_reason?: string | null
  header_names_seen?: string[]
  rate_header_names_seen?: string[]
  partial?: boolean
}

export interface PaginationParams {
  path: string
  filters: Record<string, string>
  walk_size: number | null
  page_cap: number
  boundary_tests: boolean
}

export interface BoundaryRow {
  case: string
  size_sent: number | null
  status: number | null
  items: number | null
  list_key: string | null
  cursor_returned: boolean | null
  error_sample: string | null
  request_id: number
}

export interface PageRow {
  page: number
  status: number | null
  items: number
  duplicates_of_earlier_pages: number
  cursor_length: number | null
  cursor_prefix: string | null
  cursor_repeated: boolean
  end_signal: string | null
  list_key: string | null
  request_id: number
}

export interface PaginationResult {
  params: PaginationParams
  spec: PaginationChoice
  walk_size: number
  boundary: BoundaryRow[]
  pages: PageRow[]
  summary?: {
    identity_key: string | null
    unique_items: number
    duplicate_items: number
    pages_fetched: number
    last_page_reached: boolean
    last_page_signal: string | null
    last_page_items: number | null
    last_page_smaller_than_size: boolean
  }
  partial?: boolean
}

/* ---------- M6: REST vs WebSocket ---------- */

export type WsChannel = 'ticker' | 'trade' | 'orderbook_delta'

export interface RecorderParams {
  market_ticker: string
  duration_min: number
  poll_interval_s: number
  channels: WsChannel[]
  poll_trades: boolean
}

export interface SpecCompareRow {
  aspect: string
  rest: string
  rest_source: string
  websocket: string
  ws_source: string
}

export interface FieldPairing {
  state: string
  rest: string
  websocket: string
}

export interface WsSpecView {
  ws_url: string | null
  rows: SpecCompareRow[]
  asyncapi_version: string
  channels: { name: string; title: string; messages: string[] }[]
  error_codes: { code: number; name: string; description: string }[]
  recordable_channels: WsChannel[]
  field_pairing: FieldPairing[]
  credentials_configured: boolean
  rate_limit_rps: number
}

export interface Distribution {
  count: number
  min: number | null
  median: number | null
  p95: number | null
  max: number | null
}

export interface WsEvent {
  recv_ms: number
  type: string
  sid?: number | null
  seq?: number | null
  sending_ts_ms?: number | null
  ts_ms?: number | null
  market_ticker?: string | null
  yes_bid?: number | null
  yes_ask?: number | null
  last_price?: number | null
  volume?: number | null
  trade_id?: string | null
  yes_price?: number | null
  count?: number | null
  taker_outcome_side?: string | null
  price?: number | null
  delta?: number | null
  side?: string | null
  code?: number | null
  message?: string | null
}

export interface RestPoll {
  cycle: number
  sent_ms: number
  recv_ms: number
  status: number | null
  latency_ms: number | null
  request_id: number
  yes_bid: number | null
  yes_ask: number | null
  last_price: number | null
  market_status: string | null
  clock_offset_s: number | null
  error: string | null
}

export interface TradePoll {
  cycle: number
  sent_ms: number
  status: number | null
  min_ts: number
  items: number | null
  new_trades: number
  latency_ms: number | null
  request_id: number
}

export interface PollInterval {
  start_ms: number
  end_ms: number
  ws_changes: number
  rest_changed: boolean
  missed: number
}

export interface WsConnectionRow {
  attempt: number
  at_ms: number
  status: number | null
  latency_ms: number
  error: string | null
  request_id: number
}

export interface SequenceRow {
  sid: number | null
  types: string[]
  messages: number
  first_seq: number
  last_seq: number
  missing: number
  out_of_order: number
}

export interface RecorderResult {
  params: RecorderParams
  ws_url: string
  started_at: string
  start_ms: number
  end_ms: number
  planned_duration_s: number
  recorded_s: number
  stopped_reason: string | null
  market_status: string | null
  field_pairing: FieldPairing[]
  connections: WsConnectionRow[]
  disconnects: { attempt: number; at_ms: number; code: number | null; reason: string }[]
  reconnects: number
  acks: { id?: number; type?: string; attempt: number; msg?: { channel?: string; sid?: number; code?: number; msg?: string } }[]
  ws: {
    messages: number
    message_counts: Record<string, number>
    ticker_messages: number
    price_changes: number
    errors: WsEvent[]
    latency: Record<string, { recv_minus_ts_ms: Distribution; recv_minus_sending_ts_ms: Distribution }>
    sequence: SequenceRow[]
    raw_file: string
    events_stored: number
    events_truncated: boolean
    metrics_capped_at: number | null
  }
  rest: {
    polls: number
    ok_polls: number
    price_changes: number
    latency_ms: Distribution
    clock_offset_median_s: number | null
    trade_polls: number
    trade_pages_full: number
  }
  comparison: {
    intervals: number
    ws_changes_between_polls: number
    rest_changes: number
    rest_missed_changes: number
    intervals_ws_changed_rest_unchanged: number
    intervals_rest_changed_ws_unchanged: number
    intervals_multiple_ws_changes: number
    per_interval: PollInterval[]
  }
  trades: {
    window_start_ms: number | null
    window_end_ms: number | null
    ws_trades: number
    rest_trades: number
    matched: number
    ws_only: number
    rest_only: number
    ws_only_ids: string[]
    rest_only_ids: string[]
    rest_delay_after_ws_ms: Distribution
  }
  ws_change_times: number[]
  events: WsEvent[]
  polls: RestPoll[]
  trade_polls: TradePoll[]
  partial?: boolean
}

/* ---------- M7: sportsbook overlay ---------- */

export interface DatasetSummary {
  id: string
  name: string
  is_dummy: boolean
  source_job_id: string | null
  created_at: string
  rows: number
  error_count: number
  books: string[]
  events: string[]
  markets: string[]
  first_ts: string | null
  last_ts: string | null
}

export interface DatasetUpload extends DatasetSummary {
  errors: { line: number; message: string }[]
  notes: string[]
}

export interface LabSeriesOption {
  id: string
  label: string
  note: string
  points: number
}

export interface LabSeriesResponse {
  job_id: string
  market_ticker: string | null
  window: { start: string | null; end: string | null }
  series: LabSeriesOption[]
}

export interface OverlayParams {
  dataset_id: string
  lab_job_id: string
  selection: string
  series_id: string
  max_staleness_s: number
}

export interface OverlayRow {
  timestamp_utc: string
  ts: number
  book: string
  event: string
  market: string
  implied_prob: number
  no_vig_prob: number | null
  kalshi_price: number | null
  kalshi_price_ts: string | null
  kalshi_prob: number | null
  staleness_s: number | null
  within_staleness: boolean
  gap_no_vig_pp: number | null
  gap_implied_pp: number | null
}

export interface OverlayBookSummary {
  book: string
  rows: number
  with_kalshi_price: number
  within_staleness: number
  gap_no_vig_pp: Distribution
  mean_abs_gap_no_vig_pp: number | null
  gap_implied_pp: Distribution
}

export interface OverlayResult {
  rows: OverlayRow[]
  summary: OverlayBookSummary[]
  dataset: DatasetSummary
  is_dummy: boolean
  market_ticker: string | null
  series: { id: string; label: string; note: string }
  kalshi_points: { ts: number; price: number }[]
  params: OverlayParams
}

/* ---------- M8: evidence and export ---------- */

export interface ExportSummary {
  openapi_version: string
  asyncapi_version: string
  api_version_confirmed: string | null
  date_checked: string | null
  base_url: string
  requests_by_module: Record<string, number>
  jobs_by_module: Record<string, number>
  notes_written: QuestionId[]
  questions: QuestionId[]
  latest_results: Record<string, { id: string; finished_at: string | null; status: JobStatus } | null>
  exports: number
}

export interface ExportInfo {
  name: string
  path: string
  created_at: string
  files: { path: string; bytes: number }[]
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof TypeError) {
    return 'The backend is not reachable. Is it running on port 8000?'
  }
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function detailToMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg ?? ''}`)
      .join('; ')
  }
  return `Request failed (HTTP ${status}).`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let detail: unknown = null
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail
    } catch {
      detail = null
    }
    throw new ApiError(response.status, detailToMessage(detail, response.status))
  }
  return (await response.json()) as T
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.set(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const api = {
  meta: () => request<Meta>('/api/meta'),
  status: (refresh = false) => request<ConnectionStatus>(`/api/status${refresh ? '?refresh=true' : ''}`),
  rateLimit: () => request<RateLimitSnapshot>('/api/ratelimit'),
  updateSettings: (patch: Partial<RuntimeSettings>) =>
    request<RuntimeSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(patch) }),
  home: () => request<QuestionProgress[]>('/api/home'),
  notes: () => request<Record<QuestionId, NoteEntry>>('/api/notes'),
  saveNote: (questionId: QuestionId, text: string) =>
    request<{ question_id: string; updated_at: string }>(`/api/notes/${questionId}`, {
      method: 'PUT',
      body: JSON.stringify({ text }),
    }),
  requests: (filter: { jobId?: string; module?: string; limit?: number }) =>
    request<RequestRow[]>(
      `/api/requests${query({ job_id: filter.jobId, module: filter.module, limit: filter.limit })}`,
    ),
  rawBody: (requestId: number) => request<unknown>(`/api/requests/${requestId}/raw`),
  job: <R>(jobId: string) => request<Job<R>>(`/api/jobs/${jobId}`),
  latestJob: <R>(module: string, kind: string) =>
    request<Job<R> | null>(`/api/jobs/latest${query({ module, kind })}`),
  stopJob: (jobId: string) => request<{ stopped: boolean }>(`/api/jobs/${jobId}/stop`, { method: 'POST' }),
  stopAllJobs: () => request<{ stopped: number }>('/api/jobs/stop-all', { method: 'POST' }),
  runSanityCheck: () => request<{ job_id: string }>('/api/sanity/run', { method: 'POST' }),

  catalog: () => request<Catalog>('/api/m1/catalog'),
  saveRating: (endpointId: string, rating: number | null, reason: string) =>
    request<{ endpoint_id: string; updated_at: string }>('/api/m1/ratings', {
      method: 'PUT',
      body: JSON.stringify({ endpoint_id: endpointId, rating, reason }),
    }),
  probePlan: (includeAccount: boolean) =>
    request<ProbePlan>('/api/m1/probe/plan', {
      method: 'POST',
      body: JSON.stringify({ include_account: includeAccount }),
    }),
  runProbe: (includeAccount: boolean) =>
    request<{ job_id: string }>('/api/m1/probe/run', {
      method: 'POST',
      body: JSON.stringify({ include_account: includeAccount }),
    }),

  categories: () => request<CategoriesResponse>('/api/m2/categories'),
  series: (category: string, tag: string | null) =>
    request<SeriesItem[]>(`/api/m2/series${query({ category, tag })}`),
  events: (seriesTicker: string, status: string | null, cursor: string | null) =>
    request<EventsPage>(`/api/m2/events${query({ series_ticker: seriesTicker, status, cursor })}`),
  pullGame: (seriesTicker: string, eventTicker: string) =>
    request<{ job_id: string }>('/api/m2/pull', {
      method: 'POST',
      body: JSON.stringify({ series_ticker: seriesTicker, event_ticker: eventTicker }),
    }),

  loadMarket: (ticker: string) => request<LoadedMarket>(`/api/m3/market${query({ ticker })}`),
  labPlan: (params: LabParams) =>
    request<{ estimate: RequestEstimate }>('/api/m3/plan', { method: 'POST', body: JSON.stringify(params) }),
  runLab: (params: LabParams) =>
    request<{ job_id: string }>('/api/m3/run', { method: 'POST', body: JSON.stringify(params) }),
  priceAt: (jobId: string, at: string) =>
    request<{ query_ts: string; rows: PriceAtRow[] }>(`/api/m3/price_at${query({ job_id: jobId, at })}`),

  depthTargets: () => request<DepthTargetsResponse>('/api/m4/targets'),
  depthPlan: (params: DepthParams) =>
    request<{ estimate: RequestEstimate }>('/api/m4/plan', { method: 'POST', body: JSON.stringify(params) }),
  runDepth: (params: DepthParams) =>
    request<{ job_id: string }>('/api/m4/run', { method: 'POST', body: JSON.stringify(params) }),

  rateDoc: () => request<RateDoc>('/api/m5/doc'),
  runAccountLimits: () => request<{ job_id: string }>('/api/m5/account/run', { method: 'POST' }),
  rampPlan: (params: RampParams) =>
    request<{ rates: number[]; estimate: RequestEstimate }>('/api/m5/ramp/plan', {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  runRamp: (params: RampParams) =>
    request<{ job_id: string }>('/api/m5/ramp/run', { method: 'POST', body: JSON.stringify(params) }),
  paginationPlan: (params: PaginationParams) =>
    request<{ choice: PaginationChoice; estimate: RequestEstimate }>('/api/m5/pagination/plan', {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  runPagination: (params: PaginationParams) =>
    request<{ job_id: string }>('/api/m5/pagination/run', { method: 'POST', body: JSON.stringify(params) }),

  wsSpec: () => request<WsSpecView>('/api/m6/spec'),
  recorderPlan: (params: RecorderParams) =>
    request<{ estimate: RequestEstimate }>('/api/m6/plan', { method: 'POST', body: JSON.stringify(params) }),
  runRecorder: (params: RecorderParams) =>
    request<{ job_id: string }>('/api/m6/run', { method: 'POST', body: JSON.stringify(params) }),

  datasets: () => request<DatasetSummary[]>('/api/m7/datasets'),
  uploadDataset: (name: string, csvText: string) =>
    request<DatasetUpload>('/api/m7/datasets', { method: 'POST', body: JSON.stringify({ name, csv_text: csvText }) }),
  dummyDataset: (labJobId: string) =>
    request<DatasetUpload>('/api/m7/datasets/dummy', { method: 'POST', body: JSON.stringify({ lab_job_id: labJobId }) }),
  deleteDataset: (id: string) => request<{ deleted: boolean }>(`/api/m7/datasets/${id}`, { method: 'DELETE' }),
  labJobs: () => request<Job<null>[]>(`/api/jobs${query({ module: 'M3', kind: 'price_sources' })}`),
  labSeries: (jobId: string) => request<LabSeriesResponse>(`/api/m7/lab_runs/${jobId}/series`),
  overlay: (params: OverlayParams) =>
    request<OverlayResult>('/api/m7/overlay', { method: 'POST', body: JSON.stringify(params) }),

  exportSummary: () => request<ExportSummary>('/api/m8/summary'),
  exports: () => request<ExportInfo[]>('/api/m8/exports'),
  createExport: (charts: { name: string; png_base64: string }[]) =>
    request<ExportInfo>('/api/m8/export', { method: 'POST', body: JSON.stringify({ charts }) }),
}

/* ---------- Task 3: NFL costs ---------- */

export type T3FeeRounding = 'cent' | 'exact'

export interface T3InventoryParams {
  start_date: string
  series: string[]
  request_cap: number
}

export interface T3BackfillParams {
  request_cap: number
  fee_rounding: T3FeeRounding
}

export interface T3Game {
  game_key: string
  title: string | null
  week: number | null
  kickoff_utc: string | null
  kickoff_source: string
  game_markets: number
  spread_markets: number
  total_markets: number
  markets: number
  settled: number
  complete: number
  candles: number
  errors: number
}

export interface T3Inventory {
  listed_at: number
  start_date: string
  series: string[]
  games: number
  games_without_milestone: number
  events: number
  markets: number
  markets_by_type: Record<string, number>
  markets_settled: number
  new_markets: number
  known_markets: number
  events_listed_from_archive: number
  events_before_start_skipped: number
}

export interface T3CutoffSample {
  label: string
  ticker: string
  status: string | null
  settlement_ts: number | null
  side: string | null
  live_market_status: number | null
  historical_market_status: number | null
  batch_status?: number | null
  batch_candles?: number
  historical_candles_status?: number | null
  historical_candles?: number
  live_market_request_id: number
  historical_market_request_id: number
  batch_request_id?: number
  historical_candles_request_id?: number
}

export interface T3CutoffCheck {
  checked_at: number
  cutoff: Record<string, string>
  market_settled_ts: number | null
  our_markets_by_side: Record<string, number>
  our_markets_listed_from: Record<string, number>
  samples: T3CutoffSample[]
}

export interface T3Fees {
  series: Record<string, { fee_type: string | null; fee_multiplier: number | null; title: string | null }>
  series_changes: { series_ticker: string; fee_type: string; fee_multiplier: number; scheduled_ts: string }[]
  event_overrides: { event_ticker: string; fee_type_override: string | null; fee_multiplier_override: number | null; scheduled_ts: string }[]
}

export interface T3CandleRun {
  ran_at: number
  planned_requests: number
  requests: number
  candles_added: number
  markets_failed: number
  http_errors: number
  chunk_splits: number
  markets_completed: number
  stop_reason: string | null
}

export interface T3State {
  defaults: { inventory: T3InventoryParams; backfill: T3BackfillParams }
  series: Record<string, string>
  checkpoints: string[]
  sizes: number[]
  totals: {
    games: number
    events: number
    markets: number
    markets_complete: number
    markets_settled: number
    markets_settled_complete: number
    candles: number
  }
  inventory: T3Inventory | null
  cutoff: { fetched_at: number; values: Record<string, string>; request_id: number } | null
  cutoff_check: T3CutoffCheck | null
  fees: T3Fees | null
  last_run: { source: string; started_at: number; finished_at: number; requests: number; candles: T3CandleRun | null } | null
  next_backfill_requests: number
  games: T3Game[]
  storage: { folder: string; database: string; raw: string }
  daily: { command: string; cron: string }
}

export interface T3CostRow {
  checkpoint: string
  size: number
  price_group?: string
  market_type?: string
  week?: number
  n: number
  median: number
  mean: number
  p25: number
  p75: number
  gap_part: number
  fee_part: number
  cents_per_contract: number
}

export interface T3GapRow {
  checkpoint: string
  market_type: string
  n: number
  median_gap_cents: number
  wide_share: number
  median_quote_age_s: number
}

export interface T3QualityMarket {
  ticker: string
  market_type: string
  week: number | null
  status: string | null
  open_utc: string | null
  close_utc: string | null
  fetched_through_utc: string | null
  complete: boolean
  candles: number
  bid_above_ask: number
  bid_equals_ask: number
  gap_3c_or_more: number
  gap_3c_share: number | null
  one_sided: number
  last_error: string | null
}

export interface T3QualityByType {
  market_type: string
  markets: number
  candles: number
  missing_candles: number
  not_fetched: number
  incomplete: number
  bid_above_ask: number
  markets_bid_above_ask: number
  bid_equals_ask: number
  gap_3c_or_more: number
  one_sided: number
  fetch_errors: number
}

export interface T3Quality {
  checked_at: number
  totals: Partial<Omit<T3QualityByType, 'market_type'>>
  by_market_type: T3QualityByType[]
  checkpoint_status: { market_type: string; checkpoint: string; status: string; n: number }[]
  missing_candles: T3QualityMarket[]
  missing_candles_total: number
  bid_above_ask: T3QualityMarket[]
  bid_above_ask_total: number
  wide_gap_markets: T3QualityMarket[]
  wide_gap_markets_total: number
  list_limit: number
}

export interface T3Results {
  generated_at: number
  params: { fee_rounding: T3FeeRounding }
  checkpoints: string[]
  sizes: number[]
  price_groups: string[]
  stake: number
  fee_types_used: Record<string, number>
  counts: { markets: number; quotes: number; quotes_ok: number; cost_rows: number }
  results: { by_price_group: T3CostRow[]; by_market_type: T3CostRow[]; by_week: T3CostRow[] }
  gaps: T3GapRow[]
  quality: T3Quality
  seconds: number
}

export const t3Api = {
  state: () => request<T3State>('/api/t3/state'),
  inventoryPlan: (params: T3InventoryParams) =>
    request<{ estimate: RequestEstimate }>('/api/t3/inventory/plan', { method: 'POST', body: JSON.stringify(params) }),
  runInventory: (params: T3InventoryParams) =>
    request<{ job_id: string }>('/api/t3/inventory/run', { method: 'POST', body: JSON.stringify(params) }),
  backfillPlan: (params: T3BackfillParams) =>
    request<{ estimate: RequestEstimate }>('/api/t3/backfill/plan', { method: 'POST', body: JSON.stringify(params) }),
  runBackfill: (params: T3BackfillParams) =>
    request<{ job_id: string }>('/api/t3/backfill/run', { method: 'POST', body: JSON.stringify(params) }),
  analyze: (feeRounding: T3FeeRounding) =>
    request<T3Results>('/api/t3/analyze', { method: 'POST', body: JSON.stringify({ fee_rounding: feeRounding }) }),
  results: () => request<T3Results | null>('/api/t3/results'),
  exportUrl: (name: string) => `/api/t3/exports/${encodeURIComponent(name)}`,
}

// ---------------------------------------------------------------------------------------------
// Task 4: sportsbook vig and cost per $10 (no Kalshi requests)
// ---------------------------------------------------------------------------------------------

export interface T4State {
  source_path: string | null
  source_as_of: string | null
  last_run: string | null
  games_saved: number
  games_complete: number
  games_partial: number
  games_by_season: Record<string, number>
  raw_dir: string
  results_at: string | null
  api_source: string
  books: string[]
}

export interface T4Stat {
  bookmaker: string
  market: string
  n: number
  mean: number
  median: number
  min: number
  max: number
}

export interface T4Check {
  id: string
  title: string
  status: 'pass' | 'warn' | 'fail' | 'skip'
  detail: string
  guards: string
}

export interface T4Facts {
  season: number
  label: string
  games: number
  regular_season_games: number
  playoff_games: number
  first_kickoff: string | null
  last_kickoff: string | null
  closing_minutes_min: number | null
  closing_minutes_max: number | null
  games_by_book_at_close: Record<string, number>
  time_bucket_games: Record<string, Record<string, number>>
  price_group_sides: Record<string, Record<string, number>>
  longshot_sides_min: number
  longshot_sides_max: number
  weeks: { week: number; label: string; games: number }[]
  last_week: string | null
  last_week_games: number
  last_week_partial: boolean
}

export interface T4Season {
  season: number
  facts: T4Facts
  checks: T4Check[]
  by_book_market: (T4Stat & { mean_overround: number })[]
  by_price_group: (T4Stat & { price_group: string; n_vs_pinnacle: number | null; mean_cost_vs_pinnacle: number | null })[]
  by_week: (T4Stat & { week: number; week_label: string })[]
  by_time_to_kickoff: { bookmaker: string; market: string; time_bucket: string; games: number; mean_cost_per_10: number; mean_overround: number }[]
  favorites_longshots: {
    bookmaker: string
    group: string
    n: number
    mean_fair_prob: number
    mean_cost_per_10: number
    n_vs_pinnacle: number
    mean_cost_vs_pinnacle: number | null
  }[]
  qc_summary: { check: string; bookmaker: string; issues: number; games: number }[]
  qc_examples: { check: string; event_id: string; bookmaker: string; market: string; snapshot_ts: string | null; detail: string }[]
  games: (Record<string, string | number> & { event_id: string; week: number; home_team: string; away_team: string; kickoff_et: string; books_posting_all_3_markets: number })[]
  kalshi_info: {
    available: boolean
    source: string
    closing_checkpoint: string
    size_contracts: number
    note?: string
    games_by_market?: Record<string, number>
    first_kickoff?: string
    last_kickoff?: string
    exports_modified?: string | null
  }
  kalshi_all_strikes: { market: string; rows: string; n: number; mean: number; median: number; min: number; max: number }[]
}

export interface T4Results {
  generated_at: string
  seasons: T4Season[]
}

export interface T4RunResult {
  backfill: { in_source: number; played: number; skipped_complete: number; saved_complete: number; saved_partial: number; not_played_yet: number }
  seasons: { season: number; games: number; checks: number; checks_failed: number; warnings: number }[]
  seconds: number
}

export const t4Api = {
  state: () => request<T4State>('/api/t4/state'),
  results: () => request<T4Results | null>('/api/t4/results'),
  run: (path: string | null) => request<T4RunResult>('/api/t4/run', { method: 'POST', body: JSON.stringify({ path }) }),
  exportUrl: (season: number, name: string) => `/api/t4/exports/${season}/${encodeURIComponent(name)}`,
}

export function exportFileUrl(name: string, path: string): string {
  return `/api/m8/exports/${encodeURIComponent(name)}/files/${path.split('/').map(encodeURIComponent).join('/')}`
}

export function jobEventsUrl(jobId: string): string {
  return `/api/jobs/${jobId}/events`
}

// ---------------------------------------------------------------------------------------------
// In-game analysis
// ---------------------------------------------------------------------------------------------

export interface IGCheck {
  id: string
  title: string
  status: 'pass' | 'warn' | 'skip' | 'fail'
  detail: string
  guards_against: string
}

export interface IGReturn {
  phase: string
  group_label?: string
  bucket_label?: string
  dollars: number
  games: number
  avg_price: number
  win_rate: number
  before_fees: number
  after_fees: number
  before_lo: number
  before_hi: number
  after_lo: number
  after_hi: number
}

export interface IGFacts {
  season: number
  games: number
  settled_games: number
  has_trades: boolean
  n_contracts: number
  dollars?: number
  fees?: number
  trades?: number
  inplay_dollar_share?: number
  inplay_fee_share?: number
  fee_per_10?: number
  fee_per_10_pre?: number
  fee_per_10_in?: number
  taker_after_fees?: Record<string, number>
  taker_before_fees?: Record<string, number>
  taker_after_ci?: Record<string, [number, number]>
  sizes?: Record<string, { median: number; p75: number; p90: number; trades: number; share_1_or_less: number }>
  near_certain?: { dollar_share_90_plus: number; trade_share_90_plus: number; fee_share_90_plus: number; dollar_share_10_minus: number }
  top10_inplay_share?: number
  rounding_small?: Record<string, number>
  rounding_total?: number
  games_with_trades?: number
  returns_games?: number
  peak_bin?: string
  peak_bin_share?: number
  late_fee_per_10?: number
  prime_inplay_per_game?: number
  day_inplay_per_game?: number
  inplay_longshot_dollar_share?: number
  inplay_longshot_fee_share?: number
  brier?: Record<string, number>
  slope?: Record<string, number>
  cost_phase_group?: Record<string, number>
  spread_phase_group?: Record<string, number>
}

export interface IGSeason {
  season: number
  generated_at: string
  games: number
  settled_games: number
  has_trades: boolean
  n_contracts: number
  n_source: string
  facts: IGFacts
  checks: IGCheck[]
  spread_by_minute?: { minute: number; markets: number; spread_c: number; cost: number; spread_part: number; fee_part: number; two_sided_share: number }[]
  cost_by_phase_group?: { phase: string; group_label: string; quotes: number; spread_c: number; cost: number; fee_part: number; spread_part: number }[]
  calibration: {
    by_checkpoint: { minute: number; games: number; brier: number; brier_lo: number; brier_hi: number; slope: number; intercept: number }[]
    reliability: { minute: number; bucket_label: string; games: number; mean_price: number; won: number }[]
  }
  trades?: {
    totals: Record<string, number>
    by_bin: { bin_label: string; trades: number; dollars: number; fee: number; dollar_share: number; fee_share: number; fee_per_10: number | null }[]
    by_phase_group: { phase: string; group_label: string; trades: number; dollars: number; fee: number; dollar_share: number; fee_share: number; fee_per_10: number }[]
    sizes: { phase: string; trades: number; median: number; p75: number; p90: number; median_dollars: number; p90_dollars: number; share_1_or_less: number }[]
    rounding: { phase: string; size_label: string; trades: number; fee: number; fee_exact: number; rounding_extra: number }[]
    returns_by_group: IGReturn[]
    returns_by_decile: IGReturn[]
    returns_by_phase: IGReturn[]
    returns_games: number
    by_slot: { slot: string; games: number; pre: number; inplay: number; inplay_per_game: number; pre_per_game: number; inplay_share: number }[]
    top10_inplay_share: number
    games_with_trades: number
    near_certain: Record<string, number>
  }
}

export interface IGResults {
  generated_at: string
  seasons: IGSeason[]
}

export const ingameApi = {
  results: () => request<IGResults | null>('/api/ingame/results'),
  run: () => request<{ seasons: { season: number; games: number; has_trades: boolean; checks_failed: number }[]; seconds: number }>('/api/ingame/run', { method: 'POST' }),
}
