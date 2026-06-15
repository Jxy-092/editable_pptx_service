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
from models import db
from models.task import Task
from controllers.editable_ppt_api import editable_ppt_bp


def create_app():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    app = Flask(__name__)

    data_folder = Path(os.getenv("DATA_FOLDER", str(Path(app.root_path) / "data")))
    data_folder.mkdir(parents=True, exist_ok=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{data_folder / 'editable_pptx_service.db'}",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

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

    for path in (UPLOAD_FOLDER, OUTPUT_FOLDER, TMP_FOLDER, data_folder):
        Path(path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        db.create_all()

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