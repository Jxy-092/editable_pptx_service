"""
OSS文件下载和上传工具
"""
import os
import requests
import tempfile
import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def is_url(path: str) -> bool:
    """判断是否为URL"""
    return path.startswith('http://') or path.startswith('https://')


def download_file(url: str, save_dir: str = None) -> str:
    """
    从URL下载文件到本地

    Args:
        url: 文件URL
        save_dir: 保存目录，默认使用临时目录

    Returns:
        本地文件路径
    """
    if save_dir is None:
        save_dir = tempfile.mkdtemp()

    # 从URL提取文件名
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = f"download_{hash(url)}.tmp"

    local_path = os.path.join(save_dir, filename)

    # 下载文件
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    with open(local_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return local_path


def process_image_paths(image_paths: List[str]) -> tuple[List[str], List[str]]:
    """
    处理图片路径，下载OSS文件

    Args:
        image_paths: 图片路径列表（可以是本地路径或OSS URL）

    Returns:
        (本地路径列表, 需要清理的临时文件列表)
    """
    local_paths = []
    temp_files = []
    temp_dir = tempfile.mkdtemp()

    for path in image_paths:
        if is_url(path):
            # OSS URL，下载到本地
            local_path = download_file(path, temp_dir)
            local_paths.append(local_path)
            temp_files.append(local_path)
        else:
            # 本地路径，直接使用
            local_paths.append(path)

    return local_paths, temp_files


def upload_bytes_to_oss(
    file_bytes: bytes,
    object_key: str,
    oss_endpoint: str = None,
    oss_access_key_id: str = None,
    oss_access_key_secret: str = None,
    oss_bucket_name: str = None,
    use_base_path: bool = True,
    expires: int = 259200  # 3天
) -> str:
    """
    上传字节流到OSS并返回签名URL

    Args:
        file_bytes: 文件字节流
        object_key: OSS对象键（如 'file.pptx'，会自动添加base_path和path前缀）
        oss_endpoint: OSS端点（如果为None，从Flask配置读取）
        oss_access_key_id: OSS访问密钥ID
        oss_access_key_secret: OSS访问密钥Secret
        oss_bucket_name: OSS存储桶名称
        use_base_path: 是否使用base_path和path前缀（默认True）
        expires: 签名URL过期时间（秒，默认259200=3天）

    Returns:
        str: OSS签名URL
    """
    import oss2

    # 如果参数为None，从Flask配置读取
    if not all([oss_endpoint, oss_access_key_id, oss_access_key_secret, oss_bucket_name]):
        from flask import current_app
        oss_endpoint = oss_endpoint or current_app.config.get('OSS_ENDPOINT')
        oss_access_key_id = oss_access_key_id or current_app.config.get('OSS_ACCESS_KEY_ID')
        oss_access_key_secret = oss_access_key_secret or current_app.config.get('OSS_ACCESS_KEY_SECRET')
        oss_bucket_name = oss_bucket_name or current_app.config.get('OSS_BUCKET_NAME')

    if not all([oss_endpoint, oss_access_key_id, oss_access_key_secret, oss_bucket_name]):
        raise ValueError("OSS配置不完整")

    # 构建完整的对象键（添加base_path和path前缀）
    if use_base_path:
        from flask import current_app
        base_path = current_app.config.get('OSS_BASE_PATH', '')
        upload_path = current_app.config.get('OSS_UPLOAD_PATH', '')
        object_key = f"{base_path}{upload_path}{object_key}"
        logger.info(f"使用完整路径: {object_key}")

    # 创建OSS客户端（确保使用HTTPS）
    # 如果endpoint不包含协议，添加https://
    if not oss_endpoint.startswith('http'):
        oss_endpoint = f'https://{oss_endpoint}'

    auth = oss2.Auth(oss_access_key_id, oss_access_key_secret)
    bucket = oss2.Bucket(auth, oss_endpoint, oss_bucket_name, is_cname=False)

    # 上传文件
    result = bucket.put_object(object_key, file_bytes)

    if result.status == 200:
        # 提取原始文件名（不包含路径）
        original_filename = object_key.split('/')[-1]

        # 对文件名进行URL编码（支持中文）
        from urllib.parse import quote
        encoded_filename = quote(original_filename)

        # 生成签名URL，指定下载时的文件名
        oss_url = bucket.sign_url(
            'GET',
            object_key,
            expires,
            params={
                'response-content-disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
            }
        )

        # 强制使用 HTTPS 协议，避免 Mixed Content 错误
        if oss_url.startswith('http://'):
            oss_url = oss_url.replace('http://', 'https://', 1)
            logger.info(f"已将 OSS URL 从 HTTP 转换为 HTTPS")

        logger.info(f"文件已上传到OSS（签名URL，{expires}秒有效）: {oss_url[:100]}... ({len(file_bytes)} bytes)")
        return oss_url
    else:
        raise Exception(f"OSS上传失败: {result.status}")

def cleanup_temp_paths(paths: List[str]):
    """
    清理临时文件或临时目录。
    """
    if not paths:
        return

    # 去重并按路径长度倒序清理，避免先删父目录后子文件报错。
    unique_paths = sorted(set(str(p) for p in paths if p), key=len, reverse=True)

    for path in unique_paths:
        try:
            if not os.path.exists(path):
                logger.info(f"Temp path already removed or missing: {path}")
                continue

            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
                logger.info(f"Cleaned temp directory: {path}")
            else:
                os.remove(path)
                logger.info(f"Cleaned temp file: {path}")

        except Exception as cleanup_error:
            logger.warning(f"Failed to clean temp path {path}: {cleanup_error}")

