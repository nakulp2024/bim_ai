import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import type { Schedule } from "@/lib/types";
import { addDays, cn, daysBetween, formatDate } from "@/lib/utils";

interface Props {
  schedule: Schedule;
  selectedId: string | null;
  onSelect: (taskId: string) => void;
}

const DAY_WIDTH = 22;
const ROW_HEIGHT = 30;

export function GanttChart({ schedule, selectedId, onSelect }: Props) {
  const [criticalOnly, setCriticalOnly] = useState(false);
  const [showLinks, setShowLinks] = useState(true);

  const tasks = useMemo(
    () =>
      [...schedule.tasks].sort(
        (a, b) => a.early_start_offset - b.early_start_offset || a.wbs_code.localeCompare(b.wbs_code),
      ),
    [schedule.tasks],
  );

  const visible = criticalOnly ? tasks.filter((task) => task.is_critical) : tasks;

  const { origin, totalDays } = useMemo(() => {
    if (!tasks.length) return { origin: schedule.calendar.start_date, totalDays: 1 };
    const starts = tasks.map((task) => task.start_date).sort();
    const finishes = tasks.map((task) => task.finish_date).sort();
    const first = starts[0];
    const last = finishes[finishes.length - 1];
    return { origin: first, totalDays: Math.max(1, daysBetween(first, last) + 1) };
  }, [tasks, schedule.calendar.start_date]);

  // Calendar-day index of each task, so bars line up with the date ruler.
  const positions = useMemo(() => {
    const map = new Map<string, { left: number; width: number }>();
    for (const task of tasks) {
      const left = daysBetween(origin, task.start_date);
      const width = Math.max(1, daysBetween(task.start_date, task.finish_date) + 1);
      map.set(task.id, { left, width });
    }
    return map;
  }, [tasks, origin]);

  const rowIndex = useMemo(() => {
    const map = new Map<string, number>();
    visible.forEach((task, index) => map.set(task.id, index));
    return map;
  }, [visible]);

  const months = useMemo(() => {
    const result: { label: string; left: number; days: number }[] = [];
    let cursor = 0;
    while (cursor < totalDays) {
      const date = new Date(`${addDays(origin, cursor)}T00:00:00`);
      const daysInMonth = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
      const remainingInMonth = daysInMonth - date.getDate() + 1;
      const span = Math.min(remainingInMonth, totalDays - cursor);
      result.push({
        label: date.toLocaleDateString(undefined, { month: "short", year: "numeric" }),
        left: cursor,
        days: span,
      });
      cursor += span;
    }
    return result;
  }, [origin, totalDays]);

  const links = useMemo(() => {
    if (!showLinks) return [];
    return schedule.links
      .map((link) => {
        const from = positions.get(link.predecessor_id);
        const to = positions.get(link.successor_id);
        const fromRow = rowIndex.get(link.predecessor_id);
        const toRow = rowIndex.get(link.successor_id);
        if (!from || !to || fromRow === undefined || toRow === undefined) return null;
        const critical =
          schedule.tasks.find((t) => t.id === link.predecessor_id)?.is_critical &&
          schedule.tasks.find((t) => t.id === link.successor_id)?.is_critical;
        return {
          key: `${link.predecessor_id}->${link.successor_id}`,
          x1: (from.left + from.width) * DAY_WIDTH,
          y1: fromRow * ROW_HEIGHT + ROW_HEIGHT / 2,
          x2: to.left * DAY_WIDTH,
          y2: toRow * ROW_HEIGHT + ROW_HEIGHT / 2,
          critical: Boolean(critical),
        };
      })
      .filter((value): value is NonNullable<typeof value> => value !== null);
  }, [schedule.links, schedule.tasks, positions, rowIndex, showLinks]);

  if (!tasks.length) {
    return <p className="p-8 text-center text-sm text-muted-foreground">No tasks to chart.</p>;
  }

  const chartWidth = totalDays * DAY_WIDTH;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={criticalOnly}
            onChange={(event) => setCriticalOnly(event.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          <Label className="cursor-pointer">Critical path only</Label>
        </label>
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={showLinks}
            onChange={(event) => setShowLinks(event.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          <Label className="cursor-pointer">Show logic links</Label>
        </label>
        <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm bg-primary" /> Normal
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm bg-critical" /> Critical
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm border border-dashed border-muted-foreground" />{" "}
            Float
          </span>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <div className="flex">
          {/* Task name column */}
          <div className="w-[400px] shrink-0 border-r bg-muted/30">
            <div className="h-[44px] border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Task
            </div>
            <div className="max-h-[560px] overflow-y-auto" id="gantt-names">
              {visible.map((task) => (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => onSelect(task.id)}
                  style={{ height: ROW_HEIGHT }}
                  className={cn(
                    "flex w-full items-center gap-2 border-b px-3 text-left text-xs transition-colors last:border-b-0",
                    selectedId === task.id ? "bg-accent" : "hover:bg-accent/50",
                  )}
                >
                  <span
                    className="w-[88px] shrink-0 truncate tabular-nums text-muted-foreground"
                    title={task.wbs_code}
                  >
                    {task.wbs_code}
                  </span>
                  <span className="truncate" title={task.label}>
                    {task.label}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Timeline */}
          <div className="min-w-0 flex-1 overflow-x-auto">
            <div style={{ width: chartWidth }}>
              <div className="h-[44px] border-b">
                <div className="flex h-[22px]">
                  {months.map((month) => (
                    <div
                      key={`${month.label}-${month.left}`}
                      style={{ width: month.days * DAY_WIDTH }}
                      className="shrink-0 truncate border-r px-2 text-xs font-medium leading-[22px]"
                    >
                      {month.label}
                    </div>
                  ))}
                </div>
                <div className="flex h-[22px]">
                  {Array.from({ length: totalDays }, (_, index) => {
                    const iso = addDays(origin, index);
                    const weekday = new Date(`${iso}T00:00:00`).getDay();
                    const nonWorking = !schedule.calendar.work_days.includes((weekday + 6) % 7);
                    return (
                      <div
                        key={iso}
                        style={{ width: DAY_WIDTH }}
                        className={cn(
                          "shrink-0 border-r text-center text-[10px] leading-[22px] text-muted-foreground",
                          nonWorking && "bg-muted/60",
                        )}
                      >
                        {new Date(`${iso}T00:00:00`).getDate()}
                      </div>
                    );
                  })}
                </div>
              </div>

              <div
                className="relative max-h-[560px] overflow-y-auto"
                style={{ height: visible.length * ROW_HEIGHT }}
              >
                {showLinks && (
                  <svg
                    className="pointer-events-none absolute inset-0"
                    width={chartWidth}
                    height={visible.length * ROW_HEIGHT}
                  >
                    {links.map((link) => {
                      const midX = Math.max(link.x1 + 6, link.x2 - 6);
                      return (
                        <polyline
                          key={link.key}
                          points={`${link.x1},${link.y1} ${midX},${link.y1} ${midX},${link.y2} ${link.x2},${link.y2}`}
                          fill="none"
                          strokeWidth={1}
                          className={cn(
                            link.critical ? "stroke-critical" : "stroke-muted-foreground/40",
                          )}
                        />
                      );
                    })}
                  </svg>
                )}

                {visible.map((task, index) => {
                  const position = positions.get(task.id);
                  if (!position) return null;
                  const floatDays = Math.max(0, task.total_float);
                  return (
                    <div
                      key={task.id}
                      style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT }}
                      className={cn(
                        "absolute left-0 right-0 border-b",
                        selectedId === task.id && "bg-accent/60",
                      )}
                    >
                      {floatDays > 0 && (
                        <div
                          style={{
                            left: (position.left + position.width) * DAY_WIDTH,
                            width: floatDays * DAY_WIDTH,
                          }}
                          className="absolute top-1/2 h-3 -translate-y-1/2 rounded-sm border border-dashed border-muted-foreground/60"
                          title={`${floatDays} days total float`}
                        />
                      )}
                      <button
                        type="button"
                        onClick={() => onSelect(task.id)}
                        style={{
                          left: position.left * DAY_WIDTH,
                          width: Math.max(DAY_WIDTH - 2, position.width * DAY_WIDTH - 2),
                        }}
                        title={`${task.label}\n${formatDate(task.start_date)} → ${formatDate(
                          task.finish_date,
                        )}\n${task.duration_days} working days, float ${task.total_float}`}
                        className={cn(
                          "absolute top-1/2 h-4 -translate-y-1/2 rounded-sm transition-opacity hover:opacity-80",
                          task.is_critical ? "bg-critical" : "bg-primary",
                          task.user_edited && "ring-2 ring-amber-400 ring-offset-1",
                        )}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Badge variant="outline">
          {formatDate(origin)} → {formatDate(addDays(origin, totalDays - 1))}
        </Badge>
        <span>
          {schedule.project_duration_days} working days ·{" "}
          {schedule.report.cpm?.critical_task_count ?? 0} critical tasks
        </span>
      </div>
    </div>
  );
}
