from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict

from flask import Blueprint, current_app, request

from models import db, Task
from utils.oss_utils import download_file
from utils import (
    error_response, not_found, bad_request, success_response
)

logger = logging.getLogger(__name__)
editable_ppt_bp = Blueprint("editable_ppt_api", __name__)

def _apply_oss_config(data: Dict[str, Any]):
    oss = data.get("oss") or {}
    mapping = {
        "OSS_ENDPOINT": oss.get("endpoint") or data.get("OSS_ENDPOINT") or data.get("oss_endpoint"),
        "OSS_ACCESS_KEY_ID": oss.get("access_key_id") or oss.get("accessKeyId") or data.get("OSS_ACCESS_KEY_ID") or data.get("oss_access_key_id"),
        "OSS_ACCESS_KEY_SECRET": oss.get("access_key_secret") or oss.get("accessKeySecret") or data.get("OSS_ACCESS_KEY_SECRET") or data.get("oss_access_key_secret"),
        "OSS_BUCKET_NAME": oss.get("bucket") or oss.get("bucketName") or data.get("OSS_BUCKET_NAME") or data.get("oss_bucket_name"),
        "OSS_BASE_PATH": oss.get("base_path") or oss.get("basePath") or data.get("OSS_BASE_PATH") or data.get("oss_base_path"),
        "OSS_UPLOAD_PATH": oss.get("upload_path") or oss.get("uploadPath") or data.get("OSS_UPLOAD_PATH") or data.get("oss_upload_path"),
    }
    for key, value in mapping.items():
        if value not in (None, ""):
            current_app.config[key] = value
            os.environ[key] = str(value)


@editable_ppt_bp.post("/api/export/editable-pptx")
def export_editable_pptx():
    """
    POST /api/projects/{project_id}/export/editable-pptx - 导出可编辑PPTX（异步）

    使用递归分析方法（支持任意尺寸、递归子图分析）

    这个端点创建一个异步任务来执行以下操作：
    1. 递归分析图片（支持任意尺寸和分辨率）
    2. 转换为PDF并上传MinerU识别
    3. 提取元素bbox和生成clean background（inpainting）
    4. 递归处理图片/图表中的子元素
    5. 创建可编辑PPTX

    Request body (JSON):
        {
            "filename": "optional_custom_name.pptx",
            "page_ids": ["id1", "id2"],  // 可选，要导出的页面ID列表（不提供则导出所有）
            "max_depth": 1,      // 可选，递归深度（默认1=不递归，2=递归一层）
            "max_workers": 4     // 可选，并发数（默认4）
        }

    Returns:
        JSON with task_id, e.g.
        {
            "success": true,
            "data": {
                "task_id": "uuid-here",
                "method": "recursive_analysis",
                "max_depth": 2,
                "max_workers": 4
            },
            "message": "Export task created"
        }

    轮询 /api/projects/{project_id}/tasks/{task_id} 获取进度和下载链接
    """
    try:
        # Get parameters from request body
        data = request.get_json() or {}

        project_id = data.get("project_id") or data.get("projectId")
        if not project_id:
            return bad_request("projectId 不能为空")

        image_paths = data.get("image_paths") or data.get("imagePaths") or []
        if not image_paths:
            return bad_request("imagePaths 不能为空")

        if isinstance(image_paths, str):
            image_paths = [image_paths]

        image_paths = image_paths[:1]

        export_project_dir = os.path.join(current_app.root_path, "export", project_id)
        os.makedirs(export_project_dir, exist_ok=True)
        local_image_path = download_file(image_paths[0], export_project_dir)

        if not local_image_path or not os.path.exists(local_image_path):
            logger.error(
                "图片下载失败或本地文件不存在: image_url=%s, local_image_path=%s, export_project_dir=%s",
                image_paths[0],
                local_image_path,
                export_project_dir
            )
            return bad_request("图片下载失败或本地文件不存在")

        local_paths = [local_image_path]

        # 如果没有传filename这个字段使用，
        filename = data.get('filename', f'editable_{project_id}.pptx')
        if not filename.endswith('.pptx'):
            filename += '.pptx'

        # 递归分析参数
        # max_depth 语义：1=只处理表层不递归，2=递归一层（处理图片/图表中的子元素）
        max_depth = data.get('max_depth') or data.get("maxDepth") or 1  # 默认不递归，与测试脚本一致
        max_workers = data.get('max_workers') or data.get("maxWorkers") or 4

        # Validate parameters
        # max_depth >= 1: 至少处理表层元素
        if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 5:
            return bad_request("max_depth must be an integer between 1 and 5")

        if not isinstance(max_workers, int) or max_workers < 1 or max_workers > 16:
            return bad_request("max_workers must be an integer between 1 and 16")

        # Create task record
        task = Task(
            project_id=project_id,
            task_type='EXPORT_EDITABLE_PPTX',
            status='PENDING'
        )
        db.session.add(task)
        db.session.commit()

        logger.info(f"Created export task {task.id} for project {project_id} (recursive analysis: depth={max_depth}, workers={max_workers})")

        # Get services
        from services.file_service import FileService
        from services.task_manager import task_manager, export_editable_pptx_with_recursive_analysis_task

        file_service = FileService(current_app.config['UPLOAD_FOLDER'])

        # Get Flask app instance for background task
        app = current_app._get_current_object()

        # 读取项目的导出设置
        export_extractor_method = data.get("export_extractor_method") or data.get("exportExtractorMethod") or "hybrid"
        export_inpaint_method = data.get("export_inpaint_method") or data.get("exportInpaintMethod") or "hybrid"
        enable_icon_subject_extraction = True

        logger.info(
            f"Export settings: extractor={export_extractor_method}, "
            f"inpaint={export_inpaint_method}, "
            f"icon_subject_extraction={enable_icon_subject_extraction}"
        )

        # 使用递归分析任务（不需要 ai_service，使用 ImageEditabilityService）
        task_manager.submit_task(
            task.id,
            export_editable_pptx_with_recursive_analysis_task,
            project_id=project_id,
            filename=filename,
            image_paths=local_paths,
            file_service=file_service,
            page_ids=["page_1"],
            max_depth=max_depth,
            max_workers=max_workers,
            export_extractor_method=export_extractor_method,
            export_inpaint_method=export_inpaint_method,
            enable_icon_subject_extraction=enable_icon_subject_extraction,
            app=app
        )

        logger.info(f"Submitted recursive export task {task.id} to task manager")

        return success_response(
            data={
                "task_id": task.id,
                "method": "recursive_analysis",
                "max_depth": max_depth,
                "max_workers": max_workers
            },
            message="Export task created (using recursive analysis)"
        )

    except Exception as e:
        logger.exception("Error creating export task")
        return error_response('SERVER_ERROR', str(e), 500)


@editable_ppt_bp.get("/api/tasks/<task_id>")
def get_task(task_id: str):
    try:
        task = Task.query.get(task_id)

        if not task :
            return not_found('Task')

        return success_response(task.to_dict())

    except Exception as e:
        logger.error(f"get_task_status failed: {str(e)}", exc_info=True)
        return error_response('SERVER_ERROR', str(e), 500)
