import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", str(BASE_DIR / "outputs"))
TMP_FOLDER = os.getenv("TMP_FOLDER", str(BASE_DIR / "tmp"))
SOURCE_BACKEND_PATH = os.getenv("SOURCE_BACKEND_PATH", "")

OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")
OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")
OSS_BASE_PATH = os.getenv("OSS_BASE_PATH", "")
OSS_UPLOAD_PATH = os.getenv("OSS_UPLOAD_PATH", "")


@dataclass
class ExportConfig:
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    provider_format: str = "gemini"
    text_model: Optional[str] = None
    image_model: Optional[str] = None
    image_caption_model: Optional[str] = None
    image_caption_model_source: Optional[str] = None
    mineru_token: Optional[str] = None
    mineru_api_base: Optional[str] = None
    baidu_api_key: Optional[str] = None
    max_depth: int = 2
    max_workers: int = 4
    export_extractor_method: str = "hybrid"
    export_inpaint_method: str = "hybrid"
    enable_icon_subject_extraction: bool = True
    export_allow_partial: bool = False
    source_backend_path: Optional[str] = None
    extra_config: Dict[str, Any] = field(default_factory=dict)

    def to_runtime_config(self) -> Dict[str, Any]:
        caption_source = self.image_caption_model_source or self.provider_format
        config = {
            "AI_PROVIDER_FORMAT": self.provider_format,
            "TEXT_MODEL": self.text_model,
            "IMAGE_MODEL": self.image_model,
            "IMAGE_CAPTION_MODEL": self.image_caption_model or self.image_model or self.text_model,
            "IMAGE_CAPTION_MODEL_SOURCE": caption_source,
            "MINERU_TOKEN": self.mineru_token,
            "MINERU_API_BASE": self.mineru_api_base,
            "BAIDU_API_KEY": self.baidu_api_key,
            "EXPORT_EXTRACTOR_METHOD": self.export_extractor_method,
            "EXPORT_INPAINT_METHOD": self.export_inpaint_method,
        }
        if self.api_key:
            config["IMAGE_CAPTION_API_KEY"] = self.api_key
            if self.provider_format == "gemini":
                config["GOOGLE_API_KEY"] = self.api_key
            elif self.provider_format == "openai":
                config["OPENAI_API_KEY"] = self.api_key
        if self.api_base:
            config["IMAGE_CAPTION_API_BASE"] = self.api_base
            if self.provider_format == "gemini":
                config["GOOGLE_API_BASE"] = self.api_base
            elif self.provider_format == "openai":
                config["OPENAI_API_BASE"] = self.api_base
        for key, value in self.extra_config.items():
            if value not in (None, ""):
                config[key] = value
        return {key: value for key, value in config.items() if value not in (None, "")}

