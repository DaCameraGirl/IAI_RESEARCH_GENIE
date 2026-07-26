#!/usr/bin/env python3
"""Ranked query-plan generation from requirement concept matrices."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QueryConceptMatrix:
    component: list[str] = field(default_factory=list)
    function: list[str] = field(default_factory=list)
    geometry: list[str] = field(default_factory=list)
    measurement: list[str] = field(default_factory=list)
    relationship: list[str] = field(default_factory=list)
    industry_language: list[str] = field(default_factory=list)
    historical_synonyms: list[str] = field(default_factory=list)
    classifications: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    inventors: list[str] = field(default_factory=list)
    product_classes: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)


def _combine(left: list[str], right: list[str]) -> list[str]:
    out: list[str] = []
    for a in left:
        for b in right:
            out.append(f"\"{a}\" \"{b}\"")
    return out


def ranked_query_plan(matrix: QueryConceptMatrix) -> list[dict[str, str | int]]:
    ranked: list[tuple[int, str, str]] = []
    ranked.extend((1, "relationship_plus_product_class", q) for q in _combine(matrix.relationship, matrix.product_classes or matrix.component))
    ranked.extend((2, "relationship_plus_measurement", q) for q in _combine(matrix.relationship, matrix.measurement))
    ranked.extend((3, "component_plus_geometry", q) for q in _combine(matrix.component, matrix.geometry))
    ranked.extend((4, "component_plus_measurement", q) for q in _combine(matrix.component, matrix.measurement))
    ranked.extend((5, "function_plus_measurement", q) for q in _combine(matrix.function, matrix.measurement))
    ranked.extend((6, "classification_plus_historical_synonym", q) for q in _combine(matrix.classifications, matrix.historical_synonyms))
    ranked.extend((7, "assignee_plus_requirement", q) for q in _combine(matrix.assignees, matrix.relationship or matrix.component))
    ranked.extend((8, "inventor_plus_feature", q) for q in _combine(matrix.inventors, matrix.geometry or matrix.relationship))
    ranked.extend((9, "broad_component", f"\"{component}\"") for component in matrix.component)

    deduped: list[dict[str, str | int]] = []
    seen: set[str] = set()
    for priority, pattern, query in ranked:
        if query in seen:
            continue
        seen.add(query)
        deduped.append({"priority": priority, "pattern": pattern, "query": query})
    return deduped
