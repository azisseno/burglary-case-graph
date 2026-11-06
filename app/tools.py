from datetime import date

from . import normalize as N

ATTRIBUTE_RELS = {
    "method": "USED_METHOD",
    "vehicle": "VEHICLE_SEEN",
    "item": "ITEM_TAKEN",
    "location": "AT_LOCATION",
    "time_window": "IN_WINDOW",
}
SCORE_WEIGHTS = {
    "method": 3,
    "vehicle": 3,
    "neighborhood": 2,
    "city": 1,
    "within_14_days": 2,
    "within_window": 1,
    "scene_type": 1,
    "item": 1,
}


def case_attributes(graph, case_id):
    out = {t: [] for t in ATTRIBUTE_RELS}
    for node, edge in graph.neighbors(case_id):
        if node["type"] in out:
            out[node["type"]].append({"node": node, "edge": edge})
    return out


def case_series(graph, case_id):
    for node, edge in graph.neighbors(case_id, "PART_OF_SERIES"):
        if node["type"] == "series":
            return node
    return None


def parse_date(text):
    if not text:
        return None
    try:
        y, m, d = (int(x) for x in text[:10].split("-"))
        return date(y, m, d)
    except ValueError:
        return None


def get_case(graph, case_id):
    node = graph.nodes.get(case_id)
    if node is None or node["type"] != "case":
        return None
    attrs = case_attributes(graph, case_id)
    series = case_series(graph, case_id)
    return {
        "case": node,
        "attributes": {t: [{"id": a["node"]["id"], "label": a["node"]["label"], "edge_id": a["edge"]["id"], "provenance": a["edge"]["provenance"]} for a in items] for t, items in attrs.items()},
        "series": {"id": series["id"], "label": series["label"]} if series else None,
        "edges": graph.edges_of(case_id),
    }


def find_cases(graph, city=None, method=None, scene_type=None, date_from=None, date_to=None, series_id=None, limit=25):
    start = parse_date(date_from)
    end = parse_date(date_to)
    out = []
    for node in graph.nodes_of_type("case"):
        props = node["props"]
        if scene_type and props.get("scene_type") != scene_type:
            continue
        if series_id and props.get("series_id") != series_id:
            continue
        case_day = parse_date(props.get("date"))
        if start and (case_day is None or case_day < start):
            continue
        if end and (case_day is None or case_day > end):
            continue
        attrs = case_attributes(graph, node["id"])
        if city and not any(a["node"]["props"].get("city", "").lower() == city.lower() for a in attrs["location"]):
            continue
        if method and not any(a["node"]["props"].get("key") == method for a in attrs["method"]):
            continue
        out.append({"id": node["id"], "label": node["label"], "date": props.get("date"), "scene_type": props.get("scene_type"), "location": props.get("location"), "series_id": props.get("series_id"), "status": node["status"]})
        if len(out) >= limit:
            break
    return out


def shared_attributes(graph, case_ids):
    seen = {}
    for case_id in case_ids:
        for node, edge in graph.neighbors(case_id):
            if node["type"] in ATTRIBUTE_RELS:
                entry = seen.setdefault(node["id"], {"id": node["id"], "type": node["type"], "label": node["label"], "cases": [], "edge_ids": []})
                entry["cases"].append(case_id)
                entry["edge_ids"].append(edge["id"])
    return [v for v in seen.values() if len(set(v["cases"])) >= 2]


def neighbors(graph, node_id, depth=1):
    frontier = {node_id}
    visited = {node_id}
    nodes, edges = [], []
    for _ in range(max(1, depth)):
        next_frontier = set()
        for nid in frontier:
            for node, edge in graph.neighbors(nid):
                if edge["id"] not in {e["id"] for e in edges}:
                    edges.append(edge)
                if node["id"] not in visited:
                    visited.add(node["id"])
                    nodes.append(node)
                    next_frontier.add(node["id"])
        frontier = next_frontier
    return {"nodes": nodes, "edges": edges}


