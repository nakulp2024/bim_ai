import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { RunReport as RunReportData } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

const REASON_LABELS: Record<string, string> = {
  excluded_class: "Excluded IFC class",
  assembly_child: "Collapsed into a parent assembly",
  below_size_threshold: "Below the size threshold",
  name_pattern: "Matched a name exclusion pattern",
};

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b py-1.5 last:border-b-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="shrink-0 tabular-nums text-sm font-medium">{value}</span>
    </div>
  );
}

export function RunReport({ report }: { report: RunReportData }) {
  const { parse, filter, grouping, durations, sequencing, cpm } = report;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Elements read</CardTitle>
          <CardDescription>What the parser got out of the IFC file</CardDescription>
        </CardHeader>
        <CardContent>
          <Row label="Schema" value={parse?.schema ?? "—"} />
          <Row label="Products seen" value={formatNumber(parse?.products_seen ?? 0, 0)} />
          <Row label="Elements read" value={formatNumber(parse?.elements_read ?? 0, 0)} />
          <Row label="Spatial containers skipped" value={formatNumber(parse?.skipped_spatial ?? 0, 0)} />
          <Row
            label="Quantities from Qto base quantities"
            value={formatNumber(parse?.quantities_from_base ?? 0, 0)}
          />
          <Row
            label="Quantities derived from geometry"
            value={formatNumber(parse?.quantities_derived ?? 0, 0)}
          />
          <Row label="Quantities missing" value={formatNumber(parse?.quantities_missing ?? 0, 0)} />
          <Row label="Quantity coverage" value={`${parse?.quantity_coverage_pct ?? 0}%`} />
          {(parse?.geometry_failures ?? 0) > 0 && (
            <Row label="Geometry failures" value={formatNumber(parse?.geometry_failures ?? 0, 0)} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Elements filtered out</CardTitle>
          <CardDescription>Why each element did not become a task</CardDescription>
        </CardHeader>
        <CardContent>
          <Row label="Into the filter" value={formatNumber(filter?.elements_in ?? 0, 0)} />
          <Row label="Kept" value={formatNumber(filter?.elements_kept ?? 0, 0)} />
          <Row label="Removed" value={formatNumber(filter?.elements_removed ?? 0, 0)} />
          {Object.entries(filter?.removed_by_reason ?? {}).map(([reason, count]) => (
            <Row
              key={reason}
              label={`— ${REASON_LABELS[reason] ?? reason}`}
              value={formatNumber(count, 0)}
            />
          ))}
          {Object.entries(filter?.rolled_up_quantity ?? {}).map(([key, value]) => (
            <Row key={key} label={`Rolled-up ${key}`} value={formatNumber(value, 3)} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Tasks created</CardTitle>
        </CardHeader>
        <CardContent>
          <Row label="Level of detail" value={grouping?.level ?? "—"} />
          <Row label="Zone split" value={grouping?.zone_split ?? "none"} />
          <Row label="Tasks" value={formatNumber(grouping?.task_count ?? 0, 0)} />
          <Row
            label="Elements represented in tasks"
            value={formatNumber(grouping?.elements_in_tasks ?? 0, 0)}
          />
          <Row
            label="Groups aggregated as too trivial for L5"
            value={formatNumber(grouping?.aggregated_trivial_groups ?? 0, 0)}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Durations and confidence</CardTitle>
          <CardDescription>Which link of the rate fallback chain was used</CardDescription>
        </CardHeader>
        <CardContent>
          <Row label="High confidence" value={formatNumber(durations?.confidence.high ?? 0, 0)} />
          <Row label="Medium confidence" value={formatNumber(durations?.confidence.medium ?? 0, 0)} />
          <Row label="Low confidence" value={formatNumber(durations?.confidence.low ?? 0, 0)} />
          <Row
            label="Tasks with a measured quantity"
            value={`${durations?.quantity_coverage_pct ?? 0}%`}
          />
          {Object.entries(durations?.by_rate_source ?? {}).map(([source, count]) => (
            <Row key={source} label={`— ${source.replace(/_/g, " ")}`} value={formatNumber(count, 0)} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Sequencing</CardTitle>
          <CardDescription>Every link traced back to the rule that made it</CardDescription>
        </CardHeader>
        <CardContent>
          <Row label="Links" value={formatNumber(sequencing?.link_count ?? 0, 0)} />
          {Object.entries(sequencing?.by_origin ?? {}).map(([origin, count]) => (
            <Row key={origin} label={`— ${origin}`} value={formatNumber(count, 0)} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Critical path</CardTitle>
        </CardHeader>
        <CardContent>
          <Row
            label="Project duration (working days)"
            value={formatNumber(cpm?.project_duration_days ?? 0, 0)}
          />
          <Row label="Finish date" value={cpm?.finish_date ?? "—"} />
          <Row label="Critical tasks" value={formatNumber(cpm?.critical_task_count ?? 0, 0)} />
          <Row label="Cycles broken" value={formatNumber(cpm?.cycles_broken.length ?? 0, 0)} />
          <Row label="Links dropped" value={formatNumber(cpm?.dropped_links.length ?? 0, 0)} />
          {(cpm?.cycles_broken.length ?? 0) > 0 && (
            <p className="pt-3 text-sm text-amber-600 dark:text-amber-400">
              A circular dependency was detected and broken so the schedule could be calculated.
              Check the affected links.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
