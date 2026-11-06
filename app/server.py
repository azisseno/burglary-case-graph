import asyncio
import json
import re
import shutil
import statistics
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agents, extract, seed, tools
from .cli import CliError
from .store import Graph

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_BASE = "http://127.0.0.1:8000"
KEEPALIVE_SECONDS = 15
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


def summarize_tool_result(name, result):
    if isinstance(result, list):
        return f"{len(result)} results"
    if isinstance(result, dict):
        if name == "propose_hypothesis":
            return f"proposed {result['hypothesis']['id']}"
        return ", ".join(f"{k}: {len(v)}" for k, v in result.items() if isinstance(v, (list, dict))) or "ok"
    return "ok"


class Pipeline:
    def __init__(self, graph, runs_dir, cases_dir, demo_dir, api_base):
        self.graph = graph
        self.runs_dir = Path(runs_dir)
        self.cases_dir = Path(cases_dir)
        self.demo_dir = Path(demo_dir)
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

    def start_run(self, files, label, overrides):
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        number = self.graph.next_id("case")
        case_label = f"NEW-{number:03d}"
        run_dir = self.runs_dir / run_id
        upload_dir = run_dir / "uploads"
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
        case_id = case_node_id(case_label)
        self.spawn(self.run, run_id, case_id, case_label, label or case_label, saved, overrides)
        return {"run_id": run_id, "case_id": case_id}

    def run(self, run_id, case_id, case_label, label, files, overrides):
        started = time.monotonic()
        run_dir = self.runs_dir / run_id
        count = 0
        try:
            self.event("run.started", run_id, "intake", f"Run started for {label}: {len(files)} files, case id {case_label}",
                       {"case_id": case_id, "label": label, "file_count": len(files)})
            images, texts = self.intake(run_id, files)
            observations = self.observe(run_id, run_dir, images)
            text_file, text_record = self.extract(run_id, run_dir, texts)
            self.build(run_id, case_id, case_label, files, text_file, text_record, observations, overrides)
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

    def report_error(self, run_id, agent, step, label, error):
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "errors.log").open("a") as handle:
            handle.write(f"{step}: {error!r}\n")
        self.event("run.error", run_id, agent, f"{label} failed",
                   {"step": step, "message": f"{label} failed; details are in runs/{run_id}/errors.log"})

    def finish_case(self, case_id):
        node = self.graph.nodes.get(case_id)
        if node is not None and node["status"] == "new":
            return [self.graph.set_status(case_id, "existing")]
        return []

    def intake(self, run_id, files):
        images, texts = [], []
        for path in files:
            kind = file_kind(path)
            size = path.stat().st_size
            if kind is None:
                self.event("run.error", run_id, "intake", f"{path.name} has an unsupported type and was skipped",
                           {"step": "intake", "message": f"unsupported file type {path.suffix}"})
                continue
            self.event("intake.file", run_id, "intake", f"{path.name} sorted as {kind}, {size_text(size)}",
                       {"name": path.name, "kind": kind, "size": size})
            (images if kind == "image" else texts).append(path)
        return images, texts

    def observe(self, run_id, run_dir, images):
        results = []
        for path in images:
            try:
                result = extract.observe_photo(path, run_dir, f"observe_{path.name}")
            except CliError as error:
                self.report_error(run_id, "photo_observer", "observe", f"Reading {path.name}", error)
                continue
            results.append(result)
            self.event("observe.photo", run_id, "photo_observer",
                       f"{path.name}: {len(result['observations'])} observations", result)
        return results

    def extract(self, run_id, run_dir, texts):
        if not texts:
            return None, None
        chunks = []
        for path in texts:
            try:
                chunks.append(f"--- {path.name} ---\n{extract.read_text_file(path)}")
            except Exception as error:
                self.report_error(run_id, "record_extractor", "extract", f"Reading {path.name}", error)
        if not chunks:
            return None, None
        text_file = texts[0].name
        try:
            record = extract.extract_record("\n\n".join(chunks), run_dir, "extract")
        except CliError as error:
            self.report_error(run_id, "record_extractor", "extract", "Extraction", error)
            return text_file, None
        self.event("extract.text", run_id, "record_extractor", f"Record extracted from {text_file}",
                   {"file": text_file, "record": record})
        return text_file, record

    def build(self, run_id, case_id, case_label, files, text_file, text_record, observations, overrides):
        record = merge_record(case_label, text_file, text_record, observations, overrides)
        provenance = text_file or (files[0].name if files else "upload")
        record["media"] = [{"path": f.name, "kind": file_kind(f) or "other"} for f in files if file_kind(f)]
        delta = seed.add_case(self.graph, record, status="new", default_provenance=provenance)
        node = self.graph.nodes[case_id]
        node["props"]["run_id"] = run_id
        node["sources"] = [f.name for f in files]
        self.event("build.nodes", run_id, "builder",
                   f"{len(delta['nodes'])} nodes, {len(delta['edges'])} edges written for {case_label}",
                   {"nodes": delta["nodes"], "edges": delta["edges"]})
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
        cases = [tools.get_case(self.graph, cid) for cid in hypothesis["props"]["case_ids"]]
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
        if decision == "accept":
            self.spawn(self.find_gaps, hyp_id)
        return {"nodes": nodes, "edges": delta["edges"]}

    def find_gaps(self, hyp_id):
        hypothesis = self.graph.nodes[hyp_id]
        run_id = hypothesis["props"]["run_id"]
        cases = [tools.get_case(self.graph, cid) for cid in hypothesis["props"]["case_ids"]]
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
    graph = seed.build_graph(cases_dir)
    graph.save(graph_path)
    return graph


def create_app(root=ROOT, graph=None, api_base=DEFAULT_API_BASE, runs_dir=None):
    root = Path(root)
    runs_dir = Path(runs_dir) if runs_dir else root / "runs"
    cases_dir = root / "data" / "cases"
    demo_dir = root / "data" / "demo-inputs"
    web_dir = ROOT / "web"
    pipeline = Pipeline(graph or load_graph(runs_dir, cases_dir), runs_dir, cases_dir, demo_dir, api_base)

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
            if props.get("run_id"):
                url = f"/api/uploads/{props['run_id']}/{name}"
            else:
                url = f"/api/media/{props.get('series_id')}/{incident}/{name}"
            entries.append({"path": item["path"], "kind": item.get("kind"), "url": url})
        return entries

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        detail = tools.get_case(pipeline.graph, case_node_id(case_id))
        if detail is None:
            raise HTTPException(404, f"unknown case {case_id}")
        node = detail["case"]
        return {**detail, "node": node, "media": media_entries(node), "sources": list(node["sources"])}

    def inside(base, candidate):
        resolved = candidate.resolve()
        return resolved.is_file() and resolved.is_relative_to(base.resolve())

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

    @app.post("/api/cases")
    def post_case(files: list[UploadFile] = File(alias="files[]"), label: str | None = Form(None),
                  date: str | None = Form(None), location: str | None = Form(None),
                  scene_type: str | None = Form(None)):
        if not files:
            raise HTTPException(400, "no files")
        sources = [(f.filename, f.file) for f in files]
        overrides = {"date": date, "location": location, "scene_type": scene_type}
        return pipeline.start_run(sources, label, overrides)

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
        return pipeline.start_run(sources, name, {})

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
