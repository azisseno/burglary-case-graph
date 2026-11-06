const MOCK = new URLSearchParams(window.location.search).get("mock") === "1";
const MOCK_GRAPH_URL = "mock/graph.json";
const MOCK_EVENTS_URL = "mock/events.json";
const CONSOLE_LIMIT = 400;

const TYPE_STYLE = {
  case: { color: "#6fa8ff", shape: "ellipse", width: 34, height: 34 },
  series: { color: "#b48bff", shape: "hexagon", width: 46, height: 42 },
  method: { color: "#ff7b5c", shape: "diamond", width: 32, height: 32 },
  location: { color: "#4fd1b9", shape: "round-rectangle", width: 30, height: 30 },
  time_window: { color: "#c3ccdd", shape: "round-rectangle", width: 50, height: 20 },
  vehicle: { color: "#ff8fcb", shape: "triangle", width: 32, height: 28 },
  item: { color: "#9ca9c2", shape: "ellipse", width: 18, height: 18 },
  hypothesis: { color: "#ffb224", shape: "octagon", width: 40, height: 40 },
};

const AGENTS = {
  intake: { short: "intake", color: "var(--agent-intake)" },
  photo_observer: { short: "photo", color: "var(--agent-photo)" },
  record_extractor: { short: "extract", color: "var(--agent-extract)" },
  builder: { short: "build", color: "var(--agent-builder)" },
  linker: { short: "linker", color: "var(--agent-linker)" },
  critic: { short: "critic", color: "var(--agent-critic)" },
  gap_finder: { short: "gaps", color: "var(--agent-gaps)" },
  detective: { short: "you", color: "var(--agent-detective)" },
};

const STAGE_ORDER = ["intake", "observe", "extract", "build", "link", "critic", "review", "gaps"];
const STAGE_BY_EVENT = {
  "run.started": "intake",
  "intake.file": "intake",
  "observe.photo": "observe",
  "extract.text": "extract",
  "build.nodes": "build",
  "link.candidates": "link",
  "link.tool_call": "link",
  "link.hypothesis": "link",
  "critic.verdict": "critic",
  "decision.recorded": "review",
  "gap.next_steps": "gaps",
};

const STAGE_BY_STEP = {
  intake: "intake",
  run: "intake",
  observe: "observe",
  extract: "extract",
  build: "build",
  linker: "link",
  linker_fallback: "link",
  critic: "critic",
  gap_finder: "gaps",
};

const MAX_FOCUS_ZOOM = 1.3;
const RELEASE_VIEW_DELAY_MS = 4000;
const REJECT_FADE_MS = 1800;
const ID_PREFIXES = /\b(hyp|case|series|method|vehicle|item|loc|tw):/g;

const state = {
  cy: null,
  activeRuns: new Set(),
  noLinks: [],
  drafts: new Map(),
  submitting: false,
  hypotheses: new Map(),
  runs: new Map(),
  sessionCaseIds: new Set(),
  eventCount: 0,
  showRejected: false,
  currentRunId: null,
  clockTimer: null,
  selectedNodeId: null,
  pendingFiles: [],
  mockGraph: null,
  mockEvents: null,
  mockReplayHandle: null,
  mockReplayed: false,
};

const el = (id) => document.getElementById(id);

function init() {
  state.cy = createGraph();
  bindIntake();
  bindReviewControls();
  bindDrawer();
  window.addEventListener("resize", () => {
    state.cy.resize();
    fitAboveLegend();
  });
  if (MOCK) startMock();
  else startLive();
}

function createGraph() {
  const cy = cytoscape({
    container: el("cy"),
    style: graphStyle(),
    minZoom: 0.25,
    maxZoom: 3,
  });
  cy.on("tap", "node", (evt) => showNode(evt.target.id()));
  cy.on("tap", (evt) => {
    if (evt.target === cy) clearDrawer();
  });
  return cy;
}

function graphStyle() {
  const typeStyles = Object.entries(TYPE_STYLE).map(([type, s]) => ({
    selector: `node[type = "${type}"]`,
    style: {
      "background-color": s.color,
      shape: s.shape,
      width: s.width,
      height: s.height,
      "underlay-color": s.color,
    },
  }));
  return [
    {
      selector: "node",
      style: {
        label: "data(label)",
        color: "#c3ccdd",
        "font-family": "IBM Plex Mono, monospace",
        "font-size": 11,
        "min-zoomed-font-size": 7,
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 5,
        "text-outline-color": "#0a0f1e",
        "text-outline-width": 2,
        "text-max-width": 110,
        "text-wrap": "ellipsis",
        "border-width": 0,
        "underlay-opacity": 0,
        "underlay-padding": 4,
        "overlay-opacity": 0,
        "transition-property": "opacity, background-color",
        "transition-duration": "0.4s",
      },
    },
    ...typeStyles,
    { selector: 'node[type = "time_window"]', style: { color: "#0a0f1e", "font-size": 9, "text-valign": "center", "text-margin-y": 0, "text-outline-width": 0 } },
    { selector: 'node[type = "item"]', style: { "font-size": 9 } },
    { selector: 'node[type = "series"]', style: { "font-size": 11, "font-family": "Barlow Condensed, sans-serif", "font-weight": 600, "text-max-width": 150 } },
    { selector: "node.existing", style: { opacity: 0.5 } },
    { selector: "node.recent", style: { opacity: 1 } },
    { selector: "node.new", style: { opacity: 1, "underlay-opacity": 0.3, "underlay-padding": 10, "border-width": 2, "border-color": "#ffffff" } },
    { selector: "node.proposed", style: { opacity: 1, "underlay-opacity": 0.2, "underlay-padding": 8 } },
    { selector: "node.confirmed", style: { opacity: 1, "background-color": "#3ddc84", "underlay-color": "#3ddc84", "underlay-opacity": 0.18, "underlay-padding": 8 } },
    { selector: "node.rejected", style: { opacity: 0.22 } },
    { selector: "node.linked", style: { opacity: 0.95 } },
    { selector: "node:selected", style: { "border-width": 2, "border-color": "#ffffff", opacity: 1 } },
    { selector: "node.hidden", style: { display: "none" } },
    {
      selector: "edge",
      style: {
        "curve-style": "straight",
        width: 1.2,
        "line-color": "#3a4766",
        opacity: 0.55,
        "overlay-opacity": 0,
        "transition-property": "opacity, line-color, width",
        "transition-duration": "0.4s",
      },
    },
    { selector: "edge.observed", style: { "line-color": "#3a4766" } },
    { selector: "edge.hypothesis", style: { "line-color": "#ffb224", "line-style": "dashed", "line-dash-pattern": [6, 4], width: 1.6, opacity: 0.95 } },
    { selector: "edge.confirmed", style: { "line-color": "#3ddc84", "line-style": "solid", width: 2.4, opacity: 0.95 } },
    { selector: 'edge[rel = "PART_OF_SERIES"]', style: { "line-color": "#b48bff", width: 1, opacity: 0.35 } },
    { selector: "edge.observed.fresh", style: { "line-color": "#6fa8ff", opacity: 0.95, width: 1.8 } },
    { selector: "edge.rejected", style: { opacity: 0.2 } },
    { selector: "node.rejecting", style: { opacity: 0.35, "border-width": 2, "border-color": "#ff5c5c", "underlay-color": "#ff5c5c", "underlay-opacity": 0.2 } },
    { selector: "edge.rejecting", style: { "line-color": "#ff5c5c", opacity: 0.35 } },
    { selector: "edge.hidden", style: { display: "none" } },
    { selector: "edge.decided", style: { "line-color": "#3ddc84", "line-style": "solid", width: 3.5, opacity: 1 } },
  ];
}

