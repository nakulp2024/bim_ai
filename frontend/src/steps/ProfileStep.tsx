import { AlertTriangle, Layers, Ruler, Boxes } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { CountEntry, ModelProfile, ParseReport } from "@/lib/types";
import { formatNumber } from "@/lib/utils";

interface Props {
  profile: ModelProfile;
  parseReport: ParseReport;
}

function BreakdownList({ entries, limit = 12 }: { entries: CountEntry[]; limit?: number }) {
  const shown = entries.slice(0, limit);
  const max = Math.max(1, ...shown.map((entry) => entry.count));
  if (!shown.length) return <p className="text-sm text-muted-foreground">Nothing recorded.</p>;

  return (
    <ul className="space-y-1.5">
      {shown.map((entry) => (
        <li key={entry.key} className="grid grid-cols-[1fr_auto] items-center gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm" title={entry.key}>
              {entry.key}
            </div>
            <div className="mt-1 h-1.5 rounded-full bg-secondary">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${(entry.count / max) * 100}%` }}
              />
            </div>
          </div>
          <span className="tabular-nums text-sm text-muted-foreground">
            {formatNumber(entry.count, 0)}
          </span>
        </li>
      ))}
      {entries.length > limit && (
        <li className="pt-1 text-xs text-muted-foreground">
          + {entries.length - limit} more
        </li>
      )}
    </ul>
  );
}

export function ProfileStep({ profile, parseReport }: Props) {
  const coverage = profile.quantity_coverage;
  const hasIssues = parseReport.errors.length > 0 || parseReport.warnings.length > 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<Boxes className="h-4 w-4" />}
          label="Elements read"
          value={formatNumber(profile.element_count, 0)}
          hint={`${formatNumber(parseReport.products_seen, 0)} products seen`}
        />
        <StatCard
          icon={<Layers className="h-4 w-4" />}
          label="Storeys"
          value={formatNumber(profile.storeys.length, 0)}
          hint={parseReport.schema}
        />
        <StatCard
          icon={<Ruler className="h-4 w-4" />}
          label="Quantity coverage"
          value={`${coverage.coverage_pct}%`}
          hint={`${formatNumber(coverage.derived, 0)} geometry-derived`}
        />
        <StatCard
          icon={<AlertTriangle className="h-4 w-4" />}
          label="Missing quantities"
          value={formatNumber(coverage.none, 0)}
          hint={
            coverage.none === 0 ? "every element is measured" : "these fall back to count-based rates"
          }
        />
      </div>

      {coverage.coverage_pct < 100 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Where the quantities came from</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Progress value={coverage.coverage_pct} />
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant="success">
                Qto base quantities: {formatNumber(coverage.base_quantity, 0)}
              </Badge>
              <Badge variant="warning">
                Geometry-derived: {formatNumber(coverage.derived, 0)}
              </Badge>
              <Badge variant="danger">Unmeasured: {formatNumber(coverage.none, 0)}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              Geometry-derived quantities are computed from the element's bounding box and mesh
              volume. Tasks built from them are capped at medium confidence.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">By IFC class</CardTitle>
          </CardHeader>
          <CardContent>
            <BreakdownList entries={profile.by_class} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">By discipline</CardTitle>
            <CardDescription>Derived from work_packages.yaml</CardDescription>
          </CardHeader>
          <CardContent>
            <BreakdownList entries={profile.by_discipline} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">By storey</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {profile.storeys.map((storey) => (
                <li key={storey.storey_id} className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-sm">{storey.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {storey.elevation === null ? "no elevation" : `${storey.elevation.toFixed(2)} m`}
                    {" · "}
                    {formatNumber(storey.count, 0)}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">By type</CardTitle>
          </CardHeader>
          <CardContent>
            <BreakdownList entries={profile.by_type} limit={10} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">By material</CardTitle>
          </CardHeader>
          <CardContent>
            <BreakdownList entries={profile.by_material} limit={10} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Zone sources available</CardTitle>
            <CardDescription>Usable as a secondary split</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {profile.zones.length > 0 && (
              <div>
                <p className="mb-1 text-sm font-medium">IfcZone / IfcSpatialZone</p>
                <BreakdownList entries={profile.zones} limit={6} />
              </div>
            )}
            {profile.available_zone_properties.length > 0 ? (
              <div>
                <p className="mb-1 text-sm font-medium">Property sets</p>
                <div className="flex flex-wrap gap-1.5">
                  {profile.available_zone_properties.map((property) => (
                    <Badge key={property} variant="secondary">
                      {property}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              profile.zones.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No zones or zone-like properties found in this model.
                </p>
              )
            )}
          </CardContent>
        </Card>
      </div>

      {hasIssues && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>The parser skipped or degraded some data</AlertTitle>
          <AlertDescription>
            <ul className="mt-2 list-disc space-y-1 pl-4">
              {[...parseReport.errors, ...parseReport.warnings].slice(0, 8).map((issue, index) => (
                // eslint-disable-next-line react/no-array-index-key
                <li key={index}>{issue}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-muted-foreground">
          {icon}
          <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
        </div>
        <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}
