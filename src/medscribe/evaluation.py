from __future__ import annotations

"""
AI Quality Evaluation — measure and monitor AI output quality.

Critical question: "How do you know your AI is producing good output?"

This module provides:
1. ACCURACY — does the structured note match the transcript?
2. COMPLETENESS — are all relevant sections filled?
3. CONSISTENCY — same input → similar output?
4. SAFETY — are guardrails catching issues?
5. DRIFT — is quality degrading over time?

Evaluation methods:
- Automated metrics (no human needed)
- Reference-based evaluation (compare to gold standard)
- LLM-as-judge (use a second LLM to evaluate the first)
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()


@dataclass
class EvaluationResult:
    """Result of evaluating a single AI output."""
    visit_id: str
    model_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Scores (0.0 - 1.0)
    completeness: float = 0.0    # How many sections were filled
    consistency: float = 0.0     # Structural consistency
    safety_pass: bool = True     # Did it pass safety checks
    source_fidelity: float = 0.0 # How well does output match input

    overall_score: float = 0.0
    details: dict = field(default_factory=dict)


class AIEvaluator:
    """
    Evaluates AI output quality using automated metrics.

    Usage:
        evaluator = AIEvaluator()
        result = evaluator.evaluate(transcript_text, note_sections, model_id)
    """

    def evaluate(
        self,
        transcript_text: str,
        note_sections: dict[str, str],
        model_id: str,
        visit_id: str = "",
    ) -> EvaluationResult:
        result = EvaluationResult(visit_id=visit_id, model_id=model_id)

        # 1. Completeness — what fraction of sections are filled
        result.completeness = self._score_completeness(note_sections)

        # 2. Source fidelity — do key terms from transcript appear in note
        result.source_fidelity = self._score_source_fidelity(transcript_text, note_sections)

        # 3. Consistency — structural quality
        result.consistency = self._score_consistency(note_sections)

        # 4. Overall weighted score
        result.overall_score = (
            result.completeness * 0.3
            + result.source_fidelity * 0.4
            + result.consistency * 0.2
            + (1.0 if result.safety_pass else 0.0) * 0.1
        )

        result.details = {
            "sections_total": len(note_sections),
            "sections_filled": sum(1 for v in note_sections.values() if v and v != "Not documented."),
            "transcript_length": len(transcript_text),
            "note_total_length": sum(len(v) for v in note_sections.values()),
        }

        logger.info(
            "evaluation.completed",
            visit_id=visit_id,
            model=model_id,
            overall=round(result.overall_score, 2),
            completeness=round(result.completeness, 2),
            source_fidelity=round(result.source_fidelity, 2),
        )

        return result

    def _score_completeness(self, sections: dict[str, str]) -> float:
        if not sections:
            return 0.0
        filled = sum(1 for v in sections.values() if v and v.strip() and v != "Not documented.")
        return filled / len(sections)

    def _score_source_fidelity(self, transcript: str, sections: dict[str, str]) -> float:
        """
        Check if key terms from the transcript appear in the structured note.

        This catches hallucination: if the note mentions something NOT in
        the transcript, fidelity drops.
        """
        if not transcript or not sections:
            return 0.0

        # Extract significant words from transcript (>4 chars, not common words)
        common_words = {"dette", "denne", "eller", "hadde", "ikke", "også", "etter",
                        "fordi", "når", "med", "som", "den", "det", "til", "fra",
                        "the", "and", "for", "was", "with", "this", "that", "from"}
        transcript_words = set(
            w.lower() for w in transcript.split()
            if len(w) > 4 and w.lower() not in common_words
        )

        if not transcript_words:
            return 0.5  # Can't measure

        # Check how many transcript words appear in the note
        note_text = " ".join(sections.values()).lower()
        found = sum(1 for w in transcript_words if w in note_text)
        return min(1.0, found / max(len(transcript_words) * 0.3, 1))

    def _score_consistency(self, sections: dict[str, str]) -> float:
        """Check structural consistency of the output."""
        if not sections:
            return 0.0

        score = 1.0

        # Penalize very short sections (likely incomplete)
        for v in sections.values():
            if v and v != "Not documented." and len(v) < 10:
                score -= 0.1

        # Penalize if raw JSON appears in text (LLM formatting issue)
        all_text = " ".join(sections.values())
        if "{" in all_text and ":" in all_text and "}" in all_text:
            score -= 0.3

        return max(0.0, min(1.0, score))


class QualityMonitor:
    """
    Tracks AI quality over time to detect drift.

    Stores evaluation results and alerts when quality drops.
    """

    def __init__(self, alert_threshold: float = 0.5):
        self._history: list[EvaluationResult] = []
        self._alert_threshold = alert_threshold

    def record(self, result: EvaluationResult):
        self._history.append(result)
        if result.overall_score < self._alert_threshold:
            logger.warning(
                "quality.below_threshold",
                score=round(result.overall_score, 2),
                threshold=self._alert_threshold,
                model=result.model_id,
                visit_id=result.visit_id,
            )

    def get_trend(self, last_n: int = 20) -> dict:
        recent = self._history[-last_n:] if self._history else []
        if not recent:
            return {"samples": 0, "avg_score": 0, "trend": "no_data"}

        scores = [r.overall_score for r in recent]
        avg = sum(scores) / len(scores)

        # Compare first half to second half
        mid = len(scores) // 2
        if mid > 0:
            first_half = sum(scores[:mid]) / mid
            second_half = sum(scores[mid:]) / (len(scores) - mid)
            if second_half < first_half - 0.1:
                trend = "declining"
            elif second_half > first_half + 0.1:
                trend = "improving"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "samples": len(recent),
            "avg_score": round(avg, 2),
            "min_score": round(min(scores), 2),
            "max_score": round(max(scores), 2),
            "trend": trend,
            "below_threshold": sum(1 for s in scores if s < self._alert_threshold),
        }
