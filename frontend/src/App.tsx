import { AlertCircle, ArrowLeft, Building2, Loader2, RefreshCw } from "lucide-react";
import { Suspense, lazy, useCallback, useState } from "react";

import { ExportBar } from "@/components/ExportBar";
import { GanttChart } from "@/components/GanttChart";
import { ProgressPanel } from "@/components/ProgressPanel";
import { RatesEditor } from "@/components/RatesEditor";
import { RelinkDialog } from "@/components/RelinkDialog";
import { RunReport } from "@/components/RunReport";
import { TaskTable } from "@/components/TaskTable";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LodPicker } from "@/steps/LodPicker";
import { ProfileStep } from "@/steps/ProfileStep";
import { UploadStep } from "@/steps/UploadStep";
import { ApiError, api, pollJob } from "@/lib/api";
import type {
  LinkType,
  ModelProfile,
  ParseReport,
  ProgressEntryInput,
  ProgressView,
  Project,
  Schedule,
  ScheduleRequest,
} from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

// three.js is most of the bundle and only the 4D tab needs it.
const FourDPlayer = lazy(() =>
  import("@/components/FourDPlayer").then((module) => ({ default: module.FourDPlayer })),
);

type Stage = "upload" | "configure" | "schedule";

const STEPS: { id: Stage; label: string }[] = [
  { id: "upload", label: "1. Upload" },
  { id: "configure", label: "2. Profile & level of detail" },
  { id: "schedule", label: "3. Schedule" },
];

