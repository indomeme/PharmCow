from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. All can be overridden with PHARMCOW_* env vars."""

    model_config = SettingsConfigDict(
        env_prefix="PHARMCOW_", env_file=".env", extra="ignore"
    )

    data_dir: Path = Path("data")
    database_url: str | None = None

    # Job runner
    max_workers: int = 1
    pypgx_threads: int = 4

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Defaults for a run
    assembly: str = "GRCh38"  # "auto" to detect from contigs
    # Comma-separated gene override, e.g. "CYP2C19,CYP2D6" (empty = all 58).
    genes: str = ""

    @property
    def gene_list(self) -> list[str] | None:
        if not self.genes.strip():
            return None
        return [g.strip().upper() for g in self.genes.split(",") if g.strip()]

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'pharmcow.db'}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
