import json
import os
import sys
import tempfile
import traceback
from pathlib import Path


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main(request_file: str):
    with open(request_file, "r", encoding="utf-8") as f:
        request = json.load(f)
    source_backend_path = request["source_backend_path"]
    sys.path.insert(0, source_backend_path)
    runtime_config = request.get("runtime_config") or {}
    for key, value in runtime_config.items():
        if value not in (None, ""):
            os.environ[key] = str(value)
    from flask import Flask
    app = Flask("source_export_runner")
    app.config.update(runtime_config)
    app.config.setdefault("UPLOAD_FOLDER", str(Path(source_backend_path).parent / "uploads"))
    with app.app_context():
        from services.export_service import ExportService
        from services.image_editability import TextAttributeExtractorFactory
        text_attribute_extractor = TextAttributeExtractorFactory.create_caption_model_extractor()

        def progress_callback(step, message, percent):
            emit({"event": "progress", "step": step, "message": message, "percent": percent})

        pptx_bytes, warnings = ExportService.create_editable_pptx_with_recursive_analysis(
            image_paths=request["image_paths"],
            output_file=request.get("output_file"),
            slide_width_pixels=request.get("slide_width_pixels", 1920),
            slide_height_pixels=request.get("slide_height_pixels", 1080),
            max_depth=request.get("max_depth", 2),
            max_workers=request.get("max_workers", 4),
            text_attribute_extractor=text_attribute_extractor,
            progress_callback=progress_callback,
            export_extractor_method=request.get("export_extractor_method", "hybrid"),
            export_inpaint_method=request.get("export_inpaint_method", "hybrid"),
            enable_icon_subject_extraction=request.get("enable_icon_subject_extraction", True),
            fail_fast=request.get("fail_fast", True),
        )
        output_bytes_path = None
        if pptx_bytes:
            fd, output_bytes_path = tempfile.mkstemp(suffix=".pptx")
            with os.fdopen(fd, "wb") as f:
                f.write(pptx_bytes)
        emit({
            "event": "result",
            "output_file": request.get("output_file"),
            "output_bytes_path": output_bytes_path,
            "warnings": warnings.to_dict() if warnings else {},
        })


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception as exc:
        emit({"event": "log", "message": traceback.format_exc()})
        raise
