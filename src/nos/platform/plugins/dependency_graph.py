"""Topological ordering for plugin ``requires`` and ``requires_capabilities`` edges."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, Iterable, List


def merge_requires_with_capabilities(
    requires_map: Dict[str, List[str]],
    requires_caps_map: Dict[str, List[str]],
    capability_providers: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """
    For each capability required by an entry point, add an edge from a **provider** entry point.

    If multiple plugins advertise the same capability, the lexicographically first provider name
    (other than the consumer) is chosen so ordering stays deterministic.
    """
    merged: Dict[str, List[str]] = {k: list(dict.fromkeys(v)) for k, v in requires_map.items()}

    for consumer, caps in requires_caps_map.items():
        for cap in caps:
            providers = list(capability_providers.get(cap, []))
            candidates = sorted(p for p in providers if p != consumer)
            if not candidates:
                raise ValueError(
                    f"Capability {cap!r} required by entry point {consumer!r} has no other provider "
                    f"(advertised by: {providers!r})"
                )
            provider = candidates[0]
            lst = merged.setdefault(consumer, [])
            if provider not in lst:
                lst.append(provider)

    return merged


def topological_sort(entry_names: Iterable[str], requires_map: Dict[str, List[str]]) -> List[str]:
    """
    ``requires_map[name]`` lists prerequisite entry-point names that must appear **before** ``name``.
    Every prerequisite must itself be present in ``entry_names`` (same discovery set).

    Raises:
        ValueError: unknown dependency, or cycle detected.
    """
    names = list(entry_names)
    name_set = set(names)
    requires_map = {k: list(dict.fromkeys(v)) for k, v in requires_map.items()}

    for n, reqs in requires_map.items():
        for r in reqs:
            if r not in name_set:
                raise ValueError(
                    f"Plugin {n!r} requires entry point {r!r} which is not in the discovered set"
                )

    indegree: Dict[str, int] = {n: len(requires_map.get(n, [])) for n in names}
    adj: Dict[str, List[str]] = defaultdict(list)
    for name in names:
        for dep in requires_map.get(name, []):
            adj[dep].append(name)

    queue = deque([n for n in names if indegree[n] == 0])
    order: List[str] = []

    while queue:
        u = queue.popleft()
        order.append(u)
        for v in adj[u]:
            indegree[v] -= 1
            if indegree[v] == 0:
                queue.append(v)

    if len(order) != len(names):
        raise ValueError("Cycle detected in plugin dependency graph")

    return order
