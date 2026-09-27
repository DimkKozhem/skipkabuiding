export type Detection = {
  id?: string;
  class_name: string;
  confidence: number;
  bbox: number[];
};

export type CaptureOrigin = "scheduled_capture" | "manual_upload";

export type Observation = {
  id: string;
  timestamp: string;
  source?: string;
  zone?: string;
  camera_id?: string;
  camera_code?: string;
  camera_name?: string;
  capture_origin?: CaptureOrigin | null;
  capture_origin_label?: string | null;
  image_path?: string;
  image_url?: string;
  viz_path?: string;
  viz_url?: string;
  detections?: Detection[];
  /** false — кадр за сутки слишком похож на уже оставленный и в хронологию не входит. */
  kept?: boolean;
};

export type ModelBox = {
  evidence_id?: string;
  class_name: string;
  confidence: number;
  bbox: number[];
};

export type ModelLayer = {
  source: string;
  label: string;
  status?: string;
  model?: string;
  model_version?: string;
  error?: string | null;
  boxes: ModelBox[];
};

export type CandidateReviewRecord = {
  id: string;
  source: string;
  verdict: "correct" | "incorrect" | "indeterminate";
  wrong_type?: string;
  missed_object?: string;
  completeness: string;
  actor?: string;
  created_at: string;
};

export type EvidenceItem = {
  id: string;
  media_path?: string;
  media_url?: string;
  viz_path?: string;
  viz_url?: string;
  timestamp: string;
  note?: string;
  observation_id?: string;
  source?: string;
  camera_code?: string;
  camera_name?: string;
  detections?: Detection[];
};

export type EvidencePreview = {
  id?: string;
  media_url?: string;
  viz_url?: string;
  timestamp: string;
};

export type AlertEvent = {
  id: string;
  action: string;
  from_status: string;
  to_status: string;
  reason: string;
  note: string;
  actor: string;
  created_at: string;
};

export type AlertSummary = {
  total: number;
  by_type: Record<string, number>;
};

export type AlertListItem = {
  id: string;
  type: string;
  severity: string;
  status: string;
  status_label?: string;
  fingerprint?: string;
  decision_reason?: string;
  decision_note?: string;
  decided_at?: string | null;
  decided_by?: string;
  message: string;
  created_at: string;
  project: string;
  project_name?: string | null;
  zone: string | null;
  zone_name?: string | null;
  title?: string;
  expected?: Record<string, unknown>;
  observed?: Record<string, unknown>;
  rationale?: string;
  related_dates?: string[];
  latest_evidence?: EvidencePreview | null;
  first_observed_at?: string | null;
  last_observed_at?: string | null;
};

export type AlertDetail = AlertListItem & {
  deviation: {
    expected?: Record<string, unknown>;
    observed?: Record<string, unknown>;
    rationale?: string;
    title?: string;
    rule_id?: string;
    stage?: string;
    stage_label?: string;
    model_confidence?: number;
    evidence_confidence?: number;
    rule_confidence?: number;
    evidence_ids?: string[];
    related_dates?: string[];
  };
  evidence: EvidenceItem[];
  model_layers?: ModelLayer[];
  candidate_reviews?: CandidateReviewRecord[];
  diagnostics?: {
    alert_id?: string;
    observation_ids?: string[];
    layers?: Array<{ source?: string; model?: string; model_version?: string; n_boxes?: number; evidence_ids?: string[] }>;
  } | null;
  events: AlertEvent[];
  project_name?: string | null;
  zone_name?: string | null;
};

export type InspectionBrief = {
  alert_id: string;
  disclaimer: string;
  status: string;
  status_label?: string;
  type: string;
  zone?: string;
  project?: string;
  expected?: Record<string, unknown>;
  observed?: Record<string, unknown>;
  rationale?: string;
  message?: string;
  on_site_checks: string[];
  evidence: EvidenceItem[];
  events: AlertEvent[];
};

