"""Pydantic schemas for Team Lead Crew structured output."""

from typing import Literal

from pydantic import BaseModel, Field


class SubTaskSpec(BaseModel):
    """Schema for a single sub-task in a breakdown."""

    title: str = Field(..., description="Sub-task title")
    body: str = Field(default="", description="Sub-task description")
    label: Literal["frontend", "backend", "fullstack"] = Field(
        ...,
        description="Label indicating which agent type handles this task",
    )


class BreakdownSpec(BaseModel):
    """Structured schema for breaking down a feature into sub-tasks."""

    parent_issue: int = Field(..., description="Parent issue number")
    sub_tasks: list[SubTaskSpec] = Field(
        default_factory=list,
        description="List of sub-tasks with frontend/backend/fullstack labels",
    )
