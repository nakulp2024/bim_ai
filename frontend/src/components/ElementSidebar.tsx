import { useMemo, useState } from "react";
import { useAppStore } from "../store";

export function ElementSidebar() {
  const elements = useAppStore((s) => s.elements);
  const selectedGuid = useAppStore((s) => s.selectedGuid);
  const setSelectedGuid = useAppStore((s) => s.setSelectedGuid);
  const [filter, setFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("");

  const types = useMemo(() => {
    const set = new Set<string>();
    elements.forEach((e) => set.add(e.ifc_type));
    return Array.from(set).sort();
  }, [elements]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return elements.filter((e) => {
      if (typeFilter && e.ifc_type !== typeFilter) return false;
      if (!q) return true;
      return (
        (e.name ?? "").toLowerCase().includes(q) ||
        e.ifc_guid.toLowerCase().includes(q) ||
        (e.storey ?? "").toLowerCase().includes(q)
      );
    });
  }, [elements, filter, typeFilter]);

  const selected = elements.find((e) => e.ifc_guid === selectedGuid) ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: 8, borderBottom: "1px solid #333" }}>
        <input
          placeholder="Filter (name / GUID / storey)"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{
            width: "100%",
            background: "#111",
            color: "#eee",
            border: "1px solid #333",
            padding: "6px 8px",
            borderRadius: 3,
            boxSizing: "border-box",
          }}
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          style={{
            marginTop: 6,
            width: "100%",
            background: "#111",
            color: "#eee",
            border: "1px solid #333",
            padding: "6px 8px",
            borderRadius: 3,
          }}
        >
          <option value="">All types ({elements.length})</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      <div style={{ flex: 1, overflowY: "auto", fontSize: 12 }}>
        {filtered.slice(0, 500).map((e) => (
          <div
            key={e.ifc_guid}
            onClick={() => setSelectedGuid(e.ifc_guid)}
            style={{
              padding: "6px 8px",
              borderBottom: "1px solid #222",
              cursor: "pointer",
              background: e.ifc_guid === selectedGuid ? "#3a4" : "transparent",
            }}
          >
            <div style={{ fontWeight: 600 }}>{e.name ?? "(unnamed)"}</div>
            <div style={{ color: "#888" }}>
              {e.ifc_type} · {e.storey ?? "—"}
            </div>
          </div>
        ))}
        {filtered.length > 500 && (
          <div style={{ padding: 8, color: "#888" }}>
            Showing first 500 of {filtered.length}. Refine the filter to see more.
          </div>
        )}
      </div>

      {selected && (
        <div
          style={{
            borderTop: "1px solid #333",
            padding: 8,
            maxHeight: "40%",
            overflowY: "auto",
            fontSize: 12,
            background: "#181818",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {selected.name ?? "(unnamed)"}
          </div>
          <div style={{ color: "#888", marginBottom: 8 }}>
            {selected.ifc_type} · {selected.ifc_guid}
          </div>
          {Object.entries(selected.psets).map(([psetName, props]) => (
            <div key={psetName} style={{ marginBottom: 8 }}>
              <div style={{ color: "#9cf" }}>{psetName}</div>
              {Object.entries(props).map(([k, v]) => (
                <div key={k} style={{ display: "flex", gap: 6 }}>
                  <span style={{ color: "#888", minWidth: 120 }}>{k}</span>
                  <span>{String(v)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
