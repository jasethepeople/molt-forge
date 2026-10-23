"""Investigation graph: repos, modules, findings, artifacts and their relations."""

from __future__ import annotations

import json


class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []

    def add_node(self, node_id: str, kind: str, label: str, data: dict | None = None):
        self.nodes[node_id] = {"id": node_id, "kind": kind, "label": label, "data": data or {}}
        return node_id

    def add_edge(self, src: str, dst: str, relation: str):
        self.edges.append({"from": src, "to": dst, "relation": relation})

    def to_dict(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": self.edges}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())
