import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from pydantic import ValidationError

from config import Settings

VALID_KEY = "a" * 64
VALID_DB = "postgresql://user:pass@db.example.com:5432/incidentsdb"


def build(**overrides):
    """
    Constructs Settings from explicit values. Optional keys are pinned to empty
    strings so the developer's own .env (which may hold a real Gemini or Twilio
    key) can't change what these assertions see.
    """
    values = {
        "DATABASE_URL": VALID_DB,
        "PHONE_ENCRYPTION_KEY": VALID_KEY,
        "GEMINI_API_KEY": "",
        "TWILIO_ACCOUNT_SID": "",
        "TWILIO_AUTH_TOKEN": "",
        "REDIS_URL": None,
    }
    values.update(overrides)
    return Settings(**values)


class TestRequiredConfig:
    def test_valid_config_loads(self):
        settings = build()
        assert settings.database_url == VALID_DB

    def test_missing_database_url_is_rejected(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ValidationError):
            Settings(PHONE_ENCRYPTION_KEY=VALID_KEY)

    @pytest.mark.parametrize(
        "bad_key",
        ["", "tooshort", "z" * 64, "a" * 63, "a" * 65],
        ids=["empty", "short", "non-hex", "63-chars", "65-chars"],
    )
    def test_malformed_encryption_key_is_rejected(self, bad_key):
        # A wrong-length or non-hex key would surface much later as silent
        # decrypt failures — phone numbers that never receive an SMS.
        with pytest.raises(ValidationError):
            build(PHONE_ENCRYPTION_KEY=bad_key)

    def test_unsupported_database_scheme_is_rejected(self):
        with pytest.raises(ValidationError):
            build(DATABASE_URL="mysql://user:pass@host/db")


class TestProductionHardening:
    def test_dev_defaults_allowed_in_development(self):
        settings = build(
            ENVIRONMENT="development",
            DATABASE_URL="postgresql://postgres:postgres@localhost:5433/incidentsdb",
        )
        assert settings.is_production is False

    def test_default_credentials_rejected_in_production(self):
        with pytest.raises(ValidationError, match="dev credentials"):
            build(
                ENVIRONMENT="production",
                DATABASE_URL="postgresql://postgres:postgres@db.example.com:5432/incidentsdb",
            )

    def test_localhost_database_rejected_in_production(self):
        with pytest.raises(ValidationError, match="localhost"):
            build(
                ENVIRONMENT="production",
                DATABASE_URL="postgresql://appuser:s3cret@localhost:5432/incidentsdb",
            )

    def test_half_configured_twilio_rejected_in_production(self):
        # A placeholder SID with a real token silently downgrades every alert to
        # a console print that looks like success in the logs.
        with pytest.raises(ValidationError, match="TWILIO_ACCOUNT_SID"):
            build(
                ENVIRONMENT="production",
                TWILIO_AUTH_TOKEN="real-token-value",
                TWILIO_ACCOUNT_SID="dummy_sid",
            )


class TestDerivedFlags:
    def test_sms_disabled_for_placeholder_credentials(self):
        assert build(TWILIO_ACCOUNT_SID="dummy_sid", TWILIO_AUTH_TOKEN="dummy_token").sms_enabled is False
        assert build().sms_enabled is False

    def test_sms_enabled_with_real_credentials(self):
        settings = build(TWILIO_ACCOUNT_SID="AC123", TWILIO_AUTH_TOKEN="token")
        assert settings.sms_enabled is True

    def test_gemini_disabled_when_unset(self):
        assert build().gemini_enabled is False
        assert build(GEMINI_API_KEY="key").gemini_enabled is True

    def test_describe_redacts_credentials(self):
        summary = build(
            DATABASE_URL="postgresql://appuser:hunter2@db.example.com:5432/incidentsdb",
            REDIS_URL="rediss://default:s3cr3t@redis.example.com:6379",
        ).describe()
        assert "hunter2" not in summary
        assert "s3cr3t" not in summary
        assert "db.example.com" in summary
