from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    debug: bool = os.getenv("AGAVE_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    db_path: Path = Path(os.getenv("AGAVE_DB_PATH", BASE_DIR / "data/db/agave_obs.sqlite3"))
    upload_dir: Path = Path(os.getenv("AGAVE_UPLOAD_DIR", BASE_DIR / "data/uploads/documents"))
    secret_key: str = os.getenv("AGAVE_SECRET_KEY", "dev-agave-secret-change-me")
    admin_user: str = os.getenv("AGAVE_ADMIN_USER", "admin")
    admin_password: str = os.getenv("AGAVE_ADMIN_PASSWORD", "agave123")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path.is_absolute() else self.base_dir / self.db_path

    def resolved_upload_dir(self) -> Path:
        return self.upload_dir if self.upload_dir.is_absolute() else self.base_dir / self.upload_dir


settings = Settings()
