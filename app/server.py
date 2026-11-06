import asyncio
import json
import os
import re
import shutil
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import agents, extract, finder, scoring, scrub, seed, tools
from .cli import CliError
from .store import Graph

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_BASE = "http://127.0.0.1:8000"
KEEPALIVE_SECONDS = 15
BULK_WORKERS = 6
BULK_EXTRACT_MODEL = "haiku"
RUNS_ENV = "CASE_GRAPH_RUNS"
API_ENV = "CASE_GRAPH_API"
SEED_ENV = "CASE_GRAPH_SEED"
FULL_SEED = "full"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
TEXT_SUFFIXES = {".txt", ".md"}
DOCUMENT_SUFFIXES = {".pdf", ".docx"}
MEDIA_FOLDERS = ("photos", "documents", "audio", "")
IMAGE_ENTRY_TYPES = {"entry_damage", "forced_entry"}
TOOL_PARAMETERS = {
    "find_cases": ("city", "method", "scene_type", "date_from", "date_to", "series_id", "limit"),
    "get_case": ("case_id",),
    "shared_attributes": ("case_ids",),
    "neighbors": ("node_id", "depth"),
    "cluster_candidates": ("case_id", "window_days", "same_city"),
    "missing_evidence": ("case_id",),
    "propose_hypothesis": ("case_id", "linked_case_ids", "rationale", "cited_edge_ids", "confidence"),
}
TOOL_NAMES = tuple(TOOL_PARAMETERS)
UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")
CASE_PREFIX = "case:"
FAST_REPORT_NAME = "report.txt"
DEMO_SOURCE_IDS_FILE = "source_ids.json"


def file_kind(path):
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in DOCUMENT_SUFFIXES:
        return "document"
    return None


def safe_name(name):
    cleaned = UNSAFE_NAME_CHARS.sub("_", Path((name or "").replace("\\", "/")).name).lstrip(".")
    return cleaned or "upload"


def unique_name(name, taken):
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    candidate, number = name, 1
    while candidate in taken:
        number += 1
        candidate = f"{stem}-{number}{dot}{suffix}"
    taken.add(candidate)
    return candidate


def case_node_id(case_id):
    return case_id if case_id.startswith(CASE_PREFIX) else f"{CASE_PREFIX}{case_id}"


def with_case(data, case_id, upload_dir=None):
    if not case_id:
        return data
    data = {**data, "case_id": case_id}
    return {**data, "upload_dir": upload_dir} if upload_dir else data


def size_text(size):
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"


def merge_record(label, text_file, text_record, observations, overrides):
    record = dict(text_record or {})
    evidence = [
        {"type": e.get("type", "other"), "description": e.get("description", ""), "provenance": text_file}
        for e in record.get("evidence") or []
    ]
    for photo in observations:
        for obs in photo["observations"]:
            if obs["type"] == "vehicle":
                evidence.append({"type": "vehicle", "description": obs["description"], "provenance": photo["file"]})
            elif obs["type"] in IMAGE_ENTRY_TYPES:
                evidence.append({"type": obs["type"], "description": obs["description"], "provenance": photo["file"]})
    merged = {
        "id": label,
        "label": label,
        "series_id": None,
        "date": record.get("date"),
        "date_precision": record.get("date_precision") or ("day" if record.get("date") else "unknown"),
        "time": record.get("time"),
        "location": record.get("location"),
        "neighborhood": record.get("neighborhood"),
        "scene_type": record.get("scene_type"),
        "entry_method": record.get("entry_method"),
        "items_taken": record.get("items_taken") or [],
        "vehicle": record.get("vehicle"),
        "unknowns": record.get("unknowns") or [],
        "evidence": evidence,
        "notes": None,
    }
    for key, value in overrides.items():
        if value:
            merged[key] = value
            if key == "date":
                merged["date_precision"] = "day"
    return merged