export type WorkFactSummary = {
  indicator_id: string;
  certainty: string;
  value?: number | boolean | null;
  limitations?: string[];
};

export type ActualState = {
  elements?: Record<string, { count?: number; detected?: boolean; max_confidence?: number }>;
  equipment?: Record<string, { count?: number }>;
  scene_attributes?: Record<string, unknown>;
  work_facts_summary?: WorkFactSummary[];
  camera_code?: string;
  timestamp?: string;
};

export type ExpectedState = {
  stage?: string;
  stage_label?: string;
  expected?: Record<string, unknown>;
  required_equipment?: { type: string; min_count: number }[];
  unexpected_equipment?: string[];
};

export type CameraRef = {
  code: string;
  name: string;
  source_type?: string;
  location?: string;
  orientation?: string;
  uri?: string;
  enabled?: boolean;
  interval_minutes?: number;
  last_captured_at?: string | null;
  last_error?: string;
  project?: string | null;
  project_name?: string | null;
  zone?: string | null;
  zone_name?: string | null;
  due?: boolean;
};

export type ZonePrimaryBadge = "schedule_delay" | "equipment" | "no_dynamics" | null;

export type ZoneCardState =
  | "on_plan"
  | "observation"
  | "possible_issue"
  | "needs_check"
  | "confirmed"
  | "stale"
  | "no_frame";

export type ZoneBadge = {
  code: "schedule_delay" | "equipment" | "no_dynamics";
  label: string;
};

export type ZoneDash = {
  zone_id: string;
  code: string;
  name: string;
  description?: string;
  construction_type_id?: string | null;
  construction_type_name?: string | null;
  stage?: string | null;
  stage_label?: string | null;
  last_actual?: ActualState | null;
  last_expected?: ExpectedState | null;
  last_observed_at?: string | null;
  last_source?: string | null;
  preview_url?: string | null;
  /** Первый годный кадр той же камеры — историческая точка «было». */
  prior_preview_url?: string | null;
  /** Засечки графика: done | now | lag | ahead. */
  schedule_ticks?: { label: string; state: "done" | "now" | "lag" | "ahead" }[];
  /** Канал обложки с сервера: scheduled_capture | manual_upload | null. */
  cover_origin?: CaptureOrigin | null;
  /** «Камера» | «Инспекция» | null (без метки → UI: «Кадр»). */
  cover_origin_label?: string | null;
  /** Имя точки съёмки, не id детектора. */
  cover_camera_name?: string | null;
  cameras?: CameraRef[];
  open_alerts: number;
  /** Открытая проверка: тип сигнала, без текста вердикта. */
  check?: { id: string; type: string; status: string } | null;
  alert_counts?: Record<string, number>;
  status_counts?: Record<string, number>;
  schedule_deviations?: number;
  no_dynamics?: number;
  /** Серверные бейджи витрины (порядок: schedule_delay > equipment > no_dynamics). */
  badges?: ZoneBadge[];
  /** Совместимость: первый элемент badges. */
  primary_badge?: ZonePrimaryBadge;
  badge_label?: string | null;
  schedule_delay?: boolean;
  attention?: boolean;
  last_alert?: string | null;
  /** Почему карточка на этом месте (сервер, RU). */
  rank_reason?: string;
  /** Нет сигнала выше tier и кадр старше порога / кадра нет. */
  stale?: boolean;
  /**
   * Состояние карточки с API.
   * possible_issue = open delay/equipment/no_dynamics (needs_check не дублируем).
   */
  card_state?: ZoneCardState;
  /** Человеческая свежесть кадра. */
  freshness_label?: string;
  /** Open или confirmed schedule_delay (для tier 0). */
  confirmed_schedule_delay?: boolean;
};

export type ProjectDash = {
  id: string;
  code: string;
  name: string;
  address: string;
  zones: ZoneDash[];
  alert_counts: Record<string, number>;
};

