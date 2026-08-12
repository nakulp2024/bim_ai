import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { LinkType, Task } from "@/lib/types";

const LINK_TYPES: LinkType[] = ["FS", "SS", "FF", "SF"];

interface Props {
  task: Task | null;
  allTasks: Task[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (predecessors: { id: string; type: LinkType; lag: number }[]) => void;
}

export function RelinkDialog({ task, allTasks, open, onOpenChange, onSave }: Props) {
  const [links, setLinks] = useState<{ id: string; type: LinkType; lag: number }[]>([]);

  useEffect(() => {
    if (task) setLinks(task.predecessors.map((link) => ({ ...link })));
  }, [task]);

  if (!task) return null;

  const candidates = allTasks.filter((candidate) => candidate.id !== task.id);

  function update(index: number, patch: Partial<{ id: string; type: LinkType; lag: number }>) {
    setLinks((current) =>
      current.map((link, position) => (position === index ? { ...link, ...patch } : link)),
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Predecessors for "{task.label}"</DialogTitle>
          <DialogDescription>
            Replaces every incoming link on this task. The schedule is recalculated on save.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[50vh] space-y-3 overflow-y-auto py-2">
          {links.map((link, index) => (
            // eslint-disable-next-line react/no-array-index-key
            <div key={index} className="grid grid-cols-[1fr_90px_90px_auto] items-end gap-2">
              <div className="min-w-0 space-y-1">
                <Label>Predecessor</Label>
                <Select value={link.id} onValueChange={(value) => update(index, { id: value })}>
                  <SelectTrigger>
                    <SelectValue placeholder="Pick a task" />
                  </SelectTrigger>
                  <SelectContent className="max-h-72">
                    {candidates.map((candidate) => (
                      <SelectItem key={candidate.id} value={candidate.id}>
                        {candidate.wbs_code} — {candidate.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Type</Label>
                <Select
                  value={link.type}
                  onValueChange={(value) => update(index, { type: value as LinkType })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LINK_TYPES.map((type) => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Lag</Label>
                <Input
                  type="number"
                  value={link.lag}
                  onChange={(event) => update(index, { lag: Number(event.target.value) || 0 })}
                />
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive"
                onClick={() => setLinks((current) => current.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}

          {!links.length && (
            <p className="py-4 text-sm text-muted-foreground">
              This task has no predecessors — it starts as soon as the project does.
            </p>
          )}

          <Button
            variant="outline"
            size="sm"
            disabled={!candidates.length}
            onClick={() =>
              setLinks((current) => [...current, { id: candidates[0].id, type: "FS", lag: 0 }])
            }
          >
            <Plus /> Add predecessor
          </Button>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              // Drop incomplete rows rather than sending them to the API.
              onSave(links.filter((link) => link.id));
              onOpenChange(false);
            }}
          >
            Save links
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