def report_shaped_record(raw, label):
    return {
        "id": label,
        "label": label,
        "series_id": None,
        "date": raw.get("date"),
        "date_precision": raw.get("date_precision") or ("day" if raw.get("date") else "unknown"),
        "time": raw.get("time"),
        "location": raw.get("location"),
        "neighborhood": raw.get("neighborhood"),
        "scene_type": raw.get("scene_type"),
        "entry_method": raw.get("entry_method"),
        "items_taken": raw.get("items_taken") or [],
        "vehicle": raw.get("vehicle"),
        "unknowns": [u for u in raw.get("unknowns") or [] if not scrub.UNKNOWN_DROP.search(u)],
        "evidence": [{"type": e.get("type", "other"), "description": scrub.scrub(e.get("description", "")),
                      "provenance": FAST_REPORT_NAME} for e in raw.get("evidence") or []],
        "notes": None,
        "media": [],
    }


def demo_source_ids(demo_dir):
    path = Path(demo_dir) / DEMO_SOURCE_IDS_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def summarize_tool_result(name, result):
    if isinstance(result, list):
        return f"{len(result)} results"
    if isinstance(result, dict):
        if name == "propose_hypothesis":
            return f"proposed {result['hypothesis']['id']}"
        return ", ".join(f"{k}: {len(v)}" for k, v in result.items() if isinstance(v, (list, dict))) or "ok"
    return "ok"


