export type ProjectStatus =
  | "created"
  | "parsing"
  | "parsed"
  | "scheduling"
  | "ready"
  | "failed";

export interface Project {
  id: number;
  name: string;
  created_at: string | null;
  updated_at: string | null;
  ifc_filename: string | null;
  ifc_schema: string | null;
  element_count: number;
  status: ProjectStatus;
  error: string | null;
  has_schedule: boolean;
  data_date: string | null;
  geometry_status: "building" | "ready" | "failed" | null;
}

export interface Job {
  id: string;
  project_id: number;
  kind: "parse" | "schedule" | "geometry";
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string;
  error: string | null;
  result: Record<string, unknown>;
}

export interface CountEntry {
  key: string;
  count: number;
}

export interface StoreyEntry {
  storey_id: string;
  name: string;
  elevation: number | null;
  count: number;
}

export interface ModelProfile {
  element_count: number;
  by_class: CountEntry[];
  by_storey: CountEntry[];
  by_type: CountEntry[];
  by_discipline: CountEntry[];
  by_material: CountEntry[];
  by_predefined_type: CountEntry[];
  storeys: StoreyEntry[];
  zones: CountEntry[];
  quantity_coverage: {
    base_quantity: number;
    derived: number;
    none: number;
    coverage_pct: number;
  };
  available_zone_properties: string[];
}

export interface ParseReport {
  schema: string;
  elements_read: number;
  products_seen: number;
  skipped_spatial: number;
  quantities_from_base: number;
  quantities_derived: number;
  quantities_missing: number;
  quantity_coverage_pct: number;
  geometry_failures: number;
  errors: string[];
  warnings: string[];
}

export interface LevelPrediction {
  level: "L1" | "L2" | "L3" | "L4" | "L5";
  name: string;
  description: string;
  task_count: number;
  is_default: boolean;
  warn: boolean;
}

export interface FilterReport {
  elements_in: number;
  elements_kept: number;
  elements_removed: number;
  removed_by_reason: Record<string, number>;
  removed_by_reason_and_class: Record<string, Record<string, number>>;
  rolled_up_quantity: Record<string, number>;
  examples: Record<string, string[]>;
}

export type LinkType = "FS" | "SS" | "FF" | "SF";

export interface TaskLink {
  id: string;
  type: LinkType;
  lag: number;
}

export interface ScheduleLink {
  predecessor_id: string;
  successor_id: string;
  type: LinkType;
  lag: number;
  origin: string;
}

export interface Task {
  id: string;
  wbs_code: string;
  wbs_path: string[];
  label: string;
  level: string;
  work_package: string;
  storey_id: string | null;
  storey_name: string;
  storey_elevation: number | null;
  zone_name: string | null;
  ifc_class: string | null;
  predefined_type: string | null;
  type_name: string | null;
  material: string | null;
  element_ids: string[];
  element_count: number;
  quantities: Record<string, number>;
  quantity_source: "base_quantity" | "derived" | "mixed" | "none";
  aggregated_trivial: boolean;
  notes: string[];
  duration_days: number;
  quantity: number | null;
  quantity_key: string | null;
  unit: string;
  rate_id: string;
  rate_source: string;
  confidence: "high" | "medium" | "low";
  crew: number;
  output_per_crew_day: number;
  user_edited: boolean;
  duration_notes: string[];
  early_start_offset: number;
  early_finish_offset: number;
  total_float: number;
  free_float: number;
  is_critical: boolean;
  start_date: string;
  finish_date: string;
  late_start_date: string;
  late_finish_date: string;
  predecessors: TaskLink[];
}

export interface WorkCalendar {
  start_date: string;
  work_days: number[];
  holidays: string[];
  days_per_week: number;
}

export interface RunReport {
  parse?: ParseReport;
  filter?: FilterReport;
  grouping?: {
    level: string;
    zone_split: string | null;
    task_count: number;
    elements_in_tasks: number;
    aggregated_trivial_groups: number;
  };
  durations?: {
    confidence: { high: number; medium: number; low: number };
    quantity_coverage_pct: number;
    by_rate_source: Record<string, number>;
  };
  sequencing?: { link_count: number; by_origin: Record<string, number> };
  cpm?: {
    project_duration_days: number;
    critical_task_count: number;
    cycles_broken: { from: string; to: string }[];
    dropped_links: { from: string; to: string; reason: string }[];
    finish_date: string;
  };
}

