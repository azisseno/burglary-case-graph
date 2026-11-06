import json
from types import SimpleNamespace

import pytest

from app import cli, leads, seed
from tests.test_server import client, fake_claude, fake_linker, run_demo, seeded

SERIES = "series:new-orleans-suv-series-2023"
RENTON = "series:renton-crash-and-grab-2023"


@pytest.fixture(scope="module")
def graph():
    return seed.build_graph()


def lead_of(sheet, kind):
    return next((lead for lead in sheet["leads"] if lead["kind"] == kind), None)


def test_sheet_matches_contract(graph):
    sheet = leads.build_leads(graph, SERIES)
    assert set(sheet) == {"series_id", "label", "case_ids", "window", "pattern", "leads", "missing", "phrased_by"}
    assert sheet["series_id"] == SERIES
    assert sheet["phrased_by"] == "code"
    assert sheet["window"] == {"from": "2023-07-22", "to": "2023-07-27"}
    assert sheet["pattern"].endswith(".")
    assert len(sheet["case_ids"]) == 6


def test_vehicle_geography_and_timing_leads_cite_their_cases(graph):
    sheet = leads.build_leads(graph, SERIES)
    vehicle = lead_of(sheet, "vehicle")
    assert "SUV" in vehicle["fact"]
    assert vehicle["case_ids"] == sheet["case_ids"]
    assert "Plate-reader" in vehicle["action"]
    assert lead_of(sheet, "geography")["case_ids"] == sheet["case_ids"]
    assert lead_of(sheet, "timing")["case_ids"] == sheet["case_ids"]
    assert "No plate recorded in any report" in sheet["missing"]


def test_vehicle_lead_lists_only_cases_with_the_vehicle(graph):
    sheet = leads.build_leads(graph, RENTON)
    vehicle = lead_of(sheet, "vehicle")
    assert set(vehicle["case_ids"]) < set(sheet["case_ids"])
    for case_id in vehicle["case_ids"]:
        labels = [n["label"] for n, e in graph.neighbors(case_id) if n["type"] == "vehicle"]
        assert any(label in vehicle["fact"].lower() for label in labels)


def test_video_and_agencies_leads_appear_when_the_graph_has_them(graph):
    sheet = leads.build_leads(graph, RENTON)
    assert lead_of(sheet, "video")["case_ids"]
    assert "Kent" in lead_of(sheet, "agencies")["fact"]


def test_lead_kinds_are_omitted_when_the_graph_has_nothing(graph):
    sheet = leads.build_leads(graph, SERIES)
    assert lead_of(sheet, "agencies") is None
    assert lead_of(sheet, "video") is None


def test_every_lead_cites_real_cases_of_the_series(graph):
    for series in graph.nodes_of_type("series"):
        sheet = leads.build_leads(graph, series["id"])
        for lead in sheet["leads"]:
            assert lead["case_ids"]
            assert set(lead["case_ids"]) <= set(sheet["case_ids"])


def test_unknown_series_returns_none(graph):
    assert leads.build_leads(graph, "series:nope") is None
    assert leads.build_leads(graph, "case:rcg-01") is None


def test_build_is_deterministic(graph):
    assert leads.build_leads(graph, RENTON) == leads.build_leads(graph, RENTON)


def fake_phrasing(monkeypatch, payload=None, error=None):
    def run(command, **kwargs):
        if error:
            raise error
        return SimpleNamespace(stdout=json.dumps({"is_error": False, "result": json.dumps(payload)}), stderr="", returncode=0)

    monkeypatch.setattr(cli, "runner", run)


def test_phrase_rewrites_only_actions(graph, monkeypatch, tmp_path):
    sheet = leads.build_leads(graph, SERIES)
    fake_phrasing(monkeypatch, {"actions": [f"Do {i}" for i in range(len(sheet["leads"]))]})
    phrased = leads.phrase_leads(sheet, tmp_path)
    assert phrased["phrased_by"] == "sonnet"
    assert [l["action"] for l in phrased["leads"]] == [f"Do {i}" for i in range(len(sheet["leads"]))]
    assert [(l["kind"], l["fact"], l["case_ids"]) for l in phrased["leads"]] == [(l["kind"], l["fact"], l["case_ids"]) for l in sheet["leads"]]
    assert sheet["phrased_by"] == "code"


@pytest.mark.parametrize("payload", [{"actions": ["only one"]}, {"actions": "no"}, {"other": 1}, {"actions": ["", "", ""]}])
def test_phrase_falls_back_on_bad_reply(graph, monkeypatch, tmp_path, payload):
    sheet = leads.build_leads(graph, SERIES)
    fake_phrasing(monkeypatch, payload)
    assert leads.phrase_leads(sheet, tmp_path) == sheet


def test_phrase_falls_back_on_cli_failure_and_timeout(graph, monkeypatch, tmp_path):
    import subprocess
    sheet = leads.build_leads(graph, SERIES)
    fake_phrasing(monkeypatch, error=subprocess.TimeoutExpired("claude", 40))
    assert leads.phrase_leads(sheet, tmp_path) == sheet
    fake_phrasing(monkeypatch, error=OSError("no claude"))
    assert leads.phrase_leads(sheet, tmp_path) == sheet


def test_phrase_call_is_capped_at_forty_seconds(graph, monkeypatch, tmp_path):
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(stdout="", stderr="", returncode=1)

    monkeypatch.setattr(cli, "runner", run)
    leads.phrase_leads(leads.build_leads(graph, SERIES), tmp_path)
    assert seen["timeout"] == 40


def test_endpoint_returns_sheet_and_404(client):
    response = client.get(f"/api/series/{SERIES}/leads")
    assert response.status_code == 200
    assert response.json()["series_id"] == SERIES
    assert client.get("/api/series/series:missing/leads").status_code == 404
    assert client.get("/api/series/case:rcg-01/leads").status_code == 404


def test_accept_emits_leads_ready(client):
    run_demo(client)
    hyp_id = client.get("/api/hypotheses").json()[0]["id"]
    client.post(f"/api/hypotheses/{hyp_id}/decision", json={"decision": "accept", "reason": "same Jeep"})
    client.app.state.pipeline.join()
    entries = client.get("/api/audit").json()["entries"]
    event = next(e for e in entries if e["type"] == "leads.ready")
    series_id = event["data"]["series_id"]
    assert event["agent"] == "leads"
    assert event["run_id"] == next(e for e in entries if e["type"] == "decision.recorded")["run_id"]
    assert event["message"] == f"Lead sheet ready for {event['data']['label']} ({len(event['data']['leads'])} leads)"
    assert event["data"]["leads"]
    assert client.get(f"/api/series/{series_id}/leads").json()["leads"] == event["data"]["leads"]


def test_reject_emits_no_leads(client):
    run_demo(client)
    hyp_id = client.get("/api/hypotheses").json()[0]["id"]
    client.post(f"/api/hypotheses/{hyp_id}/decision", json={"decision": "reject", "reason": "different city"})
    client.app.state.pipeline.join()
    assert "leads.ready" not in [e["type"] for e in client.get("/api/audit").json()["entries"]]
