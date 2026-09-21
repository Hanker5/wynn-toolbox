"""Exact ability-tree selection as a mixed-integer program (scipy/HiGHS).

Constraints mirror WynnBuilder's activation rules:
  * every selected node is reached from the root through selected parents, with
    level variables ordering the path (mutual-parent cycles cannot fake a link);
  * dependencies selected, blockers excluded;
  * archetype requirements counted only over nodes activated EARLIER, via
    pairwise ordering variables;
  * total cost within the ability-point cap.
"""
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

AP_PENALTY = 0.02   # per ability point, so zero-value nodes are not added as padding


def solve_tree(tree, weights, ap_cap):
    """weights: {node display name: value}. Returns the set of selected node ids."""
    nodes = sorted(tree, key=lambda n: n["id"])
    idx = {n["id"]: k for k, n in enumerate(nodes)}
    name_to_id = {n["display_name"]: n["id"] for n in nodes}
    unknown = set(weights) - set(name_to_id)
    if unknown:
        raise KeyError(f"nodes not in this tree: {sorted(unknown)}")
    nv = len(nodes)
    root = next(n["id"] for n in nodes if not n["parents"])
    edges = [(p, n["id"]) for n in nodes for p in n["parents"]]
    eidx = {e: i for i, e in enumerate(edges)}
    arch_of = lambda n: n.get("req_archetype") or n.get("archetype")
    reqs = [n for n in nodes if n.get("archetype_req")]
    pairs = [(m["id"], n["id"]) for n in reqs for m in nodes
             if m["id"] != n["id"] and m.get("archetype") == arch_of(n)]
    pidx = {p: i for i, p in enumerate(pairs)}
    ne, npair, big = len(edges), len(pairs), nv + 1
    X = lambda i: i
    Y = lambda i: nv + i
    L = lambda i: nv + ne + i
    Z = lambda i: nv + ne + nv + i
    total = nv + ne + nv + npair

    obj = np.zeros(total)
    for name, w in weights.items():
        obj[X(idx[name_to_id[name]])] += w
    for n in nodes:
        obj[X(idx[n["id"]])] -= AP_PENALTY * (n.get("cost") or 0)

    rows, lo, hi = [], [], []

    def row(terms, lower, upper):
        r = np.zeros(total)
        for k, v in terms:
            r[k] += v
        rows.append(r)
        lo.append(lower)
        hi.append(upper)

    row([(X(idx[root]), 1)], 1, 1)
    row([(L(idx[root]), 1)], 0, 0)
    for n in nodes:
        k = idx[n["id"]]
        if n["id"] != root:   # selected <=> exactly one activating parent edge
            row([(X(k), -1)] + [(Y(eidx[(p, n["id"])]), 1) for p in n["parents"]], 0, 0)
        for d in n.get("dependencies") or []:
            row([(X(k), 1), (X(idx[d]), -1)], -np.inf, 0)
        for b in n.get("blockers") or []:
            row([(X(k), 1), (X(idx[b]), 1)], -np.inf, 1)
    for (p, c), i in eidx.items():
        row([(Y(i), 1), (X(idx[p]), -1)], -np.inf, 0)
        row([(L(idx[p]), 1), (L(idx[c]), -1), (Y(i), big)], -np.inf, big - 1)
    for n in reqs:
        k = idx[n["id"]]
        zs = [pidx[(m["id"], n["id"])] for m in nodes
              if m["id"] != n["id"] and m.get("archetype") == arch_of(n)]
        row([(X(k), float(n["archetype_req"]))] + [(Z(z), -1.0) for z in zs], -np.inf, 0)
        for z in zs:
            m = idx[pairs[z][0]]
            row([(Z(z), 1), (X(m), -1)], -np.inf, 0)                   # counts only if selected
            row([(L(m), 1), (L(k), -1), (Z(z), big)], -np.inf, big - 1)  # ...and earlier
    row([(X(i), float(nodes[i].get("cost") or 0)) for i in range(nv)], -np.inf, ap_cap)

    integrality = np.zeros(total)
    integrality[:nv + ne] = 1
    integrality[nv + ne + nv:] = 1
    ub = np.ones(total)
    ub[nv + ne:nv + ne + nv] = nv
    res = milp(c=-obj, constraints=LinearConstraint(np.array(rows), lo, hi),
               integrality=integrality, bounds=Bounds(np.zeros(total), ub))
    if not res.success:
        raise RuntimeError(f"tree solver failed: {res.message}")
    return {nodes[i]["id"] for i in range(nv) if round(res.x[i])}
