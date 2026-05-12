from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    workspace_dir: str = "../workspace"
    cors_origins: str = "http://localhost:5173"

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir).resolve()

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
