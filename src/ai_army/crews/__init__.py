"""AI-Army crews – Product, Team Lead, Dev, QA.

- ProductCrew: PM + Product Agent. Creates/prioritizes issues (backlog, prioritized, ready-for-breakdown).
- TeamLeadCrew: Breaks ready-for-breakdown issues into frontend/backend/fullstack sub-issues.
- DevCrew: Frontend, Backend, or Fullstack agent. Picks sub-issues, implements, opens PRs.
- QACrew: Reviews PRs, merges when approved, sets linked issues to done.
"""

from ai_army.crews.product_crew import ProductCrew
from ai_army.crews.team_lead_crew import TeamLeadCrew
from ai_army.crews.dev_crew import DevCrew
from ai_army.crews.qa_crew import QACrew

__all__ = ["ProductCrew", "TeamLeadCrew", "DevCrew", "QACrew"]
