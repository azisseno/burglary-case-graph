import threading
from concurrent.futures import ThreadPoolExecutor

from . import agents, tools
from .cli import CliError

PAIR_SCORE_MINIMUM = 6
CLUSTER_CAP = 12
CLUSTER_WORKERS = 4


def case_city(graph, case_id):
    for item in tools.case_attributes(graph, case_id)["location"]:
        city = item["node"]["props"].get("city", "").lower()
        if city:
            return city
    return ""


def scored_pairs(graph, minimum=PAIR_SCORE_MINIMUM):
    case_ids = [n["id"] for n in graph.nodes_of_type("case")]
    cities = {cid: case_city(graph, cid) for cid in case_ids}
    pairs = {}
    for case_id in case_ids:
        if not cities[case_id]:
            continue
        for candidate in tools.cluster_candidates(graph, case_id, limit=len(case_ids)):
            other = candidate["case_id"]
            if candidate["score"] >= minimum and cities.get(other) == cities[case_id]:
                key = tuple(sorted((case_id, other)))
                pairs[key] = max(pairs.get(key, 0), candidate["score"])
    return pairs


def candidate_clusters(graph, minimum=PAIR_SCORE_MINIMUM):
    pairs = scored_pairs(graph, minimum)
    confirmed = {n["id"] for n in graph.nodes_of_type("case") if tools.case_series(graph, n["id"])}
    parent = {}

    def find(item):
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for (first, second), _ in pairs.items():
        if first in confirmed and second in confirmed:
            continue
        if first in confirmed or second in confirmed:
            find(second if first in confirmed else first)
            continue
        parent[find(first)] = find(second)
    members, anchors, top_score = {}, {}, {}
    for item in list(parent):
        members.setdefault(find(item), set()).add(item)
    for (first, second), pair_score in pairs.items():
        for member, other in ((first, second), (second, first)):
            if member not in confirmed and other in confirmed:
                root = find(member)
                anchors.setdefault(root, set()).add(other)
        if first not in confirmed or second not in confirmed:
            root = find(first if first not in confirmed else second)
            top_score[root] = max(top_score.get(root, 0), pair_score)
    clusters = []
    for root, group in members.items():
        anchor_ids = sorted(anchors.get(root, ()))
        case_ids = sorted(group | set(anchor_ids))
        if len(case_ids) >= 2:
            clusters.append({"case_ids": case_ids, "member_ids": sorted(group), "anchor_ids": anchor_ids,
                             "max_score": top_score.get(root, 0)})
    clusters.sort(key=lambda c: (-len(c["case_ids"]), c["case_ids"]))
    for number, cluster in enumerate(clusters, 1):
        cluster["id"] = f"cluster-{number}"
    return clusters


def select_clusters(clusters, cap=CLUSTER_CAP):
    return clusters[:cap], clusters[cap:]


def already_reviewed(graph, cluster):
    members = set(cluster["case_ids"])
    return any(set(h["props"]["case_ids"]) == members and h["status"] in ("proposed", "rejected")
               for h in graph.nodes_of_type("hypothesis"))


def cluster_hypotheses(pipeline, run_id, cluster, claimed, claim_lock):
    case_ids = set(cluster["case_ids"])
    chosen = []
    for hypothesis in pipeline.run_hypotheses(run_id):
        if not set(hypothesis["props"]["case_ids"]) <= case_ids:
            continue
        with claim_lock:
            if hypothesis["id"] in claimed:
                continue
            claimed.add(hypothesis["id"])
        chosen.append(hypothesis)
    return chosen


def review_cluster(pipeline, run_id, cluster, claimed, claim_lock):
    run_dir = pipeline.runs_dir / run_id / "finder" / cluster["id"]
    pipeline.event("finder.cluster_started", run_id, "finder",
                   f"{cluster['id']}: reviewing {len(cluster['case_ids'])} cases",
                   {"cluster_id": cluster["id"], "case_ids": cluster["case_ids"], "anchor_ids": cluster["anchor_ids"]})
    try:
        agents.run_linker(pipeline.api_base, cluster["case_ids"], run_id, run_dir, pipeline.emit,
                          graph=pipeline.graph, anchor_ids=cluster["anchor_ids"])
    except CliError as error:
        pipeline.report_error(run_id, "linker", f"linker_{cluster['id']}", f"Linker for {cluster['id']}", error)
    pipeline.announce(run_id)
    hypotheses = cluster_hypotheses(pipeline, run_id, cluster, claimed, claim_lock)
    for hypothesis in hypotheses:
        pipeline.save()
        pipeline.critique(run_id, hypothesis, run_dir)
    pipeline.save()
    return len(hypotheses)


def review_safely(pipeline, run_id, cluster, claimed, claim_lock):
    try:
        return review_cluster(pipeline, run_id, cluster, claimed, claim_lock)
    except Exception as error:
        pipeline.report_error(run_id, "finder", f"finder_{cluster['id']}", f"Finder for {cluster['id']}", error)
        return 0


def run_finder(pipeline, run_id):
    clusters = [c for c in candidate_clusters(pipeline.graph) if not already_reviewed(pipeline.graph, c)]
    reviewed, dropped = select_clusters(clusters)
    dropped_ids = [c["id"] for c in dropped]
    message = f"{len(clusters)} candidate clusters, {len(reviewed)} to review"
    if dropped_ids:
        message += f"; dropped the smallest {len(dropped_ids)}: {', '.join(dropped_ids)}"
    pipeline.event("finder.clusters", run_id, "finder", message,
                   {"clusters": clusters, "reviewed": [c["id"] for c in reviewed], "dropped": dropped_ids})
    claimed, claim_lock = set(), threading.Lock()
    with pipeline.state_lock:
        pipeline.linker_runs.add(run_id)
    try:
        with ThreadPoolExecutor(CLUSTER_WORKERS) as pool:
            counts = list(pool.map(lambda cluster: review_safely(pipeline, run_id, cluster, claimed, claim_lock), reviewed))
    finally:
        with pipeline.state_lock:
            pipeline.linker_runs.discard(run_id)
    total = sum(counts)
    pipeline.event("finder.finished", run_id, "finder", f"Finder reviewed {len(reviewed)} clusters and found {total} hypotheses",
                   {"clusters": len(clusters), "reviewed": len(reviewed), "dropped": len(dropped_ids), "hypotheses": total})
    pipeline.emit_score(run_id)
    return total