function nodeElement(node) {
  return {
    group: "nodes",
    data: {
      id: node.id,
      label: node.label || node.id,
      type: node.type,
      status: node.status || "existing",
      props: node.props || {},
      sources: node.sources || [],
    },
    classes: node.status || "existing",
  };
}

function edgeElement(edge) {
  return {
    group: "edges",
    data: {
      id: edge.id || `${edge.source}-${edge.rel}-${edge.target}`,
      source: edge.source,
      target: edge.target,
      rel: edge.rel,
      kind: edge.kind || "observed",
      confidence: edge.confidence,
      provenance: asList(edge.provenance),
      cites: asList(edge.cites),
    },
    classes: edge.kind || "observed",
  };
}

function loadGraph(graph) {
  const cy = state.cy;
  cy.elements().remove();
  state.hypotheses.clear();
  const nodes = (graph.nodes || []).map((n) => nodeElement(n.status === "new" ? { ...n, status: "existing" } : n));
  const nodeIds = new Set(nodes.map((n) => n.data.id));
  const edges = (graph.edges || []).filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map(edgeElement);
  cy.add([...nodes, ...edges]);
  (graph.nodes || []).filter((n) => n.type === "hypothesis").forEach((n) => registerHypothesisNode(n));
  cy.layout(fullLayoutOptions()).run();
  fitAboveLegend();
  el("graph-empty").hidden = true;
  applyVisibility();
  renderHypotheses();
  renderGraphStats();
}

function fullLayoutOptions() {
  return {
    name: "cose",
    animate: false,
    randomize: true,
    fit: false,
    nodeRepulsion: () => 2000,
    idealEdgeLength: () => 40,
    edgeElasticity: () => 150,
    gravity: 5,
    numIter: 1200,
    componentSpacing: 20,
    nodeDimensionsIncludeLabels: false,
  };
}

function viewportFor(bb, pad, maxZoom) {
  const cy = state.cy;
  const legendHeight = el("legend").offsetHeight + 16;
  const availableWidth = cy.width() - pad * 2;
  const availableHeight = cy.height() - legendHeight - pad * 2;
  const zoom = Math.max(cy.minZoom(), Math.min(availableWidth / Math.max(bb.w, 1), availableHeight / Math.max(bb.h, 1), maxZoom));
  const pan = {
    x: pad + (availableWidth - bb.w * zoom) / 2 - bb.x1 * zoom,
    y: pad + (availableHeight - bb.h * zoom) / 2 - bb.y1 * zoom,
  };
  return { zoom, pan };
}

function fitAboveLegend() {
  const cy = state.cy;
  const bb = cy.elements().boundingBox();
  if (!bb.w || !bb.h) return;
  cy.viewport(viewportFor(bb, 36, 1.15));
}

function focusOn(eles) {
  const cy = state.cy;
  const visible = eles.closedNeighborhood().filter((ele) => !ele.hasClass("hidden"));
  if (visible.empty()) return;
  cy.animate({ ...viewportFor(visible.boundingBox(), 90, MAX_FOCUS_ZOOM), duration: 800, easing: "ease-in-out" });
}

function releaseView() {
  const bb = state.cy.elements().boundingBox();
  if (!bb.w || !bb.h) return;
  state.cy.animate({ ...viewportFor(bb, 36, 1.15), duration: 900, easing: "ease-in-out" });
}

function applyDelta(nodes = [], edges = []) {
  const cy = state.cy;
  const added = cy.collection();
  nodes.forEach((node) => {
    const existing = cy.getElementById(node.id);
    if (existing.nonempty()) {
      updateNode(existing, node);
    } else {
      const position = placementFor(node.id, edges);
      added.merge(cy.add({ ...nodeElement(node), position }));
    }
  });
  const freshEdges = cy.collection();
  edges.forEach((edge) => {
    if (cy.getElementById(edge.source).empty() || cy.getElementById(edge.target).empty()) return;
    const id = edge.id || `${edge.source}-${edge.rel}-${edge.target}`;
    const current = cy.getElementById(id);
    if (current.nonempty()) {
      if (edge.kind && edge.kind !== current.data("kind")) {
        current.data("kind", edge.kind);
        current.removeClass("observed hypothesis confirmed").addClass(edge.kind);
      }
      return;
    }
    freshEdges.merge(cy.add(edgeElement({ ...edge, id })));
  });
  freshEdges.filter(".observed").addClass("fresh");
  nodes.filter((n) => n.type === "hypothesis").forEach((n) => registerHypothesisNode(n));
  if (added.nonempty()) settleNeighborhood(added);
  applyVisibility();
  renderGraphStats();
  if (state.selectedNodeId && cy.getElementById(state.selectedNodeId).nonempty()) showNode(state.selectedNodeId);
  return added;
}

function updateNode(ele, node) {
  const mergedProps = { ...ele.data("props"), ...(node.props || {}) };
  ele.data("props", mergedProps);
  if (node.label) ele.data("label", node.label);
  if (node.sources && node.sources.length) ele.data("sources", node.sources);
  if (node.status) setNodeStatus(ele, node.status);
}

function setNodeStatus(ele, status) {
  ele.removeClass("existing new proposed confirmed rejected");
  ele.data("status", status);
  ele.addClass(status);
  if (status === "confirmed") ele.connectedEdges(".hypothesis").removeClass("hypothesis").addClass("confirmed");
  if (status === "rejected") ele.connectedEdges().addClass("rejected");
}

function placementFor(nodeId, edges) {
  const cy = state.cy;
  const anchors = edges
    .filter((e) => e.source === nodeId || e.target === nodeId)
    .map((e) => cy.getElementById(e.source === nodeId ? e.target : e.source))
    .filter((ele) => ele.nonempty() && !ele.hasClass("hidden"));
  const extent = cy.extent();
  if (anchors.length === 0) {
    return { x: extent.x1 + extent.w / 2 + jitter(60), y: extent.y1 + extent.h / 2 + jitter(60) };
  }
  const sum = anchors.reduce((acc, ele) => ({ x: acc.x + ele.position("x"), y: acc.y + ele.position("y") }), { x: 0, y: 0 });
  return { x: sum.x / anchors.length + jitter(40), y: sum.y / anchors.length + jitter(40) };
}

