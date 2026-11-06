import json
from pathlib import Path

from .seed import GROUND_TRUTH_LINKED

CASE_PREFIX = "case:"
SCORED_STATUSES = ("proposed", "confirmed")


def police_linked_series(cases_dir):
    linked = {}
    for series_path in sorted(Path(cases_dir).glob("*/series.json")):
        series = json.loads(series_path.read_text())
        truth = series.get("ground_truth", {})
        if truth.get("status") not in GROUND_TRUTH_LINKED:
            continue
        incidents = set(truth.get("linked_incidents") or [])
        if not incidents and truth["status"] == "linked_by_police":
            incidents = {p.parent.name for p in series_path.parent.glob("*/record.json")}
        if incidents:
            linked[series["series_id"]] = incidents
    return linked


def source_id_of(case):
    return case["props"].get("source_id") or case["id"].removeprefix(CASE_PREFIX)


def series_of_hypothesis(graph, hypothesis, linked):
    sources = []
    for case_id in hypothesis["props"]["case_ids"]:
        case = graph.nodes.get(case_id)
        if case is None:
            return set()
        sources.append(source_id_of(case))
    return {name for name, incidents in linked.items() if all(source in incidents for source in sources)}


def score(graph, cases_dir):
    linked = police_linked_series(cases_dir)
    scored = [h for h in graph.nodes_of_type("hypothesis") if h["status"] in SCORED_STATUSES]
    accepted = [h for h in scored if h["status"] == "confirmed"]
    covered = {c for h in accepted for c in h["props"]["case_ids"]}
    touched = set()
    for hypothesis in accepted:
        touched |= series_of_hypothesis(graph, hypothesis, linked)
    return {
        "proposed_total": len(scored),
        "proposed_agreeing": sum(1 for h in scored if series_of_hypothesis(graph, h, linked)),
        "accepted_total": len(accepted),
        "accepted_agreeing": sum(1 for h in accepted if series_of_hypothesis(graph, h, linked)),
        "cases_in_graph": len(graph.nodes_of_type("case")),
        "cases_covered_by_accepted_series": len(covered),
        "known_series_touched": len(touched),
        "known_series_total": len(linked),
    }
