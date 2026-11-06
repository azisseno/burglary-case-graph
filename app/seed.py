import json
import os
from pathlib import Path

from . import normalize as N
from .store import Graph

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "data" / "cases"
RUNS_DIR = ROOT / "runs"
GRAPH_PATH = RUNS_DIR / "graph.json"
HELD_OUT_PATH = RUNS_DIR / "held_out.json"
HELD_OUT = ["rcg-04", "rcg-05", "scr-03"]

METHOD_EVIDENCE = {"forced_entry", "entry_damage", "safe_access", "tool", "other", "alarm", "theft", "vehicle", "footage"}


GROUND_TRUTH_LINKED = ("linked_by_police", "partly_linked")


def case_node_id(case_id):
    return f"case:{case_id}"


def add_case(graph, record, status="existing", default_provenance="record", area_hint=None):
    cid = case_node_id(record["id"])
    label = record.get("label") or record["id"].upper()
    props = {
        "series_id": record.get("series_id"),
        "date": record.get("date"),
        "date_precision": record.get("date_precision", "day" if record.get("date") else "unknown"),
        "time": record.get("time"),
        "time_precision": record.get("time_precision"),
        "scene_type": N.canonical_scene(record.get("scene_type"), record.get("notes")),
        "location": record.get("location"),
        "location_precision": record.get("location_precision"),
        "items_taken": record.get("items_taken") or [],
        "unknowns": record.get("unknowns") or [],
        "notes": record.get("notes"),
        "media": record.get("media") or [],
        "evidence": record.get("evidence") or [],
    }
    sources = sorted({e.get("source_url") for e in props["evidence"] if e.get("source_url")})
    node = graph.add_node(cid, "case", label, status=status, props=props, sources=sources)
    delta_nodes = [node]
    delta_edges = []

    def attach(node_id, node_type, label, rel, provenance, props=None):
        attr = graph.add_node(node_id, node_type, label, status="existing", props=props or {})
        if attr not in delta_nodes:
            delta_nodes.append(attr)
        delta_edges.append(graph.add_edge(cid, node_id, rel, kind="observed", provenance=provenance))

    evidence = props["evidence"]

    def provenance_of(match, fallback):
        return next((p for e in evidence if match(e) for p in (e.get("source_url"), e.get("provenance")) if p), fallback)

    method_items = [e for e in evidence if e.get("type") in METHOD_EVIDENCE]
    method_texts = [e.get("description", "") for e in method_items]
    method_texts.append(record.get("entry_method") or "")
    for key in N.canonical_method(*method_texts):
        prov = provenance_of(lambda e: e.get("type") in METHOD_EVIDENCE and key in N.canonical_method(e.get("description", "")), default_provenance)
        attach(f"method:{key}", "method", key.replace("_", " "), "USED_METHOD", prov, {"key": key})

    vehicle_texts = [e.get("description", "") for e in evidence if e.get("type") in ("vehicle", "footage", "plate_reader")]
    if record.get("vehicle"):
        vehicle_texts.insert(0, record["vehicle"])
    for text in vehicle_texts:
        key = N.canonical_vehicle(text)
        if key:
            prov = provenance_of(lambda e: e.get("description") == text, default_provenance)
            attach(f"vehicle:{key}", "vehicle", key.replace("_", " "), "VEHICLE_SEEN", prov, {"key": key})
            break

    theft_texts = [e.get("description", "") for e in evidence if e.get("type") in ("theft", "property_recovered")]
    for key in N.canonical_items(props["items_taken"], *theft_texts):
        attach(f"item:{key}", "item", key.replace("_", " "), "ITEM_TAKEN", default_provenance, {"key": key})

    loc = N.parse_location(record.get("location"), neighborhood=record.get("neighborhood"))
    if not loc["city"] and area_hint:
        loc = N.parse_location(area_hint)
    if loc["city"]:
        label_loc = f"{loc['city']}, {loc['state']}" if loc["state"] else loc["city"]
        attach(f"loc:{N.location_key(loc)}", "location", label_loc, "AT_LOCATION", default_provenance, loc)

    window = N.time_window(record.get("date"), props["date_precision"])
    if window:
        start, end = N.window_bounds(window)
        attach(f"tw:{window}", "time_window", window, "IN_WINDOW", default_provenance, {"start": start.isoformat(), "end": end.isoformat()})

    return {"nodes": delta_nodes, "edges": delta_edges}


SERIES_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}


def series_media(series_dir):
    photos_dir = series_dir / "photos"
    if not photos_dir.is_dir():
        return []
    publishers = {}
    sources = photos_dir / "sources.txt"
    if sources.exists():
        for line in sources.read_text().splitlines():
            fields = line.split("\t")
            if len(fields) >= 3 and fields[2].strip():
                publishers[fields[0].strip()] = fields[2].strip()
    files = sorted(p for p in photos_dir.iterdir() if p.suffix.lower() in SERIES_PHOTO_SUFFIXES)
    return [{"path": f"photos/{p.name}", "kind": "image", "publisher": publishers.get(p.name)} for p in files]


def load_series(series_dir):
    series = json.loads((series_dir / "series.json").read_text())
    records = []
    for record_path in sorted(series_dir.glob("*/record.json")):
        records.append(json.loads(record_path.read_text()))
    return series, records


def build_graph(cases_dir=CASES_DIR, held_out=HELD_OUT):
    graph = Graph()
    held = set(held_out)
    for series_dir in sorted(p for p in Path(cases_dir).iterdir() if p.is_dir()):
        series, records = load_series(series_dir)
        status = series.get("ground_truth", {}).get("status", "unknown")
        linked = set(series.get("ground_truth", {}).get("linked_incidents") or [])
        if status == "linked_by_police" and not linked:
            linked = {r["id"] for r in records}
        series_node = None
        if status in ("linked_by_police", "partly_linked") and linked:
            series_node = graph.add_node(f"series:{series['series_id']}", "series", series.get("label", series["series_id"]), status="existing", props={
                "ground_truth": status,
                "area": series.get("area"),
                "period": series.get("period"),
                "outcome": series.get("outcome"),
                "notes": series.get("ground_truth", {}).get("notes"),
                "media": series_media(series_dir),
            }, sources=[s.get("url") for s in series.get("sources", []) if s.get("url")])
        for record in records:
            if record["id"] in held:
                continue
            add_case(graph, record, status="existing", default_provenance=f"{series['series_id']}/{record['id']}/record.json", area_hint=series.get("area"))
            if series_node and record["id"] in linked:
                graph.add_edge(case_node_id(record["id"]), series_node["id"], "PART_OF_SERIES", kind="confirmed", provenance=series.get("sources", [{}])[0].get("url", "series.json"))
    return graph


def main():
    runs_dir = Path(os.environ.get("CASE_GRAPH_RUNS") or RUNS_DIR)
    graph = build_graph()
    graph.save(runs_dir / "graph.json")
    (runs_dir / "held_out.json").write_text(json.dumps(HELD_OUT, indent=1))
    print(json.dumps(graph.stats(), indent=1))


if __name__ == "__main__":
    main()
