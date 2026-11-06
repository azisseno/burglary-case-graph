# Prototype design: agentic case linking on a knowledge graph

Case competition demo for stage 6, detective follow-up. An officer drops a case's files in, agents turn them into graph nodes and propose links to existing cases, a detective accepts or rejects, and the graph grows. Everything runs on one laptop.

## What it is for

A 60 to 90 second recorded demo that shows: the department's memory as a graph, a new case entering it, agents working visibly, a confident link accepted, a weak link rejected, and the outcome for the detective. Judges reward visible mechanism and honest limits over polish.

## Scope

In: text or document evidence and photos. Out: audio, video, cloud graph, real identity data. All data is public or synthetic, no suspect or victim names anywhere.

## Runtime

- Python 3.12, FastAPI, uvicorn. One process serves the page and the API.
- Graph store in memory, persisted to `runs/graph.json`. Built from `data/cases` by `seed`.
- Agents run through the Claude Code CLI in headless mode: `claude -p` with `--output-format json`, `--json-schema` for fixed outputs, `--model sonnet` by default and `haiku` for photo observation. The Linker gets graph tools through a local MCP server over stdio with `--mcp-config` and `--strict-mcp-config`.
- Front end: one HTML page, vanilla JavaScript, Cytoscape.js from a CDN, dark theme. Live updates over server-sent events.

## Folders

```
app/            backend package
  server.py     FastAPI routes and SSE
  store.py      graph store and persistence
  tools.py      graph tools used by the Linker and the API
  normalize.py  canonical methods, vehicles, items, time windows
  extract.py    photo observer and record extractor (CLI calls)
  agents.py     Linker, Critic, Gap finder
  cli.py        wrapper around the claude command
  mcp_server.py MCP server exposing tools.py to the Linker
  seed.py       builds the initial graph from data/cases, excluding held-out inputs
web/            index.html, app.js, styles.css, mock/
data/cases/     dataset, see data/cases/SCHEMA.md
data/demo-inputs/<name>/   held-out cases as drop-in input folders
runs/           graph.json, audit.jsonl, one folder per run with every CLI call logged
tests/          pytest for store, tools, normalize, and the API with the CLI stubbed
```

## Graph model

Nodes carry `id`, `type`, `label`, `status`, `props`, `sources`.

| type | label example | props |
|---|---|---|
| case | RCG-04 | series_id, date, date_precision, time, scene_type, location text, items_taken, unknowns, notes, media |
| location | Renton, WA | city, state, neighborhood |
| time_window | 2023-W36 | start, end |
| method | vehicle ramming | canonical key, synonyms seen |
| vehicle | dark SUV | canonical key |
| item | cash | category |
| series | Renton crash and grab, 2023 | ground truth status, outcome |
| hypothesis | H-0001 | run_id, case_ids, confidence, rationale, critic verdict, decision |

`status` is `existing`, `new`, `proposed`, `confirmed`, or `rejected`. New cases enter as `new` and become `existing` after a run finishes.

Edges carry `id`, `source`, `target`, `rel`, `kind`, `confidence`, `provenance`.

| rel | from, to | kind |
|---|---|---|
| AT_LOCATION | case, location | observed |
| IN_WINDOW | case, time_window | observed |
| USED_METHOD | case, method | observed |
| VEHICLE_SEEN | case, vehicle | observed |
| ITEM_TAKEN | case, item | observed |
| PART_OF_SERIES | case, series | confirmed |
| PROPOSES_LINK | hypothesis, case | hypothesis |
| SUPPORTED_BY | hypothesis, method or vehicle or time_window or location | hypothesis |

`kind` is `observed`, `hypothesis`, or `confirmed`. `provenance` is a source URL or an input file name, never empty. Accepting a hypothesis writes `PART_OF_SERIES` edges as `confirmed` for the new case, creating a series node if the matched cases had none. Rejecting marks the hypothesis `rejected` and leaves its edges in place for the audit view, hidden by default.

## Pipeline for one dropped case

1. **Intake.** Files sorted by type: image, text or document (`.txt`, `.md`, `.pdf`, `.docx` read as text). A case id is minted, `NEW-001` style. Event `intake.file` per file.
2. **Observe.** Each image goes to the photo observer: one CLI call with the image path and a fixed schema returning observations such as `entry_damage`, `vehicle`, `tool`, `footage` with a short description and confidence. Event `observe.photo` per image.
3. **Extract.** The text goes to the record extractor: one CLI call with a fixed schema returning date, time, location text, scene type, entry method, items taken, vehicle description, evidence mentions, unknowns. Event `extract.text`.
4. **Build.** Code normalizes to canonical attribute nodes and writes the case node and observed edges, every edge with the file it came from. Event `build.nodes` with the delta.
5. **Link.** The Linker runs as a CLI call with the graph MCP tools and the new case id. It calls `cluster_candidates`, inspects candidates with `get_case` and `shared_attributes`, and ends with one or more `propose_hypothesis` calls or none. Each proposal is validated: cited edges must exist. Events `link.candidates`, `link.hypothesis`.
6. **Critic.** One CLI call per hypothesis with the hypothesis, its cited evidence, and the candidate cases: returns `holds`, `weak`, or `refuted` with reasons and what would change its mind. Event `critic.verdict`. Stored on the hypothesis node.
7. **Review.** The hypothesis appears in the review panel. Decision endpoint records accept, reject, or more evidence. Event `decision.recorded` with the graph delta.
8. **Gap finder.** On accept, one CLI call returns missing evidence and next steps for the cluster. Event `gap.next_steps`.

