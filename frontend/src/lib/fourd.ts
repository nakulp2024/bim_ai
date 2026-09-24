import type { Rgba } from "./scene";
import type { GeometryManifest, ProgressTask, ScheduleFlag, Task } from "./types";

/**
 * planned  - the current plan's dates
 * actual   - what happened, then the forecast from the data date onward
 * variance - actual/forecast timing, coloured by how far off the baseline it is
 */
export type FourDMode = "planned" | "actual" | "variance";

/** Where an element's work stands on a given day. */
export type Phase = "future" | "active" | "built" | "context";

export interface TaskWindow {
  task: Task | ProgressTask;
  start: string;
  finish: string;
}

const hex = (value: number, alpha = 1): Rgba => [
  ((value >> 16) & 255) / 255,
  ((value >> 8) & 255) / 255,
  (value & 255) / 255,
  alpha,
];

export const PACKAGE_COLORS: Record<string, number> = {
  Substructure: 0x78716c,
  Superstructure: 0x3b82f6,
  Envelope: 0x14b8a6,
  MEP: 0xa855f7,
  Interior: 0xec4899,
  Finishes: 0x84cc16,
};

export const FLAG_COLORS: Record<ScheduleFlag, number> = {
  complete: 0x64748b,
  ahead: 0x16a34a,
  on_track: 0x2563eb,
  behind: 0xdc2626,
  not_started: 0x94a3b8,
};

export const ACTIVE_COLOR = 0xf59e0b;
export const CRITICAL_COLOR = 0xdc2626;
export const SELECTED_COLOR = 0xd946ef;
const GHOST: Rgba = hex(0x94a3b8, 0.1);
const CONTEXT: Rgba = hex(0xcbd5e1, 0.35);
const HIDDEN: Rgba = [0, 0, 0, 0];

export function packageColor(workPackage: string): number {
  return PACKAGE_COLORS[workPackage] ?? 0x64748b;
}

/**
 * The task each rendered element belongs to, by position in the manifest.
 *
 * Assembly parts are collapsed into their parent before scheduling, so they
 * are in no task's element list; they resolve through ``parent_id`` instead.
 * Anything still unresolved (filtered-out noise, for instance) is context.
 */
export function resolveElementTasks<T extends Task>(
  manifest: GeometryManifest,
  tasks: T[],
): (T | null)[] {
  const byGlobalId = new Map<string, T>();
  for (const task of tasks) {
    for (const globalId of task.element_ids) byGlobalId.set(globalId, task);
  }
  return manifest.elements.map(
    (element) =>
      byGlobalId.get(element.global_id) ??
      (element.parent_id ? byGlobalId.get(element.parent_id) : undefined) ??
      null,
  );
}

/** The dates that drive an element in each mode. */
export function windowFor(task: Task | ProgressTask, mode: FourDMode): TaskWindow {
  if (mode === "planned" || !("forecast_start" in task)) {
    return { task, start: task.start_date, finish: task.finish_date };
  }
  return {
    task,
    start: task.actual_start ?? task.forecast_start,
    finish: task.actual_finish ?? task.forecast_finish,
  };
}

/** ISO dates compare correctly as strings, which keeps this cheap per frame. */
export function phaseAt(window: TaskWindow | null, date: string): Phase {
  if (!window) return "context";
  if (date < window.start) return "future";
  if (date > window.finish) return "built";
  return "active";
}

/** The plan's critical path in planned mode; the forecast's otherwise. */
function isCritical(task: Task | ProgressTask | null, mode: FourDMode): boolean {
  if (!task) return false;
  if (mode !== "planned" && "forecast_critical" in task) return task.forecast_critical;
  return task.is_critical;
}

export interface PaintOptions {
  mode: FourDMode;
  hideFuture: boolean;
  highlightCritical: boolean;
  selectedTaskId: string | null;
}

export function colorFor(
  phase: Phase,
  task: Task | ProgressTask | null,
  options: PaintOptions,
): Rgba {
  if (task && options.selectedTaskId === task.id && phase !== "context") {
    return hex(SELECTED_COLOR);
  }
  switch (phase) {
    case "context":
      return CONTEXT;
    case "future":
      return options.hideFuture ? HIDDEN : GHOST;
    case "active": {
      // In the variance view red already means "behind"; critical would
      // collide with it, so the flag colour wins there.
      if (
        options.highlightCritical &&
        options.mode !== "variance" &&
        isCritical(task, options.mode)
      ) {
        return hex(CRITICAL_COLOR);
      }
      if (options.mode === "variance" && task && "schedule_flag" in task) {
        return hex(FLAG_COLORS[task.schedule_flag]);
      }
      return hex(ACTIVE_COLOR);
    }
    case "built":
      if (options.mode === "variance" && task && "schedule_flag" in task) {
        return hex(FLAG_COLORS[task.schedule_flag]);
      }
      return hex(task ? packageColor(task.work_package) : 0x64748b);
  }
}

/** First start and last finish across all windows, as ISO dates. */
export function dateRange(windows: (TaskWindow | null)[]): [string, string] | null {
  let first: string | null = null;
  let last: string | null = null;
  for (const window of windows) {
    if (!window) continue;
    if (first === null || window.start < first) first = window.start;
    if (last === null || window.finish > last) last = window.finish;
  }
  return first && last ? [first, last] : null;
}
