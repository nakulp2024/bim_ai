import { AlertCircle, FileUp, Loader2 } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { ApiError, api, pollJob } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  onParsed: (projectId: number) => void;
}

export function UploadStep({ onParsed }: Props) {
  const [name, setName] = useState("Untitled project");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const pickFile = useCallback((candidate: File | null | undefined) => {
    if (!candidate) return;
    const lower = candidate.name.toLowerCase();
    if (!/\.(ifc|ifcxml|ifczip)$/.test(lower)) {
      setError(`"${candidate.name}" is not an IFC file (.ifc, .ifcxml or .ifczip).`);
      return;
    }
    setError(null);
    setFile(candidate);
  }, []);

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setProgress(0);
    setMessage("Creating project…");

    try {
      const project = await api.createProject(name.trim() || file.name);
      setMessage("Uploading…");
      const { job_id } = await api.upload(project.id, file);

      const job = await pollJob(job_id, (update) => {
        setProgress(Math.round(update.progress * 100));
        setMessage(update.message || "Parsing…");
      });

      if (job.status === "failed") {
        setError(job.error?.split("\n")[0] ?? "The parse failed.");
        setBusy(false);
        return;
      }
      if ((job.result?.elements_read as number) === 0) {
        setError(
          "No schedulable elements were read from this file. It may be empty or malformed.",
        );
        setBusy(false);
        return;
      }
      onParsed(project.id);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause));
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle>Upload an IFC model</CardTitle>
        <CardDescription>
          IFC2X3 and IFC4 are both supported. Large models are parsed in the background — you can
          watch the progress here.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <Label htmlFor="project-name">Project name</Label>
          <Input
            id="project-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={busy}
          />
        </div>

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            pickFile(event.dataTransfer.files?.[0]);
          }}
          onClick={() => !busy && inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-10 text-center transition-colors",
            dragging ? "border-primary bg-accent" : "border-input hover:bg-accent/50",
            busy && "pointer-events-none opacity-60",
          )}
        >
          <FileUp className="h-8 w-8 text-muted-foreground" />
          {file ? (
            <>
              <p className="font-medium">{file.name}</p>
              <p className="text-sm text-muted-foreground">
                {(file.size / 1024 / 1024).toFixed(1)} MB
              </p>
            </>
          ) : (
            <>
              <p className="font-medium">Drop an IFC file here</p>
              <p className="text-sm text-muted-foreground">or click to browse</p>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept=".ifc,.ifcxml,.ifczip"
            className="hidden"
            onChange={(event) => pickFile(event.target.files?.[0])}
          />
        </div>

        {busy && (
          <div className="space-y-2">
            <Progress value={progress} />
            <p className="text-sm text-muted-foreground">
              {message} {progress > 0 && `— ${progress}%`}
            </p>
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Could not read that file</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button onClick={submit} disabled={!file || busy} className="w-full">
          {busy && <Loader2 className="animate-spin" />}
          {busy ? "Parsing…" : "Parse model"}
        </Button>
      </CardContent>
    </Card>
  );
}