class Pipeline:
    def __init__(self, graph, runs_dir, cases_dir, demo_dir, api_base, folders_dir=None):
        self.graph = graph
        self.runs_dir = Path(runs_dir)
        self.cases_dir = Path(cases_dir)
        self.demo_dir = Path(demo_dir)
        self.folders_dir = Path(folders_dir) if folders_dir else self.demo_dir.parent / "demo-folders"
        self.api_base = api_base
        self.audit_path = self.runs_dir / "audit.jsonl"
        self.graph_path = self.runs_dir / "graph.json"
        self.subscribers = set()
        self.loop = None
        self.emit_lock = threading.Lock()
        self.threads = []
        self.linker_runs = set()
        self.announced = set()
        self.state_lock = threading.Lock()

    def emit(self, event):
        line = json.dumps(event, default=str)
        with self.emit_lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a") as handle:
                handle.write(line + "\n")
            loop = self.loop
            if loop is not None:
                for queue in list(self.subscribers):
                    loop.call_soon_threadsafe(queue.put_nowait, line)

    def event(self, event_type, run_id, agent, message, data):
        self.emit(agents.make_event(event_type, run_id, agent, message, data))

    def save(self):
        self.graph.save(self.graph_path)

    def spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        self.threads.append(thread)
        thread.start()

    def join(self, timeout=60):
        for thread in list(self.threads):
            thread.join(timeout)

    def save_uploads(self, upload_dir, files):
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        taken = set()
        for name, source in files:
            destination = upload_dir / unique_name(safe_name(name), taken)
            if isinstance(source, Path):
                shutil.copyfile(source, destination)
            else:
                with destination.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
            saved.append(destination)
        return saved

    def start_run(self, files, label, overrides, source_id=None):
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        number = self.graph.next_id("case")
        case_label = f"NEW-{number:03d}"
        saved = self.save_uploads(self.runs_dir / run_id / "uploads", files)
        case_id = case_node_id(case_label)
        self.spawn(self.run, run_id, case_id, case_label, label or case_label, saved, overrides, source_id)
        return {"run_id": run_id, "case_id": case_id}

    def record_index(self):
        if not hasattr(self, "_record_index"):
            self._record_index = {path.parent.name: path for path in sorted(self.cases_dir.glob("*/*/record.json"))}
        return self._record_index

    def start_bulk(self, label, incidents, fast=False):
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        jobs = []
        for index, (incident_id, files) in enumerate(incidents, 1):
            case_label = f"NEW-{self.graph.next_id('case'):03d}"
            saved = [] if fast else self.save_uploads(self.runs_dir / run_id / "uploads" / case_label, files)
            jobs.append({"index": index, "source_id": incident_id, "label": case_label,
                         "case_id": case_node_id(case_label), "files": saved})
        self.spawn(self.run_bulk, run_id, label, jobs, fast)
        return {"run_id": run_id, "total": len(jobs), "fast": fast,
                "cases": [{"case_id": j["case_id"], "label": j["label"], "source_id": j["source_id"]} for j in jobs]}

    def run_bulk(self, run_id, label, jobs, fast):
        started = time.monotonic()
        total = len(jobs)
        mode = "fast import from record.json, Claude extraction skipped" if fast else "Claude extraction"
        self.event("run.started", run_id, "intake", f"Bulk run started for {label}: {total} cases, {mode}",
                   {"label": label, "total": total, "fast": fast, "bulk": True, "case_ids": [j["case_id"] for j in jobs]})
        hypotheses = 0
        try:
            with ThreadPoolExecutor(BULK_WORKERS) as pool:
                list(pool.map(lambda job: self.run_bulk_case(run_id, job, total, fast), jobs))
            hypotheses = finder.run_finder(self, run_id)
        except Exception as error:
            self.report_error(run_id, "finder", "bulk", "Bulk run", error)
        finally:
            self.save()
            seconds = round(time.monotonic() - started, 1)
            self.event("run.finished", run_id, "intake", f"Bulk run finished in {seconds}s: {total} cases, {hypotheses} hypotheses",
                       {"seconds": seconds, "cases": total, "hypotheses": hypotheses, "nodes": [], "bulk": True})

    def run_bulk_case(self, run_id, job, total, fast):
        case_id, case_label, index = job["case_id"], job["label"], job["index"]
        case_dir = self.runs_dir / run_id / case_label
        self.event("run.case_started", run_id, "intake", f"Case {index} of {total}: {case_label}",
                   {"case_id": case_id, "label": case_label, "source_id": job["source_id"], "index": index, "total": total,
                    "file_count": len(job["files"]), "fast": fast})
        try:
            if fast:
                self.build_fast(run_id, job)
            else:
                images, texts = self.intake(run_id, job["files"], case_id, case_label)
                observations = self.observe(run_id, case_dir, images, case_id, case_label)
                text_file, text_record = self.extract(run_id, case_dir, texts, case_id, BULK_EXTRACT_MODEL)
                self.build(run_id, case_id, case_label, job["files"], text_file, text_record, observations, {},
                           source_id=job["source_id"], upload_dir=case_label)
        except Exception as error:
            self.report_error(run_id, "intake", "case", f"Case {case_label}", error, case_id)
        finally:
            self.finish_bulk_case(run_id, job, total)

    def finish_bulk_case(self, run_id, job, total):
        case_id, case_label = job["case_id"], job["label"]
        try:
            nodes = self.finish_case(case_id)
            self.save()
            self.event("run.case_finished", run_id, "intake", f"Case {job['index']} of {total} finished: {case_label}",
                       {"case_id": case_id, "label": case_label, "source_id": job["source_id"], "index": job["index"],
                        "total": total, "nodes": nodes})
        except Exception as error:
            self.report_error(run_id, "intake", "case_finish", f"Finishing {case_label}", error, case_id)

    def build_fast(self, run_id, job):
        path = self.record_index().get(job["source_id"])
        if path is None:
            raise KeyError(f"no record.json for incident {job['source_id']}")
        record = report_shaped_record(json.loads(path.read_text()), job["label"])
        self.write_case(run_id, job["case_id"], job["label"], record, FAST_REPORT_NAME,
                        sources=[FAST_REPORT_NAME], source_id=job["source_id"])

    def run(self, run_id, case_id, case_label, label, files, overrides, source_id=None):
        started = time.monotonic()
        run_dir = self.runs_dir / run_id
        count = 0
        try:
            self.event("run.started", run_id, "intake", f"Run started for {label}: {len(files)} files, case id {case_label}",
                       {"case_id": case_id, "label": label, "file_count": len(files)})
            images, texts = self.intake(run_id, files)
            observations = self.observe(run_id, run_dir, images)
            text_file, text_record = self.extract(run_id, run_dir, texts)
            self.build(run_id, case_id, case_label, files, text_file, text_record, observations, overrides,
                       source_id=source_id)
            count = self.link(run_id, case_id, run_dir)
        except Exception as error:
            self.report_error(run_id, "intake", "run", "Run", error)
        finally:
            nodes = self.finish_case(case_id)
            self.save()
            seconds = round(time.monotonic() - started, 1)
            noun = "hypothesis" if count == 1 else "hypotheses"
            self.event("run.finished", run_id, "intake", f"Run finished in {seconds}s with {count} {noun}",
                       {"case_id": case_id, "seconds": seconds, "hypotheses": count, "nodes": nodes})

    def report_error(self, run_id, agent, step, label, error, case_id=None):
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "errors.log").open("a") as handle:
            handle.write(f"{step}: {error!r}\n")
        self.event("run.error", run_id, agent, f"{label} failed",
                   with_case({"step": step, "message": f"{label} failed; details are in runs/{run_id}/errors.log"}, case_id))

    def finish_case(self, case_id):
        node = self.graph.nodes.get(case_id)
        if node is not None and node["status"] == "new":
            return [self.graph.set_status(case_id, "existing")]
        return []

    def intake(self, run_id, files, case_id=None, upload_dir=None):
        images, texts = [], []
        for path in files:
            kind = file_kind(path)
            size = path.stat().st_size
            if kind is None:
                self.event("run.error", run_id, "intake", f"{path.name} has an unsupported type and was skipped",
                           with_case({"step": "intake", "message": f"unsupported file type {path.suffix}"}, case_id))
                continue
            self.event("intake.file", run_id, "intake", f"{path.name} sorted as {kind}, {size_text(size)}",
                       with_case({"name": path.name, "kind": kind, "size": size}, case_id, upload_dir))
            (images if kind == "image" else texts).append(path)
        return images, texts

    def observe(self, run_id, run_dir, images, case_id=None, upload_dir=None):
        results = []
        for path in images:
            try:
                result = extract.observe_photo(path, run_dir, f"observe_{path.name}")
            except CliError as error:
                self.report_error(run_id, "photo_observer", "observe", f"Reading {path.name}", error, case_id)
                continue
            results.append(result)
            self.event("observe.photo", run_id, "photo_observer",
                       f"{path.name}: {len(result['observations'])} observations", with_case(result, case_id, upload_dir))
        return results

    def extract(self, run_id, run_dir, texts, case_id=None, model=None):
        if not texts:
            return None, None
        chunks = []
        for path in texts:
            try:
                chunks.append(f"--- {path.name} ---\n{extract.read_text_file(path)}")
            except Exception as error:
                self.report_error(run_id, "record_extractor", "extract", f"Reading {path.name}", error, case_id)
        if not chunks:
            return None, None
        text_file = texts[0].name
        try:
            extra = {"model": model} if model else {}
            record = extract.extract_record("\n\n".join(chunks), run_dir, "extract", **extra)
        except CliError as error:
            self.report_error(run_id, "record_extractor", "extract", "Extraction", error, case_id)
            return text_file, None
        self.event("extract.text", run_id, "record_extractor", f"Record extracted from {text_file}",
                   with_case({"file": text_file, "record": record}, case_id))
        return text_file, record

    def build(self, run_id, case_id, case_label, files, text_file, text_record, observations, overrides,
              source_id=None, upload_dir=None):
        record = merge_record(case_label, text_file, text_record, observations, overrides)
        provenance = text_file or (files[0].name if files else "upload")
        record["media"] = [{"path": f.name, "kind": file_kind(f) or "other"} for f in files if file_kind(f)]
        self.write_case(run_id, case_id, case_label, record, provenance, [f.name for f in files], source_id, upload_dir)

    def write_case(self, run_id, case_id, case_label, record, provenance, sources, source_id=None, upload_dir=None):
        with self.graph.lock:
            delta = seed.add_case(self.graph, record, status="new", default_provenance=provenance)
            node = self.graph.nodes[case_id]
            node["props"]["run_id"] = run_id
            if source_id:
                node["props"]["source_id"] = source_id
            if upload_dir:
                node["props"]["upload_dir"] = upload_dir
            if sources is not None:
                node["sources"] = sources
        self.event("build.nodes", run_id, "builder",
                   f"{len(delta['nodes'])} nodes, {len(delta['edges'])} edges written for {case_label}",
                   {"nodes": delta["nodes"], "edges": delta["edges"], "case_id": case_id})
        self.save()

    def run_hypotheses(self, run_id):
        return [n for n in self.graph.nodes_of_type("hypothesis") if n["props"].get("run_id") == run_id]

    def link(self, run_id, case_id, run_dir):
        linker_failed = False
        with self.state_lock:
            self.linker_runs.add(run_id)
        try:
            agents.run_linker(self.api_base, case_id, run_id, run_dir, self.emit, graph=self.graph)
        except CliError as error:
            linker_failed = True
            self.report_error(run_id, "linker", "linker", "Linker", error)
        finally:
            with self.state_lock:
                self.linker_runs.discard(run_id)
        self.announce(run_id)
        if linker_failed and not self.run_hypotheses(run_id):
            self.fallback(run_id, case_id)
        hypotheses = self.run_hypotheses(run_id)
        for hypothesis in hypotheses:
            self.save()
            self.critique(run_id, hypothesis, run_dir)
        self.save()
        return len(hypotheses)

    def emit_score(self, run_id):
        result = scoring.score(self.graph, self.cases_dir)
        agreeing = f"{result['proposed_agreeing']} of {result['proposed_total']}"
        self.event("score.updated", run_id, "scorer", f"Agrees with public record: {agreeing} proposed series", result)
        return result

    def announce(self, run_id):
        for hypothesis in self.run_hypotheses(run_id):
            with self.state_lock:
                if hypothesis["id"] in self.announced:
                    continue
                self.announced.add(hypothesis["id"])
            props = hypothesis["props"]
            edges = self.graph.edges_of(hypothesis["id"])
            data = {"hypothesis": hypothesis, "edges": edges, "rationale": props["rationale"],
                    "confidence": props["confidence"]}
            if props.get("fallback"):
                data["fallback"] = True
            self.event("link.hypothesis", run_id, "linker", props["rationale"], data)

    def fallback(self, run_id, case_id):
        try:
            agents.run_linker_fallback(self.graph, case_id, run_id)
        except (tools.HypothesisError, KeyError) as error:
            self.report_error(run_id, "linker", "linker_fallback", "Fallback", error)
            return
        self.announce(run_id)

    def critique(self, run_id, hypothesis, run_dir):
        cases = [tools.case_brief(self.graph, cid) for cid in hypothesis["props"]["case_ids"]]
        try:
            verdict = agents.run_critic(hypothesis, cases, run_dir)
        except CliError as error:
            self.report_error(run_id, "critic", "critic", f"Critic for {hypothesis['id']}", error)
            return
        hypothesis["props"]["critic"] = verdict
        self.event("critic.verdict", run_id, "critic", f"{hypothesis['id']}: {verdict['verdict']}",
                   {"hypothesis_id": hypothesis["id"], **verdict})

    def decide(self, hyp_id, decision, reason):
        delta = tools.record_decision(self.graph, hyp_id, decision, reason)
        hypothesis = self.graph.nodes[hyp_id]
        run_id = hypothesis["props"]["run_id"]
        nodes = list(delta["nodes"])
        if decision == "reject":
            for case_id in hypothesis["props"]["case_ids"]:
                case = self.graph.nodes[case_id]
                if case["status"] == "new":
                    nodes.append(self.graph.set_status(case_id, "existing"))
        self.event("decision.recorded", run_id, "detective", f"{hypothesis['label']} {decision}: {reason or 'no reason given'}",
                   {"hypothesis_id": hyp_id, "decision": decision, "reason": reason, "nodes": nodes, "edges": delta["edges"]})
        self.save()
        self.emit_score(run_id)
        if decision == "accept":
            self.spawn(self.find_gaps, hyp_id)
        return {"nodes": nodes, "edges": delta["edges"]}

    def find_gaps(self, hyp_id):
        hypothesis = self.graph.nodes[hyp_id]
        run_id = hypothesis["props"]["run_id"]
        cases = [tools.case_brief(self.graph, cid) for cid in hypothesis["props"]["case_ids"]]
        try:
            result = agents.run_gap_finder(cases, hypothesis, self.runs_dir / run_id)
        except CliError as error:
            self.report_error(run_id, "gap_finder", "gap_finder", "Gap finder", error)
            return
        self.event("gap.next_steps", run_id, "gap_finder", f"{len(result['next_steps'])} next steps for {hypothesis['label']}",
                   {"hypothesis_id": hyp_id, **result})

    def call_tool(self, name, body):
        graph = self.graph
        arguments = {key: body[key] for key in TOOL_PARAMETERS[name] if key in body}
        if name == "propose_hypothesis":
            arguments["run_id"] = body["run_id"] if body.get("run_id") in self.linker_runs else "adhoc"
        result = getattr(tools, name)(graph, **arguments)
        if name == "propose_hypothesis":
            self.save()
        return result

    def audit_entries(self):
        if not self.audit_path.exists():
            return []
        entries = []
        for line in self.audit_path.read_text().splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries

    def metrics(self, entries):
        started, first_proposal = {}, {}
        proposed = accepted = rejected = 0
        for entry in entries:
            kind = entry["type"]
            if kind == "run.started":
                started[entry["run_id"]] = datetime.fromisoformat(entry["ts"])
            elif kind == "link.hypothesis":
                proposed += 1
                first_proposal.setdefault(entry["run_id"], datetime.fromisoformat(entry["ts"]))
            elif kind == "decision.recorded":
                accepted += entry["data"]["decision"] == "accept"
                rejected += entry["data"]["decision"] == "reject"
        gaps = [(first_proposal[r] - started[r]).total_seconds() for r in first_proposal if r in started]
        return {
            "cases_added": sum(1 for e in entries if e["type"] == "build.nodes"),
            "hypotheses_proposed": proposed,
            "accepted": accepted,
            "rejected": rejected,
            "median_seconds_to_proposal": round(statistics.median(gaps), 1) if gaps else 0,
        }


