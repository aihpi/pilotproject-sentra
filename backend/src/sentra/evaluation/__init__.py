"""The evaluation harness.

Implements the KISZ Testverfahren (docs/Vorlage_Strukturierte_Testverfahren_KISZ.md)
as a module of SENTRA rather than a second service, while keeping it at arm's
length from the system it measures:

  - it reaches SENTRA over HTTP at SENTRA_BASE_URL, never in process, because
    the API layer is part of what is under test
  - it judges with a different model from CHAT_MODEL, asserted at boot
  - it imports neither rag.generator nor api.models, enforced by import-linter

Nothing here is imported unless EVAL_ENABLED is set. main does the check and
the import together, so an image built without the `eval` extra never loads
this package. See mount_evaluation in sentra.main.
"""

from sentra.evaluation.categories import Kategorie
from sentra.evaluation.config import EvalSettings, get_eval_settings
from sentra.evaluation.db import Base, EvalDatabaseUnavailable, session_scope
from sentra.evaluation.judge import (
    JudgeConfig,
    JudgeNotIndependent,
    MissingJudgeConfiguration,
    assert_judge_is_independent,
    judge_config,
)
from sentra.evaluation.router import router

__all__ = [
    "Base",
    "EvalDatabaseUnavailable",
    "EvalSettings",
    "JudgeConfig",
    "Kategorie",
    "JudgeNotIndependent",
    "MissingJudgeConfiguration",
    "assert_judge_is_independent",
    "get_eval_settings",
    "judge_config",
    "router",
    "session_scope",
]
