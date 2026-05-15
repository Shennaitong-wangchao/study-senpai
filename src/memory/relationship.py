from __future__ import annotations

from src.memory.models import RelationshipStateRecord, RelationshipUpdateCandidate


class RelationshipManager:
    KNOWN_DIMENSIONS = {
        "addressing_style",
        "comfort_level",
        "response_style",
        "boundaries",
        "interaction_rhythm",
        "trust_signal",
        "guidance_preference",
        "soothing_style",
        "care_expectation",
    }

    def normalize_candidate(self, candidate: RelationshipUpdateCandidate) -> RelationshipUpdateCandidate:
        dimension = candidate.dimension.strip().lower().replace(" ", "_")
        if dimension not in self.KNOWN_DIMENSIONS:
            dimension = "trust_signal"
        return RelationshipUpdateCandidate(
            dimension=dimension,
            value=candidate.value.strip(),
            weight=candidate.weight,
            confidence=candidate.confidence,
            note=candidate.note.strip() if candidate.note else None,
            reason=candidate.reason,
            source_message_ids=candidate.source_message_ids,
            metadata=candidate.metadata,
        )

    def describe(self, states: list[RelationshipStateRecord]) -> list[str]:
        return [
            f"{state.dimension}: {state.value}"
            + (f" | note: {state.note}" if state.note else "")
            for state in states
        ]
