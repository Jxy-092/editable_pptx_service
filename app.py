"""
Simplified Flask Application Entry Point
"""
import os
import sys
import hmac
import logging
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3
from sqlalchemy.exc import SQLAlchemyError
from flask_migrate import Migrate
from controllers.editable_ppt_api import editable_ppt_bp

# Load environment variables from project root .env file
# resolve 把路径转换成绝对路径，并尽量解析路径中的符号链接、..、. 等内容
# 以当前 app.py 文件所在目录作为项目根目录
_project_root = Path(__file__).resolve().parent
_env_file = _project_root / '.env'
# 读取指定的 .env 文件，并把里面的配置加载到 os.environ 环境变量中
load_dotenv(dotenv_path=_env_file, override=True)

from flask import Flask
from flask_cors import CORS
from models import db
from config import Config

# Enable SQLite WAL mode for all connections
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """
    Enable WAL mode and related PRAGMAs for each SQLite connection.
    Registered once at import time to avoid duplicate handlers when
    create_app() is called multiple times.
    """
    # Only apply to SQLite connections
    if not isinstance(dbapi_conn, sqlite3.Connection):
        return

    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=60000")  # 60 seconds timeout
    finally:
        cursor.close()


def create_app():
    """Application factory"""
    app = Flask(__name__)

    # Load configuration from Config class
    app.config.from_object(Config)

    # Allow DATABASE_URL env var to override config at runtime (supports test isolation)
    if os.getenv('DATABASE_URL'):
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')

    # Ensure instance directory exists for the default SQLite path in Config
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    instance_dir = os.path.join(backend_dir, 'instance')
    os.makedirs(instance_dir, exist_ok=True)

    # Ensure upload folder exists
    project_root = os.path.dirname(backend_dir)
    upload_folder = os.path.join(project_root, 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = upload_folder

    # CORS configuration (parse from environment)
    raw_cors = os.getenv('CORS_ORIGINS', 'http://localhost:3000')
    if raw_cors.strip() == '*':
        cors_origins = '*'
    else:
        cors_origins = [o.strip() for o in raw_cors.split(',') if o.strip()]
    app.config['CORS_ORIGINS'] = cors_origins

    # Initialize logging (log to stdout so Docker can capture it)
    log_level = getattr(logging, app.config['LOG_LEVEL'], logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # 设置第三方库的日志级别，避免过多的DEBUG日志
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    werkzeug_log_level = app.config.get('WERKZEUG_LOG_LEVEL', 'INFO')
    if isinstance(werkzeug_log_level, str):
        werkzeug_log_level = werkzeug_log_level.strip()
        werkzeug_log_level = (
            int(werkzeug_log_level)
            if werkzeug_log_level.isdigit()
            else werkzeug_log_level.upper()
        )
    werkzeug_logger = logging.getLogger('werkzeug')
    try:
        werkzeug_logger.setLevel(werkzeug_log_level)
    except (ValueError, TypeError):
        werkzeug_logger.setLevel(logging.INFO)
    logging.getLogger('volcenginesdkarkruntime').setLevel(logging.WARNING)

    # Initialize extensions
    db.init_app(app)
    CORS(app, origins=cors_origins)
    # Database migrations (Alembic via Flask-Migrate)
    Migrate(app, db)

    # 注册多个路由  先不需要故删除
    # Register blueprints
    app.register_blueprint(editable_ppt_bp)

    with app.app_context():
        # 本地独立服务启动时自动创建缺失的数据表。
        try:
            db.create_all()
            logging.info("Database tables checked/created successfully")
        except SQLAlchemyError as db_error:
            logging.error(f"Failed to create database tables: {db_error}", exc_info=True)
            raise

    # Access code enforcement on all /api/ routes
    @app.before_request
    def _enforce_access_code():
        from flask import request, jsonify
        expected = os.getenv('ACCESS_CODE', '').strip()
        if not expected:
            return  # not enabled
        if not request.path.startswith('/api/'):
            return  # non-API routes (health, static, etc.)
        if request.path.startswith('/api/access-code/'):
            return  # allow check/verify endpoints
        code = request.headers.get('X-Access-Code', '')
        if hmac.compare_digest(code, expected):
            return
        return jsonify({'error': 'Access code required'}), 403

    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'ok', 'message': 'Banana Slides API is running'}

    # Access code verification
    @app.route('/api/access-code/check', methods=['GET'])
    def check_access_code():
        """Check if access code protection is enabled"""
        enabled = bool(os.getenv('ACCESS_CODE', '').strip())
        return {'data': {'enabled': enabled}}

    @app.route('/api/access-code/verify', methods=['POST'])
    def verify_access_code():
        """Verify the provided access code"""
        from flask import request, jsonify
        expected = os.getenv('ACCESS_CODE', '').strip()
        if not expected:
            return {'data': {'valid': True}}
        code = (request.json or {}).get('code', '')
        if hmac.compare_digest(code, expected):
            return {'data': {'valid': True}}
        return jsonify({'error': 'Invalid access code'}), 403

    # Output language endpoint
    @app.route('/api/output-language', methods=['GET'])
    def get_output_language():
        """
        返回: zh, ja, en, auto
        """
        try:
            return {'data': {'language': Config.OUTPUT_LANGUAGE}}
        except SQLAlchemyError as db_error:
            logging.warning(f"Failed to load output language from settings: {db_error}")
            return {'data': {'language': Config.OUTPUT_LANGUAGE}}  # 默认中文

    # Root endpoint
    @app.route('/')
    def index():
        return {
            'name': 'Banana Slides API',
            'version': '1.0.0',
            'description': 'AI-powered PPT generation service',
            'endpoints': {
                'health': '/health',
                'api_docs': '/api',
                'projects': '/api/projects'
            }
        }

    return app


# Create app instance
app = create_app()


def _compute_worktree_port(base_port: int) -> int:
    """Compute a deterministic port from the worktree directory name.

    Uses MD5 of the project root basename so each worktree gets a unique,
    stable port pair (backend 5xxx, frontend 3xxx) without manual config.
    """
    import hashlib
    basename = _project_root.name
    offset = int(hashlib.md5(basename.encode()).hexdigest()[:8], 16) % 500
    return base_port + offset


if __name__ == '__main__':
    # Run development server
    if os.getenv("IN_DOCKER", "0") == "1":
        port = 5000  # Docker 容器内部固定使用 5000 端口
    elif os.getenv('BACKEND_PORT'):
        port = int(os.getenv('BACKEND_PORT'))
    else:
        port = _compute_worktree_port(5000)
    debug = os.getenv('FLASK_ENV', 'development') == 'development'

    logging.info(
        "\n"
        "╔══════════════════════════════════════╗\n"
        "║   🍌 Banana Slides API Server 🍌   ║\n"
        "╚══════════════════════════════════════╝\n"
        f"Server starting on: http://localhost:{port}\n"
        f"Output Language: {Config.OUTPUT_LANGUAGE}\n"
        f"Environment: {os.getenv('FLASK_ENV', 'development')}\n"
        f"Debug mode: {debug}\n"
        f"API Base URL: http://localhost:{port}/api\n"
        f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}\n"
        f"Uploads: {app.config['UPLOAD_FOLDER']}"
    )

    # Using absolute paths for database, so WSL path issues should not occur
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)
