export type Level = "мир" | "регионы РФ" | "Свердловская область";
export type Stage = "неизвестно" | "в разработке" | "пилот" | "внедрён" | "масштабирование";
export type Reliability = "высокая" | "средняя" | "низкая" | "не_оценена";
export type SourceType = "официальная" | "статистика" | "кейсы" | "аналитика" | "аналитика рынка" | "СМИ" | "неизвестно";
export type ConfirmationStatus = "подтверждено" | "противоречие" | "один_источник";
export type Flag =
  | "цифра_не_найдена_в_тексте"
  | "противоречие_источников"
  | "один_источник"
  | "стадия_неясна"
  | "нет_измеримых_показателей"
  | "источник_не_оценён"
  | "подтверждение_не_проводилось";
export type StatusClass = "ok" | "warn" | "bad" | "muted";

export interface SessionState {
  authenticated: boolean;
  login_required: boolean;
}

export interface Option {
  value: string;
  label: string;
}

export interface Meta {
  levels: Level[];
  statuses: (Option & { class: StatusClass })[];
  reliability: Option[];
  criteria: Option[];
  plan_indicators: Option[];
  industries: Option[];
  flag_help: Record<Flag, [string, string]>;
}

interface CaseSummary {
  id: string;
  title: string;
  level: Level;
  country: string;
  region: string | null;
  organization: string | null;
  industry: string;
  stage: Stage;
  first_seen: string;
  updated: string;
  metrics: Metric[];
  plan_links: PlanLink[];
  status_label: string;
  status_class: StatusClass;
  reliability_label: string;
  flags: Flag[];
}

export interface CaseRow extends CaseSummary {
  status: ConfirmationStatus;
  headline: string;
  headline_unverified: boolean;
  reliability: Reliability | null;
  reliability_class: StatusClass;
}

export interface CaseList {
  total: number;
  updated: string | null;
  cases: CaseRow[];
}

export interface Metric {
  name: string;
  criterion: string;
  before: string | null;
  after: string | null;
  change: string | null;
  unit: string | null;
  kind: "факт" | "план";
  quote: string;
  source_url: string;
  quote_verified: boolean;
  confirmed_by: string[];
  confirmation_evidence?: { source_url: string; quote: string; basis_quote: string }[];
  conflicting_values: string[];
}

export interface PlanLink {
  indicator_id: string;
  explanation: string;
  source_url: string;
  quote: string;
}

export interface QualitativeEvidence {
  criterion: string;
  fact: string;
  source_url: string;
  quote: string;
}

export interface Source {
  url: string;
  domain: string;
  title: string;
  published_at: string | null;
  reliability: Reliability;
  source_type: SourceType;
}

export interface CaseDetail extends CaseSummary {
  municipality: string | null;
  sector: "госсектор" | "бизнес";
  ai_technology: string;
  summary: string;
  methodology: "М-1" | "Р-1" | "бизнес-метрики";
  m1_profile: Record<string, QualitativeEvidence[]>;
  r1_ratios: (number | null)[];
  sources: Source[];
  confirmation_status: ConfirmationStatus;
  confirmation_attempts: number;
  last_confirmation_attempt: string | null;
}

export interface RunStarted {
  run_id: string;
}

export type RunCurrent =
  | { running: false }
  | (RunStarted & { running: true; started: string; minutes: number; tail: string[] });

export interface RunRow extends RunStarted {
  state: string;
  label: string;
  started: string;
  finished: string | null;
  minutes: number;
  exit_code: number | null;
  reason: string | null;
  report: Record<string, string>;
  params: Record<string, unknown>;
}

export interface QuerySpec {
  level: Level;
  text: string;
  use_registry_domains: boolean;
  language: string;
}

export interface QueriesResp {
  groups: { level: Level; queries: QuerySpec[] }[];
  total: number;
  freshness_days: number;
  error: string | null;
}

export interface SourceInfo {
  name: string;
  domains: string[];
  urls?: string[];
  level: Level | null;
  reliability: Reliability;
  source_type: SourceType;
  update_frequency: string;
}

export interface SourcesResp {
  sources: SourceInfo[];
  total: number;
  error: string | null;
  level_options: Option[];
  reliability_options: Option[];
}
