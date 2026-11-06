import pytest

from app import normalize as N
from app import seed, tools
from app.store import Graph


def record(cid, **over):
    base = {
        "id": cid,
        "series_id": "s",
        "date": "2023-09-07",
        "time": "03:10",
        "time_precision": "reported",
        "location": "4200 block of SW Morgan St, Renton, WA",
        "location_precision": "block",
        "scene_type": "restaurant",
        "evidence": [
            {"type": "forced_entry", "description": "Stolen SUV rammed through the front door", "provenance": "RPD", "source_url": "https://example.org/a"},
            {"type": "vehicle", "description": "Dark SUV seen on camera", "provenance": "RPD", "source_url": "https://example.org/a"},
            {"type": "theft", "description": "Cash register taken", "provenance": "RPD", "source_url": "https://example.org/a"},
        ],
        "items_taken": ["cash register"],
        "unknowns": ["tool identity"],
        "media": [],
        "notes": None,
    }
    base.update(over)
    return base


def test_canonical_method_and_vehicle():
    assert N.canonical_method("Stolen SUV rammed through the front door") == ["vehicle_ramming"]
    assert "safe_cut" in N.canonical_method("the safe was cut open with a saw")
    assert N.canonical_vehicle("Dark SUV seen on camera") == "dark_suv"
    assert N.canonical_vehicle("a white Ford pickup") == "light_pickup"
    assert N.canonical_vehicle("U-Haul box truck") == "u_haul"
    assert N.canonical_vehicle("no vehicle mentioned") is None


def test_time_window_and_location():
    assert N.time_window("2023-09-07") == "2023-W36"
    assert N.time_window("2024-11-01", "month") == "2024-11"
    loc = N.parse_location("4200 block of SW Morgan St, Seattle, WA")
    assert loc == {"city": "Seattle", "state": "WA", "neighborhood": ""}
    assert N.location_key(loc) == "seattle_wa"


def build():
    g = Graph()
    seed.add_case(g, record("a-01"))
    seed.add_case(g, record("a-02", date="2023-09-09"))
    seed.add_case(g, record("b-01", date="2024-05-01", location="Belltown, Seattle, WA", evidence=[
        {"type": "forced_entry", "description": "Smashed window", "provenance": "SPD", "source_url": "https://example.org/b"},
    ], items_taken=["cannabis"]))
    return g


def test_add_case_builds_attribute_edges():
    g = build()
    case = tools.get_case(g, "case:a-01")
    assert [a["label"] for a in case["attributes"]["method"]] == ["vehicle ramming"]
    assert [a["label"] for a in case["attributes"]["vehicle"]] == ["dark suv"]
    assert [a["label"] for a in case["attributes"]["location"]] == ["Renton, WA"]
    assert [a["label"] for a in case["attributes"]["time_window"]] == ["2023-W36"]
    assert all(e["provenance"] for e in case["edges"])


def test_cluster_candidates_scores_shared_method_vehicle_and_time():
    g = build()
    seed.add_case(g, record("new-1", date="2023-09-08", location="Renton, WA"), status="new")
    ranked = tools.cluster_candidates(g, "case:new-1")
    assert [r["case_id"] for r in ranked[:2]] == ["case:a-01", "case:a-02"]
    top = ranked[0]
    assert top["score"] == 3 + 3 + 1 + 2 + 1 + 1
    assert {m["kind"] for m in top["matched"]} == {"method", "vehicle", "city", "time", "scene_type", "item"}
    assert all(eid in g.edges for eid in top["cited_edge_ids"])
    assert "case:b-01" not in [r["case_id"] for r in ranked]


