import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import agents, cli, seed, server, tools
from app.cli import CliError
from app.store import Graph

PHOTO = {"observations": [
    {"type": "vehicle", "description": "Dark SUV with the door open", "confidence": 0.8},
    {"type": "entry_damage", "description": "Glass on the ground at the entrance", "confidence": 0.5},
    {"type": "footage", "description": "Exterior camera still", "confidence": 0.9},
]}
RECORD = {
    "date": "2023-09-07", "date_precision": "day", "time": None, "location": "Renton, WA",
    "scene_type": "business", "entry_method": "vehicle backed through glass storefront",
    "items_taken": [], "vehicle": "stolen black Jeep",
    "evidence": [{"type": "vehicle", "description": "Stolen black Jeep backed through the glass front"}],
    "unknowns": ["time", "items taken"],
}
CRITIC = {"verdict": "holds", "reasons": ["method and vehicle match"], "would_change_mind": ["plate mismatch"]}
GAPS = {"missing": ["plate"], "next_steps": ["pull neighbouring camera footage"]}


def envelope(payload):
    return json.dumps({"is_error": False, "result": json.dumps(payload), "total_cost_usd": 0, "duration_api_ms": 1})


def schema_of(command):
    return json.loads(command[command.index("--json-schema") + 1])["properties"]


