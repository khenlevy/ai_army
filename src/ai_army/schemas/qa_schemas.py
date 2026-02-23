"""Pydantic schemas for QA Crew structured output."""

from typing import Literal

from pydantic import BaseModel, Field


class FeedbackPoint(BaseModel):
    """A single feedback point for a PR review."""

    file: str = Field(default="", description="File path (or empty if general)")
    line: int | None = Field(default=None, description="Line number if applicable")
    comment: str = Field(..., description="Feedback comment")


class ReviewSpec(BaseModel):
    """Structured schema for PR review decision and feedback."""

    decision: Literal["merge", "request_changes"] = Field(
        ...,
        description="Whether to merge the PR or request changes",
    )
    feedback_points: list[FeedbackPoint] = Field(
        default_factory=list,
        description="List of feedback points (file, line, comment)",
    )
    summary: str = Field(default="", description="Brief summary of the review")
