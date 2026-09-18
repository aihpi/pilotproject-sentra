"""SENTRA does not know the evaluation harness exists.

The harness measures SENTRA, so it lives in its own distribution, its own
process and its own image, and reaches SENTRA over HTTP like any other client.
This is the SENTRA half of that: nothing here imports it, serves its routes, or
carries its settings.

It is asserted from this side on purpose. The harness cannot check it — it has
no dependency on `sentra` to check it with, which is the point — and "SENTRA's
image does not need the harness's dependencies" is a claim about SENTRA's build.
"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


class TestNoRoutes:
    def test_sentra_serves_no_eval_routes(self):
        from sentra.main import app

        paths = [getattr(route, "path", "") for route in app.routes]

        assert not any(path.startswith("/api/eval") for path in paths)


class TestNoImport:
    def test_importing_sentra_does_not_load_the_harness(self):
        """If it did, SENTRA's image would need the harness's dependencies and
        its build would fail — this is not a tidiness check."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys, sentra.main; print('sentra_eval' in sys.modules)"],
            capture_output=True,
            text=True,
            cwd=BACKEND,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"

    def test_no_source_file_mentions_the_harness(self):
        """A dependency that only appears under a condition is still a
        dependency, and would be found at the worst moment."""
        offenders = [
            path.relative_to(BACKEND)
            for path in (BACKEND / "src").rglob("*.py")
            if "sentra_eval" in path.read_text(encoding="utf-8")
        ]

        assert offenders == []


class TestNoSettings:
    def test_sentra_has_no_eval_settings(self):
        """EVAL_ENABLED is gone. Whether the harness runs is decided by whether
        its process runs, which is what independence means for something whose
        job is to measure SENTRA."""
        from sentra.config import Settings

        assert [name for name in Settings.model_fields if name.startswith("eval")] == []

    def test_sentra_does_not_point_at_the_harness_database(self):
        """This replaced a check that SENTRA declared no sqlalchemy, alembic or
        psycopg at all, which was true until #141 and is not any more: the
        document registry is SENTRA's own database.

        Sharing the packages is fine. Sharing the *database* is not, and that
        is what the old assertion was standing in for — the harness is a
        separate distribution precisely so that SENTRA starting does not depend
        on it, and a shared server would hand that back.
        """
        from sentra.config import Settings

        url = Settings.model_fields["registry_database_url"].default

        assert "sentra_eval" not in url, "the registry must not be the harness's database"
        assert ":5433" not in url, "5433 is the harness's Postgres"


class TestTheHarnessIsItsOwnDistribution:
    def test_it_has_its_own_pyproject(self):
        assert (REPO / "evaluation" / "pyproject.toml").is_file()

    def test_it_does_not_depend_on_sentra(self):
        """The structural version of the import-linter contract this replaced.
        A contract forbade `evaluation -> rag.generator` and `-> api.models`;
        a distribution that does not depend on `sentra` cannot reach them at
        all, which is stronger than a lint rule."""
        pyproject = (REPO / "evaluation" / "pyproject.toml").read_text(encoding="utf-8")
        dependencies = pyproject[pyproject.index("dependencies = [") :]
        dependencies = dependencies[: dependencies.index("]")]

        assert "sentra" not in dependencies
