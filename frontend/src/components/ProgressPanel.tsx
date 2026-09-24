import {
  AlertTriangle,
  CalendarClock,
  Flag,
  Loader2,
  RotateCcw,
  Save,
  Search,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  DelayCause,
  ProgressEntryInput,
  ProgressTask,
  ProgressView,
  ScheduleFlag,
} from "@/lib/types";
import { cn, formatDate, formatNumber } from "@/lib/utils";

interface Props {
  view: ProgressView;
  busy: boolean;
  selectedId: string | null;
  onSelect: (taskId: string) => void;
  onReport: (entries: ProgressEntryInput[], reportedOn?: string) => Promise<void>;
  onClear: (taskId: string) => void;
  onDataDate: (date: string) => void;
  onBaseline: () => void;
}

type Filter = "all" | "behind" | "active" | "critical";

const FLAG_BADGE: Record<ScheduleFlag, { label: string; variant: "success" | "warning" | "danger" | "secondary" | "outline" }> = {
  complete: { label: "complete", variant: "secondary" },
  ahead: { label: "ahead", variant: "success" },
  on_track: { label: "on track", variant: "outline" },
  behind: { label: "behind", variant: "danger" },
  not_started: { label: "not started", variant: "outline" },
};

const CAUSE_LABEL: Record<DelayCause, string> = {
  late_start: "Late start",
  slow_progress: "Slow progress",
  predecessor_delay: "Waiting on predecessor",
};

/** A pending edit to one task, not yet sent. */
type Draft = Omit<ProgressEntryInput, "task_id">;