@pytest.fixture
def fake_claude(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        properties = schema_of(command)
        if "observations" in properties:
            payload = PHOTO
        elif "entry_method" in properties:
            payload = RECORD
        elif "verdict" in properties:
            payload = CRITIC
        else:
            payload = GAPS
        return SimpleNamespace(stdout=envelope(payload), stderr="", returncode=0)

    monkeypatch.setattr(cli, "runner", fake_run)
    return calls


def fake_linker(monkeypatch):
    def run_linker(api_base, case_id, run_id, run_dir, emit, graph=None):
        candidates = tools.cluster_candidates(graph, case_id)
        emit(agents.make_event("link.candidates", run_id, "linker", "scored",
                               {"candidates": [{"case_id": c["case_id"], "score": c["score"], "matched": c["matched"]} for c in candidates]}))
        top = candidates[0]
        tools.propose_hypothesis(graph, case_id, [top["case_id"]], "same method and vehicle",
                                 top["cited_edge_ids"], 0.8, run_id)
        return "done"

    monkeypatch.setattr(agents, "run_linker", run_linker)


@pytest.fixture(scope="module")
def seeded():
    return seed.build_graph()


@pytest.fixture
def client(tmp_path, seeded, fake_claude, monkeypatch):
    fake_linker(monkeypatch)
    snapshot = tmp_path / "snapshot.json"
    seeded.save(snapshot)
    app = server.create_app(graph=Graph.load(snapshot), runs_dir=tmp_path / "runs")
    with TestClient(app) as test_client:
        yield test_client


def audit_types(client, run_id=None):
    entries = client.get("/api/audit").json()["entries"]
    return [e["type"] for e in entries if run_id is None or e["run_id"] == run_id]


def run_demo(client, name="renton-a"):
    started = client.post(f"/api/demo/{name}").json()
    client.app.state.pipeline.join()
    return started


def test_demo_list(client):
    names = [d["name"] for d in client.get("/api/demo").json()]
    assert names == ["decoy-cannabis", "renton-a", "renton-b"]


def test_demo_run_event_sequence(client):
    started = run_demo(client)
    assert started["case_id"] == "case:NEW-001"
    types = audit_types(client, started["run_id"])
    assert types == [
        "run.started", "intake.file", "intake.file", "intake.file",
        "observe.photo", "observe.photo", "extract.text", "build.nodes",
        "link.candidates", "link.hypothesis", "critic.verdict", "run.finished",
    ]
    entries = client.get("/api/audit").json()["entries"]
    finished = entries[-1]
    assert finished["data"]["hypotheses"] == 1
    build = next(e for e in entries if e["type"] == "build.nodes")
    case = next(n for n in build["data"]["nodes"] if n["type"] == "case")
    assert case["status"] == "new"
    assert case["props"]["run_id"] == started["run_id"]
    provenance = {p for e in build["data"]["edges"] for p in e["provenance"]}
    assert provenance <= {"report.txt", "still-01.jpg", "still-02.jpg"}
    assert any(e["rel"] == "VEHICLE_SEEN" for e in build["data"]["edges"])


def test_critic_stored_on_node(client):
    run_demo(client)
    hypothesis = client.get("/api/hypotheses").json()[0]
    assert hypothesis["props"]["critic"]["verdict"] == "holds"
    assert hypothesis["props"]["decision"] is None


def test_metrics_after_run(client):
    run_demo(client)
    metrics = client.get("/api/audit").json()["metrics"]
    assert metrics["cases_added"] == 1
    assert metrics["hypotheses_proposed"] == 1
    assert metrics["accepted"] == 0
    assert metrics["median_seconds_to_proposal"] >= 0


def test_graph_saved_to_disk(client):
    started = run_demo(client)
    saved = json.loads((client.app.state.pipeline.graph_path).read_text())
    assert any(n["id"] == "case:NEW-001" for n in saved["nodes"])
    assert any(n["type"] == "hypothesis" for n in saved["nodes"])
    assert (client.app.state.pipeline.runs_dir / started["run_id"] / "uploads" / "report.txt").exists()


def test_accept_confirms_edges_and_finds_gaps(client):
    run_demo(client)
    hyp_id = client.get("/api/hypotheses").json()[0]["id"]
    response = client.post(f"/api/hypotheses/{hyp_id}/decision", json={"decision": "accept", "reason": "same Jeep"})
    assert response.status_code == 200
    client.app.state.pipeline.join()
    entries = client.get("/api/audit").json()["entries"]
    decision = next(e for e in entries if e["type"] == "decision.recorded")
    assert decision["data"]["decision"] == "accept"
    assert {e["kind"] for e in decision["data"]["edges"]} == {"confirmed"}
    assert any(e["rel"] == "PART_OF_SERIES" for e in decision["data"]["edges"])
    gaps = entries[-1]
    assert gaps["type"] == "gap.next_steps"
    assert gaps["data"]["next_steps"] == GAPS["next_steps"]
    graph = client.get("/api/graph").json()
    assert next(n for n in graph["nodes"] if n["id"] == hyp_id)["status"] == "confirmed"
    assert client.get("/api/audit").json()["metrics"]["accepted"] == 1


def test_reject_hides_nothing_and_skips_gap_finder(client):
    run_demo(client)
    hyp_id = client.get("/api/hypotheses").json()[0]["id"]
    client.post(f"/api/hypotheses/{hyp_id}/decision", json={"decision": "reject", "reason": "different city"})
    client.app.state.pipeline.join()
    types = audit_types(client)
    assert "gap.next_steps" not in types
    node = next(n for n in client.get("/api/graph").json()["nodes"] if n["id"] == hyp_id)
    assert node["status"] == "rejected"
    assert node["props"]["decision_reason"] == "different city"
    assert client.get("/api/cases/NEW-001").json()["node"]["status"] == "existing"


def test_decision_unknown_hypothesis(client):
    response = client.post("/api/hypotheses/hyp:H-9999/decision", json={"decision": "accept", "reason": ""})
    assert response.status_code == 400


def test_linker_failure_uses_fallback(client, monkeypatch):
    def broken(*args, **kwargs):
        raise CliError("claude exited 1: boom")

    monkeypatch.setattr(agents, "run_linker", broken)
    started = run_demo(client)
    entries = [e for e in client.get("/api/audit").json()["entries"] if e["run_id"] == started["run_id"]]
    types = [e["type"] for e in entries]
    assert "run.error" in types
    hypothesis = next(e for e in entries if e["type"] == "link.hypothesis")
    assert hypothesis["data"]["fallback"] is True
    assert hypothesis["data"]["hypothesis"]["props"]["fallback"] is True
    assert types[-2:] == ["critic.verdict", "run.finished"]


def test_photo_failure_continues(client, fake_claude, monkeypatch):
    original = cli.runner

    def flaky(command, **kwargs):
        if "observations" in schema_of(command):
            return SimpleNamespace(stdout="", stderr="no", returncode=1)
        return original(command, **kwargs)

    monkeypatch.setattr(cli, "runner", flaky)
    started = run_demo(client)
    types = audit_types(client, started["run_id"])
    assert types.count("run.error") == 2
    assert "observe.photo" not in types
    assert types[-1] == "run.finished"


def test_decoy_has_no_candidates_and_finishes_empty(client, monkeypatch):
    monkeypatch.setattr(agents, "run_linker", lambda *a, **k: "nothing")
    original = cli.runner
    seattle = {**RECORD, "location": "Seattle, WA", "entry_method": "stolen car driven into the storefront",
               "vehicle": "stolen car", "evidence": [{"type": "vehicle", "description": "stolen car driven into the storefront"}]}

    def decoy_runner(command, **kwargs):
        if "entry_method" in schema_of(command):
            return SimpleNamespace(stdout=envelope(seattle), stderr="", returncode=0)
        return original(command, **kwargs)

    monkeypatch.setattr(cli, "runner", decoy_runner)
    started = run_demo(client, "decoy-cannabis")
    pipeline = client.app.state.pipeline
    assert not [c for c in tools.cluster_candidates(pipeline.graph, "case:NEW-001") if c["score"] > agents.FALLBACK_SCORE_THRESHOLD]
    entries = [e for e in client.get("/api/audit").json()["entries"] if e["run_id"] == started["run_id"]]
    assert entries[-1]["data"]["hypotheses"] == 0
    assert "run.error" not in [e["type"] for e in entries]
    assert client.get("/api/cases/NEW-001").json()["node"]["status"] == "existing"


def test_linker_that_proposes_nothing_skips_fallback(client, monkeypatch):
    monkeypatch.setattr(agents, "run_linker", lambda *a, **k: "evidence is thin")
    started = run_demo(client)
    entries = [e for e in client.get("/api/audit").json()["entries"] if e["run_id"] == started["run_id"]]
    assert "link.hypothesis" not in [e["type"] for e in entries]
    assert entries[-1]["data"]["hypotheses"] == 0


def test_case_with_pending_hypothesis_becomes_existing_and_is_a_candidate(client):
    run_demo(client)
    entries = client.get("/api/audit").json()["entries"]
    finished = entries[-1]
    assert finished["type"] == "run.finished"
    assert finished["data"]["nodes"][0]["id"] == "case:NEW-001"
    assert finished["data"]["nodes"][0]["status"] == "existing"
    assert client.get("/api/cases/NEW-001").json()["node"]["status"] == "existing"
    run_demo(client, "renton-b")
    candidates = tools.cluster_candidates(client.app.state.pipeline.graph, "case:NEW-002")
    assert "case:NEW-001" in [c["case_id"] for c in candidates]


def linker_runner(client, original, fail_after_proposing=False):
    def run(command, **kwargs):
        if "--mcp-config" not in command:
            return original(command, **kwargs)
        config = json.loads(open(command[command.index("--mcp-config") + 1]).read())
        run_id = config["mcpServers"]["graph"]["env"]["CASE_GRAPH_RUN_ID"]
        case_id = kwargs["input"].rsplit(": ", 1)[1]
        scored = client.post("/api/tools/cluster_candidates", json={"case_id": case_id, "run_id": run_id}).json()
        top = scored[0]
        client.post("/api/tools/propose_hypothesis", json={
            "case_id": case_id, "linked_case_ids": [top["case_id"]], "rationale": "same method and vehicle",
            "cited_edge_ids": top["cited_edge_ids"], "confidence": 0.8, "run_id": run_id})
        if fail_after_proposing:
            return SimpleNamespace(stdout="", stderr="max turns", returncode=1)
        return SimpleNamespace(stdout=envelope("Proposed one cluster."), stderr="", returncode=0)
    return run


@pytest.fixture
def real_linker_client(tmp_path, seeded, fake_claude, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    seeded.save(snapshot)
    app = server.create_app(graph=Graph.load(snapshot), runs_dir=tmp_path / "runs")
    with TestClient(app) as test_client:
        yield test_client


def test_real_linker_path_end_to_end(real_linker_client, monkeypatch):
    client = real_linker_client
    monkeypatch.setattr(cli, "runner", linker_runner(client, cli.runner))
    started = run_demo(client)
    entries = [e for e in client.get("/api/audit").json()["entries"] if e["run_id"] == started["run_id"]]
    types = [e["type"] for e in entries]
    assert "link.tool_call" in types
    assert types.count("link.hypothesis") == 1
    assert types[-2:] == ["critic.verdict", "run.finished"]
    hypothesis = next(e for e in entries if e["type"] == "link.hypothesis")["data"]["hypothesis"]
    assert any(e["id"] == hypothesis["id"] for e in client.get("/api/hypotheses").json())
    assert all(e["data"]["tool"] != "propose_hypothesis" or "rejected" not in e["data"]["summary"]
               for e in entries if e["type"] == "link.tool_call")


def test_hypotheses_proposed_before_linker_error_are_announced(real_linker_client, monkeypatch):
    client = real_linker_client
    monkeypatch.setattr(cli, "runner", linker_runner(client, cli.runner, fail_after_proposing=True))
    started = run_demo(client)
    entries = [e for e in client.get("/api/audit").json()["entries"] if e["run_id"] == started["run_id"]]
    types = [e["type"] for e in entries]
    assert "run.error" in types
    assert types.count("link.hypothesis") == 1
    announced = next(e for e in entries if e["type"] == "link.hypothesis")["data"]
    assert not announced.get("fallback")
    assert types.index("link.hypothesis") < types.index("critic.verdict")
    assert client.get("/api/audit").json()["metrics"]["hypotheses_proposed"] == 1


def test_error_events_hide_paths_and_details(client, monkeypatch):
    def broken(*args, **kwargs):
        raise CliError("claude exited 1: /Users/someone/secret/path")

    monkeypatch.setattr(agents, "run_linker", broken)
    started = run_demo(client)
    entries = [e for e in client.get("/api/audit").json()["entries"] if e["run_id"] == started["run_id"]]
    error = next(e for e in entries if e["type"] == "run.error")
    assert "/Users" not in json.dumps(error)
    log = client.app.state.pipeline.runs_dir / started["run_id"] / "errors.log"
    assert "secret/path" in log.read_text()


def test_upload_names_are_sanitized_and_unique(client):
    names = ["..", ".", "a/..", "../x.txt", "same.txt", "same.txt", "bad\x01name.txt"]
    files = [("files[]", (name, io.BytesIO(b"report"), "text/plain")) for name in names]
    started = client.post("/api/cases", files=files).json()
    client.app.state.pipeline.join()
    uploads = client.app.state.pipeline.runs_dir / started["run_id"] / "uploads"
    saved = sorted(p.name for p in uploads.iterdir())
    assert len(saved) == len(names)
    assert all(server.UNSAFE_NAME_CHARS.search(n) is None and n not in ("", ".", "..") for n in saved)
    assert {"same.txt", "same-2.txt"} <= set(saved)


def test_pluralised_finish_message(client):
    run_demo(client)
    finished = client.get("/api/audit").json()["entries"][-1]
    assert finished["message"].endswith("with 1 hypothesis")


def test_upload_endpoint_accepts_files_and_fields(client):
    files = [("files[]", ("note.txt", io.BytesIO(b"burglary report"), "text/plain")),
             ("files[]", ("scene.jpg", io.BytesIO(b"\xff\xd8fake"), "image/jpeg"))]
    started = client.post("/api/cases", files=files, data={"location": "Renton, WA", "label": "mine", "date": "2023-09-08"}).json()
    client.app.state.pipeline.join()
    assert started["case_id"] == "case:NEW-001"
    entries = [e for e in client.get("/api/audit").json()["entries"] if e["run_id"] == started["run_id"]]
    assert entries[0]["data"] == {"case_id": "case:NEW-001", "label": "mine", "file_count": 2}
    case = client.get("/api/cases/NEW-001").json()
    assert case["node"]["props"]["date"] == "2023-09-08"
    assert case["sources"] == ["note.txt", "scene.jpg"]
    urls = {m["url"] for m in case["media"]}
    assert f"/api/uploads/{started['run_id']}/scene.jpg" in urls
    assert client.get(f"/api/uploads/{started['run_id']}/scene.jpg").content == b"\xff\xd8fake"


def test_second_case_gets_next_id(client):
    run_demo(client)
    assert run_demo(client, "renton-b")["case_id"] == "case:NEW-002"


def test_unknown_demo(client):
    assert client.post("/api/demo/nope").status_code == 404


def test_tools_dispatch(client):
    found = client.post("/api/tools/find_cases", json={"city": "Renton", "limit": 3}).json()
    assert 0 < len(found) <= 3
    case_id = found[0]["id"]
    detail = client.post("/api/tools/get_case", json={"case_id": case_id}).json()
    assert detail["case"]["id"] == case_id
    scores = client.post("/api/tools/cluster_candidates", json={"case_id": case_id}).json()
    assert scores and "cited_edge_ids" in scores[0]


def test_tools_propose_hypothesis_and_errors(client):
    graph = client.app.state.pipeline.graph
    first = "case:rcg-06"
    client.app.state.pipeline.linker_runs.add("run-x")
    top = client.post("/api/tools/cluster_candidates", json={"case_id": first}).json()[0]
    ids = [first, top["case_id"]]
    cited = top["cited_edge_ids"]
    body = {"case_id": ids[0], "linked_case_ids": [ids[1]], "rationale": "r", "cited_edge_ids": cited, "confidence": 0.7, "run_id": "run-x"}
    created = client.post("/api/tools/propose_hypothesis", json=body).json()
    assert created["hypothesis"]["props"]["run_id"] == "run-x"
    spoofed = client.post("/api/tools/propose_hypothesis", json={**body, "run_id": "run-other", "fallback": True}).json()
    assert spoofed["hypothesis"]["props"]["run_id"] == "adhoc"
    assert spoofed["hypothesis"]["props"]["fallback"] is False
    bad = client.post("/api/tools/propose_hypothesis", json={**body, "cited_edge_ids": ["nope"]})
    assert bad.status_code == 400 and "does not exist" in bad.json()["error"]
    assert client.post("/api/tools/get_case", json={"case_id": "case:zzz"}).status_code == 404
    assert client.post("/api/tools/delete_everything", json={}).status_code == 404
    assert client.post("/api/tools/get_case", json={"wrong": 1}).status_code == 422


def test_tool_calls_emit_events_during_linker_run(client):
    pipeline = client.app.state.pipeline
    pipeline.linker_runs.update({"run-live", "run-other"})
    client.post("/api/tools/find_cases", json={"city": "Renton", "limit": 2, "run_id": "run-live"})
    client.post("/api/tools/find_cases", json={"city": "Renton", "limit": 2, "run_id": "run-other"})
    pipeline.linker_runs.discard("run-live")
    client.post("/api/tools/find_cases", json={"city": "Renton", "limit": 2, "run_id": "run-other"})
    client.post("/api/tools/find_cases", json={"city": "Renton", "limit": 2, "run_id": "run-live"})
    client.post("/api/tools/find_cases", json={"city": "Renton", "limit": 2})
    entries = client.get("/api/audit").json()["entries"]
    assert [e["run_id"] for e in entries] == ["run-live", "run-other", "run-other"]
    assert entries[-1]["type"] == "link.tool_call"
    assert entries[-1]["data"]["tool"] == "find_cases"


def test_media_routes(client):
    case = client.get("/api/cases/rcg-01").json()
    assert case["node"]["label"] == "RCG-01"
    graph = client.app.state.pipeline.graph
    with_media = next(n for n in graph.nodes_of_type("case") if n["props"].get("media"))
    detail = client.get(f"/api/cases/{with_media['id']}").json()
    assert detail["media"]
    response = client.get(detail["media"][0]["url"])
    assert response.status_code == 200
    assert response.content
    assert client.get("/api/media/renton-crash-and-grab-2023/rcg-01/nothing.jpg").status_code == 404
    assert client.get("/api/uploads/run-none/nothing.jpg").status_code == 404


def test_series_media_route(client):
    series = client.app.state.pipeline.graph.nodes["series:renton-crash-and-grab-2023"]
    media = series["props"]["media"]
    assert media and all(m["kind"] == "image" for m in media)
    assert media[0]["publisher"].startswith("Renton Police Department")
    name = media[0]["path"].split("/")[-1]
    response = client.get(f"/api/media/renton-crash-and-grab-2023/_series/{name}")
    assert response.status_code == 200
    assert response.content
    assert client.get("/api/media/renton-crash-and-grab-2023/_series/nothing.jpg").status_code == 404
    assert client.get("/api/media/renton-crash-and-grab-2023/_series/..%2Fseries.json").status_code == 404


def test_page_and_assets(client):
    assert "<html" in client.get("/").text.lower()
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200
    assert client.get("/web/app.js").status_code == 200


def test_graph_shape(client):
    body = client.get("/api/graph").json()
    assert set(body) >= {"nodes", "edges", "stats"}


def test_events_are_broadcast_to_subscribers(client):
    pipeline = client.app.state.pipeline
    received = []

    class ImmediateLoop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    class Subscriber:
        def put_nowait(self, line):
            received.append(json.loads(line))

    pipeline.loop = ImmediateLoop()
    pipeline.subscribers.add(Subscriber())
    pipeline.event("run.started", "run-z", "intake", "hello", {"case_id": "x"})
    assert received[0]["type"] == "run.started"
    assert received[0]["run_id"] == "run-z"
