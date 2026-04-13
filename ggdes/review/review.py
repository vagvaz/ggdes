"""Review session data models for interactive pipeline review.

Defines the structure for tracking review decisions, feedback,
and partial regeneration targets across pipeline stages.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ReviewDecision(Enum):
    """User decision after reviewing a stage's output."""

    ACCEPT = "accept"
    """Accept the output as-is and proceed to the next stage."""

    REGENERATE_ALL = "regenerate_all"
    """Regenerate the entire stage output with user feedback."""

    REGENERATE_PARTIAL = "regenerate_partial"
    """Regenerate only specific items (keys provided in partial_keys)."""

    SKIP = "skip"
    """Skip review for this and all remaining stages."""


@dataclass
class StageReview:
    """Result of reviewing a single pipeline stage."""

    stage_name: str
    decision: ReviewDecision
    feedback: Optional[str] = None
    partial_keys: list[str] = field(default_factory=list)
    items_reviewed: int = 0
    items_accepted: int = 0


@dataclass
class ReviewSession:
    """Tracks the review state across all stages for one analysis run."""

    analysis_id: str
    interactive: bool = False
    stage_reviews: list[StageReview] = field(default_factory=list)
    current_stage: Optional[str] = None
    # Maps stage_name -> list of item keys to regenerate (for partial regen)
    pending_partial_regen: dict[str, list[str]] = field(default_factory=dict)
    # Accumulated feedback keyed by stage name
    stage_feedback: dict[str, str] = field(default_factory=dict)
    # Set to True when user chooses "skip" for remaining stages
    skip_remaining: bool = False

    def add_review(self, review: StageReview) -> None:
        """Record a stage review decision."""
        self.stage_reviews.append(review)
        if review.feedback:
            self.stage_feedback[review.stage_name] = review.feedback
        if review.decision == ReviewDecision.REGENERATE_PARTIAL:
            self.pending_partial_regen[review.stage_name] = review.partial_keys
        elif review.decision == ReviewDecision.SKIP:
            self.skip_remaining = True

    def get_feedback(self, stage_name: str) -> Optional[str]:
        """Get accumulated feedback for a stage (from itself or earlier)."""
        return self.stage_feedback.get(stage_name)

    def get_partial_keys(self, stage_name: str) -> Optional[list[str]]:
        """Get partial regeneration keys for a stage, if any."""
        return self.pending_partial_regen.get(stage_name)

    def is_skipping(self) -> bool:
        """Whether remaining stages should skip review."""
        return self.skip_remaining

    def to_dict(self) -> dict[str, Any]:
        """Serialize for KB storage."""
        return {
            "analysis_id": self.analysis_id,
            "interactive": self.interactive,
            "stage_reviews": [
                {
                    "stage_name": r.stage_name,
                    "decision": r.decision.value,
                    "feedback": r.feedback,
                    "partial_keys": r.partial_keys,
                    "items_reviewed": r.items_reviewed,
                    "items_accepted": r.items_accepted,
                }
                for r in self.stage_reviews
            ],
            "pending_partial_regen": self.pending_partial_regen,
            "stage_feedback": self.stage_feedback,
            "skip_remaining": self.skip_remaining,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewSession":
        """Deserialize from KB storage."""
        session = cls(
            analysis_id=data["analysis_id"],
            interactive=data.get("interactive", False),
            pending_partial_regen=data.get("pending_partial_regen", {}),
            stage_feedback=data.get("stage_feedback", {}),
            skip_remaining=data.get("skip_remaining", False),
        )
        for r in data.get("stage_reviews", []):
            session.stage_reviews.append(
                StageReview(
                    stage_name=r["stage_name"],
                    decision=ReviewDecision(r["decision"]),
                    feedback=r.get("feedback"),
                    partial_keys=r.get("partial_keys", []),
                    items_reviewed=r.get("items_reviewed", 0),
                    items_accepted=r.get("items_accepted", 0),
                )
            )
        return session