def load_graph(runs_dir, cases_dir):
    graph_path = Path(runs_dir) / "graph.json"
    if graph_path.exists():
        return Graph.load(graph_path)
    if os.environ.get(SEED_ENV) != FULL_SEED:
        return Graph()
    graph = seed.build_graph(cases_dir)
    graph.save(graph_path)
    return graph


def create_app(root=ROOT, graph=None, api_base=None, runs_dir=None):
    api_base = api_base or os.environ.get(API_ENV) or DEFAULT_API_BASE
    root = Path(root)
    runs_dir = Path(runs_dir or os.environ.get(RUNS_ENV) or root / "runs")
    cases_dir = root / "data" / "cases"
    demo_dir = root / "data" / "demo-inputs"
    folders_dir = root / "data" / "demo-folders"
    web_dir = ROOT / "web"
    pipeline = Pipeline(graph if graph is not None else load_graph(runs_dir, cases_dir), runs_dir, cases_dir, demo_dir, api_base, folders_dir)

    @asynccontextmanager
    async def lifespan(app):
        pipeline.loop = asyncio.get_running_loop()
        yield
        pipeline.loop = None

    app = FastAPI(lifespan=lifespan)
    app.state.pipeline = pipeline

    @app.get("/")
    def index():
        return FileResponse(web_dir / "index.html")

    @app.get("/styles.css")
    def styles():
        return FileResponse(web_dir / "styles.css")

    @app.get("/app.js")
    def script():
        return FileResponse(web_dir / "app.js", media_type="text/javascript")

    @app.get("/api/graph")
    def get_graph():
        return pipeline.graph.to_dict()

    def media_entries(node):
        props = node["props"]
        incident = node["id"].removeprefix(CASE_PREFIX)
        entries = []
        for item in props.get("media") or []:
            name = Path(item["path"]).name
            if props.get("run_id") and props.get("upload_dir"):
                url = f"/api/uploads/{props['run_id']}/{props['upload_dir']}/{name}"
            elif props.get("run_id"):
                url = f"/api/uploads/{props['run_id']}/{name}"
            else:
                url = f"/api/media/{props.get('series_id')}/{incident}/{name}"
            entries.append({"path": item["path"], "kind": item.get("kind"), "url": url})
        return entries

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        detail = tools.get_case(pipeline.graph, case_node_id(case_id), redact=False)
        if detail is None:
            raise HTTPException(404, f"unknown case {case_id}")
        node = detail["case"]
        return {**detail, "node": node, "media": media_entries(node), "sources": list(node["sources"])}

    def inside(base, candidate):
        resolved = candidate.resolve()
        return resolved.is_file() and resolved.is_relative_to(base.resolve())

    @app.get("/api/media/{series}/_series/{file}")
    def get_series_media(series: str, file: str):
        candidate = cases_dir / series / "photos" / file
        if not inside(cases_dir, candidate):
            raise HTTPException(404, "media not found")
        return FileResponse(candidate)

    @app.get("/api/media/{series}/{incident}/{file}")
    def get_media(series: str, incident: str, file: str):
        series_dir = cases_dir / series
        incident_dir = series_dir / incident.removeprefix(CASE_PREFIX)
        for base in (incident_dir, series_dir):
            for folder in MEDIA_FOLDERS:
                candidate = base / folder / file
                if inside(cases_dir, candidate):
                    return FileResponse(candidate)
        raise HTTPException(404, "media not found")

    @app.get("/api/uploads/{run_id}/{file}")
    def get_upload(run_id: str, file: str):
        candidate = runs_dir / run_id / "uploads" / file
        if not inside(runs_dir, candidate):
            raise HTTPException(404, "upload not found")
        return FileResponse(candidate)

    @app.get("/api/uploads/{run_id}/{case}/{file}")
    def get_case_upload(run_id: str, case: str, file: str):
        candidate = runs_dir / run_id / "uploads" / case / file
        if not inside(runs_dir, candidate):
            raise HTTPException(404, "upload not found")
        return FileResponse(candidate)

    @app.get("/api/score")
    def get_score():
        return scoring.score(pipeline.graph, cases_dir)

    @app.post("/api/cases")
    def post_case(files: list[UploadFile] = File(alias="files[]"), label: str | None = Form(None),
                  date: str | None = Form(None), location: str | None = Form(None),
                  scene_type: str | None = Form(None)):
        if not files:
            raise HTTPException(400, "no files")
        sources = [(f.filename, f.file) for f in files]
        overrides = {"date": date, "location": location, "scene_type": scene_type}
        return pipeline.start_run(sources, label, overrides, demo_source_ids(demo_dir).get(label))

    def demo_names():
        return sorted(p.name for p in demo_dir.iterdir() if p.is_dir()) if demo_dir.exists() else []

    @app.get("/api/demo")
    def list_demos():
        return [{"name": n, "files": sorted(p.name for p in (demo_dir / n).iterdir() if p.is_file())} for n in demo_names()]

    @app.post("/api/demo/{name}")
    def post_demo(name: str):
        folder = demo_dir / name
        if name not in demo_names():
            raise HTTPException(404, f"unknown demo {name}")
        sources = [(p.name, p) for p in sorted(folder.iterdir()) if p.is_file()]
        return pipeline.start_run(sources, name, {}, demo_source_ids(demo_dir).get(name))

    def folder_names():
        return sorted(p.name for p in folders_dir.iterdir() if p.is_dir()) if folders_dir.exists() else []

    def incident_dirs(name):
        return sorted(p for p in (folders_dir / name).iterdir() if p.is_dir() and not p.name.startswith("."))

    @app.get("/api/folders")
    def list_folders():
        return [{"name": n, "incidents": [p.name for p in incident_dirs(n)]} for n in folder_names()]

    def folder_incidents(name, fast):
        if name not in folder_names():
            raise HTTPException(404, f"unknown folder {name}")
        incidents = []
        for incident in incident_dirs(name):
            files = [] if fast else [(p.name, p) for p in sorted(incident.rglob("*")) if p.is_file() and not p.name.startswith(".")]
            incidents.append((incident.name, files))
        return incidents

    def uploaded_incidents(uploads):
        groups = {}
        for upload in uploads:
            parts = [part for part in (upload.filename or "").replace("\\", "/").split("/") if part and part != ".."]
            if not parts or parts[-1].startswith("."):
                continue
            incident = parts[1] if len(parts) >= 3 else parts[0] if len(parts) == 2 else "upload"
            groups.setdefault(incident, []).append((parts[-1], upload.file))
        return sorted(groups.items())

    @app.post("/api/bulk")
    async def post_bulk(request: Request):
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
            name = body.get("folder") if isinstance(body, dict) else None
            if not isinstance(name, str):
                raise HTTPException(400, "folder is required")
            fast = bool(body.get("fast"))
            incidents = folder_incidents(name, fast)
            label = name
        else:
            form = await request.form()
            uploads = [u for key in ("files[]", "files") for u in form.getlist(key) if hasattr(u, "filename")]
            incidents = uploaded_incidents(uploads)
            first = (uploads[0].filename or "").replace("\\", "/").split("/")[0] if uploads else ""
            label = first if "/" in (uploads[0].filename if uploads else "") else "dropped files"
            fast = False
        if not incidents:
            raise HTTPException(400, "no incidents")
        return await run_in_threadpool(pipeline.start_bulk, label, incidents, fast)

    @app.get("/api/events")
    async def events():
        queue = asyncio.Queue()
        pipeline.subscribers.add(queue)

        async def stream():
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {line}\n\n"
            finally:
                pipeline.subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/hypotheses")
    def list_hypotheses():
        return list(reversed(pipeline.graph.nodes_of_type("hypothesis")))

    @app.post("/api/hypotheses/{hyp_id}/recritic")
    def recritic(hyp_id: str):
        node_id = hyp_id if hyp_id in pipeline.graph.nodes else f"hyp:{hyp_id}"
        hypothesis = pipeline.graph.nodes.get(node_id)
        if hypothesis is None or hypothesis["type"] != "hypothesis":
            raise HTTPException(404, f"unknown hypothesis {hyp_id}")
        run_id = hypothesis["props"]["run_id"]
        pipeline.critique(run_id, hypothesis, pipeline.runs_dir / run_id / "recritic")
        pipeline.save()
        return hypothesis["props"].get("critic")

    @app.post("/api/hypotheses/{hyp_id}/decision")
    def decide(hyp_id: str, body: dict = Body(...)):
        node_id = hyp_id if hyp_id in pipeline.graph.nodes else f"hyp:{hyp_id}"
        try:
            return pipeline.decide(node_id, body.get("decision"), body.get("reason") or "")
        except tools.HypothesisError as error:
            raise HTTPException(400, str(error))

    @app.get("/api/audit")
    def audit():
        entries = pipeline.audit_entries()
        return {"metrics": pipeline.metrics(entries), "entries": entries}

    @app.post("/api/tools/{name}")
    def call_tool(name: str, body: dict = Body(default_factory=dict)):
        if name not in TOOL_NAMES:
            raise HTTPException(404, f"unknown tool {name}")
        active = body.get("run_id") if body.get("run_id") in pipeline.linker_runs else None
        try:
            result = pipeline.call_tool(name, body)
        except tools.HypothesisError as error:
            if active:
                pipeline.event("link.tool_call", active, "linker", f"{name} rejected: {error}",
                               {"tool": name, "args": body, "summary": f"rejected: {error}"})
            return JSONResponse({"error": str(error)}, status_code=400)
        except TypeError as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        if result is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if active:
            summary = summarize_tool_result(name, result)
            pipeline.event("link.tool_call", active, "linker", f"{name}: {summary}",
                           {"tool": name, "args": body, "summary": summary})
        return result

    app.mount("/web", StaticFiles(directory=web_dir), name="web")
    app.mount("/mock", StaticFiles(directory=web_dir / "mock"), name="mock")
    return app


app = create_app()
