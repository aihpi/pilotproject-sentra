from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # backend/.env is the single configuration file, shared with the
        # evaluation harness, compose and the tests. pydantic-settings forbids
        # unknown keys by default, and that applies to a dotenv file — so a
        # JUDGE_MODEL the harness needs made SENTRA refuse to start.
        #
        # Asymmetric, which is what made it nasty: under compose those keys
        # arrive as environment variables, where unknown names are ignored, so
        # the container came up healthy while a local run crashed. And the
        # validation error quotes each offending value back, which put a
        # JUDGE_API_KEY into a traceback.
        #
        # EvalSettings has said extra="ignore" from the start for the same
        # reason. One file, several readers, each taking what it knows.
        extra="ignore",
    )

    # AI Model Hub
    ai_hub_base_url: str
    ai_hub_api_key: str

    # Model names (as shown in AI Hub)
    # How long to wait on the AI Hub before giving up. Both were measured
    # against the live hub rather than guessed: embedding one query takes about
    # 0.2s, and generating an answer or an overview 20 to 29 seconds over six
    # samples. The values leave roughly 4x headroom over the slowest.
    #
    # Generation had no value at all, which left the openai client's own
    # default of 600 seconds for reads. That is ten minutes of a held worker
    # for a request someone is watching a spinner for, and the frontend sets
    # no timeout of its own, so the browser waits exactly as long as we do.
    #
    # A timeout that fires raises APITimeoutError, an OpenAIError, so the
    # handler in api/errors.py already turns it into a 503.
    embedding_timeout_seconds: float = 60.0
    generation_timeout_seconds: float = 120.0

    embedding_model: str = "octen-embedding-8b"
    chat_model: str = "llama-3-3-70b"

    # Vector width the embedding model produces. Changing embedding_model almost
    # certainly means changing this too, and a collection built at one width
    # cannot serve vectors of another, so startup checks the two agree.
    embedding_dim: int = 4096

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    collection_name: str = "bundestag_documents"
    doc_collection_name: str = "bundestag_doc_summaries"

    # Ingestion
    # Paths default to what works when the app is run directly from
    # backend. compose and the k8s configmap both set the container
    # paths explicitly, so a /data default here buys nothing and only
    # breaks developer machines, where /data does not exist.
    documents_dir: str = "../data/Ausarbeitungen"
    chunk_max_tokens: int = 2048
    embedding_batch_size: int = 32

    # How many chunks to retrieve for a generated answer when the request does
    # not say. Document search and similar-document lookups have their own
    # defaults, because they count documents rather than chunks.
    retrieval_top_k: int = 10

    # Origins allowed to call the API from a browser. Only the vite dev server
    # needs this: under docker compose nginx proxies /api, so the browser sees a
    # single origin and CORS never applies. Accepts a comma-separated list.
    # NoDecode: without it pydantic-settings tries to JSON-parse the value
    # before the validator below ever sees it, so a plain comma-separated
    # string raises instead of being split.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Feedback
    feedback_file: str = "../data/feedback.jsonl"

    # The token guarding the write path and the personal-data read path
    # (#162). Not identity — it says a caller was given the secret, nothing
    # about who they are. See api/auth.py and references/SECURITY_NOTES.md.
    #
    # Empty means those endpoints stay open, which /api/health reports, because
    # a pilot that 401s everything on update is a pilot that gets rolled back
    # and a developer running compose should not need a secret to start.
    admin_token: str = ""

    # ── The prototype login (#165) ──────────────────────────────────
    # Users as `name:role:hash`, comma- or newline-separated. Roles are leser,
    # pruefer, admin. The hash contains no `$`, deliberately: docker compose
    # substitutes variables in the env file it is handed, so a `$` in a value
    # is read as the start of a variable name and silently becomes nothing.
    # Produce a hash with:
    #
    #   cd backend && uv run python -m sentra.api.identity
    #
    # Empty means no login is possible, which /api/health reports.
    sentra_users: str = ""

    # Signs the session cookie. No default on purpose: a default signing key is
    # a forged session for anyone who can read this repository, so absent means
    # no login rather than a weak one.
    session_secret: str = ""

    session_max_age_seconds: int = 12 * 60 * 60

    # Whether the session cookie is marked Secure, i.e. HTTPS only.
    #
    # **Defaults to on, and an operator has to turn it off deliberately to run
    # without TLS.** This is the one place the decision to ship a login before
    # TLS becomes visible in code rather than in a document: today there is no
    # cookie to steal, afterwards there is one, and SENTRA is published as a
    # bare LoadBalancer. Defaulting this off would be convenient and would mean
    # nobody ever noticed. See references/SECURITY_NOTES.md and #161 item 1.
    session_cookie_secure: bool = True
    # The document registry (#141). Its own database, not the evaluation
    # harness's: the harness is a separate distribution on purpose, and sharing
    # a server would re-couple them. Port 5434 because 5433 is already the
    # harness's, and 5432 is whatever a developer has running locally.
    #
    # Nothing connects at import and retrieval never reads this, so SENTRA
    # answers questions normally with the registry database down.
    registry_database_url: str = "postgresql+psycopg://sentra:sentra@localhost:5434/sentra_registry"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept CORS_ORIGINS as a comma-separated string or a JSON array."""
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                import json

                return json.loads(raw)
            return [part.strip() for part in raw.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
