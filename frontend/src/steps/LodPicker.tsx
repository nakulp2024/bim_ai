import { AlertTriangle, Check, Loader2, Filter } from "lucide-react";
import { useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, api } from "@/lib/api";
import type { FilterReport, LevelPrediction, ModelProfile, ScheduleRequest } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

const NO_ZONE = "__none__";

const WEEKDAYS = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" },
];

const REASON_LABELS: Record<string, string> = {
  excluded_class: "Excluded IFC class (fasteners, openings, annotation…)",
  assembly_child: "Collapsed into a parent assembly",
  below_size_threshold: "Below the size threshold",
  name_pattern: "Matched a name exclusion pattern",
};

interface Props {
  projectId: number;
  profile: ModelProfile;
  busy: boolean;
  onGenerate: (request: ScheduleRequest) => void;
}

export function LodPicker({ projectId, profile, busy, onGenerate }: Props) {
  const [zoneSplit, setZoneSplit] = useState<string>(NO_ZONE);
  const [level, setLevel] = useState<string>("L3");
  const [levels, setLevels] = useState<LevelPrediction[] | null>(null);
  const [filterReport, setFilterReport] = useState<FilterReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [startDate, setStartDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [workDays, setWorkDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [holidays, setHolidays] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .lodPreview(projectId, zoneSplit === NO_ZONE ? null : zoneSplit)
      .then((payload) => {
        if (cancelled) return;
        setLevels(payload.levels);
        setFilterReport(payload.filter);
        setError(null);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof ApiError ? cause.message : String(cause));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [projectId, zoneSplit]);

  const selected = levels?.find((item) => item.level === level);
  const zoneOptions = [
    ...(profile.zones.length ? [{ value: "zone", label: "IfcZone / IfcSpatialZone" }] : []),
    ...profile.available_zone_properties.map((property) => ({
      value: property,
      label: property,
    })),
  ];

  function toggleWorkDay(day: number) {
    setWorkDays((current) =>
      current.includes(day) ? current.filter((d) => d !== day) : [...current, day].sort(),
    );
  }

  function submit() {
    onGenerate({
      level,
      zone_split: zoneSplit === NO_ZONE ? null : zoneSplit,
      start_date: startDate,
      work_days: workDays.length ? workDays : [0, 1, 2, 3, 4],
      holidays: holidays
        .split(/[\s,]+/)
        .map((value) => value.trim())
        .filter(Boolean),
    });
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Schedule level of detail</CardTitle>
          <CardDescription>
            Every level groups the same elements differently. The task count is calculated from
            your model before you commit.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Could not calculate the preview</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="grid gap-3">
            {(levels ?? []).map((item) => {
              const active = item.level === level;
              return (
                <button
                  key={item.level}
                  type="button"
                  onClick={() => setLevel(item.level)}
                  className={cn(
                    "flex items-start gap-4 rounded-lg border p-4 text-left transition-colors",
                    active ? "border-primary bg-accent" : "hover:bg-accent/50",
                  )}
                >
                  <div
                    className={cn(
                      "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                      active ? "border-primary bg-primary text-primary-foreground" : "border-input",
                    )}
                  >
                    {active && <Check className="h-3 w-3" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">
                        {item.level} — {item.name}
                      </span>
                      {item.is_default && <Badge variant="secondary">default</Badge>}
                      {item.warn && (
                        <Badge variant="warning">
                          <AlertTriangle className="mr-1 h-3 w-3" />
                          large
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-2xl font-semibold tabular-nums">
                      {loading ? "…" : formatNumber(item.task_count, 0)}
                    </div>
                    <div className="text-xs text-muted-foreground">tasks</div>
                  </div>
                </button>
              );
            })}
            {loading && !levels && (
              <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Calculating task counts…
              </div>
            )}
          </div>

          {selected?.warn && (
            <Alert variant="warning">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>{formatNumber(selected.task_count, 0)} tasks is a lot</AlertTitle>
              <AlertDescription>
                A programme this size is hard to manage by hand and slow to render. Consider L3 or
                L4, or add a zone split to break the work down more meaningfully.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Secondary zone split</CardTitle>
            <CardDescription>
              Optional. Subdivides every level by zone, and switches on zone-repetition sequencing.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {zoneOptions.length ? (
              <Select value={zoneSplit} onValueChange={setZoneSplit}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_ZONE}>No zone split</SelectItem>
                  {zoneOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="text-sm text-muted-foreground">
                This model has no IfcZone and no zone-like property set, so no split is available.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Calendar</CardTitle>
            <CardDescription>Drives the CPM date calculation.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="start-date">Start date</Label>
              <Input
                id="start-date"
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Work week</Label>
              <div className="flex flex-wrap gap-1.5">
                {WEEKDAYS.map((day) => (
                  <button
                    key={day.value}
                    type="button"
                    onClick={() => toggleWorkDay(day.value)}
                    className={cn(
                      "rounded-md border px-3 py-1.5 text-sm transition-colors",
                      workDays.includes(day.value)
                        ? "border-primary bg-primary text-primary-foreground"
                        : "hover:bg-accent",
                    )}
                  >
                    {day.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="holidays">Holidays</Label>
              <Input
                id="holidays"
                placeholder="2026-12-25, 2026-12-28"
                value={holidays}
                onChange={(event) => setHolidays(event.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {filterReport && filterReport.elements_removed > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Filter className="h-4 w-4" />
              Noise filtered out before grouping
            </CardTitle>
            <CardDescription>
              {formatNumber(filterReport.elements_kept, 0)} of{" "}
              {formatNumber(filterReport.elements_in, 0)} elements are schedulable. Edit
              backend/config/filters.yaml to change these rules.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {Object.entries(filterReport.removed_by_reason).map(([reason, count]) => (
                <li key={reason} className="flex items-baseline justify-between gap-4">
                  <span className="text-sm">{REASON_LABELS[reason] ?? reason}</span>
                  <span className="shrink-0 tabular-nums text-sm text-muted-foreground">
                    {formatNumber(count, 0)}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="flex justify-end">
        <Button size="lg" onClick={submit} disabled={busy || loading || !levels}>
          {busy && <Loader2 className="animate-spin" />}
          {busy
            ? "Generating…"
            : `Generate ${selected ? formatNumber(selected.task_count, 0) : ""} tasks`}
        </Button>
      </div>
    </div>
  );
}
