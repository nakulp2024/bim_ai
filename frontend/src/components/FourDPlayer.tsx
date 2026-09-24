import {
  AlertTriangle,
  Box,
  Loader2,
  Maximize2,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, api, pollJob } from "@/lib/api";
import {
  ACTIVE_COLOR,
  CRITICAL_COLOR,
  FLAG_COLORS,
  type FourDMode,
  PACKAGE_COLORS,
  type PaintOptions,
  type Phase,
  type TaskWindow,
  colorFor,
  dateRange,
  phaseAt,
  resolveElementTasks,
  windowFor,
} from "@/lib/fourd";
import { FourDScene } from "@/lib/scene";
import type { GeometryManifest, ProgressTask, ProgressView, Schedule, Task } from "@/lib/types";
import { addDays, cn, daysBetween, formatDate } from "@/lib/utils";

interface Props {
  projectId: number;
  schedule: Schedule;
  progress: ProgressView | null;
  selectedTaskId: string | null;
  onSelectTask: (taskId: string | null) => void;
}

type LoadState =
  | { kind: "loading"; message: string; percent: number }
  | { kind: "ready" }
  | { kind: "empty" }
  | { kind: "error"; message: string };

const SPEEDS = [
  { value: "1", label: "1 day / s" },
  { value: "3", label: "3 days / s" },
  { value: "7", label: "1 week / s" },
  { value: "14", label: "2 weeks / s" },
];

const toCss = (value: number) => `#${value.toString(16).padStart(6, "0")}`;

/** Fetch the model's geometry, building it first if it has never been built. */
async function loadGeometry(
  projectId: number,
  onProgress: (message: string, percent: number) => void,
): Promise<{ manifest: GeometryManifest; buffer: ArrayBuffer }> {
  let job: string | null = null;
  try {
    job = (await api.buildGeometry(projectId)).job_id;
  } catch (cause) {
    // Someone else started the build; wait for it rather than failing.
    if (!(cause instanceof ApiError && cause.status === 409)) throw cause;
    for (;;) {
      onProgress("Waiting for another build to finish…", 0);
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        await api.getGeometryManifest(projectId);
        break;
      } catch (waiting) {
        if (!(waiting instanceof ApiError && waiting.status === 409)) throw waiting;
      }
    }
  }
  if (job) {
    const result = await pollJob(job, (update) =>
      onProgress(update.message || "Tessellating model…", Math.round(update.progress * 100)),
    );
    if (result.status === "failed") {
      throw new Error(result.error?.split("\n")[0] ?? "Geometry extraction failed.");
    }
  }
  onProgress("Downloading geometry…", 100);
  const manifest = await api.getGeometryManifest(projectId);
  const buffer = await api.getGeometryBuffer(projectId, manifest.build_id);
  return { manifest, buffer };
}

