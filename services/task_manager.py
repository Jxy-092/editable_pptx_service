from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from PIL import Image

from contextlib import contextmanager
from services.export_service import ExportError, ExportService
from utils.oss_utils import upload_bytes_to_oss
from models import db, Task

logger = logging.getLogger(__name__)

class ResourceLimiter:
    """Thread-safe concurrency limiter for a shared external resource."""

    def __init__(self, name: str, capacity: int):
        self.name = name
        self.capacity = max(1, int(capacity))
        self._in_use = 0
        self._condition = threading.Condition()

    def update_capacity(self, capacity: int):
        new_capacity = max(1, int(capacity))
        with self._condition:
            if new_capacity == self.capacity:
                return
            logger.info(f"Updating {self.name} limiter: {self.capacity} -> {new_capacity}")
            self.capacity = new_capacity
            self._condition.notify_all()

    @contextmanager
    def slot(self, label: str, on_acquire: Optional[Callable[[], None]] = None):
        waited = False
        with self._condition:
            while self._in_use >= self.capacity:
                if not waited:
                    waited = True
                    logger.info(
                        f"{self.name} limiter full ({self._in_use}/{self.capacity}), "
                        f"waiting: {label}"
                    )
                self._condition.wait(timeout=0.5)

            self._in_use += 1

        if waited:
            logger.info(f"{self.name} limiter slot acquired: {label}")

        try:
            if on_acquire:
                on_acquire()
            yield
        finally:
            with self._condition:
                self._in_use -= 1
                self._condition.notify()