def cluster_candidates(graph, case_id, window_days=120, same_city=True, limit=10):
    target = graph.nodes.get(case_id)
    if target is None:
        return []
    t_attrs = case_attributes(graph, case_id)
    t_methods = {a["node"]["id"]: a["edge"]["id"] for a in t_attrs["method"]}
    t_vehicles = {a["node"]["id"]: a["edge"]["id"] for a in t_attrs["vehicle"]}
    t_items = {a["node"]["id"]: a["edge"]["id"] for a in t_attrs["item"]}
    t_locs = {a["node"]["id"]: a["edge"]["id"] for a in t_attrs["location"]}
    t_city = next((a["node"]["props"].get("city", "").lower() for a in t_attrs["location"]), "")
    t_hood = next((a["node"]["props"].get("neighborhood", "").lower() for a in t_attrs["location"]), "")
    t_day = parse_date(target["props"].get("date"))
    t_scene = target["props"].get("scene_type")
    results = []
    for node in graph.nodes_of_type("case"):
        if node["id"] == case_id or node["status"] == "new":
            continue
        attrs = case_attributes(graph, node["id"])
        city = next((a["node"]["props"].get("city", "").lower() for a in attrs["location"]), "")
        if same_city and t_city and city != t_city:
            continue
        score = 0
        matched = []
        cited = []
        for a in attrs["method"]:
            if a["node"]["id"] in t_methods:
                score += SCORE_WEIGHTS["method"]
                matched.append({"kind": "method", "label": a["node"]["label"]})
                cited += [t_methods[a["node"]["id"]], a["edge"]["id"]]
        for a in attrs["vehicle"]:
            if a["node"]["id"] in t_vehicles:
                score += SCORE_WEIGHTS["vehicle"]
                matched.append({"kind": "vehicle", "label": a["node"]["label"]})
                cited += [t_vehicles[a["node"]["id"]], a["edge"]["id"]]
        hood = next((a["node"]["props"].get("neighborhood", "").lower() for a in attrs["location"]), "")
        if t_city and city == t_city:
            score += SCORE_WEIGHTS["city"]
            matched.append({"kind": "city", "label": city.title()})
            for a in attrs["location"]:
                if a["node"]["id"] in t_locs:
                    cited += [t_locs[a["node"]["id"]], a["edge"]["id"]]
            if t_hood and hood == t_hood:
                score += SCORE_WEIGHTS["neighborhood"]
                matched.append({"kind": "neighborhood", "label": hood.title()})
        day = parse_date(node["props"].get("date"))
        if t_day and day:
            gap = abs((day - t_day).days)
            if gap <= 14:
                score += SCORE_WEIGHTS["within_14_days"]
                matched.append({"kind": "time", "label": f"{gap} days apart"})
            elif gap <= window_days:
                score += SCORE_WEIGHTS["within_window"]
                matched.append({"kind": "time", "label": f"{gap} days apart"})
        if t_scene and node["props"].get("scene_type") == t_scene:
            score += SCORE_WEIGHTS["scene_type"]
            matched.append({"kind": "scene_type", "label": t_scene})
        item_hits = [a for a in attrs["item"] if a["node"]["id"] in t_items]
        if item_hits:
            score += SCORE_WEIGHTS["item"]
            matched.append({"kind": "item", "label": ", ".join(a["node"]["label"] for a in item_hits)})
            for a in item_hits:
                cited += [t_items[a["node"]["id"]], a["edge"]["id"]]
        if score <= 0:
            continue
        series = case_series(graph, node["id"])
        results.append({
            "case_id": node["id"],
            "label": node["label"],
            "date": node["props"].get("date"),
            "location": node["props"].get("location"),
            "scene_type": node["props"].get("scene_type"),
            "series_id": series["id"] if series else None,
            "series_label": series["label"] if series else None,
            "score": score,
            "matched": matched,
            "cited_edge_ids": sorted(set(cited)),
        })
    results.sort(key=lambda r: (-r["score"], r["case_id"]))
    return results[:limit]


def missing_evidence(graph, case_id):
    node = graph.nodes.get(case_id)
    if node is None:
        return {"unknowns": [], "absent": []}
    attrs = case_attributes(graph, case_id)
    absent = [t for t, items in attrs.items() if not items]
    return {"unknowns": node["props"].get("unknowns") or [], "absent": absent}


class HypothesisError(ValueError):
    pass


def attribute_targets(graph, case_id):
    rels = set(ATTRIBUTE_RELS.values())
    return {e["target"] for e in graph.edges_of(case_id) if e["source"] == case_id and e["rel"] in rels}


