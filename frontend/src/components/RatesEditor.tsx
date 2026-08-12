import { Loader2, RotateCcw, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, api } from "@/lib/api";
import type { Rate, RatesResponse } from "@/lib/types";

interface Props {
  projectId: number;
  onSaved: () => void;
}

interface Draft {
  output_per_crew_day: number;
  default_crew: number;
}

export function RatesEditor({ projectId, onSaved }: Props) {
  const [rates, setRates] = useState<RatesResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    api
      .getRates(projectId)
      .then((payload) => {
        setRates(payload);
        setDrafts(
          Object.fromEntries(
            payload.effective.rules.map((rate) => [
              rate.id,
              { output_per_crew_day: rate.output_per_crew_day, default_crew: rate.default_crew },
            ]),
          ),
        );
      })
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : String(cause)));
  }, [projectId]);

  const defaults = useMemo(() => {
    const map = new Map<string, Rate>();
    for (const rate of rates?.defaults.rules ?? []) map.set(rate.id, rate);
    return map;
  }, [rates]);

  const changed = useMemo(() => {
    if (!rates) return [];
    return rates.effective.rules.filter((rate) => {
      const draft = drafts[rate.id];
      const base = defaults.get(rate.id);
      if (!draft || !base) return false;
      return (
        draft.output_per_crew_day !== base.output_per_crew_day ||
        draft.default_crew !== base.default_crew
      );
    });
  }, [rates, drafts, defaults]);

  async function save() {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const payload = changed.map((rate) => ({
        id: rate.id,
        output_per_crew_day: drafts[rate.id].output_per_crew_day,
        default_crew: drafts[rate.id].default_crew,
      }));
      const result = await api.updateRates(projectId, payload);
      setStatus(
        payload.length === 0
          ? "Rates reset to the packaged library."
          : `Saved. ${result.repriced_tasks} task(s) repriced.`,
      );
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  }

  function resetAll() {
    if (!rates) return;
    setDrafts(
      Object.fromEntries(
        rates.defaults.rules.map((rate) => [
          rate.id,
          { output_per_crew_day: rate.output_per_crew_day, default_crew: rate.default_crew },
        ]),
      ),
    );
  }

  if (error && !rates) {
    return <p className="p-6 text-sm text-destructive">{error}</p>;
  }
  if (!rates) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading rate library…
      </div>
    );
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>Productivity rates</CardTitle>
          <CardDescription>
            duration = ceil(quantity ÷ (output × crew)), floored at the rule's minimum. Changes are
            saved against this project; the packaged library in backend/config/rates.yaml is not
            modified.
          </CardDescription>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" onClick={resetAll} disabled={saving}>
            <RotateCcw /> Reset
          </Button>
          <Button size="sm" onClick={save} disabled={saving}>
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            Save & reprice
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {status && <p className="text-sm text-emerald-600 dark:text-emerald-400">{status}</p>}
        {error && <p className="text-sm text-destructive">{error}</p>}
        {changed.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {changed.length} rate(s) differ from the defaults. Tasks whose duration you edited by
            hand are never repriced.
          </p>
        )}

        <div className="max-h-[520px] overflow-auto rounded-lg border">
          <Table>
            <TableHeader className="sticky top-0 bg-background shadow-[0_1px_0_0_hsl(var(--border))]">
              <TableRow>
                <TableHead className="min-w-[180px]">Rate</TableHead>
                <TableHead>Matches</TableHead>
                <TableHead className="w-16">Unit</TableHead>
                <TableHead className="w-32 text-right">Output / crew-day</TableHead>
                <TableHead className="w-24 text-right">Crew</TableHead>
                <TableHead className="w-20 text-right">Min days</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rates.effective.rules.map((rate) => {
                const draft = drafts[rate.id];
                const base = defaults.get(rate.id);
                const isChanged =
                  base &&
                  draft &&
                  (draft.output_per_crew_day !== base.output_per_crew_day ||
                    draft.default_crew !== base.default_crew);
                return (
                  <TableRow key={rate.id}>
                    <TableCell className="font-mono text-xs">
                      <div className="flex items-center gap-2">
                        {rate.id}
                        {isChanged && <Badge variant="warning">changed</Badge>}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {[
                        rate.ifc_class,
                        rate.predefined_types?.join("/"),
                        rate.material_pattern,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "any"}
                    </TableCell>
                    <TableCell className="text-xs">{rate.unit}</TableCell>
                    <TableCell className="text-right">
                      <Input
                        type="number"
                        min={0.01}
                        step={0.5}
                        value={draft?.output_per_crew_day ?? rate.output_per_crew_day}
                        onChange={(event) =>
                          setDrafts((current) => ({
                            ...current,
                            [rate.id]: {
                              ...current[rate.id],
                              output_per_crew_day: Number(event.target.value),
                            },
                          }))
                        }
                        className="h-7 w-24 px-2 text-right tabular-nums"
                      />
                    </TableCell>
                    <TableCell className="text-right">
                      <Input
                        type="number"
                        min={1}
                        step={1}
                        value={draft?.default_crew ?? rate.default_crew}
                        onChange={(event) =>
                          setDrafts((current) => ({
                            ...current,
                            [rate.id]: {
                              ...current[rate.id],
                              default_crew: Number(event.target.value),
                            },
                          }))
                        }
                        className="h-7 w-16 px-2 text-right tabular-nums"
                      />
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-xs">
                      {rate.min_duration_days}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
