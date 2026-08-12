"""Sequencing: every link must come from a rule, not from Python."""

from __future__ import annotations

import pytest

from app.schedule.sequencing import SequencingEngine

CONFIG = {
    "trade_order": ["Substructure", "Superstructure", "Envelope", "MEP", "Interior", "Finishes"],
    "within_storey": [
        {"from": "Substructure", "to": "Superstructure", "type": "FS", "lag": 0},
        {"from": "Superstructure", "to": "Envelope", "type": "SS", "lag": 3},
        {"from": "MEP", "to": "Interior", "type": "SS", "lag": 2},
    ],
    "vertical": {
        "enabled": True,
        "driving_packages": ["Substructure", "Superstructure"],
        "type": "FS",
        "lag": 0,
    },
    "zone_repetition": {"enabled": True, "type": "SS", "lag": 2, "exclude_packages": []},
    "within_bucket": {
        "mode": "chain",
        "type": "SS",
        "lag": 1,
        "class_order": ["IfcColumn", "IfcSlab"],
    },
}


def make_task(task_id, package, storey, elevation, ifc_class=None, zone=None, duration=2):
    return {
        "id": task_id,
        "label": f"{storey} {package} {ifc_class or ''}".strip(),
        "work_package": package,
        "storey_id": storey,
        "storey_name": storey,
        "storey_elevation": elevation,
        "zone_name": zone,
        "ifc_class": ifc_class,
        "duration_days": duration,
    }


def links_between(links, predecessor, successor):
    return [
        link for link in links if link.predecessor == predecessor and link.successor == successor
    ]


# --- within storey --------------------------------------------------------


def test_within_storey_rules_produce_the_declared_links():
    tasks = [
        make_task("sub", "Substructure", "L00", 0.0),
        make_task("sup", "Superstructure", "L00", 0.0),
        make_task("env", "Envelope", "L00", 0.0),
    ]
    links = SequencingEngine(CONFIG).build_links(tasks)
    fs = links_between(links, "sub", "sup")
    assert fs and fs[0].type == "FS" and fs[0].lag == 0
    ss = links_between(links, "sup", "env")
    assert ss and ss[0].type == "SS" and ss[0].lag == 3


def test_packages_with_no_rule_get_no_link():
    tasks = [
        make_task("sup", "Superstructure", "L00", 0.0),
        make_task("fin", "Finishes", "L00", 0.0),
    ]
    links = SequencingEngine(CONFIG).build_links(tasks)
    assert not links_between(links, "sup", "fin")


def test_missing_within_storey_rules_fall_back_to_the_trade_order():
    config = {**CONFIG, "within_storey": []}
    tasks = [
        make_task("sub", "Substructure", "L00", 0.0),
        make_task("sup", "Superstructure", "L00", 0.0),
    ]
    links = SequencingEngine(config).build_links(tasks)
    fs = links_between(links, "sub", "sup")
    assert fs and fs[0].type == "FS"


def test_links_do_not_cross_storeys_via_the_within_storey_rules():
    tasks = [
        make_task("sub0", "Substructure", "L00", 0.0),
        make_task("sup1", "Superstructure", "L01", 3.5),
    ]
    links = SequencingEngine(CONFIG).build_links(tasks)
    assert not [link for link in links if link.origin == "within_storey"]


# --- vertical -------------------------------------------------------------


def test_vertical_chain_follows_elevation_not_input_order():
    tasks = [
        make_task("l02", "Superstructure", "L02", 7.0),
        make_task("l00", "Substructure", "L00", 0.0),
        make_task("l01", "Superstructure", "L01", 3.5),
    ]
    links = [
        link for link in SequencingEngine(CONFIG).build_links(tasks) if link.origin == "vertical"
    ]
    pairs = {(link.predecessor, link.successor) for link in links}
    assert pairs == {("l00", "l01"), ("l01", "l02")}
    assert all(link.type == "FS" for link in links)


def test_vertical_chain_bridges_different_driving_packages():
    """L00 structure is Substructure, L01 structure is Superstructure."""
    tasks = [
        make_task("sub0", "Substructure", "L00", 0.0),
        make_task("sup1", "Superstructure", "L01", 3.5),
    ]
    links = SequencingEngine(CONFIG).build_links(tasks)
    assert links_between(links, "sub0", "sup1")


def test_vertical_can_be_disabled():
    config = {**CONFIG, "vertical": {"enabled": False}}
    tasks = [
        make_task("l00", "Superstructure", "L00", 0.0),
        make_task("l01", "Superstructure", "L01", 3.5),
    ]
    links = SequencingEngine(config).build_links(tasks)
    assert not [link for link in links if link.origin == "vertical"]


def test_non_driving_packages_do_not_join_the_vertical_chain():
    tasks = [
        make_task("f0", "Finishes", "L00", 0.0),
        make_task("f1", "Finishes", "L01", 3.5),
    ]
    links = SequencingEngine(CONFIG).build_links(tasks)
    assert not [link for link in links if link.origin == "vertical"]


