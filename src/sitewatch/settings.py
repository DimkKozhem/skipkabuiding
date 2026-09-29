from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_dotenv_file() -> None:
    """Load LCT2026/.env into process env once (OPENROUTR_KEY and friends)."""
    import os

    path = project_root() / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SITEWATCH_", extra="ignore")

    root: Path = Field(default_factory=project_root)
    db_path: Path | None = None
    detector: str = "annotation"
    yolo_weights: Path | None = None
    yolo_device: str = "0"
    enable_sam: bool = False
    enable_dino: bool = False
    enable_ocr: bool = False
    capture_loop: bool = False
    capture_tick_seconds: int = 20

    # Perception — None means "take from config/perception.yaml"
    perception_mode: str | None = None  # annotation | real | full
    sam3_enabled: bool | None = None
    sam3_device: str | None = None
    sam3_threshold: float | None = None
    sam3_checkpoint: Path | None = None
    grounding_dino_enabled: bool | None = None
    grounding_dino_device: str | None = None
    grounding_dino_box_threshold: float | None = None
    grounding_dino_text_threshold: float | None = None
    qwen_vl_enabled: bool | None = None
    qwen_vl_base_url: str | None = None
    qwen_vl_model: str | None = None
    qwen_vl_timeout_seconds: float | None = None
    qwen_vl_api_key: str | None = None
    qwen_vl_max_tokens: int | None = None
    analysis_workers: int = 1
    analysis_max_queued: int = 4
    analysis_job_stale_seconds: int = 3600

    @property
    def sqlite_path(self) -> Path:
        path = self.db_path or (self.root / "data" / "observations" / "sitewatch.db")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.sqlite_path}"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def models_dir(self) -> Path:
        path = self.root / "models"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_data_dirs(self) -> None:
        for name in (
            "source",
            "raw",
            "annotations",
            "train",
            "val",
            "test",
            "predictions",
            "observations",
            "observations/artifacts",
        ):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_data_dirs()
    return settings


def load_yaml(name: str) -> dict:
    path = get_settings().config_dir / name
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
