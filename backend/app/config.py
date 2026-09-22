"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime configuration. All names and limits come from env, not literals in callers."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Roland TM-2 Sample Loader")
    app_author: str = Field(default="levensailor")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    log_dir: str = Field(default="logs")
    log_file_name: str = Field(default="tm2_loader.log")
    log_max_bytes: int = Field(default=1_048_576)
    log_backup_count: int = Field(default=3)
    log_timezone: str = Field(default="America/New_York")
    sdcard_path: str = Field(default="")
    wave_root: str = Field(default="Roland/TM-2/WAVE")
    sample_rate: int = Field(default=44100)
    bit_depth: int = Field(default=16)
    default_channels: str = Field(default="stereo")
    max_files_per_folder: int = Field(default=300)
    max_folders: int = Field(default=300)
    max_upload_mb: int = Field(default=200)
    max_filename_length: int = Field(default=32)
    ffmpeg_binary: str = Field(default="ffmpeg")
    default_folders: str = Field(
        default="Kicks,Snares,Toms,Hats,Cymbals,Perc,FX,Loops,Tracks"
    )
    allowed_extensions: str = Field(
        default=".wav,.mp3,.aiff,.aif,.flac,.m4a,.aac,.ogg,.oga,.caf,.wma,.mp4"
    )
    cors_origins: str = Field(default="*")
    freesound_api_key: str = Field(default="")
    freesound_search_url: str = Field(default="https://freesound.org/apiv2/search/")
    freesound_sound_url: str = Field(default="https://freesound.org/apiv2/sounds/")
    archive_search_url: str = Field(default="https://archive.org/advancedsearch.php")
    archive_metadata_url: str = Field(default="https://archive.org/metadata/")
    archive_download_url: str = Field(default="https://archive.org/download/")
    library_license_mode: str = Field(default="performance")
    library_user_agent: str = Field(default="Roland-TM-2-Sample-Loader/1.0")
    library_page_size: int = Field(default=24)

    @field_validator("default_channels")
    @classmethod
    def validate_channels(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"auto", "mono", "stereo"}
        if normalized not in allowed:
            raise ValueError(f"default_channels must be one of {sorted(allowed)}")
        return normalized

    @field_validator("library_license_mode")
    @classmethod
    def validate_license_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"performance", "any"}
        if normalized not in allowed:
            raise ValueError(f"library_license_mode must be one of {sorted(allowed)}")
        return normalized

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def frontend_dir(self) -> Path:
        return FRONTEND_DIR

    @property
    def log_directory(self) -> Path:
        path = Path(self.log_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def log_file_path(self) -> Path:
        return self.log_directory / self.log_file_name

    @property
    def wave_parts(self) -> list[str]:
        return [part for part in Path(self.wave_root).parts if part not in (".", "")]

    @property
    def default_folder_names(self) -> list[str]:
        return [name.strip() for name in self.default_folders.split(",") if name.strip()]

    @property
    def allowed_extension_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.allowed_extensions.split(",")
            if item.strip()
        }

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def catalog_path(self) -> Path:
        return BACKEND_ROOT / "app" / "library" / "catalog.json"

    @property
    def freesound_configured(self) -> bool:
        return bool(self.freesound_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