def propose_hypothesis(graph, case_id, linked_case_ids, rationale, cited_edge_ids, confidence, run_id, fallback=False):
    involved = [case_id, *[c for c in linked_case_ids if c != case_id]]
    for cid in involved:
        if cid not in graph.nodes or graph.nodes[cid]["type"] != "case":
            raise HypothesisError(f"unknown case {cid}")
    if len(involved) < 2:
        raise HypothesisError("a hypothesis needs at least two cases")
    if not cited_edge_ids:
        raise HypothesisError("a hypothesis must cite at least one edge")
    attribute_rels = set(ATTRIBUTE_RELS.values())
    cited_nodes = set()
    for eid in cited_edge_ids:
        edge = graph.edges.get(eid)
        if edge is None:
            raise HypothesisError(f"cited edge does not exist: {eid}")
        if edge["rel"] not in attribute_rels or edge["source"] not in involved:
            raise HypothesisError(f"cited edge is not an attribute edge of the cases: {eid}")
        cited_nodes.add(edge["target"])
    own_nodes = attribute_targets(graph, case_id)
    for linked in involved[1:]:
        if not cited_nodes & own_nodes & attribute_targets(graph, linked):
            raise HypothesisError(f"cited edges show no attribute shared by {case_id} and {linked}")
    confidence = max(0.0, min(1.0, float(confidence)))
    number = graph.next_id("hypothesis")
    hyp_id = f"hyp:H-{number:04d}"
    node = graph.add_node(hyp_id, "hypothesis", f"H-{number:04d}", status="proposed", props={
        "run_id": run_id,
        "case_ids": involved,
        "confidence": confidence,
        "rationale": rationale,
        "cited_edge_ids": list(cited_edge_ids),
        "fallback": fallback,
        "critic": None,
        "decision": None,
        "decision_reason": None,
    }, sources=[f"run:{run_id}"])
    edges = []
    for cid in involved:
        edges.append(graph.add_edge(hyp_id, cid, "PROPOSES_LINK", kind="hypothesis", confidence=confidence, provenance=f"run:{run_id}"))
    supported = set()
    for eid in cited_edge_ids:
        edge = graph.edges[eid]
        other = edge["target"] if edge["source"] in involved else edge["source"]
        if graph.nodes[other]["type"] in ATTRIBUTE_RELS and other not in supported:
            supported.add(other)
            edges.append(graph.add_edge(hyp_id, other, "SUPPORTED_BY", kind="hypothesis", confidence=confidence,
                                        provenance=edge["provenance"], cites=[eid]))
    return {"hypothesis": node, "nodes": [node], "edges": edges}


def record_decision(graph, hyp_id, decision, reason):
    node = graph.nodes.get(hyp_id)
    if node is None or node["type"] != "hypothesis":
        raise HypothesisError(f"unknown hypothesis {hyp_id}")
    if decision not in ("accept", "reject", "more"):
        raise HypothesisError(f"unknown decision {decision}")
    if node["props"].get("decision") in ("accept", "reject"):
        raise HypothesisError(f"{hyp_id} was already decided: {node['props']['decision']}")
    node["props"]["decision"] = decision
    node["props"]["decision_reason"] = reason
    delta_nodes = [node]
    delta_edges = []
    if decision == "reject":
        graph.set_status(hyp_id, "rejected")
        for e in graph.edges_of(hyp_id):
            delta_edges.append(e)
        return {"nodes": delta_nodes, "edges": delta_edges}
    if decision == "more":
        return {"nodes": delta_nodes, "edges": delta_edges}
    graph.set_status(hyp_id, "confirmed")
    for e in graph.edges_of(hyp_id):
        delta_edges.append(graph.set_edge_kind(e["id"], "confirmed"))
    case_ids = node["props"]["case_ids"]
    series = next((s for s in (case_series(graph, c) for c in case_ids) if s), None)
    if series is None:
        number = graph.next_id("series")
        series = graph.add_node(f"series:S-{number:03d}", "series", f"Series S-{number:03d}", status="confirmed", props={"ground_truth": "detective_confirmed", "created_from": hyp_id}, sources=[f"decision:{hyp_id}"])
        delta_nodes.append(series)
    for cid in case_ids:
        if case_series(graph, cid) is None:
            delta_edges.append(graph.add_edge(cid, series["id"], "PART_OF_SERIES", kind="confirmed", provenance=f"decision:{hyp_id}"))
        if graph.nodes[cid]["status"] == "new":
            delta_nodes.append(graph.set_status(cid, "confirmed"))
    return {"nodes": delta_nodes, "edges": delta_edges, "series": series}