If any CLI call fails, the run emits `run.error` with the step and continues where it can. The Linker has a fallback that uses `cluster_candidates` scores alone to propose, marked `fallback: true`.

## Linking rules inside the tools

`cluster_candidates(case_id, window_days=120, same_city=true)` scores every other case: method match 3, vehicle match 3, same city 1, same neighborhood 2, time window within 14 days 2, within window_days 1, same scene type 1, item overlap 1. Returns the top 10 with the matched attributes. Scores are shown in the event so the audience sees the arithmetic, and the Linker is told they are hints, not conclusions.

## API

- `GET /` page.
- `GET /api/graph` whole graph: `{nodes, edges, stats}`.
- `GET /api/cases/{id}` case node with its edges, media URLs, and sources.
- `GET /api/media/{series}/{incident}/{file}` and `GET /api/uploads/{run_id}/{file}` static files.
- `POST /api/cases` multipart `files[]` plus optional `label`, `date`, `location`, `scene_type`; returns `{run_id, case_id}` and starts the pipeline in the background.
- `POST /api/demo/{name}` same as above but reads `data/demo-inputs/<name>`; `GET /api/demo` lists them.
- `GET /api/events` server-sent events, one JSON object per message.
- `GET /api/hypotheses` all, newest first. `POST /api/hypotheses/{id}/decision` body `{decision: "accept"|"reject"|"more", reason}`.
- `GET /api/audit` entries from `runs/audit.jsonl` and metrics: cases added, hypotheses proposed, accepted, rejected, median seconds from drop to proposal.

## Event contract

Every event: `{"type": ..., "run_id": ..., "ts": ISO8601, "agent": ..., "message": ..., "data": {...}}`. `agent` is one of `intake`, `photo_observer`, `record_extractor`, `builder`, `linker`, `critic`, `gap_finder`, `detective`.

| type | data |
|---|---|
| run.started | case_id, label, file_count |
| intake.file | name, kind (image, text, document), size |
| observe.photo | file, observations: [{type, description, confidence}] |
| extract.text | file, record: {date, time, location, scene_type, entry_method, items_taken, vehicle, evidence: [...], unknowns} |
| build.nodes | nodes: [...], edges: [...] (graph delta) |
| link.candidates | candidates: [{case_id, score, matched: [...]}] |
| link.tool_call | tool, args, summary (one per MCP call, so the console shows the agent walking) |
| link.hypothesis | hypothesis node, edges (delta), rationale, confidence |
| critic.verdict | hypothesis_id, verdict, reasons, would_change_mind |
| decision.recorded | hypothesis_id, decision, reason, nodes, edges (delta) |
| gap.next_steps | hypothesis_id, missing: [...], next_steps: [...] |
| run.finished | case_id, seconds, hypotheses: n |
| run.error | step, message |

The page applies deltas to the graph as they arrive. Nodes in a delta carry `status`; edges carry `kind`.

## Front end behaviour

Three regions on a dark screen. Left: intake drop zone, sample buttons, agent console streaming the events as lines with the agent name, time, and message. Center: Cytoscape graph of the whole store. Right: review panel listing hypotheses with rationale, cited evidence, critic verdict, and accept, reject, more buttons; below it, the case detail drawer for the clicked node and a metrics strip.

Visual rules: existing nodes dim, new nodes glow and pulse until the run ends, hypothesis nodes amber with dashed edges, confirmed edges green and solid, rejected hypotheses fade and are hidden unless the audit toggle is on. Node color by type, shape by type: case circle, series hexagon, method diamond, location rounded square, time window pill, vehicle triangle, item small circle, hypothesis octagon. New nodes drop in near their linked attributes and the layout animates. Clicking a node opens its detail with provenance. A legend sits in a corner. Works at 1440 wide for the recording and does not break at 1024.

Mock mode: `index.html?mock=1` loads `web/mock/graph.json` and replays `web/mock/events.json` with delays, so the page can be built and shown without the backend.

## Held-out demo inputs

- `renton-a`: `rcg-04` text record plus police stills 01 and 02.
- `renton-b`: `rcg-05` text record plus stills 03 and 04.
- `decoy-cannabis`: one `scr` record as text only.

These three incidents are excluded from the seeded graph. The seed writes the exclusion list to `runs/held_out.json`.

## Guardrails built in

No person node type exists. Prompts tell every agent never to infer who a suspect is. `propose_hypothesis` rejects proposals whose cited edges do not exist. Every CLI call's prompt and output is logged under `runs/<run_id>/`. Decisions are logged with the reason. The page never auto-accepts.

## Testing

Pytest covers the store, the tools and their scoring, normalization, and the API with the CLI replaced by a fake that returns canned JSON. One end-to-end run against the real CLI is done by hand before recording.

## Out of scope for the demo

Neptune, Bedrock, CJIS deployment, audio, video, authentication, multi-user state. These stay on the slide as the production path.
