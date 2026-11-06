import json

import pytest

from app import scoring, seed, tools
from app.store import Graph


@pytest.fixture
def cases_dir(tmp_path):
    def write(slug, status, linked, incidents):
        folder = tmp_path / slug
        folder.mkdir()
        truth = {"status": status, "linked_incidents": linked}
        (folder / "series.json").write_text(json.dumps({"series_id": slug, "ground_truth": truth}))
        for incident in incidents:
            (folder / incident).mkdir()
            (folder / incident / "record.json").write_text("{}")

    write("alpha", "linked_by_police", ["a-1", "a-2"], ["a-1", "a-2", "a-3"])
    write("beta", "partly_linked", ["b-1", "b-2"], ["b-1", "b-2", "b-3"])
    write("gamma", "linked_by_police", [], ["g-1", "g-2"])
    write("delta", "not_linked", [], ["d-1", "d-2"])
    return tmp_path


def add(graph, source_id, label=None):
    record = {"id": label or source_id, "date": "2023-01-01", "location": "Renton, WA", "entry_method": "pry bar",
              "evidence": [{"type": "forced_entry", "description": "pry bar"}]}
    seed.add_case(graph, record)
    graph.nodes[f"case:{label or source_id}"]["props"]["source_id"] = source_id


def propose(graph, first, second, run_id="run-1"):
    top = next(c for c in tools.cluster_candidates(graph, f"case:{first}") if c["case_id"] == f"case:{second}")
    return tools.propose_hypothesis(graph, f"case:{first}", [f"case:{second}"], "r", top["cited_edge_ids"], 0.8, run_id)["hypothesis"]


def test_linked_series_come_from_police_status_only(cases_dir):
    linked = scoring.police_linked_series(cases_dir)
    assert linked == {"alpha": {"a-1", "a-2"}, "beta": {"b-1", "b-2"}, "gamma": {"g-1", "g-2"}}


def test_agreement_requires_one_police_linked_series(cases_dir):
    graph = Graph()
    for name in ("a-1", "a-2", "a-3", "b-1"):
        add(graph, name)
    propose(graph, "a-1", "a-2")
    propose(graph, "a-1", "a-3")
    propose(graph, "a-2", "b-1")
    result = scoring.score(graph, cases_dir)
    assert result["proposed_total"] == 3
    assert result["proposed_agreeing"] == 1
    assert result["cases_in_graph"] == 4
    assert result["known_series_total"] == 3


def test_accepted_counts_and_series_touched(cases_dir):
    graph = Graph()
    for name in ("a-1", "a-2", "b-1", "b-2", "g-1", "d-1"):
        add(graph, name)
    good = propose(graph, "a-1", "a-2")
    mixed = propose(graph, "b-1", "d-1")
    rejected = propose(graph, "g-1", "d-1")
    for hypothesis in (good, mixed):
        tools.record_decision(graph, hypothesis["id"], "accept", "")
    tools.record_decision(graph, rejected["id"], "reject", "")
    result = scoring.score(graph, cases_dir)
    assert result["proposed_total"] == 2
    assert result["accepted_total"] == 2
    assert result["accepted_agreeing"] == 1
    assert result["cases_covered_by_accepted_series"] == 4
    assert result["known_series_touched"] == 1


def test_cases_without_source_id_use_their_dataset_id(cases_dir):
    graph = Graph()
    for name in ("a-1", "a-2"):
        seed.add_case(graph, {"id": name, "date": "2023-01-01", "location": "Renton, WA", "entry_method": "pry bar",
                              "evidence": [{"type": "forced_entry", "description": "pry bar"}]})
    propose(graph, "a-1", "a-2")
    assert scoring.score(graph, cases_dir)["proposed_agreeing"] == 1


def test_cases_with_unknown_source_never_agree(cases_dir):
    graph = Graph()
    add(graph, None, "NEW-001")
    add(graph, "a-1")
    propose(graph, "NEW-001", "a-1")
    assert scoring.score(graph, cases_dir)["proposed_agreeing"] == 0
