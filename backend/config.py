"""
Startup configuration & validation for the worker.

Mirrors what frontend/src/lib/env.ts does on the Next.js side: fail fast at
process start on missing or malformed config rather than surfacing it much
later as a confusing runtime error (a decrypt failure on the first matched
incident, a silent fallback to in-memory caching, etc.).

Import `settings` anywhere config is needed. Validation runs once, on first
import; call `settings.describe()` to log a redacted summary at boot.
"""

import os
import re
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

_HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")

# Placeholder values that are fine for local development but must never reach a
# deployed environment. Checked only when ENVIRONMENT != "development".
_PLACEHOLDERS = {
    "",
    "changeme",
    "secret",
    "dummy_sid",
    "dummy_token",
    "dummy_gemini",
    "dummy_map_key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # load_dotenv() above already populated os.environ
        case_sensitive=False,
        extra="ignore",
    )

    # --- Deployment identity -------------------------------------------------
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # --- Required ------------------------------------------------------------
    database_url: str = Field(alias="DATABASE_URL")
    phone_encryption_key: str = Field(alias="PHONE_ENCRYPTION_KEY")

    # --- Database pooling ----------------------------------------------------
    # Sized for a single worker process against a small managed Postgres — one
    # process, one pass, so the pool only needs to cover the sessions opened
    # per pass plus headroom for pre-ping reconnects.
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=5, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    # Recycle below typical managed-Postgres / PgBouncer idle timeouts so the
    # worker never hands out a connection the server has already dropped.
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")

    # --- Redis ---------------------------------------------------------------
    # REDIS_URL takes precedence when set (redis:// or rediss:// — the form
    # managed providers hand out). REDIS_HOST/REDIS_PORT remain supported for
    # the local docker-compose setup.
    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")

    # --- Worker execution ----------------------------------------------------
    # The worker always runs a single check_and_notify() pass and exits — the
    # shape a Cloud Run Job / cron invocation (or a local scheduled loop) wants.
    # TTL on the Redis lock that stops two scheduled executions overlapping.
    # Must exceed the worst-case run time (otherwise a slow run's lock expires
    # and the next execution starts anyway) and stay under the point where
    # skipping cycles matters.
    run_lock_ttl_seconds: int = Field(default=300, alias="RUN_LOCK_TTL_SECONDS")

    # --- Route matching ------------------------------------------------------
    match_radius_miles: float = Field(default=5.0, alias="MATCH_RADIUS_MILES")

    # --- External services (all optional; each degrades gracefully) ----------
    caltrans_feed_url: Optional[str] = Field(default=None, alias="CALTRANS_FEED_URL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    osrm_url: str = Field(default="http://router.project-osrm.org", alias="OSRM_URL")
    twilio_account_sid: str = Field(default="", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", alias="TWILIO_AUTH_TOKEN")
    twilio_phone_number: str = Field(default="+15550000000", alias="TWILIO_PHONE_NUMBER")

    # ------------------------------------------------------------------------

    @field_validator("phone_encryption_key")
    @classmethod
    def _validate_encryption_key(cls, v: str) -> str:
        if not _HEX_64.match(v):
            raise ValueError(
                "PHONE_ENCRYPTION_KEY must be a 64-character hex string (32 bytes). "
                "Generate one with: openssl rand -hex 32 "
                "(must match the frontend's PHONE_ENCRYPTION_KEY exactly, or phone "
                "numbers written by the frontend cannot be decrypted here)."
            )
        return v

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("postgresql", "postgres", "postgresql+psycopg2", "sqlite"):
            raise ValueError(
                f"DATABASE_URL has unsupported scheme '{parsed.scheme}'. "
                "Expected a postgresql:// connection string."
            )
        return v

    @model_validator(mode="after")
    def _validate_production_hardening(self) -> "Settings":
        """Extra checks that only make sense outside local development."""
        if self.environment.lower() in ("development", "dev", "test", "local"):
            return self

        problems: list[str] = []

        if "postgres:postgres@" in self.database_url:
            problems.append(
                "DATABASE_URL still uses the default postgres/postgres dev credentials"
            )
        if "localhost" in self.database_url or "127.0.0.1" in self.database_url:
            problems.append("DATABASE_URL points at localhost")

        # A configured-but-placeholder Twilio SID silently downgrades every alert
        # to a console print, which looks like success in logs.
        if self.twilio_account_sid in _PLACEHOLDERS and self.twilio_auth_token not in _PLACEHOLDERS:
            problems.append(
                "TWILIO_AUTH_TOKEN is set but TWILIO_ACCOUNT_SID is missing/placeholder"
            )

        if problems:
            raise ValueError(
                f"Invalid configuration for ENVIRONMENT={self.environment}: "
                + "; ".join(problems)
            )
        return self

    # --- Derived helpers -----------------------------------------------------

    @property
    def sms_enabled(self) -> bool:
        """True when real Twilio credentials are configured (not placeholders)."""
        return (
            self.twilio_account_sid not in _PLACEHOLDERS
            and self.twilio_auth_token not in _PLACEHOLDERS
        )

    @property
    def gemini_enabled(self) -> bool:
        return self.gemini_api_key not in _PLACEHOLDERS

    @property
    def is_production(self) -> bool:
        return self.environment.lower() not in ("development", "dev", "test", "local")

    def describe(self) -> str:
        """Redacted one-block config summary, safe to print at startup."""
        db = urlparse(self.database_url)
        db_display = f"{db.scheme}://{db.hostname}:{db.port or 5432}{db.path}"
        redis_display = self.redis_url and _redact_url(self.redis_url) or (
            f"{self.redis_host}:{self.redis_port}/{self.redis_db}"
        )
        return "\n".join(
            [
                "--- Worker configuration ---",
                f"  environment      : {self.environment}",
                f"  database         : {db_display}",
                f"  db pool          : size={self.db_pool_size} overflow={self.db_max_overflow} recycle={self.db_pool_recycle}s",
                f"  redis            : {redis_display}",
                f"  match radius     : {self.match_radius_miles} miles",
                f"  caltrans feed    : {self.caltrans_feed_url or 'default (quickmap.dot.ca.gov)'}",
                f"  gemini summaries : {'enabled' if self.gemini_enabled else 'disabled (mock summaries)'}",
                f"  sms dispatch     : {'twilio' if self.sms_enabled else 'console mock'}",
                "----------------------------",
            ]
        )


def _redact_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.password:
        return url.replace(parsed.password, "***")
    return url


def load_settings() -> Settings:
    """
    Builds Settings from the environment, converting pydantic's validation
    error into a single readable SystemExit instead of a traceback.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:  # pydantic.ValidationError and friends
        lines = [str(line).strip() for line in str(exc).splitlines() if line.strip()]
        raise SystemExit(
            "Worker startup aborted — invalid configuration:\n  "
            + "\n  ".join(lines)
            + "\n\nSee backend/.env.example for the expected values."
        )


# Importing this module validates configuration exactly once, at process start.
# Tests that need to exercise alternate config can construct Settings() directly.
settings = load_settings()

# Keep os.environ authoritative for the few modules that still read it directly
# (crypto_utils, caltrans_client), so there is one source of truth after
# defaults are applied.
os.environ.setdefault("PHONE_ENCRYPTION_KEY", settings.phone_encryption_key)
