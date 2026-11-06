import copy
import json
import os
import tempfile
import threading
from pathlib import Path


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.counters = {"hypothesis": 0, "case": 0, "edge": 0}
        self.lock = threading.RLock()

    def add_node(self, node_id, node_type, label, status="existing", props=None, sources=None):
        with self.lock:
            existing = self.nodes.get(node_id)
            if existing:
                if props:
                    existing["props"].update(props)
                for s in sources or []:
                    if s not in existing["sources"]:
                        existing["sources"].append(s)
                return existing
            node = {
                "id": node_id,
                "type": node_type,
                "label": label,
                "status": status,
                "props": dict(props or {}),
                "sources": list(sources or []),
            }
            self.nodes[node_id] = node
            return node

    def add_edge(self, source, target, rel, kind="observed", provenance=None, confidence=None, edge_id=None, cites=None):
        provenance = [p for p in ([provenance] if isinstance(provenance, str) else provenance or []) if p]
        if not provenance:
            raise ValueError(f"edge {source} -> {target} needs a provenance")
        with self.lock:
            if source not in self.nodes or target not in self.nodes:
                raise KeyError(f"edge endpoints must exist: {source} -> {target}")
            edge_id = edge_id or f"{source}|{rel}|{target}"
            existing = self.edges.get(edge_id)
            if existing:
                for item in provenance:
                    if item not in existing["provenance"]:
                        existing["provenance"].append(item)
                return existing
            edge = {
                "id": edge_id,
                "source": source,
                "target": target,
                "rel": rel,
                "kind": kind,
                "confidence": confidence,
                "provenance": provenance,
            }
            if cites:
                edge["cites"] = cites
            self.edges[edge_id] = edge
            return edge

    def set_status(self, node_id, status):
        with self.lock:
            self.nodes[node_id]["status"] = status
            return self.nodes[node_id]

    def set_edge_kind(self, edge_id, kind):
        with self.lock:
            self.edges[edge_id]["kind"] = kind
            return self.edges[edge_id]

    def next_id(self, kind):
        with self.lock:
            self.counters[kind] = self.counters.get(kind, 0) + 1
            return self.counters[kind]

    def edges_of(self, node_id, rel=None):
        with self.lock:
            return [
                e for e in self.edges.values()
                if (e["source"] == node_id or e["target"] == node_id) and (rel is None or e["rel"] == rel)
            ]

    def neighbors(self, node_id, rel=None):
        with self.lock:
            out = []
            for e in self.edges_of(node_id, rel):
                other = e["target"] if e["source"] == node_id else e["source"]
                out.append((self.nodes[other], e))
            return out

    def nodes_of_type(self, node_type):
        with self.lock:
            return [n for n in self.nodes.values() if n["type"] == node_type]

    def stats(self):
        with self.lock:
            by_type = {}
            for n in self.nodes.values():
                by_type[n["type"]] = by_type.get(n["type"], 0) + 1
            by_kind = {}
            for e in self.edges.values():
                by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
            return {"nodes": len(self.nodes), "edges": len(self.edges), "by_type": by_type, "by_kind": by_kind}

    def to_dict(self):
        with self.lock:
            return copy.deepcopy({
                "nodes": list(self.nodes.values()),
                "edges": list(self.edges.values()),
                "stats": self.stats(),
                "counters": dict(self.counters),
            })

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            text = json.dumps(self.to_dict(), indent=1)
        descriptor, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
        Path(tmp).replace(path)

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text())
        graph = cls()
        for n in data["nodes"]:
            graph.nodes[n["id"]] = n
        for e in data["edges"]:
            graph.edges[e["id"]] = e
        graph.counters.update(data.get("counters", {}))
        return graph
