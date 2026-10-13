from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # Empty means "start the embedded PostgreSQL in data_dir" (needs the `embedded` extra).
    database_url: str = ""
    data_dir: Path = REPO_ROOT / "data"
    # Key for encrypting API keys at rest. Empty means "generate and keep in data_dir".
    secret_key: str = ""
    # Built frontend served by the API in production.
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


settings = Settings()
