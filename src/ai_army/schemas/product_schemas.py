"""Pydantic schemas for Product Crew structured output."""

from pydantic import BaseModel, Field


class IssueSpec(BaseModel):
    """Structured schema for creating a GitHub issue."""

    title: str = Field(..., description="Clear, concise issue title")
    body: str = Field(default="", description="Issue description and context")
    labels: list[str] = Field(
        default_factory=list,
        description="Labels to apply (e.g. backlog, prioritized, feature, bug)",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="List of acceptance criteria for the issue",
    )
    technical_notes: str = Field(
        default="",
        description="Technical notes or implementation hints",
    )


class EnrichIssueSpec(BaseModel):
    """Structured schema for enriching an issue with acceptance criteria."""

    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="List of acceptance criteria",
    )
    technical_notes: str = Field(
        default="",
        description="Technical notes for implementation",
    )