function jitter(range) {
  return (Math.random() - 0.5) * range;
}

function settleNeighborhood(added) {
  const cy = state.cy;
  const hood = added.union(added.neighborhood());
  const anchored = hood.nodes().not(added);
  anchored.lock();
  const layout = hood.layout({
    name: "cose",
    animate: true,
    animationDuration: 900,
    randomize: false,
    fit: false,
    nodeRepulsion: () => 3500,
    idealEdgeLength: () => 55,
    edgeElasticity: () => 150,
    gravity: 0.5,
    numIter: 400,
  });
  layout.on("layoutstop", () => anchored.unlock());
  layout.run();
}

const SETTLE_MS = 1000;

function focusSoon(eles) {
  setTimeout(() => {
    if (eles.nonempty() && !eles.removed()) focusOn(eles);
  }, SETTLE_MS);
}

function applyVisibility() {
  const cy = state.cy;
  cy.nodes(".rejected").forEach((node) => {
    if (node.hasClass("rejecting")) return;
    node.toggleClass("hidden", !state.showRejected);
    node.connectedEdges().toggleClass("hidden", !state.showRejected);
  });
}

function fadeOutRejected(node) {
  const edges = node.connectedEdges();
  node.addClass("rejecting");
  edges.addClass("rejecting");
  setTimeout(() => {
    node.removeClass("rejecting");
    edges.removeClass("rejecting");
    applyVisibility();
  }, REJECT_FADE_MS);
}

function clearGlow(node) {
  node.stop(true);
  node.animation({ style: { "underlay-padding": 8, "underlay-opacity": 0.15 }, duration: 400 }).play().promise().then(() => {
    if (!node.removed()) node.removeStyle("underlay-padding underlay-opacity");
  });
}

function pulse(node) {
  if (!node.hasClass("pulsing") || node.removed()) return;
  node
    .animation({ style: { "underlay-padding": 20, "underlay-opacity": 0.45 }, duration: 650, easing: "ease-in-out" })
    .play()
    .promise()
    .then(() => node.animation({ style: { "underlay-padding": 8, "underlay-opacity": 0.2 }, duration: 650, easing: "ease-in-out" }).play().promise())
    .then(() => pulse(node));
}

function startPulsing(nodes) {
  nodes.forEach((node) => {
    node.addClass("pulsing");
    pulse(node);
  });
}

function stopPulsing(runId) {
  const cy = state.cy;
  cy.nodes(".pulsing").filter((node) => node.data("run") === runId).forEach((node) => {
    node.removeClass("pulsing");
    clearGlow(node);
  });
  cy.nodes(".new").filter((node) => node.data("run") === runId).forEach((node) => {
    node.removeClass("new");
    node.addClass("existing recent");
    node.data("status", "existing");
  });
  cy.edges(".fresh").removeClass("fresh");
}

function renderGraphStats() {
  const cy = state.cy;
  el("graph-stats").textContent = `${cy.nodes().length} nodes · ${cy.edges().length} edges`;
}

function registerHypothesisNode(node) {
  const props = node.props || {};
  const existing = state.hypotheses.get(node.id) || {};
  state.hypotheses.set(node.id, {
    id: node.id,
    runId: props.run_id || existing.runId || null,
    caseIds: props.case_ids || existing.caseIds || [],
    confidence: props.confidence ?? existing.confidence ?? null,
    rationale: props.rationale || existing.rationale || "",
    fallback: props.fallback ?? existing.fallback ?? false,
    verdict: readVerdict(props) || existing.verdict || null,
    gaps: existing.gaps || null,
    decision: props.decision ?? existing.decision ?? null,
    decisionReason: props.decision_reason || existing.decisionReason || "",
    status: node.status || existing.status || "proposed",
    receivedAt: existing.receivedAt || Date.now(),
  });
}

function readVerdict(props) {
  if (props.critic && typeof props.critic === "object") return props.critic;
  if (typeof props.critic_verdict === "string") {
    return { verdict: props.critic_verdict, reasons: props.critic_reasons || [], would_change_mind: props.would_change_mind || [] };
  }
  return null;
}

function hypothesisEvidence(h) {
  const node = state.cy.getElementById(h.id);
  if (node.empty()) return [];
  return node
    .connectedEdges('[rel = "SUPPORTED_BY"]')
    .map((edge) => {
      const peer = edge.source().id() === h.id ? edge.target() : edge.source();
      const sharedBy = peer.neighborhood('node[type = "case"]').filter((c) => h.caseIds.includes(c.id())).length;
      return {
        type: peer.data("type"),
        label: peer.data("label"),
        provenance: provenanceText(edge.data("provenance")) || "graph",
        shared: `${sharedBy} of ${h.caseIds.length} cases`,
        confidence: edge.data("confidence"),
      };
    });
}

function provenanceText(value) {
  return [...new Set(asList(value))].join(", ");
}

function displayId(text) {
  return String(text).replace(ID_PREFIXES, "");
}

function caseName(caseId) {
  return String(caseId).replace(/^case:/, "").toUpperCase();
}

function matchedText(matched) {
  return asList(matched).map((m) => (typeof m === "string" ? m : `${m.kind}: ${m.label}`)).join(", ");
}

function renderHypotheses() {
  const container = el("hypotheses");
  const list = [...state.hypotheses.values()].sort((a, b) => b.receivedAt - a.receivedAt);
  el("review-count").textContent = list.length ? `${list.length} total` : "";
  if (list.length === 0 && state.noLinks.length === 0) {
    container.innerHTML = '<p class="empty">No hypotheses yet. Drop a case or pick a sample.</p>';
    return;
  }
  state.drafts = new Map(
    [...container.querySelectorAll(".hyp")].map((card) => [card.dataset.id, card.querySelector(".hyp-reason")?.value || ""])
  );
  const focused = document.activeElement?.closest?.(".hyp")?.dataset.id;
  const noLinkCards = [...state.noLinks].reverse().map(noLinkCard);
  container.replaceChildren(...noLinkCards, ...list.map(hypothesisCard));
  if (focused) {
    const reason = container.querySelector(`.hyp[data-id="${CSS.escape(focused)}"] .hyp-reason`);
    if (reason) {
      reason.focus();
      reason.setSelectionRange(reason.value.length, reason.value.length);
    }
  }
}

function noLinkCard(entry) {
  const card = document.createElement("article");
  card.className = "hyp";
  card.dataset.id = `none:${entry.runId}`;
  card.dataset.decision = "none";
  const head = document.createElement("div");
  head.className = "hyp-head";
  const title = document.createElement("span");
  title.className = "hyp-id";
  title.textContent = `${caseName(entry.caseId)} · no link proposed`;
  head.append(title);
  card.append(head);
  const top = entry.candidates.slice(0, 3);
  const label = document.createElement("div");
  label.className = "hyp-label";
  label.textContent = top.length ? "Closest cases" : "No candidate cases";
  card.append(label);
  if (top.length) {
    const ul = document.createElement("ul");
    ul.className = "hyp-evidence";
    top.forEach((c) => {
      const li = document.createElement("li");
      const type = document.createElement("span");
      type.className = "ev-type";
      type.textContent = `${caseName(c.case_id)} ${c.score}`;
      const detail = document.createElement("span");
      detail.textContent = matchedText(c.matched);
      li.append(type, detail);
      ul.append(li);
    });
    card.append(ul);
  }
  return card;
}

