"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
CLIPS_DIR = DATA_DIR / "clips"
VIDEOS_DIR = DATA_DIR / "videos"
DATABASE_DIR = DATA_DIR / "database"
DATABASE_CLIPS_DIR = DATABASE_DIR / "clips"
DATABASE_INDEX = DATABASE_DIR / "index.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_verify_model: str = ""
    max_moments_per_group: int = 3

    @property
    def verify_model(self) -> str:
        return self.openai_verify_model or self.openai_model


settings = Settings()

for directory in (DATA_DIR, JOBS_DIR, CLIPS_DIR, VIDEOS_DIR, DATABASE_DIR, DATABASE_CLIPS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