def test_storeys_without_elevation_sort_last():
    tasks = [
        make_task("known", "Superstructure", "L00", 0.0),
        make_task("unknown", "Superstructure", "Unassigned", None),
    ]
    links = [
        link for link in SequencingEngine(CONFIG).build_links(tasks) if link.origin == "vertical"
    ]
    assert [(link.predecessor, link.successor) for link in links] == [("known", "unknown")]


# --- within bucket --------------------------------------------------------


def test_tasks_in_one_bucket_are_chained_in_class_order():
    tasks = [
        make_task("slab", "Superstructure", "L01", 3.5, ifc_class="IfcSlab"),
        make_task("col", "Superstructure", "L01", 3.5, ifc_class="IfcColumn"),
    ]
    links = [
        link
        for link in SequencingEngine(CONFIG).build_links(tasks)
        if link.origin == "within_bucket"
    ]
    assert [(link.predecessor, link.successor) for link in links] == [("col", "slab")]
    assert links[0].type == "SS" and links[0].lag == 1


def test_parallel_bucket_mode_emits_no_links():
    config = {**CONFIG, "within_bucket": {"mode": "parallel"}}
    tasks = [
        make_task("a", "Superstructure", "L01", 3.5, ifc_class="IfcSlab"),
        make_task("b", "Superstructure", "L01", 3.5, ifc_class="IfcColumn"),
    ]
    links = SequencingEngine(config).build_links(tasks)
    assert not [link for link in links if link.origin == "within_bucket"]


# --- zones ----------------------------------------------------------------


def test_zone_repetition_staggers_the_same_package_across_zones():
    tasks = [
        make_task("north", "Interior", "L01", 3.5, zone="North"),
        make_task("south", "Interior", "L01", 3.5, zone="South"),
    ]
    links = [
        link
        for link in SequencingEngine(CONFIG).build_links(tasks)
        if link.origin.startswith("zone_repetition")
    ]
    assert [(link.predecessor, link.successor) for link in links] == [("north", "south")]
    assert links[0].type == "SS" and links[0].lag == 2


def test_excluded_packages_run_zone_parallel():
    config = {
        **CONFIG,
        "zone_repetition": {**CONFIG["zone_repetition"], "exclude_packages": ["Substructure"]},
    }
    tasks = [
        make_task("a", "Substructure", "L00", 0.0, zone="North"),
        make_task("b", "Substructure", "L00", 0.0, zone="South"),
    ]
    links = SequencingEngine(config).build_links(tasks)
    assert not [link for link in links if link.origin.startswith("zone_repetition")]


def test_no_zone_links_without_a_zone_split():
    tasks = [
        make_task("a", "Interior", "L01", 3.5),
        make_task("b", "Interior", "L01", 3.5, ifc_class="IfcDoor"),
    ]
    links = SequencingEngine(CONFIG).build_links(tasks)
    assert not [link for link in links if link.origin.startswith("zone_repetition")]


# --- hygiene --------------------------------------------------------------


def test_links_are_deduplicated_keeping_the_largest_lag():
    config = {
        **CONFIG,
        "within_storey": [
            {"from": "Substructure", "to": "Superstructure", "type": "FS", "lag": 0},
            {"from": "Substructure", "to": "Superstructure", "type": "FS", "lag": 5},
        ],
    }
    tasks = [
        make_task("sub", "Substructure", "L00", 0.0),
        make_task("sup", "Superstructure", "L00", 0.0),
    ]
    links = links_between(SequencingEngine(config).build_links(tasks), "sub", "sup")
    assert len(links) == 1
    assert links[0].lag == 5


def test_no_self_links_are_ever_emitted():
    tasks = [
        make_task(f"t{i}", "Superstructure", "L01", 3.5, ifc_class="IfcColumn") for i in range(5)
    ]
    links = SequencingEngine(CONFIG).build_links(tasks)
    assert all(link.predecessor != link.successor for link in links)


def test_empty_input():
    assert SequencingEngine(CONFIG).build_links([]) == []


def test_output_is_deterministic():
    tasks = [
        make_task("sub", "Substructure", "L00", 0.0),
        make_task("sup", "Superstructure", "L01", 3.5, ifc_class="IfcColumn"),
        make_task("slab", "Superstructure", "L01", 3.5, ifc_class="IfcSlab"),
    ]
    engine = SequencingEngine(CONFIG)
    first = [link.as_dict() for link in engine.build_links(tasks)]
    second = [link.as_dict() for link in engine.build_links(tasks)]
    assert first == second


@pytest.mark.parametrize("link_type", ["FS", "SS", "FF", "SF"])
def test_all_link_types_are_expressible_from_config(link_type):
    config = {
        **CONFIG,
        "within_storey": [{"from": "MEP", "to": "Finishes", "type": link_type, "lag": 1}],
    }
    tasks = [
        make_task("mep", "MEP", "L01", 3.5),
        make_task("fin", "Finishes", "L01", 3.5),
    ]
    links = links_between(SequencingEngine(config).build_links(tasks), "mep", "fin")
    assert links and links[0].type == link_type