function hypothesisCard(h) {
  const card = document.createElement("article");
  card.className = "hyp";
  card.dataset.id = h.id;
  if (h.decision) card.dataset.decision = h.decision;
  card.append(hypothesisHead(h), hypothesisCases(h));
  if (h.rationale) {
    const p = document.createElement("p");
    p.className = "hyp-rationale";
    p.textContent = h.rationale;
    card.append(p);
  }
  card.append(hypothesisEvidenceList(h), verdictBlock(h.verdict));
  if (h.decision && h.decision !== "more") card.append(decidedLine(h));
  else card.append(decisionControls(h));
  if (h.gaps) card.append(gapsBlock(h.gaps));
  return card;
}

function hypothesisHead(h) {
  const head = document.createElement("div");
  head.className = "hyp-head";
  const id = document.createElement("span");
  id.className = "hyp-id";
  id.textContent = h.id.replace(/^hyp:/, "");
  const conf = document.createElement("span");
  conf.className = "hyp-conf";
  if (h.fallback) conf.textContent = `rule score ${Math.round((h.confidence || 0) * 12)}/12, fixed weights`;
  else conf.textContent = h.confidence == null ? "" : `linker estimate ${h.confidence.toFixed(2)}, unverified`;
  head.append(id, conf);
  return head;
}

function hypothesisCases(h) {
  const wrap = document.createElement("div");
  wrap.className = "hyp-cases";
  h.caseIds.forEach((caseId) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    if (state.sessionCaseIds.has(caseId)) chip.classList.add("new");
    chip.textContent = caseId.replace(/^case:/, "").toUpperCase();
    chip.addEventListener("click", () => showNode(caseId));
    wrap.append(chip);
  });
  return wrap;
}

function hypothesisEvidenceList(h) {
  const wrap = document.createElement("div");
  const label = document.createElement("div");
  label.className = "hyp-label";
  label.textContent = "Cited evidence";
  const ul = document.createElement("ul");
  ul.className = "hyp-evidence";
  const evidence = hypothesisEvidence(h);
  if (evidence.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No cited edges";
    ul.append(li);
  }
  evidence.forEach((ev) => {
    const li = document.createElement("li");
    const type = document.createElement("span");
    type.className = "ev-type";
    type.textContent = ev.type.replace("_", " ");
    const val = document.createElement("span");
    val.textContent = ev.label;
    const shared = document.createElement("span");
    shared.className = "ev-shared";
    shared.textContent = ev.shared;
    const prov = document.createElement("span");
    prov.className = "ev-prov";
    prov.textContent = ev.provenance;
    li.append(type, val, shared, prov);
    ul.append(li);
  });
  wrap.append(label, ul);
  return wrap;
}

function verdictBlock(verdict) {
  const box = document.createElement("div");
  box.className = "verdict";
  box.dataset.verdict = verdict ? verdict.verdict : "pending";
  const head = document.createElement("div");
  head.className = "verdict-head";
  const tag = document.createElement("span");
  tag.className = "verdict-tag";
  tag.textContent = verdict ? `Critic: ${verdict.verdict}` : "Critic: pending";
  head.append(tag);
  box.append(head);
  if (!verdict) return box;
  if (verdict.reasons && verdict.reasons.length) {
    const ul = document.createElement("ul");
    verdict.reasons.forEach((r) => {
      const li = document.createElement("li");
      li.textContent = r;
      ul.append(li);
    });
    box.append(ul);
  }
  const would = asList(verdict.would_change_mind);
  if (would.length) {
    const p = document.createElement("div");
    p.className = "would";
    p.textContent = `Would change its mind on: ${would.join("; ")}`;
    box.append(p);
  }
  return box;
}

function gapsBlock(gaps) {
  const box = document.createElement("div");
  box.className = "gaps";
  const label = document.createElement("div");
  label.className = "hyp-label";
  label.textContent = "Next steps";
  const ol = document.createElement("ol");
  gaps.next.forEach((step) => {
    const li = document.createElement("li");
    li.textContent = step;
    ol.append(li);
  });
  box.append(label, ol);
  gaps.missing.forEach((item) => {
    const line = document.createElement("div");
    line.className = "gap-missing";
    line.textContent = `Missing: ${item}`;
    box.append(line);
  });
  return box;
}

function asList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === "string" && value) return [value];
  return [];
}

function decisionControls(h) {
  const wrap = document.createElement("div");
  wrap.className = "hyp-decide";
  const reason = document.createElement("input");
  reason.className = "hyp-reason";
  reason.placeholder = "Reason for the record";
  reason.setAttribute("aria-label", `Reason for decision on ${h.id}`);
  reason.value = state.drafts.get(h.id) || "";
  const actions = document.createElement("div");
  actions.className = "hyp-actions";
  const make = (label, decision, cls) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `btn ${cls}`;
    btn.textContent = label;
    btn.addEventListener("click", () => submitDecision(h.id, decision, reason.value.trim(), actions));
    return btn;
  };
  actions.append(make("Accept", "accept", "btn-accept"), make("Reject", "reject", "btn-reject"), make("More", "more", "btn-more"));
  if (h.decision === "more") {
    const note = document.createElement("span");
    note.className = "hyp-decided";
    note.textContent = h.decisionReason ? `More evidence requested: ${h.decisionReason}` : "More evidence requested";
    wrap.append(note);
  }
  wrap.append(reason, actions);
  return wrap;
}

function decidedLine(h) {
  const line = document.createElement("div");
  line.className = "hyp-decided";
  const tag = document.createElement("span");
  tag.className = `decision-tag ${h.decision}`;
  tag.textContent = h.decision === "accept" ? "ACCEPTED BY DETECTIVE" : "REJECTED BY DETECTIVE";
  line.append(tag);
  if (h.decisionReason) line.append(` ${h.decisionReason}`);
  return line;
}

