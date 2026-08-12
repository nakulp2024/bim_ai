import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const FORMATS = [
  { id: "csv", label: "CSV" },
  { id: "xlsx", label: "Excel" },
  { id: "mspdi", label: "MS Project XML" },
  { id: "xer", label: "Primavera P6 XER" },
  { id: "json", label: "JSON (4D)" },
];

export function ExportBar({ projectId }: { projectId: number }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 flex items-center gap-1.5 text-sm text-muted-foreground">
        <Download className="h-4 w-4" />
        Export
      </span>
      {FORMATS.map((format) => (
        <Button key={format.id} variant="outline" size="sm" asChild>
          {/* A plain link keeps the browser's own download UX and the
              Content-Disposition filename from the API. */}
          <a href={api.exportUrl(projectId, format.id)} download>
            {format.label}
          </a>
        </Button>
      ))}
    </div>
  );
}
