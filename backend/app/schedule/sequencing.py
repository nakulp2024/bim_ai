"""Rule-based sequencing: task groups -> predecessor links.

No relationship is hardcoded here. Every link emitted comes from a rule in
config/sequencing.yaml:

  * within_storey  - links between work packages in the same storey/zone bucket
  * within_bucket  - ordering of the several tasks that share one bucket
  * vertical       - storey N before storey N+1, ordered by elevation
  * zone_repetition- staggered repetition of a package across zones
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from ..config import load_config
from .lod import TaskGroup

DEFAULT_TRADE_ORDER = (
    "Substructure",
    "Superstructure",
    "Envelope",
    "MEP",
    "Interior",
    "Finishes",
)


@dataclass
class Link:
    predecessor: str   # task id
    successor: str     # task id
    type: str          # FS | SS | FF | SF
    lag: int
    origin: str        # which rule produced it

    def as_dict(self) -> dict[str, Any]:
        return {
            "predecessor_id": self.predecessor,
            "successor_id": self.successor,
            "type": self.type,
            "lag": self.lag,
            "origin": self.origin,
        }


class SequencingEngine:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else load_config("sequencing")
        self.trade_order: list[str] = list(self.config.get("trade_order") or DEFAULT_TRADE_ORDER)
        self.within_storey: list[dict[str, Any]] = list(self.config.get("within_storey") or [])
        if not self.within_storey:
            self.within_storey = [
                {"from": a, "to": b, "type": "FS", "lag": 0}
                for a, b in zip(self.trade_order, self.trade_order[1:], strict=False)
            ]
        self.vertical: dict[str, Any] = dict(self.config.get("vertical") or {})
        self.zone_repetition: dict[str, Any] = dict(self.config.get("zone_repetition") or {})
        self.within_bucket: dict[str, Any] = dict(self.config.get("within_bucket") or {})

    # -- helpers -----------------------------------------------------------

    def _package_rank(self, package: str) -> int:
        try:
            return self.trade_order.index(package)
        except ValueError:
            return len(self.trade_order)

    def _class_rank(self, ifc_class: str | None) -> tuple[int, str]:
        order = list(self.within_bucket.get("class_order") or [])
        name = ifc_class or ""
        try:
            return (order.index(name), name)
        except ValueError:
            return (len(order), name)

    def _storey_sort(self, groups: list[TaskGroup]) -> list[tuple[str, float]]:
        """Distinct storeys ordered by elevation, unassigned last."""
        elevations: dict[str, float | None] = {}
        for group in groups:
            key = group.storey_id or group.storey_name
            current = elevations.get(key)
            if current is None and group.storey_elevation is not None:
                elevations[key] = group.storey_elevation
            elevations.setdefault(key, group.storey_elevation)
        ordered = sorted(
            elevations.items(),
            key=lambda item: (item[1] is None, item[1] if item[1] is not None else 0.0, item[0]),
        )
        return [(key, value if value is not None else 0.0) for key, value in ordered]

    # -- main --------------------------------------------------------------

    def build_links(self, tasks: list[dict[str, Any]]) -> list[Link]:
        """``tasks`` are dicts carrying id, work_package, storey_*, zone_name,
        ifc_class and label (i.e. the task rows produced by the pipeline)."""
        links: list[Link] = []
        if not tasks:
            return links

        groups = [_as_group(task) for task in tasks]
        by_id = {task["id"]: task for task in tasks}

        # bucket = (storey key, zone, package)
        buckets: dict[tuple[str, str | None, str], list[dict[str, Any]]] = defaultdict(list)
        for task, group in zip(tasks, groups, strict=False):
            key = (group.storey_id or group.storey_name, group.zone_name, group.work_package)
            buckets[key].append(task)

        for members in buckets.values():
            members.sort(key=lambda t: (self._class_rank(t.get("ifc_class")), t.get("label") or ""))

        links.extend(self._within_bucket_links(buckets))
        links.extend(self._within_storey_links(buckets))
        links.extend(self._vertical_links(buckets, groups))
        links.extend(self._zone_links(buckets))

        # De-duplicate, keeping the strongest (largest lag) of any duplicate pair.
        best: dict[tuple[str, str, str], Link] = {}
        for link in links:
            if link.predecessor not in by_id or link.successor not in by_id:
                continue
            if link.predecessor == link.successor:
                continue
            key = (link.predecessor, link.successor, link.type)
            existing = best.get(key)
            if existing is None or link.lag > existing.lag:
                best[key] = link
        return sorted(best.values(), key=lambda link: (link.successor, link.predecessor, link.type))

    # -- rule families -----------------------------------------------------

    def _within_bucket_links(self, buckets: dict[tuple, list[dict[str, Any]]]) -> list[Link]:
        mode = str(self.within_bucket.get("mode") or "parallel").lower()
        if mode != "chain":
            return []
        link_type = str(self.within_bucket.get("type") or "SS").upper()
        lag = int(self.within_bucket.get("lag") or 0)
        links: list[Link] = []
        for members in buckets.values():
            for previous, current in zip(members, members[1:], strict=False):
                links.append(
                    Link(previous["id"], current["id"], link_type, lag, "within_bucket")
                )
        return links

    def _within_storey_links(self, buckets: dict[tuple, list[dict[str, Any]]]) -> list[Link]:
        by_scope: dict[tuple[str, str | None], dict[str, list[dict[str, Any]]]] = defaultdict(dict)
        for (storey, zone, package), members in buckets.items():
            by_scope[(storey, zone)][package] = members

        links: list[Link] = []
        for packages in by_scope.values():
            for rule in self.within_storey:
                source = packages.get(rule.get("from"))
                target = packages.get(rule.get("to"))
                if not source or not target:
                    continue
                link_type = str(rule.get("type") or "FS").upper()
                lag = int(rule.get("lag") or 0)
                # FS/FF hang off the last task of the predecessor package;
                # SS/SF hang off the first one.
                anchor = source[-1] if link_type in ("FS", "FF") else source[0]
                driven = target[0] if link_type in ("FS", "SS") else target[-1]
                links.append(
                    Link(anchor["id"], driven["id"], link_type, lag, "within_storey")
                )
        return links

    def _vertical_links(
        self, buckets: dict[tuple, list[dict[str, Any]]], groups: list[TaskGroup]
    ) -> list[Link]:
        if not self.vertical.get("enabled", True):
            return []
        driving = list(self.vertical.get("driving_packages") or ["Superstructure"])
        link_type = str(self.vertical.get("type") or "FS").upper()
        lag = int(self.vertical.get("lag") or 0)
        storey_order = [key for key, _ in self._storey_sort(groups)]

        # The driving packages are treated as one structural train per storey,
        # so a storey whose structure is Substructure still gates the storey
        # above whose structure is Superstructure.
        by_storey: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (storey, _zone, package), members in buckets.items():
            if package in driving:
                by_storey[storey].extend(members)

        for members in by_storey.values():
            members.sort(
                key=lambda t: (
                    self._package_rank(str(t.get("work_package") or "")),
                    self._class_rank(t.get("ifc_class")),
                    t.get("label") or "",
                )
            )

        links: list[Link] = []
        chain = [storey for storey in storey_order if by_storey.get(storey)]
        for lower, upper in zip(chain, chain[1:], strict=False):
            predecessor = by_storey[lower][-1]
            successor = by_storey[upper][0]
            links.append(
                Link(predecessor["id"], successor["id"], link_type, lag, "vertical")
            )
        return links

    def _zone_links(self, buckets: dict[tuple, list[dict[str, Any]]]) -> list[Link]:
        if not self.zone_repetition.get("enabled", False):
            return []
        excluded = set(self.zone_repetition.get("exclude_packages") or [])
        link_type = str(self.zone_repetition.get("type") or "SS").upper()
        lag = int(self.zone_repetition.get("lag") or 0)

        by_scope: dict[tuple[str, str], list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
        for (storey, zone, package), members in buckets.items():
            if zone is None or package in excluded:
                continue
            by_scope[(storey, package)].append((zone, members))

        links: list[Link] = []
        for (_storey, package), zoned in by_scope.items():
            zoned.sort(key=lambda pair: pair[0])
            for (_zone_a, members_a), (_zone_b, members_b) in zip(zoned, zoned[1:], strict=False):
                if not members_a or not members_b:
                    continue
                links.append(
                    Link(
                        members_a[0]["id"],
                        members_b[0]["id"],
                        link_type,
                        lag,
                        f"zone_repetition:{package}",
                    )
                )
        return links


def _as_group(task: dict[str, Any]) -> TaskGroup:
    """Adapter so build_links can take plain task dicts."""
    return TaskGroup(
        key=(task.get("id"),),
        label=str(task.get("label") or ""),
        level=str(task.get("level") or "L3"),
        wbs_path=list(task.get("wbs_path") or []),
        work_package=str(task.get("work_package") or "Interior"),
        storey_id=task.get("storey_id"),
        storey_name=str(task.get("storey_name") or "Unassigned"),
        storey_elevation=task.get("storey_elevation"),
        zone_name=task.get("zone_name"),
        ifc_class=task.get("ifc_class"),
        predefined_type=task.get("predefined_type"),
        type_name=task.get("type_name"),
        material=task.get("material"),
    )
