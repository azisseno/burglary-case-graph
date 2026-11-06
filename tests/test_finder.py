from app import finder, seed, tools
from app.store import Graph

JEEP = {"entry_method": "vehicle backed through glass storefront", "vehicle": "stolen black Jeep"}
CROWBAR = {"entry_method": "pried rear window with a crowbar", "vehicle": "white van"}


def add(graph, case_id, location, day, traits, **extra):
    record = {"id": case_id, "date": day, "date_precision": "day", "location": location, "scene_type": "business",
              "items_taken": [], "evidence": [{"type": "vehicle", "description": traits["vehicle"]}], **traits, **extra}
    return seed.add_case(graph, record)


def build_graph():
    graph = Graph()
    add(graph, "a-1", "Renton, WA", "2023-09-01", JEEP)
    add(graph, "a-2", "Renton, WA", "2023-09-05", JEEP)
    add(graph, "a-3", "Renton, WA", "2023-09-09", JEEP)
    add(graph, "b-1", "Seattle, WA", "2024-02-01", CROWBAR)
    add(graph, "b-2", "Seattle, WA", "2024-02-03", CROWBAR)
    add(graph, "loner", "Tacoma, WA", "2022-01-01", {"entry_method": "unlocked door", "vehicle": "red motorcycle"})
    return graph


def test_two_clusters_and_a_loner():
    clusters = finder.candidate_clusters(build_graph())
    assert [c["case_ids"] for c in clusters] == [["case:a-1", "case:a-2", "case:a-3"], ["case:b-1", "case:b-2"]]
    assert [c["id"] for c in clusters] == ["cluster-1", "cluster-2"]
    assert all(c["anchor_ids"] == [] for c in clusters)
    assert clusters[0]["max_score"] >= finder.PAIR_SCORE_MINIMUM


def test_same_method_in_another_city_does_not_join():
    graph = build_graph()
    add(graph, "a-far", "Everett, WA", "2023-09-03", JEEP)
    members = {cid for c in finder.candidate_clusters(graph) for cid in c["case_ids"]}
    assert "case:a-far" not in members


def test_confirmed_series_cases_are_anchors_not_members():
    graph = build_graph()
    series = graph.add_node("series:S-001", "series", "Series S-001", status="confirmed")
    graph.add_edge("case:a-1", series["id"], "PART_OF_SERIES", kind="confirmed", provenance="test")
    graph.add_edge("case:a-2", series["id"], "PART_OF_SERIES", kind="confirmed", provenance="test")
    clusters = finder.candidate_clusters(graph)
    jeep_cluster = clusters[0]
    assert jeep_cluster["member_ids"] == ["case:a-3"]
    assert jeep_cluster["anchor_ids"] == ["case:a-1", "case:a-2"]
    assert jeep_cluster["case_ids"] == ["case:a-1", "case:a-2", "case:a-3"]


def test_two_confirmed_cases_alone_make_no_cluster():
    graph = Graph()
    add(graph, "a-1", "Renton, WA", "2023-09-01", JEEP)
    add(graph, "a-2", "Renton, WA", "2023-09-05", JEEP)
    series = graph.add_node("series:S-001", "series", "Series S-001", status="confirmed")
    for case_id in ("case:a-1", "case:a-2"):
        graph.add_edge(case_id, series["id"], "PART_OF_SERIES", kind="confirmed", provenance="test")
    assert finder.candidate_clusters(graph) == []


def test_chain_of_pairs_forms_one_component():
    graph = Graph()
    add(graph, "c-1", "Renton, WA", "2023-09-01", JEEP)
    add(graph, "c-2", "Renton, WA", "2023-09-05", JEEP)
    add(graph, "c-3", "Renton, WA", "2023-09-30", {"entry_method": "vehicle backed through glass storefront", "vehicle": "stolen black Jeep"})
    assert len(finder.candidate_clusters(graph)) == 1


def test_cluster_cap_keeps_largest_first_and_reports_dropped():
    clusters = [{"id": f"cluster-{n}", "case_ids": ["x"] * (20 - n)} for n in range(1, 16)]
    kept, dropped = finder.select_clusters(clusters)
    assert len(kept) == finder.CLUSTER_CAP
    assert [c["id"] for c in dropped] == ["cluster-13", "cluster-14", "cluster-15"]


def test_pair_threshold_matches_candidate_scoring():
    graph = build_graph()
    pairs = finder.scored_pairs(graph)
    assert ("case:a-1", "case:a-2") in pairs
    assert pairs[("case:a-1", "case:a-2")] == tools.cluster_candidates(graph, "case:a-1")[0]["score"]
    assert all(score >= finder.PAIR_SCORE_MINIMUM for score in pairs.values())
