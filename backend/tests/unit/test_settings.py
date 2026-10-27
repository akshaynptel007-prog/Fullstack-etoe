import pytest
from pydantic import ValidationError

from app.config import Settings


def test_local_defaults_boot_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("APP_ENV", "CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "local"
    assert settings.cors_origin_list == []


def test_production_refuses_insecure_defaults() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, app_env="production")


def test_production_accepts_real_secrets() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="x" * 48,
        admin_api_key="a-real-admin-key",
    )
    assert settings.is_production


def test_cors_origins_are_parsed_from_csv() -> None:
    settings = Settings(_env_file=None, cors_origins="http://a.test, http://b.test ,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]