def test_propose_and_accept_creates_series():
    g = build()
    seed.add_case(g, record("new-1", date="2023-09-08"), status="new")
    cand = tools.cluster_candidates(g, "case:new-1")[0]
    delta = tools.propose_hypothesis(g, "case:new-1", [cand["case_id"]], "same method and vehicle within a day", cand["cited_edge_ids"], 0.9, "run-1")
    hyp = delta["hypothesis"]
    assert hyp["status"] == "proposed"
    assert {e["rel"] for e in delta["edges"]} == {"PROPOSES_LINK", "SUPPORTED_BY"}
    result = tools.record_decision(g, hyp["id"], "accept", "method and vehicle match")
    assert g.nodes[hyp["id"]]["status"] == "confirmed"
    assert result["series"]["type"] == "series"
    assert tools.case_series(g, "case:new-1")["id"] == result["series"]["id"]
    assert g.nodes["case:new-1"]["status"] == "confirmed"


def test_propose_rejects_bad_citations():
    g = build()
    seed.add_case(g, record("new-1"), status="new")
    with pytest.raises(tools.HypothesisError):
        tools.propose_hypothesis(g, "case:new-1", ["case:a-01"], "x", ["nope"], 0.5, "run-1")
    with pytest.raises(tools.HypothesisError):
        tools.propose_hypothesis(g, "case:new-1", ["case:a-01"], "x", [], 0.5, "run-1")


def test_reject_hides_hypothesis():
    g = build()
    seed.add_case(g, record("new-1"), status="new")
    cand = tools.cluster_candidates(g, "case:new-1")[0]
    delta = tools.propose_hypothesis(g, "case:new-1", [cand["case_id"]], "x", cand["cited_edge_ids"], 0.4, "run-1")
    tools.record_decision(g, delta["hypothesis"]["id"], "reject", "different year")
    assert g.nodes[delta["hypothesis"]["id"]]["status"] == "rejected"
    assert tools.case_series(g, "case:new-1") is None


def test_save_and_load_roundtrip(tmp_path):
    g = build()
    g.save(tmp_path / "graph.json")
    loaded = Graph.load(tmp_path / "graph.json")
    assert loaded.stats() == g.stats()


def test_seed_builds_real_dataset():
    g = seed.build_graph()
    stats = g.stats()
    assert stats["by_type"]["case"] >= 120
    assert "case:rcg-04" not in g.nodes
    assert tools.case_series(g, "case:rcg-03") is not None


@pytest.mark.parametrize("text,expected", [
    ("Stolen black Jeep backed through the glass front of the store", "vehicle_ramming"),
    ("A stolen car was driven into the storefront", "vehicle_ramming"),
    ("Van driven through a garage door", "vehicle_ramming"),
    ("Suspect broke in through the front door", "forced_door"),
    ("kicking in a rear glass door or forcing open doors", "forced_door"),
    ("kicking in a rear glass door", "rear_window"),
    ("Glass smashed at ten businesses", "glass_smash"),
    ("Glass front door of the salon punched out", "glass_smash"),
    ("Front window broken with a rock", "glass_smash"),
    ("a rock was used to break the front glass door", "glass_smash"),
    ("Object thrown into the front entryway", "glass_smash"),
    ("Attempted to saw into the ATM", "safe_cut"),
    ("Perpetrators forced entry", "forced_door"),
])
def test_method_phrasings_from_dataset(text, expected):
    assert expected in N.canonical_method(text)


@pytest.mark.parametrize("text,city,state", [
    ("Renton, WA (block not reported)", "Renton", "WA"),
    ("Belltown, Seattle, WA (block not reported)", "Seattle", "WA"),
    ("Renton, Washington", "Renton", "WA"),
    ("Renton WA", "Renton", "WA"),
    ("Renton, WA 98057", "Renton", "WA"),
    ("Long Beach, California", "Long Beach", "CA"),
    ("Renton", "Renton", ""),
])
def test_parse_location_handles_report_phrasings(text, city, state):
    loc = N.parse_location(text)
    assert (loc["city"], loc["state"]) == (city, state)


def test_demo_report_locations_key_to_the_seeded_city():
    import re
    from pathlib import Path
    reports = Path(__file__).resolve().parent.parent / "data" / "demo-inputs"
    keys = {}
    for report in reports.glob("*/report.txt"):
        text = re.search(r"Location: (.*)", report.read_text())[1]
        keys[report.parent.name] = N.location_key(N.parse_location(text))
    assert keys == {"renton-a": "renton_wa", "renton-b": "renton_wa", "decoy-cannabis": "seattle_wa"}


