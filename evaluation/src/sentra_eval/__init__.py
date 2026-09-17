"""The evaluation harness.

Implements the KISZ Testverfahren (docs/Vorlage_Strukturierte_Testverfahren_KISZ.md)
as a module of SENTRA rather than a second service, while keeping it at arm's
length from the system it measures:

  - it reaches SENTRA over HTTP at SENTRA_BASE_URL, never in process, because
    the API layer is part of what is under test
  - it judges with a different model from CHAT_MODEL, asserted at boot
  - it imports neither rag.generator nor api.models, enforced by import-linter

This runs as its own process, beside SENTRA rather than inside it. The
entrypoint is sentra_eval.app; sentra.main does not import this package
and does not know it exists. A harness that could not be restarted without
restarting the thing it measures would not be independent whatever its import
graph said.
"""

from sentra_eval.categories import Kategorie
from sentra_eval.config import EvalSettings, get_eval_settings
from sentra_eval.db import Base, EvalDatabaseUnavailable, session_scope
from sentra_eval.judge import JudgeConfig, MissingJudgeConfiguration, judge_config
from sentra_eval.router import router

__all__ = [
    "Base",
    "EvalDatabaseUnavailable",
    "EvalSettings",
    "JudgeConfig",
    "Kategorie",
    "MissingJudgeConfiguration",
    "get_eval_settings",
    "judge_config",
    "router",
    "session_scope",
]
