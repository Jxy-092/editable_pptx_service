import logging
import os
from pathlib import Path

from flask import Flask, jsonify

from config import (
    OUTPUT_FOLDER,
    TMP_FOLDER,
    UPLOAD_FOLDER,
    SOURCE_BACKEND_PATH,
    OSS_ENDPOINT,
    OSS_ACCESS_KEY_ID,
    OSS_ACCESS_KEY_SECRET,
    OSS_BUCKET_NAME,
    OSS_BASE_PATH,
    OSS_UPLOAD_PATH,
)
from controllers.editable_ppt_api import editable_ppt_bp


def create_app():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
    app.config["TMP_FOLDER"] = TMP_FOLDER
    app.config["SOURCE_BACKEND_PATH"] = SOURCE_BACKEND_PATH
    app.config["OSS_ENDPOINT"] = OSS_ENDPOINT
    app.config["OSS_ACCESS_KEY_ID"] = OSS_ACCESS_KEY_ID
    app.config["OSS_ACCESS_KEY_SECRET"] = OSS_ACCESS_KEY_SECRET
    app.config["OSS_BUCKET_NAME"] = OSS_BUCKET_NAME
    app.config["OSS_BASE_PATH"] = OSS_BASE_PATH
    app.config["OSS_UPLOAD_PATH"] = OSS_UPLOAD_PATH
    for path in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER):
        Path(path).mkdir(parents=True, exist_ok=True)
    app.register_blueprint(editable_ppt_bp)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        threaded=True,
    )