def test_seeded_renton_vehicle_evidence_gives_ramming_method():
    g = seed.build_graph()
    methods = {n["id"] for n, _ in g.neighbors("case:rcg-06") if n["type"] == "method"}
    assert "method:vehicle_ramming" in methods
    assert any(e["rel"] == "USED_METHOD" and e["target"] == "method:vehicle_ramming"
               for e in g.edges_of("case:rcg-06"))


def test_citations_must_be_attribute_edges_with_shared_nodes():
    g = build()
    seed.add_case(g, record("new-1"), status="new")
    seed.add_case(g, record("far-1", location="Long Beach, CA", date="2020-01-01", evidence=[
        {"type": "forced_entry", "description": "Smashed window", "provenance": "LB", "source_url": "https://example.org/c"},
    ], items_taken=[]))
    own_location = next(e["id"] for e in g.edges_of("case:new-1") if e["rel"] == "AT_LOCATION")
    with pytest.raises(tools.HypothesisError, match="shared"):
        tools.propose_hypothesis(g, "case:new-1", ["case:far-1"], "x", [own_location], 0.5, "run-1")
    cand = tools.cluster_candidates(g, "case:new-1")[0]
    first = tools.propose_hypothesis(g, "case:new-1", [cand["case_id"]], "x", cand["cited_edge_ids"], 0.5, "run-1")
    circular = [e["id"] for e in first["edges"] if e["rel"] == "PROPOSES_LINK"]
    with pytest.raises(tools.HypothesisError, match="attribute edge"):
        tools.propose_hypothesis(g, "case:new-1", [cand["case_id"]], "again", circular, 0.5, "run-1")


def test_supported_by_edges_carry_source_provenance():
    g = build()
    seed.add_case(g, record("new-1"), status="new")
    cand = tools.cluster_candidates(g, "case:new-1")[0]
    delta = tools.propose_hypothesis(g, "case:new-1", [cand["case_id"]], "x", cand["cited_edge_ids"], 0.5, "run-1")
    supported = [e for e in delta["edges"] if e["rel"] == "SUPPORTED_BY"]
    assert supported
    for edge in supported:
        assert all(not p.startswith("case:") for p in edge["provenance"])
        assert edge["cites"][0] in cand["cited_edge_ids"]


def test_decided_hypothesis_cannot_be_decided_again():
    g = build()
    seed.add_case(g, record("new-1"), status="new")
    cand = tools.cluster_candidates(g, "case:new-1")[0]
    hyp = tools.propose_hypothesis(g, "case:new-1", [cand["case_id"]], "x", cand["cited_edge_ids"], 0.5, "run-1")["hypothesis"]["id"]
    tools.record_decision(g, hyp, "more", "")
    tools.record_decision(g, hyp, "reject", "no")
    for decision in ("accept", "reject"):
        with pytest.raises(tools.HypothesisError, match="already decided"):
            tools.record_decision(g, hyp, decision, "")


def test_edges_require_provenance():
    g = Graph()
    g.add_node("a", "case", "A")
    g.add_node("b", "method", "B")
    with pytest.raises(ValueError):
        g.add_edge("a", "b", "USED_METHOD", provenance=None)


def test_seeded_edges_all_have_provenance():
    g = seed.build_graph()
    assert all(e["provenance"] for e in g.edges.values())


def test_save_uses_unique_temp_files_and_snapshot_is_detached(tmp_path):
    g = build()
    snapshot = g.to_dict()
    g.nodes["case:a-01"]["props"]["added_later"] = True
    detached = next(n for n in snapshot["nodes"] if n["id"] == "case:a-01")
    assert "added_later" not in detached["props"]
    g.save(tmp_path / "graph.json")
    g.save(tmp_path / "graph.json")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["graph.json"]