export function ProgressPanel({
  view,
  busy,
  selectedId,
  onSelect,
  onReport,
  onClear,
  onDataDate,
  onBaseline,
}: Props) {
  const { summary } = view;
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const pending = Object.keys(drafts).length;

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return [...view.tasks]
      .filter((task) => {
        if (filter === "behind" && task.schedule_flag !== "behind") return false;
        if (filter === "active" && task.status !== "in_progress") return false;
        if (filter === "critical" && !task.forecast_critical) return false;
        return !needle || task.label.toLowerCase().includes(needle);
      })
      .sort((a, b) => a.forecast_start.localeCompare(b.forecast_start) || a.id.localeCompare(b.id));
  }, [view.tasks, filter, query]);

  function edit(taskId: string, patch: Draft) {
    setDrafts((current) => ({ ...current, [taskId]: { ...current[taskId], ...patch } }));
  }

  async function submit() {
    // A field typed into and then cleared leaves an all-blank draft; the API
    // rejects those as reporting nothing, so drop them here.
    const entries = Object.entries(drafts)
      .map(([task_id, draft]) => ({ task_id, ...draft }))
      .filter((entry) =>
        Object.entries(entry).some(([key, value]) => key !== "task_id" && value != null),
      );
    if (entries.length) await onReport(entries);
    setDrafts({});
  }

  const variance = summary.finish_variance_days;
  const spi = summary.schedule_performance_index;

  return (
    <div className="space-y-4">
      {/* --- controls ------------------------------------------------------ */}
      <div className="flex flex-wrap items-end gap-4 rounded-lg border p-3">
        <div className="space-y-1">
          <Label htmlFor="data-date">Data date</Label>
          <Input
            id="data-date"
            type="date"
            className="w-44"
            value={summary.data_date}
            disabled={busy}
            onChange={(event) => event.target.value && onDataDate(event.target.value)}
          />
        </div>
        <p className="max-w-xs pb-2 text-xs text-muted-foreground">
          Progress is reported as of this date; remaining work is forecast from it.
          {view.data_date_is_default && " Currently defaulting to today."}
        </p>
        <div className="ml-auto flex items-center gap-3">
          {view.baseline ? (
            <div className="text-right text-sm">
              <div className="font-medium">{view.baseline.name}</div>
              <div className="text-xs text-muted-foreground">
                finish {formatDate(view.baseline.finish_date)}
              </div>
            </div>
          ) : (
            <p className="max-w-[16rem] text-right text-xs text-muted-foreground">
              No baseline yet — variance is measured against the live plan, which moves when you
              edit it.
            </p>
          )}
          <Button variant="outline" size="sm" onClick={onBaseline} disabled={busy}>
            <Flag />
            {view.baseline ? "Re-baseline" : "Set baseline"}
          </Button>
        </div>
      </div>

      {view.warnings.length > 0 && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{view.warnings.join(" ")}</AlertDescription>
        </Alert>
      )}

      {/* --- headline numbers ------------------------------------------------ */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Work complete
            </div>
            <div className="text-2xl font-semibold tabular-nums">
              {formatNumber(summary.actual_percent_complete, 1)}%
            </div>
            <Progress value={summary.actual_percent_complete} />
            <div className="text-xs text-muted-foreground">
              plan says {formatNumber(summary.planned_percent_complete, 1)}% by now
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Finish date
            </div>
            <div className="text-2xl font-semibold tabular-nums">
              {formatDate(summary.forecast_finish)}
            </div>
            <div
              className={cn(
                "flex items-center gap-1 text-sm font-medium",
                variance && variance > 0
                  ? "text-destructive"
                  : variance && variance < 0
                    ? "text-emerald-600"
                    : "text-muted-foreground",
              )}
            >
              {variance && variance > 0 ? (
                <TrendingDown className="h-4 w-4" />
              ) : variance && variance < 0 ? (
                <TrendingUp className="h-4 w-4" />
              ) : null}
              {variance === null
                ? "—"
                : variance === 0
                  ? "on the " + summary.variance_basis
                  : `${Math.abs(variance)} working days ${variance > 0 ? "behind" : "ahead"}`}
            </div>
            <div className="text-xs text-muted-foreground">
              {summary.variance_basis} finish {formatDate(summary.reference_finish)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Schedule performance
            </div>
            <div
              className={cn(
                "text-2xl font-semibold tabular-nums",
                spi !== null && spi < 0.9 && "text-destructive",
              )}
            >
              {spi === null ? "—" : spi.toFixed(2)}
            </div>
            <div className="text-xs text-muted-foreground">
              {spi === null
                ? "Nothing was due yet."
                : "Work done ÷ work planned by now. Below 1 means behind."}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Quantity placed
            </div>
            {Object.entries(summary.quantity_by_unit).map(([unit, values]) => (
              <div key={unit} className="space-y-0.5">
                <div className="flex justify-between text-xs">
                  <span className="tabular-nums">
                    {formatNumber(values.placed, 1)} / {formatNumber(values.total, 1)} {unit}
                  </span>
                  <span className="text-muted-foreground">{formatNumber(values.percent, 0)}%</span>
                </div>
                <Progress value={values.percent} className="h-1.5" />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {summary.critical_behind.length > 0 && (
        <Card className="border-destructive/40">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-destructive" />
              Critical work that is behind
            </CardTitle>
            <CardDescription>
              These are driving the finish date. Recovering them is what moves the job.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {summary.critical_behind.slice(0, 8).map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(item.id)}
                    className="flex w-full items-center justify-between gap-3 rounded px-2 py-1 text-left text-sm hover:bg-accent"
                  >
                    <span className="truncate">{item.label}</span>
                    <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                      {item.delay_cause && CAUSE_LABEL[item.delay_cause]}
                      <Badge variant="danger">+{item.finish_variance_days}d</Badge>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* --- the report ------------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-64">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter tasks…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-8"
          />
        </div>
        <div className="flex gap-1 rounded-md bg-muted p-1">
          {(
            [
              ["all", "All"],
              ["active", "In progress"],
              ["behind", `Behind (${summary.by_flag.behind ?? 0})`],
              ["critical", "Critical"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilter(value)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium",
                filter === value ? "bg-background shadow-sm" : "text-muted-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {pending > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setDrafts({})} disabled={busy}>
              Discard
            </Button>
          )}
          <Button size="sm" onClick={submit} disabled={busy || pending === 0}>
            {busy ? <Loader2 className="animate-spin" /> : <Save />}
            Save report{pending > 0 && ` (${pending})`}
          </Button>
        </div>
      </div>

      <div className="max-h-[620px] overflow-auto rounded-lg border">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-background shadow-[0_1px_0_0_hsl(var(--border))]">
            <TableRow>
              <TableHead className="min-w-[240px]">Task</TableHead>
              <TableHead className="w-28">Status</TableHead>
              <TableHead className="w-24 text-right">Plan %</TableHead>
              <TableHead className="w-24 text-right">Actual %</TableHead>
              <TableHead className="w-36 text-right">Placed</TableHead>
              <TableHead className="w-36">Actual start</TableHead>
              <TableHead className="w-36">Actual finish</TableHead>
              <TableHead className="w-28">Forecast finish</TableHead>
              <TableHead className="w-20 text-right">Slip</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((task) => (
              <ProgressRow
                key={task.id}
                task={task}
                draft={drafts[task.id]}
                busy={busy}
                selected={selectedId === task.id}
                onSelect={() => onSelect(task.id)}
                onEdit={(patch) => edit(task.id, patch)}
                onClear={() => onClear(task.id)}
              />
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={10} className="py-10 text-center text-muted-foreground">
                  No tasks match.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function ProgressRow({
  task,
  draft,
  busy,
  selected,
  onSelect,
  onEdit,
  onClear,
}: {
  task: ProgressTask;
  draft: Draft | undefined;
  busy: boolean;
  selected: boolean;
  onSelect: () => void;
  onEdit: (patch: Draft) => void;
  onClear: () => void;
}) {
  const badge = FLAG_BADGE[task.schedule_flag];
  // Show the pending edit if there is one, otherwise what the server holds.
  const value = <K extends keyof Draft>(key: K, fallback: Draft[K]) =>
    draft && key in draft ? draft[key] : fallback;
  const numberOrNull = (text: string) => (text === "" ? null : Number(text));
  const hasProgress = task.status !== "not_started" || task.progress_reported_on;

  return (
    <TableRow
      onClick={onSelect}
      data-state={selected ? "selected" : undefined}
      className={cn("cursor-pointer", draft && "bg-amber-50/70 dark:bg-amber-950/20")}
    >
      <TableCell>
        <div className="truncate font-medium" title={task.label}>
          {task.label}
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {formatDate(task.baseline_start)} → {formatDate(task.baseline_finish)}
          {task.forecast_critical && (
            <span className="font-medium text-destructive">· critical</span>
          )}
        </div>
        {task.progress_assumptions.length > 0 && (
          <div
            className="mt-0.5 truncate text-[11px] text-amber-700 dark:text-amber-400"
            title={task.progress_assumptions.join("\n")}
          >
            {task.progress_assumptions[0]}
            {task.progress_assumptions.length > 1 && ` +${task.progress_assumptions.length - 1}`}
          </div>
        )}
      </TableCell>
      <TableCell>
        <Badge variant={badge.variant}>{badge.label}</Badge>
        {task.delay_cause && (
          <div className="mt-1 text-[11px] text-muted-foreground">
            {CAUSE_LABEL[task.delay_cause]}
          </div>
        )}
      </TableCell>
      <TableCell className="text-right tabular-nums text-xs text-muted-foreground">
        {formatNumber(task.planned_percent, 0)}%
      </TableCell>
      <TableCell className="text-right">
        <Input
          type="number"
          min={0}
          max={100}
          disabled={busy}
          value={value("percent_complete", task.percent_complete) ?? ""}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => onEdit({ percent_complete: numberOrNull(event.target.value) })}
          className={cn(
            "h-7 w-20 px-2 text-right tabular-nums",
            task.percent_variance < -10 && !draft && "border-destructive/60",
          )}
        />
      </TableCell>
      <TableCell className="text-right">
        {task.quantity ? (
          <div className="flex items-center justify-end gap-1">
            <Input
              type="number"
              min={0}
              step="any"
              disabled={busy}
              value={value("quantity_placed", task.quantity_placed) ?? ""}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => onEdit({ quantity_placed: numberOrNull(event.target.value) })}
              className="h-7 w-24 px-2 text-right tabular-nums"
            />
            <span className="w-6 text-left text-xs text-muted-foreground">{task.unit}</span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell>
        <Input
          type="date"
          disabled={busy}
          value={value("actual_start", task.actual_start) ?? ""}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => onEdit({ actual_start: event.target.value || null })}
          className="h-7 px-2 text-xs"
        />
      </TableCell>
      <TableCell>
        <Input
          type="date"
          disabled={busy}
          value={value("actual_finish", task.actual_finish) ?? ""}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => onEdit({ actual_finish: event.target.value || null })}
          className="h-7 px-2 text-xs"
        />
      </TableCell>
      <TableCell className="whitespace-nowrap text-xs">
        <CalendarClock className="mr-1 inline h-3 w-3 text-muted-foreground" />
        {formatDate(task.forecast_finish)}
      </TableCell>
      <TableCell
        className={cn(
          "text-right tabular-nums text-xs font-medium",
          (task.finish_variance_days ?? 0) > 0 && "text-destructive",
          (task.finish_variance_days ?? 0) < 0 && "text-emerald-600",
        )}
      >
        {task.finish_variance_days === null
          ? "—"
          : task.finish_variance_days > 0
            ? `+${task.finish_variance_days}d`
            : `${task.finish_variance_days}d`}
      </TableCell>
      <TableCell>
        {hasProgress && (
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Clear all progress on this task"
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation();
              onClear();
            }}
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