export default function App() {
  const [stage, setStage] = useState<Stage>("upload");
  const [project, setProject] = useState<Project | null>(null);
  const [profile, setProfile] = useState<ModelProfile | null>(null);
  const [parseReport, setParseReport] = useState<ParseReport | null>(null);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [progressView, setProgressView] = useState<ProgressView | null>(null);

  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [relinkId, setRelinkId] = useState<string | null>(null);

  const fail = useCallback((cause: unknown) => {
    setError(cause instanceof ApiError ? cause.message : String(cause));
    setBusy(false);
  }, []);

  const loadProfile = useCallback(
    async (projectId: number) => {
      try {
        const payload = await api.getProfile(projectId);
        setProject(payload.project);
        setProfile(payload.profile);
        setParseReport(payload.parse_report);
        setStage("configure");
      } catch (cause) {
        fail(cause);
      }
    },
    [fail],
  );

  async function generate(request: ScheduleRequest) {
    if (!project) return;
    setBusy(true);
    setError(null);
    setProgress(0);
    setProgressMessage("Starting…");
    try {
      const { job_id } = await api.generate(project.id, request);
      const job = await pollJob(job_id, (update) => {
        setProgress(Math.round(update.progress * 100));
        setProgressMessage(update.message || "Generating…");
      });
      if (job.status === "failed") {
        setError(job.error?.split("\n")[0] ?? "Schedule generation failed.");
        setBusy(false);
        return;
      }
      const payload = await api.getSchedule(project.id);
      setSchedule(payload);
      await loadProgress(project.id);
      setStage("schedule");
      setBusy(false);
    } catch (cause) {
      fail(cause);
    }
  }

  /** The forecast is derived from the plan, so any change to the plan
   * invalidates it. Failure here is not fatal: the plan is still usable. */
  async function loadProgress(projectId: number) {
    try {
      setProgressView(await api.getProgress(projectId));
    } catch {
      setProgressView(null);
    }
  }

  async function mutate(action: () => Promise<Schedule>) {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      setSchedule(await action());
      await loadProgress(project.id);
    } catch (cause) {
      fail(cause);
      return;
    }
    setBusy(false);
  }

  async function mutateProgress(action: () => Promise<ProgressView | unknown>) {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      // Some calls return the recalculated view directly; the rest need a reload.
      if (result && typeof result === "object" && "summary" in result) {
        setProgressView(result as ProgressView);
      } else {
        await loadProgress(project.id);
      }
    } catch (cause) {
      fail(cause);
      return;
    }
    setBusy(false);
  }

  async function refreshSchedule() {
    if (!project) return;
    setBusy(true);
    try {
      setSchedule(await api.getSchedule(project.id));
      await loadProgress(project.id);
    } catch (cause) {
      fail(cause);
      return;
    }
    setBusy(false);
  }

  function restart() {
    setStage("upload");
    setProject(null);
    setProfile(null);
    setParseReport(null);
    setSchedule(null);
    setProgressView(null);
    setSelectedId(null);
    setError(null);
  }

  const selectedTask = schedule?.tasks.find((task) => task.id === selectedId) ?? null;
  const relinkTask = schedule?.tasks.find((task) => task.id === relinkId) ?? null;

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
        <div className="container flex h-14 items-center gap-4">
          <div className="flex items-center gap-2 font-semibold">
            <Building2 className="h-5 w-5" />
            IFC → Construction Schedule
          </div>

          <nav className="ml-4 hidden items-center gap-1 md:flex">
            {STEPS.map((step, index) => {
              const reached = STEPS.findIndex((s) => s.id === stage) >= index;
              return (
                <span
                  key={step.id}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-sm",
                    stage === step.id
                      ? "bg-accent font-medium text-accent-foreground"
                      : reached
                        ? "text-foreground"
                        : "text-muted-foreground",
                  )}
                >
                  {step.label}
                </span>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {project && (
              <Badge variant="secondary" className="hidden sm:inline-flex">
                {project.name} · {project.ifc_schema} ·{" "}
                {formatNumber(project.element_count, 0)} elements
              </Badge>
            )}
            {stage !== "upload" && (
              <Button variant="ghost" size="sm" onClick={restart}>
                <ArrowLeft /> New model
              </Button>
            )}
          </div>
        </div>
      </header>

      <main className="container space-y-6 py-8">
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Something went wrong</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {busy && stage !== "upload" && (
          <div className="space-y-2">
            <Progress value={progress} />
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {progressMessage}
            </p>
          </div>
        )}

        {stage === "upload" && <UploadStep onParsed={loadProfile} />}

        {stage === "configure" && project && profile && parseReport && (
          <Tabs defaultValue="lod">
            <TabsList>
              <TabsTrigger value="lod">Level of detail</TabsTrigger>
              <TabsTrigger value="profile">Model profile</TabsTrigger>
              <TabsTrigger value="rates">Rates</TabsTrigger>
            </TabsList>
            <TabsContent value="lod">
              <LodPicker
                projectId={project.id}
                profile={profile}
                busy={busy}
                onGenerate={generate}
              />
            </TabsContent>
            <TabsContent value="profile">
              <ProfileStep profile={profile} parseReport={parseReport} />
            </TabsContent>
            <TabsContent value="rates">
              <RatesEditor projectId={project.id} onSaved={() => undefined} />
            </TabsContent>
          </Tabs>
        )}

        {stage === "schedule" && project && schedule && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{schedule.level}</Badge>
                {schedule.zone_split && <Badge variant="secondary">zone: {schedule.zone_split}</Badge>}
                <span className="text-sm text-muted-foreground">
                  {formatNumber(schedule.tasks.length, 0)} tasks ·{" "}
                  {formatNumber(schedule.project_duration_days, 0)} working days · finish{" "}
                  {schedule.report.cpm?.finish_date ?? "—"}
                </span>
                <Button variant="ghost" size="sm" onClick={refreshSchedule} disabled={busy}>
                  <RefreshCw /> Refresh
                </Button>
              </div>
              <ExportBar projectId={project.id} />
            </div>

            <Tabs defaultValue="gantt">
              <TabsList>
                <TabsTrigger value="gantt">Gantt</TabsTrigger>
                <TabsTrigger value="4d">4D</TabsTrigger>
                <TabsTrigger value="progress">Progress</TabsTrigger>
                <TabsTrigger value="table">Task table</TabsTrigger>
                <TabsTrigger value="rates">Rates</TabsTrigger>
                <TabsTrigger value="report">Run report</TabsTrigger>
              </TabsList>

              <TabsContent value="gantt">
                <GanttChart
                  schedule={schedule}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
                {selectedTask && (
                  <div className="mt-4 rounded-lg border p-4 text-sm">
                    <p className="font-medium">{selectedTask.label}</p>
                    <p className="mt-1 text-muted-foreground">
                      {selectedTask.element_count} element(s) ·{" "}
                      {selectedTask.quantity === null
                        ? "no quantity"
                        : `${formatNumber(selectedTask.quantity, 1)} ${selectedTask.unit} from ${
                            selectedTask.quantity_key
                          }`}{" "}
                      · rate {selectedTask.rate_id} ({selectedTask.confidence} confidence) · crew{" "}
                      {selectedTask.crew}
                    </p>
                    <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
                      {selectedTask.element_ids.slice(0, 12).join(", ")}
                      {selectedTask.element_ids.length > 12 &&
                        ` … +${selectedTask.element_ids.length - 12} more GlobalIds`}
                    </p>
                  </div>
                )}
              </TabsContent>

              <TabsContent value="4d">
                <Suspense
                  fallback={
                    <div className="flex h-[560px] items-center justify-center gap-2 rounded-lg border text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" /> Loading 3D viewer…
                    </div>
                  }
                >
                  <FourDPlayer
                    projectId={project.id}
                    schedule={schedule}
                    progress={progressView}
                    selectedTaskId={selectedId}
                    onSelectTask={setSelectedId}
                  />
                </Suspense>
              </TabsContent>

              <TabsContent value="progress">
                {progressView ? (
                  <ProgressPanel
                    view={progressView}
                    busy={busy}
                    selectedId={selectedId}
                    onSelect={setSelectedId}
                    onReport={(entries: ProgressEntryInput[], reportedOn?: string) =>
                      mutateProgress(() => api.reportProgress(project.id, entries, reportedOn))
                    }
                    onClear={(taskId) =>
                      mutateProgress(() => api.clearProgress(project.id, taskId))
                    }
                    onDataDate={(date) => mutateProgress(() => api.setDataDate(project.id, date))}
                    onBaseline={() => mutateProgress(() => api.createBaseline(project.id))}
                  />
                ) : (
                  <p className="p-8 text-center text-sm text-muted-foreground">
                    Progress could not be loaded for this schedule.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="table">
                <TaskTable
                  schedule={schedule}
                  selectedId={selectedId}
                  busy={busy}
                  onSelect={setSelectedId}
                  onRename={(taskId, label) =>
                    mutate(() => api.updateTask(project.id, taskId, { label }))
                  }
                  onDuration={(taskId, duration_days) =>
                    mutate(() => api.updateTask(project.id, taskId, { duration_days }))
                  }
                  onDelete={(taskId) => mutate(() => api.deleteTask(project.id, taskId))}
                  onRelink={setRelinkId}
                />
              </TabsContent>

              <TabsContent value="rates">
                <RatesEditor projectId={project.id} onSaved={refreshSchedule} />
              </TabsContent>

              <TabsContent value="report">
                <RunReport report={schedule.report} />
              </TabsContent>
            </Tabs>
          </div>
        )}
      </main>

      <RelinkDialog
        task={relinkTask}
        allTasks={schedule?.tasks ?? []}
        open={relinkId !== null}
        onOpenChange={(open) => !open && setRelinkId(null)}
        onSave={(predecessors) => {
          if (!project || !relinkId) return;
          const taskId = relinkId;
          mutate(() =>
            api.updateTask(project.id, taskId, {
              predecessors: predecessors as { id: string; type: LinkType; lag: number }[],
            }),
          );
        }}
      />
    </div>
  );
}