export interface Schedule {
  project_id: number;
  level: string;
  zone_split: string | null;
  tasks: Task[];
  links: ScheduleLink[];
  calendar: WorkCalendar;
  report: RunReport;
  options: Record<string, unknown>;
  project_duration_days: number;
}

export interface Rate {
  id: string;
  unit: "m3" | "m2" | "m" | "ea";
  output_per_crew_day: number;
  default_crew: number;
  min_duration_days: number;
  ifc_class: string | null;
  predefined_types: string[] | null;
  material_pattern: string | null;
}

export interface RateLibrary {
  default: Rate;
  count_fallback: Rate;
  rules: Rate[];
}

export interface RatesResponse {
  effective: RateLibrary;
  overrides: Record<string, unknown>;
  defaults: RateLibrary;
}

export interface ScheduleRequest {
  level: string;
  zone_split?: string | null;
  start_date?: string | null;
  work_days?: number[] | null;
  holidays?: string[];
  crew_overrides?: Record<string, number>;
  llm_enabled?: boolean;
}

// --- progress ---------------------------------------------------------------

export type ProgressStatus = "not_started" | "in_progress" | "complete";
export type ScheduleFlag = "complete" | "ahead" | "on_track" | "behind" | "not_started";
export type DelayCause = "late_start" | "slow_progress" | "predecessor_delay";

/** A task with its progress state, forecast and baseline variance merged in. */
export interface ProgressTask extends Task {
  status: ProgressStatus;
  percent_complete: number;
  quantity_placed: number | null;
  actual_start: string | null;
  actual_finish: string | null;
  remaining_duration: number;
  progress_note: string | null;
  progress_reported_on: string | null;
  progress_assumptions: string[];
  forecast_start: string;
  forecast_finish: string;
  forecast_total_float: number;
  forecast_critical: boolean;
  baseline_start: string | null;
  baseline_finish: string | null;
  baseline_duration: number;
  in_baseline: boolean;
  planned_percent: number;
  percent_variance: number;
  start_variance_days: number | null;
  finish_variance_days: number | null;
  schedule_flag: ScheduleFlag;
  delay_cause: DelayCause | null;
}

export interface ProgressSummary {
  data_date: string;
  variance_basis: "baseline" | "plan";
  baseline_task_count: number;
  task_count: number;
  planned_percent_complete: number;
  actual_percent_complete: number;
  schedule_performance_index: number | null;
  reference_finish: string | null;
  forecast_finish: string | null;
  finish_variance_days: number | null;
  by_status: Partial<Record<ProgressStatus, number>>;
  by_flag: Partial<Record<ScheduleFlag, number>>;
  by_delay_cause: Partial<Record<DelayCause, number>>;
  quantity_by_unit: Record<string, { placed: number; total: number; percent: number }>;
  critical_behind: {
    id: string;
    label: string;
    finish_variance_days: number;
    forecast_finish: string;
    delay_cause: DelayCause | null;
  }[];
  forecast_critical_path: string[];
}

export interface Baseline {
  id: number;
  project_id: number;
  name: string;
  created_at: string | null;
  is_current: boolean;
  finish_date: string | null;
  task_count: number;
}

export interface ProgressView {
  tasks: ProgressTask[];
  summary: ProgressSummary;
  warnings: string[];
  baseline: Baseline | null;
  data_date_is_default: boolean;
}

export interface ProgressEntryInput {
  task_id: string;
  percent_complete?: number | null;
  quantity_placed?: number | null;
  actual_start?: string | null;
  actual_finish?: string | null;
  note?: string | null;
}

// --- geometry -----------------------------------------------------------------

export interface GeometryElement {
  global_id: string;
  ifc_class: string | null;
  name: string | null;
  parent_id: string | null;
  vertex_start: number;
  vertex_count: number;
  index_start: number;
  index_count: number;
  bbox: { min: [number, number, number]; max: [number, number, number] };
}

export interface GeometryManifest {
  version: number;
  build_id: string;
  up_axis: "y";
  units: "m";
  origin_offset: [number, number, number];
  bounds: { min: [number, number, number]; max: [number, number, number] };
  element_count: number;
  vertex_count: number;
  triangle_count: number;
  buffers: {
    positions: { offset: number; length: number; type: "float32" };
    indices: { offset: number; length: number; type: "uint32" };
  };
  elements: GeometryElement[];
  warnings: string[];
}
