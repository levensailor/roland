"""Pydantic request and response models."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    app_name: str
    author: str
    ffmpeg_available: bool
    ffmpeg_binary: str


class PublicConfig(BaseModel):
    app_name: str
    author: str
    wave_root: str
    sample_rate: int
    bit_depth: int
    default_channels: str
    max_files_per_folder: int
    max_folders: int
    max_upload_mb: int
    default_folders: list[str]
    allowed_extensions: list[str]
    sdcard_path: str
    root_folder_label: str


class VolumeInfo(BaseModel):
    name: str
    path: str
    writable: bool
    looks_like_sd: bool
    has_wave_root: bool
    free_bytes: int | None = None


class FolderInfo(BaseModel):
    name: str
    path: str
    file_count: int
    remaining_slots: int


class SampleInfo(BaseModel):
    name: str
    folder: str
    path: str
    size_bytes: int
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    duration_seconds: float | None = None


class CardStatus(BaseModel):
    selected_path: str
    exists: bool
    writable: bool
    wave_root: str
    wave_path: str
    wave_ready: bool
    folder_count: int
    file_count: int
    remaining_folders: int
    folders: list[FolderInfo]
    recommended_folders: list[str]
    missing_recommended: list[str]


class InitCardRequest(BaseModel):
    card_path: str
    create_recommended: bool = True


class CreateFolderRequest(BaseModel):
    card_path: str
    folder_name: str


class DeleteSampleRequest(BaseModel):
    card_path: str
    folder: str = ""
    filename: str


class SelectCardRequest(BaseModel):
    card_path: str


class UploadResult(BaseModel):
    original_name: str
    saved_name: str
    folder: str
    path: str
    converted: bool
    sample_rate: int
    bit_depth: int
    channels: int
    duration_seconds: float
    message: str


class UploadResponse(BaseModel):
    card_path: str
    folder: str
    results: list[UploadResult]
    errors: list[str]


class InstructionStep(BaseModel):
    title: str
    detail: str


class InstructionSection(BaseModel):
    heading: str
    steps: list[InstructionStep]


class InstructionsResponse(BaseModel):
    source: str = Field(description="Where these reminders come from")
    format_rules: list[str]
    sections: list[InstructionSection]
    error_codes: list[InstructionStep]
