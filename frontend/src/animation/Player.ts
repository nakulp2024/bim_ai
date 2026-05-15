import type { FilteringExtension } from "@speckle/viewer";
import type { AnimationScript } from "../api";

export interface PlayerOptions {
  filtering: FilteringExtension;
  script: AnimationScript;
  taskToSpeckle: Record<string, string[]>;
  /** Color used while a task is in-progress (between start_day and end_day). */
  inProgressColor?: string;
}

interface ElementPlan {
  speckleId: string;
  startDay: number;
  endDay: number;
  finalColor: string; // phase color
}

/**
 * Diff-based player. State per tick is:
 *   - hidden    (before any task starts)
 *   - in-progress (between start and end)
 *   - complete  (after end)
 *
 * Speckle's FilteringExtension replaces filter intent on each call, so on every
 * day-boundary we re-apply the full color bucket set — not just deltas.
 */
export class AnimationPlayer {
  private filtering: FilteringExtension;
  private script: AnimationScript;
  private plans: ElementPlan[] = [];
  private inProgressColor: string;
  private currentDay = 0;
  private prevDay = -1;

  constructor(opts: PlayerOptions) {
    this.filtering = opts.filtering;
    this.script = opts.script;
    this.inProgressColor = opts.inProgressColor ?? "#ff9900";

    const taskById = new Map(opts.script.tasks.map((t) => [t.task_id, t]));
    const phaseColorByTask = new Map<string, string>();
    for (const phase of opts.script.phases) {
      for (const tid of phase.task_ids) {
        phaseColorByTask.set(tid, phase.color_hex);
      }
    }

    for (const [taskId, speckleIds] of Object.entries(opts.taskToSpeckle)) {
      const task = taskById.get(taskId);
      if (!task) continue;
      const finalColor = phaseColorByTask.get(taskId) ?? "#888888";
      for (const speckleId of speckleIds) {
        this.plans.push({
          speckleId,
          startDay: task.start_day,
          endDay: task.end_day,
          finalColor,
        });
      }
    }
  }

  get duration(): number {
    return this.script.duration_days;
  }

  get day(): number {
    return this.currentDay;
  }

  /** Apply the state for a given day. Idempotent if the day didn't change. */
  seek(day: number, force = false): void {
    const next = Math.max(0, Math.min(this.duration, Math.floor(day)));
    if (!force && next === this.prevDay) {
      this.currentDay = day;
      return;
    }
    this.currentDay = day;
    this.prevDay = next;

    const hidden: string[] = [];
    const colorBuckets = new Map<string, string[]>();
    for (const p of this.plans) {
      if (next < p.startDay) {
        hidden.push(p.speckleId);
      } else if (next < p.endDay) {
        const arr = colorBuckets.get(this.inProgressColor) ?? [];
        arr.push(p.speckleId);
        colorBuckets.set(this.inProgressColor, arr);
      } else {
        const arr = colorBuckets.get(p.finalColor) ?? [];
        arr.push(p.speckleId);
        colorBuckets.set(p.finalColor, arr);
      }
    }

    // Replace, not append — the Speckle Viewer Filter API replaces filter
    // intent on each call. We always pass the full set.
    if (hidden.length > 0) {
      this.filtering.hideObjects(hidden);
    } else {
      this.filtering.showObjects([]);
    }
    if (colorBuckets.size > 0) {
      this.filtering.setUserObjectColors(
        [...colorBuckets].map(([color, objectIds]) => ({ objectIds, color })),
      );
    } else {
      this.filtering.setUserObjectColors([]);
    }
  }

  reset(): void {
    try {
      this.filtering.resetFilters();
    } catch {
      // ignore
    }
  }
}
