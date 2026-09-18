"""Deterministic local compatibility evaluation and capability resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .capability_manifest import (
    CapabilityHealth,
    CapabilityKind,
    CapabilityRecord,
    CapabilityRisk,
    CapabilitySnapshot,
    CapabilityValidationError,
)

_VERSION_RE = re.compile(r"^\d+(?:\.\d+){0,3}$")
_CLAUSE_RE = re.compile(r"^(>=|<=|==|>|<)?(\d+(?:\.\d+){0,3})$")
_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)
_RISK_ORDER = {
    CapabilityRisk.LOW: 0,
    CapabilityRisk.MEDIUM: 1,
    CapabilityRisk.HIGH: 2,
}


def _parse_version(value: str, field_name: str = "version") -> tuple[int, int, int, int]:
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise CapabilityValidationError("version_invalid", f"{field_name} is invalid")
    parts = [int(part) for part in value.split(".")]
    if any(part > 999_999 for part in parts):
        raise CapabilityValidationError("version_invalid", f"{field_name} component is too large")
    return tuple(parts + [0] * (4 - len(parts)))


def evaluate_constraint(actual_version: str, constraint: str) -> bool:
    actual = _parse_version(actual_version, "actual version")
    if not isinstance(constraint, str) or not constraint or len(constraint) > 256:
        raise CapabilityValidationError("constraint_invalid", "constraint is invalid")
    clauses = [clause.strip() for clause in constraint.split(",")]
    if not clauses or len(clauses) > 8 or any(not clause for clause in clauses):
        raise CapabilityValidationError("constraint_invalid", "constraint clause count is invalid")

    comparisons = {
        "==": lambda left, right: left == right,
        ">=": lambda left, right: left >= right,
        "<=": lambda left, right: left <= right,
        ">": lambda left, right: left > right,
        "<": lambda left, right: left < right,
    }
    for clause in clauses:
        match = _CLAUSE_RE.fullmatch(clause)
        if match is None:
            raise CapabilityValidationError("constraint_invalid", "constraint clause is invalid")
        operator = match.group(1) or "=="
        expected = _parse_version(match.group(2), "constraint version")
        if not comparisons[operator](actual, expected):
            return False
    return True


@dataclass(frozen=True)
class CompatibilityTarget:
    python: Optional[str] = None
    node: Optional[str] = None
    jarvis_api: Optional[str] = None

    def __post_init__(self):
        for field_name in ("python", "node", "jarvis_api"):
            value = getattr(self, field_name)
            if value is not None:
                _parse_version(value, field_name)

    def value_for(self, runtime: str) -> Optional[str]:
        if runtime not in {"python", "node", "jarvis_api"}:
            return None
        return getattr(self, runtime)


@dataclass(frozen=True)
class CapabilityQuery:
    query: str = ""
    kind: Optional[CapabilityKind] = None
    compatible_only: bool = False
    max_risk: CapabilityRisk = CapabilityRisk.HIGH
    limit: int = 20

    def __post_init__(self):
        if not isinstance(self.query, str) or len(self.query) > 256:
            raise CapabilityValidationError("query_invalid", "query must be a bounded string")
        if self.kind is not None and not isinstance(self.kind, CapabilityKind):
            raise CapabilityValidationError("kind_invalid", "kind must be a CapabilityKind")
        if type(self.compatible_only) is not bool:
            raise CapabilityValidationError("compatible_only_invalid", "compatible_only must be boolean")
        if not isinstance(self.max_risk, CapabilityRisk):
            raise CapabilityValidationError("max_risk_invalid", "max_risk must be a CapabilityRisk")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise CapabilityValidationError("limit_invalid", "limit must be between 1 and 100")
        if any(
            ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF
            for character in self.query
        ):
            raise CapabilityValidationError("query_invalid", "query contains invalid characters")


@dataclass(frozen=True)
class CompatibilityEvaluation:
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityMatch:
    record: CapabilityRecord
    score: int
    reasons: tuple[str, ...]
    compatibility_status: str
    compatibility_reasons: tuple[str, ...]

    def to_public_dict(self, *, include_match: bool = True) -> dict[str, object]:
        body = self.record.to_public_dict()
        compatibility = dict(body["compatibility"])
        compatibility["status"] = self.compatibility_status
        compatibility["reasons"] = list(self.compatibility_reasons)
        body["compatibility"] = compatibility
        if include_match:
            body["match"] = {
                "score": self.score,
                "reasons": list(self.reasons),
            }
        return body


def evaluate_compatibility(
    record: CapabilityRecord,
    target: CompatibilityTarget,
) -> CompatibilityEvaluation:
    incompatible = []
    unknown = []
    for runtime, constraint in record.compatibility:
        if runtime not in {"python", "node", "jarvis_api"}:
            unknown.append(f"runtime_unknown:{runtime}")
            continue
        actual = target.value_for(runtime)
        if actual is None:
            unknown.append(f"runtime_unavailable:{runtime}")
            continue
        try:
            matches = evaluate_constraint(actual, constraint)
        except CapabilityValidationError:
            incompatible.append(f"constraint_invalid:{runtime}")
            continue
        if not matches:
            incompatible.append(f"constraint_mismatch:{runtime}")

    if incompatible:
        return CompatibilityEvaluation("incompatible", tuple(sorted(incompatible + unknown)))
    if unknown:
        return CompatibilityEvaluation("unknown", tuple(sorted(unknown)))
    return CompatibilityEvaluation("compatible", ())


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_RE.findall(value))


class CapabilityResolver:
    """Ranks a bounded local snapshot without side effects or mutable cache state."""

    def resolve(
        self,
        snapshot: CapabilitySnapshot,
        query: CapabilityQuery,
        target: CompatibilityTarget,
    ) -> tuple[CapabilityMatch, ...]:
        normalized_query = query.query.strip().casefold()
        query_tokens = _tokens(normalized_query)
        matches = []
        for record in snapshot.records:
            if query.kind is not None and record.kind is not query.kind:
                continue
            if _RISK_ORDER[record.risk] > _RISK_ORDER[query.max_risk]:
                continue
            compatibility = evaluate_compatibility(record, target)
            if query.compatible_only and compatibility.status != "compatible":
                continue

            score = 0
            reasons = []
            identifier = record.capability_id.casefold()
            name = record.name.casefold()
            description = record.description.casefold()
            identifier_tokens = set(_tokens(identifier))
            name_tokens = set(_tokens(name))

            if normalized_query:
                if normalized_query == identifier:
                    score += 120
                    reasons.append("id_exact")
                if normalized_query == name:
                    score += 100
                    reasons.append("name_exact")
                if query_tokens and all(token in identifier_tokens for token in query_tokens):
                    score += 35
                    reasons.append("id_token_match")
                if query_tokens and all(token in name_tokens for token in query_tokens):
                    score += 40
                    reasons.append("name_token_match")
                if normalized_query in description:
                    score += 20
                    reasons.append("description_match")
                elif query_tokens and all(token in description for token in query_tokens):
                    score += 10
                    reasons.append("description_token_match")
                if not reasons:
                    continue

            if record.health is CapabilityHealth.HEALTHY:
                score += 6
                reasons.append("healthy")
            if compatibility.status == "compatible":
                score += 5
                reasons.append("compatible")
            if record.provenance_status in {"complete", "verified"}:
                score += 4
                reasons.append("provenance_complete")
            if record.risk is CapabilityRisk.LOW:
                score += 3
                reasons.append("risk_low")
            elif record.risk is CapabilityRisk.MEDIUM:
                score += 1
                reasons.append("risk_medium")

            matches.append(CapabilityMatch(
                record=record,
                score=score,
                reasons=tuple(reasons),
                compatibility_status=compatibility.status,
                compatibility_reasons=compatibility.reasons,
            ))

        matches.sort(key=lambda match: (-match.score, match.record.capability_id))
        return tuple(matches[:query.limit])