class TaskManager:
    def __init__(self, max_workers: int = 4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_tasks = {}
        self.lock = threading.Lock()

    def submit_task(self, task_id: str, func: Callable, *args, **kwargs):
        future = self.executor.submit(func, task_id, *args, **kwargs)
        with self.lock:
            self.active_tasks[task_id] = future
        future.add_done_callback(lambda f: self._task_done_callback(task_id, f))

    def _task_done_callback(self, task_id: str, future):
        try:
            exception = future.exception()
            if exception:
                logger.error("Task %s failed with exception: %s", task_id, exception, exc_info=exception)
        except Exception as exc:
            logger.error("Error in task callback for %s: %s", task_id, exc, exc_info=True)
        finally:
            with self.lock:
                self.active_tasks.pop(task_id, None)

    def is_task_active(self, task_id: str) -> bool:
        with self.lock:
            return task_id in self.active_tasks

    def update_max_workers(self, max_workers: int):
        """Replace the shared executor so new tasks use a higher/lower ceiling."""
        new_max_workers = max(1, int(max_workers))
        old_executor = None

        with self.lock:
            if new_max_workers == self.max_workers:
                return

            logger.info(f"Updating background task pool size: {self.max_workers} -> {new_max_workers}")
            old_executor = self.executor
            self.executor = ThreadPoolExecutor(max_workers=new_max_workers)
            self.max_workers = new_max_workers

        if old_executor is not None:
            old_executor.shutdown(wait=False, cancel_futures=False)

def _compute_background_worker_target(description_workers: int, image_workers: int) -> int:
    """Keep the shared task pool from becoming the product-level bottleneck."""
    return max(8, int(description_workers) + int(image_workers) + 4)


# Global task manager and resource limiters
task_manager = TaskManager(max_workers=max(8, int(os.getenv('MAX_BACKGROUND_TASK_WORKERS', '16'))))
image_resource_limiter = ResourceLimiter("image", int(os.getenv('MAX_IMAGE_WORKERS', '20')))
text_resource_limiter = ResourceLimiter("text", int(os.getenv('MAX_DESCRIPTION_WORKERS', '20')))


def sync_resource_limits(description_workers: int, image_workers: int):
    """Apply the latest runtime settings to shared concurrency controls."""
    task_manager.update_max_workers(
        _compute_background_worker_target(description_workers, image_workers)
    )
    image_resource_limiter.update_capacity(image_workers)
    text_resource_limiter.update_capacity(description_workers)

def export_editable_pptx_with_recursive_analysis_task(
        task_id: str,
        project_id: str,
        filename: str,
        image_paths: list,
        file_service,
        page_ids: list = None,
        max_depth: int = 2,
        max_workers: int = 4,
        export_extractor_method: str = 'hybrid',
        export_inpaint_method: str = 'hybrid',
        enable_icon_subject_extraction: bool = True,
        app=None
):
    """
    使用递归图片可编辑化分析导出可编辑PPTX的后台任务

    这是新的架构方法，使用ImageEditabilityService进行递归版面分析。
    与旧方法的区别：
    - 不再假设图片是16:9
    - 支持任意尺寸和分辨率
    - 递归分析图片中的子图和图表
    - 更智能的坐标映射和元素提取
    - 不需要 ai_service（使用 ImageEditabilityService 和 MinerU）

    Args:
        task_id: 任务ID
        project_id: 项目ID
        filename: 输出文件名
        file_service: 文件服务实例
        page_ids: 可选的页面ID列表（如果提供，只导出这些页面）
        max_depth: 最大递归深度
        max_workers: 并发处理数
        export_extractor_method: 组件提取方法 ('mineru' 或 'hybrid')
        export_inpaint_method: 背景修复方法 ('generative', 'baidu', 'hybrid')
        app: Flask应用实例
    """
    logger.info(f"🚀 Task {task_id} started: export_editable_pptx_with_recursive_analysis (project={project_id}, depth={max_depth}, workers={max_workers}, extractor={export_extractor_method}, inpaint={export_inpaint_method}, icon_subject_extraction={enable_icon_subject_extraction})")

    if app is None:
        raise ValueError("Flask app instance must be provided")

    with app.app_context():
        import os
        from datetime import datetime
        from PIL import Image
        from services.export_service import ExportService, ExportError

        logger.info(f"开始递归分析导出任务 {task_id} for project {project_id}")

        try:
            # Get project
            # project = Project.query.get(project_id)
            # if not project:
            #     raise ValueError(f'Project {project_id} not found')

            # 读取项目的导出设置：是否允许返回半成品
            export_allow_partial = False
            fail_fast = True
            logger.info(f"导出设置: export_allow_partial={export_allow_partial}, fail_fast={fail_fast}")

            # IMPORTANT: Expire cached objects to ensure fresh data from database
            # This prevents reading stale generated_image_path after page regeneration
            db.session.expire_all()

            if not image_paths:
                raise ValueError('No generated images found for project')

            logger.info(f"找到 {len(image_paths)} 张图片")

            # 初始化任务进度（包含消息日志）
            task = Task.query.get(task_id)
            task.set_progress({
                "total": 100,  # 使用百分比
                "completed": 0,
                "failed": 0,
                "current_step": "准备中...",
                "percent": 0,
                "messages": ["🚀 开始导出可编辑PPTX..."]  # 消息日志
            })
            db.session.commit()

            # 进度回调函数 - 更新数据库中的进度
            progress_messages = ["🚀 开始导出可编辑PPTX..."]
            max_messages = 10  # 最多保留最近10条消息

            def progress_callback(step: str, message: str, percent: int):
                """更新任务进度到数据库"""
                nonlocal progress_messages
                try:
                    # 添加新消息到日志
                    new_message = f"[{step}] {message}"
                    progress_messages.append(new_message)
                    # 只保留最近的消息
                    if len(progress_messages) > max_messages:
                        progress_messages = progress_messages[-max_messages:]

                    # 更新数据库
                    task = Task.query.get(task_id)
                    if task:
                        task.set_progress({
                            "total": 100,
                            "completed": percent,
                            "failed": 0,
                            "current_step": message,
                            "percent": percent,
                            "messages": progress_messages.copy()
                        })
                        db.session.commit()
                except Exception as e:
                    logger.warning(f"更新进度失败: {e}")

            # Step 1: 准备工作
            logger.info("Step 1: 准备工作...")
            progress_callback("准备", f"找到 {len(image_paths)} 张幻灯片图片", 2)

            # 准备输出路径
            exports_dir = os.path.join(app.root_path, project_id, 'exports')
            os.makedirs(exports_dir, exist_ok=True)

            # Handle filename collision
            if not filename.endswith('.pptx'):
                filename += '.pptx'

            output_path = os.path.join(exports_dir, filename)
            if os.path.exists(output_path):
                base_name = filename.rsplit('.', 1)[0]
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f"{base_name}_{timestamp}.pptx"
                output_path = os.path.join(exports_dir, filename)
                logger.info(f"文件名冲突，使用新文件名: {filename}")

            # 获取第一张图片的尺寸作为参考
            first_img = Image.open(image_paths[0])
            slide_width, slide_height = first_img.size
            first_img.close()

            logger.info(f"幻灯片尺寸: {slide_width}x{slide_height}")
            logger.info(f"递归深度: {max_depth}, 并发数: {max_workers}")
            progress_callback("准备", f"幻灯片尺寸: {slide_width}×{slide_height}", 3)

            # Step 2: 创建文字属性提取器
            from services.image_editability import TextAttributeExtractorFactory
            text_attribute_extractor = TextAttributeExtractorFactory.create_caption_model_extractor()
            progress_callback("准备", "文字属性提取器已初始化", 5)

            # Step 3: 调用导出方法（使用项目的导出设置）
            logger.info(f"Step 3: 创建可编辑PPTX (extractor={export_extractor_method}, inpaint={export_inpaint_method}, fail_fast={fail_fast})...")
            progress_callback("配置", f"提取方法: {export_extractor_method}, 背景修复: {export_inpaint_method}", 6)

            pptx_bytes, export_warnings = ExportService.create_editable_pptx_with_recursive_analysis(
                image_paths=image_paths,
                output_file=output_path,
                slide_width_pixels=slide_width,
                slide_height_pixels=slide_height,
                max_depth=max_depth,
                max_workers=max_workers,
                text_attribute_extractor=text_attribute_extractor,
                progress_callback=progress_callback,
                export_extractor_method=export_extractor_method,
                export_inpaint_method=export_inpaint_method,
                enable_icon_subject_extraction=enable_icon_subject_extraction,
                fail_fast=fail_fast
            )

            logger.info(f"✓ 可编辑PPTX已创建: {output_path}")

            # Step 4: 标记任务完成 并将导出的PPTX上传至OSS
            download_path = upload_bytes_to_oss(
                file_bytes=pptx_bytes,
                object_key=filename  # 使用文件名作为对象键
            )

            logger.info(f"✓ 可编辑PPTX已上传到OSS: {download_path}")

            # 添加完成消息
            progress_messages.append("✅ 导出完成！")

            # 添加警告信息（如果有）
            warning_messages = []
            if export_warnings and export_warnings.has_warnings():
                warning_messages = export_warnings.to_summary()
                progress_messages.extend(warning_messages)
                logger.warning(f"导出有 {len(warning_messages)} 条警告")

            task = Task.query.get(task_id)
            if task:
                task.status = 'COMPLETED'
                task.completed_at = datetime.utcnow()
                task.set_progress({
                    "total": 100,
                    "completed": 100,
                    "failed": 0,
                    "current_step": "✓ 导出完成",
                    "percent": 100,
                    "messages": progress_messages,
                    "download_url": download_path,
                    "filename": filename,
                    "method": "recursive_analysis",
                    "max_depth": max_depth,
                    "warnings": warning_messages,  # 单独的警告列表
                    "warning_details": export_warnings.to_dict() if export_warnings else {}  # 详细警告信息
                })
                db.session.commit()
                logger.info(f"✓ 任务 {task_id} 完成 - 递归分析导出成功（深度={max_depth}）")

        except ExportError as e:
            # 导出错误（fail_fast 模式下的详细错误）
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"✗ 任务 {task_id} 导出失败: {e.message}")
            logger.error(f"错误类型: {e.error_type}, 详情: {e.details}")

            # 标记任务失败，包含详细错误信息
            task = Task.query.get(task_id)
            if task:
                task.status = 'FAILED'
                # 构建详细的错误消息
                error_message = f"{e.message}"
                if e.help_text:
                    error_message += f"\n\n💡 {e.help_text}"
                task.error_message = error_message
                task.completed_at = datetime.utcnow()
                # 在 progress 中保存详细错误信息
                task.set_progress({
                    "total": 100,
                    "completed": 0,
                    "failed": 1,
                    "current_step": "导出失败",
                    "percent": 0,
                    "error_type": e.error_type,
                    "error_details": e.details,
                    "help_text": e.help_text
                })
                db.session.commit()

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"✗ 任务 {task_id} 失败: {error_detail}")

            # 标记任务失败
            task = Task.query.get(task_id)
            if task:
                task.status = 'FAILED'
                task.error_message = str(e)
                task.completed_at = datetime.utcnow()
                db.session.commit()