export type KsgRow = {
  id?: string;
  date: string;
  start_date: string;
  end_date?: string | null;
  stage?: string;
  stage_label?: string;
  expected?: Record<string, unknown>;
  current?: boolean;
  /** Признак изменений по сопоставимым кадрам за последние сутки внутри этапа. */
  day_done?: string | null;
  day_done_on?: string | null;
};

export type ObjectPage = {
  project: { id: string; code: string; name: string; address?: string };
  zone: {
    id?: string;
    code: string;
    name: string;
    description?: string;
    construction_type_id?: string | null;
    construction_type_name?: string | null;
  };
  cameras?: CameraRef[];
  expected: ExpectedState | null;
  actual: ActualState | null;
  last_observed_at?: string | null;
  cover_origin?: CaptureOrigin | null;
  cover_origin_label?: string | null;
  cover_camera_name?: string | null;
  ksg?: KsgRow[];
  observations: Observation[];
  alerts: AlertListItem[];
  status: string;
};

export type ConstructionType = {
  id: string;
  name: string;
};

export type ConstructionWorkNode = {
  id: string;
  code?: string | null;
  name: string;
  children?: ConstructionWorkNode[];
};

export type ConstructionWorksResponse = {
  type: ConstructionType;
  groups: {
    id: string;
    code?: string | null;
    name: string;
    works: ConstructionWorkNode[];
  }[];
};

export type ZoneNote = {
  id: string;
  body: string;
  author: string;
  created_at?: string | null;
};

export type SiteChange = {
  kind: "changed" | "unchanged" | "unknown";
  comparable: boolean;
  same_camera: boolean;
  equipment_deltas: Record<string, number>;
  element_deltas: Record<string, number>;
  visual_change?: number | null;
  notes?: string[];
};

export type TimelineRow = {
  date: string;
  actual?: ActualState | null;
  expected?: Record<string, unknown>;
  stage?: string;
  stage_label?: string;
  alerts?: AlertListItem[];
  change?: SiteChange | null;
  /** Общее описание сопоставимых кадров за сутки. */
  summary?: string | null;
  done?: string | null;
  kept_ids?: string[];
};

export type InspectorConfig = {
  disclaimer: string;
  actor_default?: string;
  statuses: Record<string, string>;
  reasons: Record<string, Record<string, string>>;
  on_site_checks: Record<string, string[]>;
};

export type UploadResult = {
  ok: boolean;
  project: string;
  zone: string;
  camera: string;
  timestamp: string;
  source_type: string;
  detector: string;
  n_detections: number;
  media_url?: string;
  alert_ids: string[];
  actual_state?: ActualState;
};

export type CatalogStage = {
  code: string;
  label: string;
  required_equipment?: { type: string; min_count: number }[];
};

export type CaptureStatus = {
  loop: boolean;
  tick_seconds: number;
  interval_default_minutes: number;
  cameras: CameraRef[];
};

export type CaptureRunResult = {
  ok: boolean;
  at: string;
  processed: number;
  captured: number;
  results: { camera: string; ok: boolean; skipped?: boolean; reason?: string; alert_ids?: string[] }[];
};

export type HousingRowStatus = "planned" | "done" | "attention";

export type HousingScheduleRow = {
  stage: string;
  catalog_code: string;
  title: string;
  date_start: string;
  date_end: string;
  plan_floors: number;
  fact_floors: number | null;
  status: HousingRowStatus;
  fact_note: string | null;
};

export type HousingSignal = {
  type: string;
  text: string;
  at: string;
};

export type HousingRunInfo = {
  frames_processed: number;
  frame_interval_minutes: number;
  video_duration_sec: number;
  signals: HousingSignal[];
};

export type HousingVideo = {
  id: string;
  title: string;
  url: string;
  runs_pipeline: boolean;
};

export type HousingSchedule = {
  project_id: string;
  title: string;
  video_url: string;
  videos?: HousingVideo[];
  frame_interval_minutes: number;
  rows: HousingScheduleRow[];
  run?: HousingRunInfo;
};
