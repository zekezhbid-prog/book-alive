from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # Empty means "start the embedded PostgreSQL in data_dir" (needs the `embedded` extra).
    database_url: str = ""
    # Empty: the app owns the database and uses the default schema (own pgvector container,
    # embedded PostgreSQL). Set it to share a server with other projects (e.g. Supabase):
    # every table then lives in this schema and the connection sees nothing else.
    db_schema: str = ""
    # Connections kept to a shared PostgreSQL; small on purpose.
    db_pool_size: int = 5
    # The model provider. With a key here the "Hubris" connection is created (and its key
    # kept current) on every start, so the key never has to be typed into the interface.
    hubris_api_key: str = ""
    hubris_base_url: str = "https://api.hubris.pw/v1"
    data_dir: Path = REPO_ROOT / "data"
    # Key for encrypting API keys at rest. Empty means "generate and keep in data_dir".
    secret_key: str = ""
    # Accounts. Empty ALLOWED_EMAILS (the local default) means no login at all. On a server
    # list the addresses that may register, comma separated; anyone else is turned away.
    allowed_emails: str = ""
    # Addresses of administrators (may change the model connections), and the first of them
    # takes over the books that existed before accounts did.
    owner_emails: str = ""
    # Public address of the site, for the link in the password reset mail.
    public_url: str = ""
    # Mail for password resets, e.g. Gmail with an app password.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    # Local embedding model for search over the book; "hash" needs no download (tests).
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # Built frontend served by the API in production.
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    @property
    def allowed_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()]

    @property
    def owner_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.owner_emails.split(",") if e.strip()]

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


settings = Settings()