async function submitDecision(id, decision, reason, actions) {
  actions.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    if (MOCK) {
      applyMockDecision(id, decision, reason);
    } else {
      const delta = await api(`/api/hypotheses/${encodeURIComponent(id)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, reason }),
      });
      onDecision({
        type: "decision.recorded",
        run_id: state.hypotheses.get(id)?.runId,
        ts: new Date().toISOString(),
        agent: "detective",
        message: `${id.replace(/^hyp:/, "")} ${decision}${reason ? `: ${reason}` : ""}`,
        data: { hypothesis_id: id, decision, reason, nodes: delta.nodes, edges: delta.edges },
      });
    }
  } catch (err) {
    showError(`Decision on ${id} failed: ${err.message}`);
    actions.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}

function recordDecision(data) {
  const h = state.hypotheses.get(data.hypothesis_id);
  if (!h) return;
  h.decision = data.decision;
  h.decisionReason = data.reason || "";
  if (data.decision === "accept") h.status = "confirmed";
  if (data.decision === "reject") h.status = "rejected";
}

function showNode(id) {
  const cy = state.cy;
  const node = cy.getElementById(id);
  if (node.empty()) return;
  state.selectedNodeId = id;
  cy.nodes().unselect();
  node.select();
  renderDrawer(node);
  if (!MOCK && node.data("type") === "case") enrichCase(node);
}

async function enrichCase(node) {
  try {
    const detail = await api(`/api/cases/${encodeURIComponent(node.id())}`);
    const media = detail.media || (detail.node && detail.node.props && detail.node.props.media);
    const sources = detail.sources || (detail.node && detail.node.sources);
    if (media) node.data("props", { ...node.data("props"), media });
    if (sources) node.data("sources", sources);
    if (state.selectedNodeId === node.id()) renderDrawer(node);
  } catch (err) {
    consoleLine({ agent: "intake", ts: new Date().toISOString(), message: `Could not load detail for ${node.id()}: ${err.message}` }, "error");
  }
}

function renderDrawer(node) {
  const body = el("drawer-body");
  el("drawer-close").hidden = false;
  const props = node.data("props") || {};
  body.replaceChildren(nodeHead(node));
  const media = Array.isArray(props.media) ? props.media : [];
  if (media.length) body.append(labelled("Media", thumbnails(node, media)));
  body.append(propsList(props));
  if (Array.isArray(props.evidence) && props.evidence.length) body.append(labelled("Evidence", evidenceList(props.evidence)));
  body.append(labelled("Edges", edgeList(node)), labelled("Sources", sourceList(node.data("sources") || [])));
}

function nodeHead(node) {
  const head = document.createElement("div");
  head.className = "node-head";
  const id = document.createElement("span");
  id.className = "node-id";
  id.textContent = node.data("label");
  const type = document.createElement("span");
  type.className = "node-type";
  type.textContent = node.data("type").replace("_", " ");
  type.style.color = TYPE_STYLE[node.data("type")]?.color || "#c3ccdd";
  const status = document.createElement("span");
  status.className = "node-status";
  status.textContent = node.data("status");
  head.append(id, type, status);
  return head;
}

const PROP_SKIP = new Set(["media", "evidence", "critic", "critic_reasons", "would_change_mind"]);

function propsList(props) {
  const dl = document.createElement("dl");
  dl.className = "props";
  Object.entries(props).forEach(([key, value]) => {
    if (PROP_SKIP.has(key)) return;
    const dt = document.createElement("dt");
    dt.textContent = key.replace(/_/g, " ");
    const dd = document.createElement("dd");
    if (value == null || (Array.isArray(value) && value.length === 0)) {
      dd.textContent = "not reported";
      dd.className = "null";
    } else if (Array.isArray(value)) {
      dd.textContent = value.join(", ");
    } else if (typeof value === "object") {
      dd.textContent = Object.entries(value).map(([k, v]) => `${k}: ${v}`).join(", ");
    } else {
      dd.textContent = String(value);
    }
    dl.append(dt, dd);
  });
  return dl;
}

function labelled(title, content) {
  const wrap = document.createElement("div");
  const label = document.createElement("div");
  label.className = "hyp-label";
  label.textContent = title;
  wrap.append(label, content);
  return wrap;
}

function thumbnails(node, media) {
  const wrap = document.createElement("div");
  wrap.className = "thumbs";
  media.forEach((m) => {
    const url = mediaUrl(node, m);
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    a.title = `${m.kind || "media"} ${m.path || ""}`.trim();
    if (isImageMedia(m)) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = m.kind ? m.kind.replace(/_/g, " ") : "media";
      img.loading = "lazy";
      a.append(img);
    } else {
      a.className = "thumb-file";
      a.textContent = (m.path || "file").split("/").pop();
    }
    wrap.append(a);
  });
  return wrap;
}

function isImageMedia(media) {
  return media.kind === "image" || (media.kind !== "text" && media.kind !== "document" && /\.(jpe?g|png|gif|webp)$/i.test(media.path || ""));
}

function mediaUrl(node, media) {
  if (media.url) return media.url;
  if (!media.path) return null;
  if (/^https?:/.test(media.path)) return media.path;
  const props = node.data("props") || {};
  const file = media.path.split("/").pop();
  if (MOCK) {
    return props.series_id ? `../data/cases/${props.series_id}/${node.id()}/${media.path}` : null;
  }
  if (props.run_id) return `/api/uploads/${props.run_id}/${file}`;
  if (props.series_id) return `/api/media/${props.series_id}/${node.id()}/${file}`;
  return null;
}

function evidenceList(evidence) {
  const ul = document.createElement("ul");
  ul.className = "hyp-evidence";
  evidence.forEach((ev) => {
    const li = document.createElement("li");
    const type = document.createElement("span");
    type.className = "ev-type";
    type.textContent = (ev.type || "other").replace(/_/g, " ");
    const desc = document.createElement("span");
    desc.textContent = ev.description || "";
    li.append(type, desc);
    ul.append(li);
  });
  return ul;
}

function edgeList(node) {
  const ul = document.createElement("ul");
  ul.className = "edge-list";
  const edges = node.connectedEdges().filter((e) => state.showRejected || !e.hasClass("hidden"));
  if (edges.empty()) {
    const li = document.createElement("li");
    li.textContent = "No edges";
    ul.append(li);
    return ul;
  }
  edges.forEach((edge) => {
    const peer = edge.source().id() === node.id() ? edge.target() : edge.source();
    const li = document.createElement("li");
    const rel = document.createElement("span");
    rel.className = "rel";
    rel.textContent = edge.data("rel");
    const peerEl = document.createElement("span");
    peerEl.className = "peer";
    peerEl.textContent = peer.data("label");
    peerEl.addEventListener("click", () => showNode(peer.id()));
    const kind = document.createElement("span");
    kind.className = `kind ${edge.data("kind")}`;
    const source = provenanceText(edge.data("provenance"));
    kind.textContent = source ? `${edge.data("kind")} · ${source}` : edge.data("kind");
    li.append(rel, peerEl, kind);
    ul.append(li);
  });
  return ul;
}

function sourceList(sources) {
  const ul = document.createElement("ul");
  ul.className = "source-list";
  if (!sources.length) {
    const li = document.createElement("li");
    li.textContent = "No sources recorded";
    ul.append(li);
    return ul;
  }
  sources.forEach((src) => {
    const li = document.createElement("li");
    if (/^https?:/.test(src)) {
      const a = document.createElement("a");
      a.href = src;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = src.replace(/^https?:\/\//, "");
      li.append(a);
    } else {
      li.textContent = src;
    }
    ul.append(li);
  });
  return ul;
}

function clearDrawer() {
  state.selectedNodeId = null;
  state.cy.nodes().unselect();
  el("drawer-close").hidden = true;
  el("drawer-body").innerHTML = '<p class="empty">Click a node to see its properties, edges and sources.</p>';
}

function bindDrawer() {
  el("drawer-close").addEventListener("click", clearDrawer);
}

function bindReviewControls() {
  el("audit-toggle").addEventListener("change", (evt) => {
    state.showRejected = evt.target.checked;
    applyVisibility();
    if (state.selectedNodeId) showNode(state.selectedNodeId);
  });
  el("error-dismiss").addEventListener("click", hideError);
}

function handleEvent(evt) {
  state.eventCount += 1;
  el("console-count").textContent = `${state.eventCount} events`;
  const stage = STAGE_BY_EVENT[evt.type];
  if (stage && evt.run_id === state.currentRunId && !state.runs.get(evt.run_id)?.finished) setStage(stage);
  if (evt.type === "link.candidates") {
    const run = state.runs.get(evt.run_id);
    if (run) run.candidates = (evt.data || {}).candidates || [];
  }
  switch (evt.type) {
    case "run.started":
      onRunStarted(evt);
      break;
    case "build.nodes":
      onBuildNodes(evt);
      break;
    case "link.hypothesis":
      onHypothesis(evt);
      break;
    case "critic.verdict":
      onVerdict(evt);
      break;
    case "decision.recorded":
      onDecision(evt);
      break;
    case "gap.next_steps":
      onGaps(evt);
      break;
    case "run.finished":
      onRunFinished(evt);
      break;
    case "run.error":
      onRunError(evt);
      break;
    default:
      consoleLine(evt, "info", eventDetail(evt));
  }
}

function onRunStarted(evt) {
  const data = evt.data || {};
  state.currentRunId = evt.run_id;
  state.runs.set(evt.run_id, { startedAt: Date.parse(evt.ts) || Date.now(), wallStart: Date.now(), caseId: data.case_id, firstProposalAt: null, finished: false, candidates: [] });
  state.activeRuns.add(evt.run_id);
  updateRunButtons();
  state.cy.nodes(".recent, .linked").removeClass("recent linked");
  if (data.case_id) state.sessionCaseIds.add(data.case_id);
  resetStages();
  setStage("intake");
  startClock(evt.run_id);
  hideError();
  consoleLine(evt, "milestone");
}

function onBuildNodes(evt) {
  const data = evt.data || {};
  (data.nodes || []).forEach((n) => {
    if (n.type === "case") state.sessionCaseIds.add(n.id);
  });
  const added = applyDelta(data.nodes || [], data.edges || []);
  const fresh = added.filter(".new");
  fresh.forEach((node) => node.data("run", evt.run_id));
  startPulsing(fresh);
  if (added.nonempty()) focusSoon(added.filter('[type = "case"]').nonempty() ? added.filter('[type = "case"]') : added);
  consoleLine(evt, "milestone");
}

function onHypothesis(evt) {
  const data = evt.data || {};
  const node = data.hypothesis || data.node;
  if (!node) return consoleLine(evt, "info");
  node.props = { ...(node.props || {}), rationale: node.props?.rationale || data.rationale, confidence: node.props?.confidence ?? data.confidence, run_id: node.props?.run_id || evt.run_id };
  const added = applyDelta([node], data.edges || []);
  const proposed = added.filter(".proposed");
  proposed.forEach((n) => n.data("run", evt.run_id));
  startPulsing(proposed);
  const linkedCases = proposed.connectedEdges('[rel = "PROPOSES_LINK"]').connectedNodes('[type = "case"]');
  linkedCases.addClass("linked");
  if (proposed.nonempty()) focusSoon(proposed.union(linkedCases));
  const run = state.runs.get(evt.run_id);
  if (run && !run.firstProposalAt) run.firstProposalAt = Date.parse(evt.ts) || Date.now();
  renderHypotheses();
  refreshMetrics();
  consoleLine(evt, "milestone", data.rationale || node.props.rationale || "");
}

function onVerdict(evt) {
  const data = evt.data || {};
  const h = state.hypotheses.get(data.hypothesis_id);
  if (h) h.verdict = { verdict: data.verdict, reasons: data.reasons || [], would_change_mind: data.would_change_mind || [] };
  const node = state.cy.getElementById(data.hypothesis_id);
  if (node.nonempty()) node.data("props", { ...node.data("props"), critic_verdict: data.verdict });
  renderHypotheses();
  consoleLine(evt, "milestone", (data.reasons || []).map((r) => `• ${r}`).join("\n"));
}

function onDecision(evt) {
  const data = evt.data || {};
  if (state.hypotheses.get(data.hypothesis_id)?.decision === data.decision) return;
  recordDecision(data);
  applyDelta(data.nodes || [], data.edges || []);
  const node = state.cy.getElementById(data.hypothesis_id);
  if (node.nonempty()) {
    node.removeClass("pulsing");
    clearGlow(node);
    node.data("props", { ...node.data("props"), decision: data.decision, decision_reason: data.reason || "" });
    if (data.decision === "accept" && !node.hasClass("confirmed")) setNodeStatus(node, "confirmed");
    if (data.decision === "reject" && !node.hasClass("rejected")) setNodeStatus(node, "rejected");
    if (data.decision === "accept") {
      const decided = node.connectedEdges();
      (data.edges || []).forEach((edge) => decided.merge(state.cy.getElementById(edge.id)));
      decided.addClass("decided");
    }
    if (data.decision === "reject") fadeOutRejected(node);
    if (data.decision !== "more") focusOn(node);
  }
  applyVisibility();
  renderHypotheses();
  refreshMetrics();
  consoleLine(evt, "milestone", data.reason || "");
}

function onRunFinished(evt) {
  const data = evt.data || {};
  const run = state.runs.get(evt.run_id);
  if (run) run.finished = true;
  state.activeRuns.delete(evt.run_id);
  updateRunButtons();
  stopPulsing(evt.run_id);
  applyDelta(data.nodes || [], []);
  if (data.hypotheses === 0 && run) {
    state.noLinks.push({ runId: evt.run_id, caseId: data.case_id || run.caseId, candidates: run.candidates || [] });
  }
  renderHypotheses();
  refreshMetrics();
  consoleLine(evt, "milestone", data.hypotheses === 0 ? "No hypotheses proposed" : "");
  if (evt.run_id !== state.currentRunId) return;
  stopClock(data.seconds);
  markStagesDone();
  setStage("review");
  setTimeout(() => {
    if (state.activeRuns.size === 0) releaseView();
  }, RELEASE_VIEW_DELAY_MS);
}

function onGaps(evt) {
  const data = evt.data || {};
  const h = state.hypotheses.get(data.hypothesis_id);
  if (h) h.gaps = { missing: asList(data.missing), next: asList(data.next_steps) };
  renderHypotheses();
  consoleLine(evt, "milestone", eventDetail(evt));
}

function updateRunButtons() {
  const busy = state.activeRuns.size > 0 || state.submitting;
  document.querySelectorAll("[data-demo], #add-case").forEach((button) => (button.disabled = busy));
}

function onRunError(evt) {
  const data = evt.data || {};
  const stageForStep = STAGE_BY_STEP[data.step];
  if (stageForStep) markStage(stageForStep, "failed");
  showError(`Run error at ${data.step || "unknown step"}: ${data.message || evt.message || "no detail"}`);
  consoleLine(evt, "error", data.step ? `step: ${data.step}` : "");
}

function eventDetail(evt) {
  const data = evt.data || {};
  switch (evt.type) {
    case "intake.file":
      return "";
    case "observe.photo":
      return (data.observations || []).map((o) => `${o.type}: ${o.description} (${Math.round((o.confidence || 0) * 100)}%)`).join("\n");
    case "extract.text": {
      const r = data.record || {};
      return [r.entry_method && `entry: ${r.entry_method}`, r.vehicle && `vehicle: ${r.vehicle}`, r.items_taken && `items: ${asList(r.items_taken).join(", ")}`, r.unknowns && `unknown: ${asList(r.unknowns).join(", ")}`].filter(Boolean).join("\n");
    }
    case "link.candidates":
      return (data.candidates || []).map((c) => `${caseName(c.case_id)} ${c.score}  ${matchedText(c.matched)}`).join("\n");
    case "link.tool_call":
      return data.summary || "";
    case "gap.next_steps":
      return [...asList(data.missing).map((m) => `missing: ${m}`), ...asList(data.next_steps).map((s) => `next: ${s}`)].join("\n");
    default:
      return "";
  }
}

function consoleLine(evt, level = "info", detail = "") {
  const list = el("console");
  const li = document.createElement("li");
  li.className = `lvl-${level}`;
  if (evt.agent === "detective") li.classList.add("human");
  const agent = AGENTS[evt.agent] || { short: evt.agent || "system", color: "var(--muted)" };
  li.style.setProperty("--agent-color", agent.color);
  const t = document.createElement("span");
  t.className = "t";
  t.textContent = clockTime(evt.ts);
  const a = document.createElement("span");
  a.className = "a";
  a.textContent = agent.short;
  const m = document.createElement("span");
  m.className = "m";
  m.textContent = displayId(evt.message || evt.type);
  li.append(t, a, m);
  if (detail && !(evt.message && evt.message.includes(detail))) {
    const d = document.createElement("span");
    d.className = "detail";
    d.textContent = displayId(detail);
    li.append(d);
  }
  list.append(li);
  while (list.children.length > CONSOLE_LIMIT) list.removeChild(list.firstChild);
  list.scrollTop = list.scrollHeight;
}

function clockTime(ts) {
  const d = ts ? new Date(ts) : new Date();
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

function setStage(stage) {
  const items = [...el("pipeline").children];
  const idx = STAGE_ORDER.indexOf(stage);
  items.forEach((li, i) => {
    if (li.classList.contains("failed")) return;
    li.classList.toggle("active", i === idx);
    if (i < idx) li.classList.add("done");
  });
}

function markStage(stage, cls) {
  const li = el("pipeline").querySelector(`[data-stage="${stage}"]`);
  if (li) li.classList.add(cls);
}

function markStagesDone() {
  const reviewIndex = STAGE_ORDER.indexOf("review");
  [...el("pipeline").children].forEach((li, i) => {
    li.classList.remove("active");
    if (i < reviewIndex && !li.classList.contains("failed")) li.classList.add("done");
  });
}

function resetStages() {
  [...el("pipeline").children].forEach((li) => li.classList.remove("active", "done", "failed"));
}

function startClock(runId) {
  const clock = el("run-clock");
  clock.hidden = false;
  clearInterval(state.clockTimer);
  state.clockTimer = setInterval(() => {
    const run = state.runs.get(runId);
    if (!run) return;
    clock.title = runId;
    clock.textContent = `${displayId(run.caseId || runId)} · ${((Date.now() - run.wallStart) / 1000).toFixed(1)}s`;
  }, 200);
}

function stopClock(seconds) {
  clearInterval(state.clockTimer);
  const clock = el("run-clock");
  const run = state.runs.get(state.currentRunId);
  const name = displayId(run && run.caseId ? run.caseId : state.currentRunId);
  if (name) clock.textContent = `${name} · done in ${seconds != null ? Number(seconds).toFixed(1) : "?"}s`;
}

function showError(message) {
  el("error-text").textContent = message;
  el("error-banner").hidden = false;
  document.body.classList.add("has-banner");
  state.cy.resize();
}

function hideError() {
  el("error-banner").hidden = true;
  document.body.classList.remove("has-banner");
  state.cy.resize();
}

function setConnection(stateName, label) {
  el("conn").dataset.state = stateName;
  el("conn-label").textContent = label;
}

function bindIntake() {
  const zone = el("dropzone");
  const input = el("file-input");
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter" || evt.key === " ") {
      evt.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => addFiles([...input.files]));
  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (evt) => {
      evt.preventDefault();
      zone.classList.add("over");
    })
  );
  ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, () => zone.classList.remove("over")));
  zone.addEventListener("drop", (evt) => {
    evt.preventDefault();
    addFiles([...evt.dataTransfer.files]);
  });
  el("add-case").addEventListener("click", submitCase);
  document.querySelectorAll("[data-demo]").forEach((btn) => btn.addEventListener("click", () => runDemo(btn.dataset.demo)));
}

function addFiles(files) {
  state.pendingFiles = [...state.pendingFiles, ...files];
  const list = el("file-list");
  list.replaceChildren(
    ...state.pendingFiles.map((f) => {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = f.name;
      const size = document.createElement("span");
      size.textContent = formatSize(f.size);
      li.append(name, size);
      return li;
    })
  );
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function submitCase() {
  if (state.pendingFiles.length === 0) {
    showError("Add at least one file before adding a case.");
    return;
  }
  state.submitting = true;
  updateRunButtons();
  try {
    if (MOCK) {
      consoleLine({ agent: "intake", ts: new Date().toISOString(), message: `Mock mode: replaying the renton-a storyboard for ${state.pendingFiles.length} dropped file(s)` });
      await replayMock();
    } else {
      const form = new FormData();
      state.pendingFiles.forEach((f) => form.append("files[]", f, f.name));
      appendIfSet(form, "date", el("field-date").value);
      appendIfSet(form, "location", el("field-location").value);
      appendIfSet(form, "scene_type", el("field-scene").value);
      const res = await api("/api/cases", { method: "POST", body: form });
      consoleLine({ agent: "intake", ts: new Date().toISOString(), message: `Queued ${res.case_id || "case"} as ${res.run_id || "run"}` });
    }
    state.pendingFiles = [];
    el("file-list").replaceChildren();
    el("file-input").value = "";
  } catch (err) {
    showError(`Add case failed: ${err.message}`);
  } finally {
    state.submitting = false;
    updateRunButtons();
  }
}

function appendIfSet(form, key, value) {
  if (value) form.append(key, value);
}

async function runDemo(name) {
  state.submitting = true;
  updateRunButtons();
  try {
    if (MOCK) {
      await replayMock(name);
    } else {
      const res = await api(`/api/demo/${encodeURIComponent(name)}`, { method: "POST" });
      consoleLine({ agent: "intake", ts: new Date().toISOString(), message: `Queued sample ${name} as ${res.run_id || "run"}` });
    }
  } catch (err) {
    showError(`Sample ${name} failed: ${err.message}`);
  } finally {
    state.submitting = false;
    updateRunButtons();
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let text = "";
    try {
      text = await res.text();
    } catch (err) {
      text = "";
    }
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text.slice(0, 160)}` : ""}`);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

async function startLive() {
  setConnection("idle", "Loading");
  try {
    const graph = await api("/api/graph");
    loadGraph(graph);
  } catch (err) {
    el("graph-empty").textContent = "Graph unavailable";
    showError(`Could not load /api/graph: ${err.message}. Add ?mock=1 to the URL to run without the backend.`);
  }
  connectEvents();
  refreshMetrics();
}

const RECONNECT_DELAY_MS = 2000;

function connectEvents() {
  const source = new EventSource("/api/events");
  let dropped = false;
  source.onopen = () => {
    setConnection("live", "Live");
    if (dropped) resync();
    dropped = false;
  };
  source.onerror = () => {
    dropped = true;
    setConnection("reconnecting", "Reconnecting");
    if (source.readyState === EventSource.CLOSED) {
      source.close();
      setTimeout(connectEvents, RECONNECT_DELAY_MS);
    }
  };
  source.onmessage = (msg) => {
    let evt;
    try {
      evt = JSON.parse(msg.data);
    } catch (err) {
      consoleLine({ agent: "intake", ts: new Date().toISOString(), message: `Unreadable event: ${err.message}` }, "error");
      return;
    }
    try {
      handleEvent(evt);
    } catch (err) {
      console.error(err);
      consoleLine({ agent: "intake", ts: new Date().toISOString(), message: `Display error on ${evt.type}: ${err.message}` }, "error");
    }
  };
}

async function resync() {
  try {
    const [graph, audit] = await Promise.all([api("/api/graph"), api("/api/audit")]);
    applyDelta(graph.nodes || [], graph.edges || []);
    const finished = (audit.entries || []).filter((entry) => entry.type === "run.finished");
    [...state.activeRuns].forEach((runId) => {
      const entry = finished.find((e) => e.run_id === runId);
      if (entry) handleEvent(entry);
    });
    renderHypotheses();
    refreshMetrics();
  } catch (err) {
    showError(`Could not resync after reconnecting: ${err.message}`);
  }
}

async function refreshMetrics() {
  if (MOCK) return renderMetrics(localMetrics());
  try {
    const audit = await api("/api/audit");
    renderMetrics(normalizeMetrics(audit.metrics || audit));
  } catch (err) {
    renderMetrics(localMetrics());
  }
}

function normalizeMetrics(m) {
  const pick = (...keys) => keys.map((k) => m[k]).find((v) => v != null) ?? 0;
  return {
    cases: pick("cases_added", "cases"),
    proposed: pick("hypotheses_proposed", "proposed", "hypotheses"),
    accepted: pick("accepted", "hypotheses_accepted"),
    rejected: pick("rejected", "hypotheses_rejected"),
    median: pick("median_seconds_to_proposal", "median_seconds", "median_drop_to_proposal_seconds"),
  };
}

function localMetrics() {
  const hyps = [...state.hypotheses.values()];
  const durations = [...state.runs.values()].filter((r) => r.firstProposalAt).map((r) => (r.firstProposalAt - r.startedAt) / 1000);
  return {
    cases: state.sessionCaseIds.size,
    proposed: hyps.length,
    accepted: hyps.filter((h) => h.decision === "accept").length,
    rejected: hyps.filter((h) => h.decision === "reject").length,
    median: median(durations),
  };
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function renderMetrics(m) {
  el("m-cases").textContent = m.cases;
  el("m-proposed").textContent = m.proposed;
  el("m-accepted").textContent = m.accepted;
  el("m-rejected").textContent = m.rejected;
  el("m-median").textContent = `${Number(m.median || 0).toFixed(1)}s`;
}

async function startMock() {
  setConnection("mock", "Mock replay");
  try {
    const [graph, events] = await Promise.all([api(MOCK_GRAPH_URL), api(MOCK_EVENTS_URL)]);
    state.mockGraph = graph;
    state.mockEvents = events;
    loadGraph(graph);
    renderMetrics(localMetrics());
    consoleLine({ agent: "intake", ts: new Date().toISOString(), message: `Mock graph loaded: ${graph.nodes.length} nodes, ${graph.edges.length} edges. Replay starts in a moment` });
    setTimeout(() => replayMock(), 1500);
  } catch (err) {
    showError(`Mock data failed to load: ${err.message}`);
  }
}

function replayMock(name = "renton-a") {
  if (state.mockReplayHandle) {
    clearTimeout(state.mockReplayHandle);
    state.mockReplayHandle = null;
  }
  if (state.mockReplayed) resetMockGraph();
  state.mockReplayed = true;
  const sequence = state.mockEvents.replays?.[name] || state.mockEvents.replay;
  return scheduleSequence(sequence.map(withLiveTimestamp));
}

function resetMockGraph() {
  state.sessionCaseIds.clear();
  state.runs.clear();
  state.activeRuns.clear();
  state.noLinks = [];
  updateRunButtons();
  clearDrawer();
  loadGraph(state.mockGraph);
  renderMetrics(localMetrics());
}

function withLiveTimestamp(step) {
  return { ...step, event: { ...step.event, ts: new Date().toISOString() } };
}

function scheduleSequence(steps) {
  return new Promise((resolve) => {
    let index = 0;
    const next = () => {
      if (index >= steps.length) {
        state.mockReplayHandle = null;
        resolve();
        return;
      }
      const step = steps[index++];
      state.mockReplayHandle = setTimeout(() => {
        handleEvent({ ...step.event, ts: new Date().toISOString() });
        next();
      }, step.after_ms || 0);
    };
    next();
  });
}

function applyMockDecision(id, decision, reason) {
  const template = state.mockEvents.after_decision[decision];
  if (!template) throw new Error(`no mock decision for ${decision}`);
  const evt = { ...template, ts: new Date().toISOString(), data: { ...template.data, hypothesis_id: id, reason: reason || template.data.reason } };
  handleEvent(evt);
  if (decision === "accept" && state.mockEvents.after_accept) scheduleSequence(state.mockEvents.after_accept);
}

document.addEventListener("DOMContentLoaded", init);
