"""Centralized environment settings for Eigenia TwinScan."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_vision_model: str = "google/gemini-2.5-flash"
    openrouter_secondary_vision_model: str = "qwen/qwen2.5-vl-72b-instruct"
    openrouter_research_model: str = "perplexity/sonar-pro"
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 1536

    database_url: str = ""
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = "twinscan_graph_secret"

    twinscan_encryption_key: str = ""
    twinscan_admin_token: str = ""
    twinscan_storage_dir: str = "./data"
    max_upload_mb: int = 25
    near_proximity_m: float = 3.0
    default_camera_fov_deg: float = 68.0
    default_camera_yaw_offset_deg: float = 0.0
    default_wall_height_m: float = 2.8
    facility_name: str = "Eigenia Lab"

    @property
    def uploads_dir(self) -> Path:
        """Return legacy local directory path (PostgreSQL stored_files is primary)."""
        path = Path(self.twinscan_storage_dir) / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application ``Settings`` instance."""
    return Settings()