export function FourDPlayer({ projectId, schedule, progress, selectedTaskId, onSelectTask }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<FourDScene | null>(null);
  const [manifest, setManifest] = useState<GeometryManifest | null>(null);
  const [load, setLoad] = useState<LoadState>({
    kind: "loading",
    message: "Preparing model…",
    percent: 0,
  });

  // A progress view always exists once there is a schedule, but until someone
  // has reported against it "actual" is just the plan pushed to today, which
  // hides the real start. Open on the plan until there is something to show.
  const hasReported = Boolean(progress?.tasks.some((task) => task.progress_reported_on));
  const [mode, setMode] = useState<FourDMode>(hasReported ? "actual" : "planned");
  const [hideFuture, setHideFuture] = useState(false);
  const [highlightCritical, setHighlightCritical] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState("3");
  const [day, setDay] = useState(0);
  const [hovered, setHovered] = useState<number | null>(null);

  // Progress rows carry actual and forecast dates; the plan does not.
  const tasks: (Task | ProgressTask)[] = useMemo(
    () => (mode !== "planned" && progress ? progress.tasks : schedule.tasks),
    [mode, progress, schedule.tasks],
  );
  const taskWindows = useMemo(() => tasks.map((task) => windowFor(task, mode)), [tasks, mode]);
  const range = useMemo(() => dateRange(taskWindows), [taskWindows]);
  const totalDays = range ? daysBetween(range[0], range[1]) + 1 : 1;
  const currentDate = range ? addDays(range[0], Math.min(day, totalDays - 1)) : null;

  // Which task each rendered element belongs to, and the window driving it.
  const elementWindows = useMemo<(TaskWindow | null)[]>(() => {
    if (!manifest) return [];
    return resolveElementTasks(manifest, tasks).map((task) =>
      task ? windowFor(task, mode) : null,
    );
  }, [manifest, tasks, mode]);

  // --- scene lifecycle -----------------------------------------------------

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const scene = new FourDScene(container);
    sceneRef.current = scene;
    let cancelled = false;

    loadGeometry(projectId, (message, percent) => {
      if (!cancelled) setLoad({ kind: "loading", message, percent });
    })
      .then(({ manifest: loaded, buffer }) => {
        if (cancelled) return;
        if (!loaded.element_count) {
          setLoad({ kind: "empty" });
          return;
        }
        scene.load(loaded, buffer);
        setManifest(loaded);
        setLoad({ kind: "ready" });
      })
      .catch((cause) => {
        if (!cancelled) {
          setLoad({
            kind: "error",
            message: cause instanceof Error ? cause.message : String(cause),
          });
        }
      });

    return () => {
      cancelled = true;
      scene.dispose();
      sceneRef.current = null;
    };
  }, [projectId]);

  // Start the timeline on the data date when there is progress to show.
  useEffect(() => {
    if (!range) return;
    const anchor = progress?.summary.data_date;
    if (mode !== "planned" && anchor && anchor >= range[0] && anchor <= range[1]) {
      setDay(daysBetween(range[0], anchor));
    }
    // Only when the mode or the dataset changes, not on every scrub.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, progress?.summary.data_date, range?.[0], range?.[1]]);

  // --- painting --------------------------------------------------------------

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !manifest || !currentDate) return;
    const options: PaintOptions = { mode, hideFuture, highlightCritical, selectedTaskId };
    scene.paint((index) => {
      const window = elementWindows[index] ?? null;
      return colorFor(phaseAt(window, currentDate), window?.task ?? null, options);
    });
  }, [manifest, elementWindows, currentDate, mode, hideFuture, highlightCritical, selectedTaskId]);

  // --- playback ----------------------------------------------------------------

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let last = performance.now();
    let carry = 0;
    const tick = (now: number) => {
      carry += ((now - last) / 1000) * Number(speed);
      last = now;
      if (carry >= 1) {
        const step = Math.floor(carry);
        carry -= step;
        setDay((current) => {
          const next = current + step;
          if (next >= totalDays - 1) {
            setPlaying(false);
            return totalDays - 1;
          }
          return next;
        });
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, totalDays]);

  // --- interaction -------------------------------------------------------------

  const handleClick = useCallback(
    (event: React.MouseEvent) => {
      const index = sceneRef.current?.pick(event);
      if (index === null || index === undefined) {
        onSelectTask(null);
        return;
      }
      onSelectTask(elementWindows[index]?.task.id ?? null);
    },
    [elementWindows, onSelectTask],
  );

  const handleMove = useCallback((event: React.MouseEvent) => {
    setHovered(sceneRef.current?.pick(event) ?? null);
  }, []);

  // --- what is happening on this date -------------------------------------------

  const snapshot = useMemo(() => {
    const counts: Record<Phase, number> = { future: 0, active: 0, built: 0, context: 0 };
    if (currentDate) {
      for (const window of elementWindows) counts[phaseAt(window, currentDate)] += 1;
    }
    const active = currentDate
      ? taskWindows
          .filter((window) => phaseAt(window, currentDate) === "active")
          .sort((a, b) => a.start.localeCompare(b.start))
      : [];
    return { counts, active };
  }, [elementWindows, taskWindows, currentDate]);

  const hoveredElement = hovered !== null ? manifest?.elements[hovered] : null;
  const hoveredTask = hovered !== null ? elementWindows[hovered]?.task : null;
  const dataDate = progress?.summary.data_date;
  const dataDateDay =
    range && dataDate && dataDate >= range[0] && dataDate <= range[1]
      ? daysBetween(range[0], dataDate)
      : null;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <div className="space-y-3">
        <div className="relative h-[560px] overflow-hidden rounded-lg border bg-slate-100">
          <div
            ref={containerRef}
            className="absolute inset-0"
            onClick={handleClick}
            onMouseMove={handleMove}
            onMouseLeave={() => setHovered(null)}
          />

          {load.kind === "loading" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background/80 p-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{load.message}</p>
              {load.percent > 0 && <Progress value={load.percent} className="w-64" />}
            </div>
          )}
          {load.kind === "empty" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-background p-8 text-center">
              <Box className="h-8 w-8 text-muted-foreground" />
              <p className="font-medium">This model has no renderable geometry</p>
              <p className="max-w-md text-sm text-muted-foreground">
                The schedule is still valid — it was built from quantities, not shapes. The 4D view
                needs elements with a body representation.
              </p>
            </div>
          )}
          {load.kind === "error" && (
            <div className="absolute inset-0 flex items-center justify-center bg-background p-8">
              <Alert variant="destructive" className="max-w-md">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Could not load the model</AlertTitle>
                <AlertDescription>{load.message}</AlertDescription>
              </Alert>
            </div>
          )}

          {load.kind === "ready" && currentDate && (
            <>
              <div className="pointer-events-none absolute left-3 top-3 rounded-md bg-background/90 px-3 py-2 shadow-sm">
                <div className="text-lg font-semibold tabular-nums">{formatDate(currentDate)}</div>
                <div className="text-xs text-muted-foreground">
                  {mode === "planned"
                    ? "As planned"
                    : dataDate && currentDate > dataDate
                      ? "Forecast"
                      : "Actual"}
                </div>
              </div>
              <Button
                variant="outline"
                size="icon"
                className="absolute right-3 top-3 bg-background/90"
                title="Fit model"
                onClick={() => sceneRef.current?.frameAll()}
              >
                <Maximize2 />
              </Button>
              {hoveredElement && (
                <div className="pointer-events-none absolute bottom-3 left-3 max-w-sm rounded-md bg-background/95 px-3 py-2 text-xs shadow-sm">
                  <div className="font-medium">{hoveredElement.name ?? hoveredElement.global_id}</div>
                  <div className="text-muted-foreground">
                    {hoveredElement.ifc_class}
                    {hoveredTask ? ` · ${hoveredTask.label}` : " · not in any task"}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {load.kind === "ready" && range && (
          <div className="space-y-3 rounded-lg border p-3">
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="icon"
                title="Back one week"
                onClick={() => setDay((d) => Math.max(0, d - 7))}
              >
                <SkipBack />
              </Button>
              <Button
                size="icon"
                title={playing ? "Pause" : "Play"}
                onClick={() => {
                  if (!playing && day >= totalDays - 1) setDay(0);
                  setPlaying((value) => !value);
                }}
              >
                {playing ? <Pause /> : <Play />}
              </Button>
              <Button
                variant="outline"
                size="icon"
                title="Forward one week"
                onClick={() => setDay((d) => Math.min(totalDays - 1, d + 7))}
              >
                <SkipForward />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title="Back to start"
                onClick={() => {
                  setPlaying(false);
                  setDay(0);
                }}
              >
                <RotateCcw />
              </Button>

              <div className="relative mx-2 flex-1">
                <input
                  type="range"
                  aria-label="Timeline"
                  min={0}
                  max={totalDays - 1}
                  value={Math.min(day, totalDays - 1)}
                  onChange={(event) => {
                    setPlaying(false);
                    setDay(Number(event.target.value));
                  }}
                  className="w-full accent-primary"
                />
                {dataDateDay !== null && mode !== "planned" && (
                  <div
                    className="pointer-events-none absolute -top-1 h-5 w-0.5 bg-critical"
                    style={{ left: `${(dataDateDay / Math.max(1, totalDays - 1)) * 100}%` }}
                    title={`Data date ${dataDate}`}
                  />
                )}
              </div>

              <Select value={speed} onValueChange={setSpeed}>
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SPEEDS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{formatDate(range[0])}</span>
              {dataDateDay !== null && mode !== "planned" && (
                <span className="text-critical">data date {formatDate(dataDate)}</span>
              )}
              <span>{formatDate(range[1])}</span>
            </div>
          </div>
        )}
      </div>

      <div className="space-y-4">
        <div className="space-y-2 rounded-lg border p-3">
          <Label>View</Label>
          <div className="grid grid-cols-3 gap-1 rounded-md bg-muted p-1">
            {(["planned", "actual", "variance"] as const).map((option) => (
              <button
                key={option}
                type="button"
                disabled={option !== "planned" && !progress}
                onClick={() => setMode(option)}
                className={cn(
                  "rounded px-2 py-1 text-xs font-medium capitalize transition-colors disabled:opacity-40",
                  mode === option ? "bg-background shadow-sm" : "text-muted-foreground",
                )}
                title={
                  option !== "planned" && !progress ? "Record progress to unlock" : undefined
                }
              >
                {option}
              </button>
            ))}
          </div>
          <label className="flex cursor-pointer items-center gap-2 pt-1 text-sm">
            <input
              type="checkbox"
              checked={hideFuture}
              onChange={(event) => setHideFuture(event.target.checked)}
            />
            Hide work not yet started
          </label>
          <label
            className={cn(
              "flex items-center gap-2 text-sm",
              mode === "variance" ? "cursor-not-allowed opacity-50" : "cursor-pointer",
            )}
            title={mode === "variance" ? "Red means behind in this view" : undefined}
          >
            <input
              type="checkbox"
              checked={highlightCritical && mode !== "variance"}
              disabled={mode === "variance"}
              onChange={(event) => setHighlightCritical(event.target.checked)}
            />
            Highlight critical work
          </label>
        </div>

        <div className="space-y-2 rounded-lg border p-3 text-sm">
          <Label>Legend</Label>
          {mode === "variance" ? (
            <>
              {(["complete", "ahead", "on_track", "behind"] as const).map((flag) => (
                <LegendRow key={flag} color={FLAG_COLORS[flag]} label={flag.replace("_", " ")} />
              ))}
            </>
          ) : (
            <>
              <LegendRow color={ACTIVE_COLOR} label="In progress" />
              {highlightCritical && <LegendRow color={CRITICAL_COLOR} label="In progress, critical" />}
              {Object.entries(PACKAGE_COLORS).map(([name, color]) => (
                <LegendRow key={name} color={color} label={`Built · ${name}`} />
              ))}
            </>
          )}
          <LegendRow color={0x94a3b8} label="Not started" ghost />
        </div>

        {load.kind === "ready" && (
          <div className="space-y-2 rounded-lg border p-3">
            <Label>On this day</Label>
            <div className="grid grid-cols-3 gap-2 text-center">
              <Stat value={snapshot.counts.built} label="built" />
              <Stat value={snapshot.counts.active} label="active" />
              <Stat value={snapshot.counts.future} label="to go" />
            </div>
            <div className="space-y-1 pt-1">
              {snapshot.active.slice(0, 8).map(({ task }) => (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => onSelectTask(task.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-accent",
                    selectedTaskId === task.id && "bg-accent",
                  )}
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: toCss(ACTIVE_COLOR) }}
                  />
                  <span className="truncate">{task.label}</span>
                  {"percent_complete" in task && task.percent_complete > 0 && (
                    <Badge variant="secondary" className="ml-auto shrink-0">
                      {Math.round(task.percent_complete)}%
                    </Badge>
                  )}
                </button>
              ))}
              {snapshot.active.length === 0 && (
                <p className="text-xs text-muted-foreground">No work scheduled on this day.</p>
              )}
              {snapshot.active.length > 8 && (
                <p className="text-xs text-muted-foreground">
                  + {snapshot.active.length - 8} more
                </p>
              )}
            </div>
          </div>
        )}

        {manifest && manifest.warnings.length > 0 && (
          <Alert variant="warning">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription className="text-xs">{manifest.warnings.join(" ")}</AlertDescription>
          </Alert>
        )}
      </div>
    </div>
  );
}

function LegendRow({ color, label, ghost }: { color: number; label: string; ghost?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs capitalize">
      <span
        className={cn("h-3 w-3 shrink-0 rounded-sm", ghost && "border border-dashed opacity-40")}
        style={{ backgroundColor: toCss(color) }}
      />
      {label}
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-md bg-muted/60 py-1.5">
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
    </div>
  );
}
