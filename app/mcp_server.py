import json
import os

import httpx
from mcp.server.mcpserver import MCPServer

DEFAULT_API = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 60

server = MCPServer("graph")
transport = None


def api_base():
    return os.environ.get("CASE_GRAPH_API", DEFAULT_API).rstrip("/")


def call_api(name, arguments):
    payload = {**arguments, "run_id": os.environ.get("CASE_GRAPH_RUN_ID")}
    with httpx.Client(transport=transport, timeout=TIMEOUT_SECONDS) as client:
        response = client.post(f"{api_base()}/api/tools/{name}", json=present(**payload))
    if response.status_code >= 400:
        return json.dumps({"error": response.text, "status": response.status_code})
    return json.dumps(response.json())


def present(**arguments):
    return {key: value for key, value in arguments.items() if value is not None}


@server.tool()
def find_cases(city: str | None = None, method: str | None = None, scene_type: str | None = None,
               date_from: str | None = None, date_to: str | None = None,
               series_id: str | None = None, limit: int = 25) -> str:
    """Search existing cases by filters. Returns a JSON list of case summaries with id, label, date, scene_type, location, series_id and status."""
    return call_api("find_cases", present(city=city, method=method, scene_type=scene_type, date_from=date_from, date_to=date_to, series_id=series_id, limit=limit))


@server.tool()
def get_case(case_id: str) -> str:
    """Fetch one case. Returns JSON with the case node, its attribute nodes (method, vehicle, item, location, time_window) each with the edge id that supports it and its provenance, its series if any, and all its edges."""
    return call_api("get_case", {"case_id": case_id})


@server.tool()
def shared_attributes(case_ids: list[str]) -> str:
    """Find attribute nodes shared by at least two of the given cases. Returns a JSON list of shared nodes with type, label, the cases that have it and the edge ids you may cite."""
    return call_api("shared_attributes", {"case_ids": case_ids})


@server.tool()
def neighbors(node_id: str, depth: int = 1) -> str:
    """Walk the graph around a node. Returns JSON with the nodes and edges within the given depth."""
    return call_api("neighbors", {"node_id": node_id, "depth": depth})


@server.tool()
def cluster_candidates(case_id: str, window_days: int = 120, same_city: bool = True) -> str:
    """Score every other case against the given case. Returns the top 10 as JSON with case_id, score, matched attributes and cited_edge_ids. Scores are hints from fixed weights, not conclusions; verify with get_case and shared_attributes."""
    return call_api("cluster_candidates", {"case_id": case_id, "window_days": window_days, "same_city": same_city})


@server.tool()
def missing_evidence(case_id: str) -> str:
    """List what is not known about a case. Returns JSON with the case's recorded unknowns and the attribute types that have no edges."""
    return call_api("missing_evidence", {"case_id": case_id})


@server.tool()
def propose_hypothesis(case_id: str, linked_case_ids: list[str], rationale: str,
                       cited_edge_ids: list[str], confidence: float) -> str:
    """Propose that the new case belongs to one series with the linked cases. Cite only edge ids you have seen in tool results; proposals citing unknown edges are rejected. Confidence is 0 to 1. Returns JSON with the created hypothesis and its edges, or an error."""
    arguments = {"case_id": case_id, "linked_case_ids": linked_case_ids, "rationale": rationale,
                 "cited_edge_ids": cited_edge_ids, "confidence": confidence}
    return call_api("propose_hypothesis", arguments)


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
