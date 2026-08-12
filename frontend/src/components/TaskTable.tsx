import { Check, Link2, Pencil, Search, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Schedule, Task } from "@/lib/types";
import { cn, formatDate, formatNumber } from "@/lib/utils";

interface Props {
  schedule: Schedule;
  selectedId: string | null;
  onSelect: (taskId: string) => void;
  onRename: (taskId: string, label: string) => void;
  onDuration: (taskId: string, days: number) => void;
  onDelete: (taskId: string) => void;
  onRelink: (taskId: string) => void;
  busy: boolean;
}

const CONFIDENCE_VARIANT = {
  high: "success",
  medium: "warning",
  low: "danger",
} as const;

const QUANTITY_SOURCE_LABEL: Record<string, string> = {
  base_quantity: "Qto",
  derived: "derived",
  mixed: "mixed",
  none: "none",
};

export function TaskTable({
  schedule,
  selectedId,
  onSelect,
  onRename,
  onDuration,
  onDelete,
  onRelink,
  busy,
}: Props) {
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draftLabel, setDraftLabel] = useState("");

  const tasks = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const sorted = [...schedule.tasks].sort((a, b) =>
      a.wbs_code.localeCompare(b.wbs_code, undefined, { numeric: true }),
    );
    if (!needle) return sorted;
    return sorted.filter((task) =>
      [task.label, task.work_package, task.storey_name, task.ifc_class, task.wbs_code]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle)),
    );
  }, [schedule.tasks, query]);

  function startEdit(task: Task) {
    setEditing(task.id);
    setDraftLabel(task.label);
  }

  function commitEdit(taskId: string) {
    const trimmed = draftLabel.trim();
    if (trimmed) onRename(taskId, trimmed);
    setEditing(null);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <div className="relative max-w-sm flex-1">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter tasks…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-8"
          />
        </div>
        <span className="text-sm text-muted-foreground">
          {formatNumber(tasks.length, 0)} of {formatNumber(schedule.tasks.length, 0)} tasks
        </span>
      </div>

      <div className="max-h-[620px] overflow-auto rounded-lg border">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-background shadow-[0_1px_0_0_hsl(var(--border))]">
            <TableRow>
              <TableHead className="w-20">WBS</TableHead>
              <TableHead className="min-w-[280px]">Task</TableHead>
              <TableHead className="w-32">Package</TableHead>
              <TableHead className="w-20 text-right">Elems</TableHead>
              <TableHead className="w-28 text-right">Quantity</TableHead>
              <TableHead className="w-20 text-right">Days</TableHead>
              <TableHead className="w-16 text-right">Crew</TableHead>
              <TableHead className="w-24">Confidence</TableHead>
              <TableHead className="w-28">Start</TableHead>
              <TableHead className="w-28">Finish</TableHead>
              <TableHead className="w-20 text-right">Float</TableHead>
              <TableHead className="w-24">Preds</TableHead>
              <TableHead className="w-24 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tasks.map((task) => (
              <TableRow
                key={task.id}
                onClick={() => onSelect(task.id)}
                data-state={selectedId === task.id ? "selected" : undefined}
                className={cn("cursor-pointer", task.is_critical && "bg-red-50/60 dark:bg-red-950/20")}
              >
                <TableCell className="tabular-nums text-xs text-muted-foreground">
                  {task.wbs_code}
                </TableCell>

                <TableCell>
                  {editing === task.id ? (
                    <div className="flex items-center gap-1">
                      <Input
                        autoFocus
                        value={draftLabel}
                        onChange={(event) => setDraftLabel(event.target.value)}
                        onClick={(event) => event.stopPropagation()}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") commitEdit(task.id);
                          if (event.key === "Escape") setEditing(null);
                        }}
                        className="h-7"
                      />
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        onClick={(event) => {
                          event.stopPropagation();
                          commitEdit(task.id);
                        }}
                      >
                        <Check className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7"
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditing(null);
                        }}
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="truncate" title={task.label}>
                        {task.label}
                      </span>
                      {task.is_critical && <Badge variant="danger">critical</Badge>}
                      {task.user_edited && <Badge variant="warning">edited</Badge>}
                      {task.aggregated_trivial && (
                        <Badge variant="secondary" title={task.notes.join(" ")}>
                          aggregated
                        </Badge>
                      )}
                    </div>
                  )}
                </TableCell>

                <TableCell className="text-xs">{task.work_package}</TableCell>
                <TableCell className="text-right tabular-nums text-xs">
                  {formatNumber(task.element_count, 0)}
                </TableCell>
                <TableCell className="text-right tabular-nums text-xs">
                  {task.quantity === null ? (
                    "—"
                  ) : (
                    <span title={`${task.quantity_key} (${QUANTITY_SOURCE_LABEL[task.quantity_source]})`}>
                      {formatNumber(task.quantity, 1)} {task.unit}
                    </span>
                  )}
                </TableCell>

                <TableCell className="text-right">
                  <Input
                    type="number"
                    min={0}
                    value={task.duration_days}
                    disabled={busy}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      if (Number.isFinite(value) && value >= 0 && value !== task.duration_days) {
                        onDuration(task.id, value);
                      }
                    }}
                    className="h-7 w-16 px-2 text-right tabular-nums"
                  />
                </TableCell>

                <TableCell className="text-right tabular-nums text-xs">{task.crew}</TableCell>
                <TableCell>
                  <Badge variant={CONFIDENCE_VARIANT[task.confidence]} title={`rate: ${task.rate_id}`}>
                    {task.confidence}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  {formatDate(task.start_date)}
                </TableCell>
                <TableCell className="whitespace-nowrap text-xs">
                  {formatDate(task.finish_date)}
                </TableCell>
                <TableCell
                  className={cn(
                    "text-right tabular-nums text-xs",
                    task.total_float <= 0 && "font-semibold text-destructive",
                  )}
                >
                  {task.total_float}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {task.predecessors.length
                    ? task.predecessors
                        .map((link) => `${link.type}${link.lag ? (link.lag > 0 ? `+${link.lag}` : link.lag) : ""}`)
                        .join(", ")
                    : "—"}
                </TableCell>

                <TableCell className="text-right">
                  <div className="flex justify-end gap-0.5">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      title="Rename"
                      disabled={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        startEdit(task);
                      }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      title="Re-link"
                      disabled={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        onRelink(task.id);
                      }}
                    >
                      <Link2 className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 text-destructive"
                      title="Delete"
                      disabled={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        onDelete(task.id);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!tasks.length && (
              <TableRow>
                <TableCell colSpan={13} className="py-10 text-center text-muted-foreground">
                  No tasks match "{query}".
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
