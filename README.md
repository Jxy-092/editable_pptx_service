# editable_pptx_service

启动：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

如需使用源项目完整可编辑化逻辑，启动前配置源项目 backend 路径：

```bash
export SOURCE_BACKEND_PATH=/path/to/banana-slides/backend
python app.py
```

Windows：

```bat
set SOURCE_BACKEND_PATH=C:\Users\appadmin\IdeaProjects\python-1\backend
python app.py
```

导出接口：

```http
POST /api/export/editable-pptx
Content-Type: application/json
```

请求示例：

```json
{
  "imagePaths": [
    "https://example-bucket.oss-cn-shanghai.aliyuncs.com/slides/page1.jpg"
  ],
  "filename": "demo.pptx",
  "maxDepth": 1,
  "maxWorkers": 4,
  "exportExtractorMethod": "hybrid",
  "exportInpaintMethod": "hybrid",
  "enableIconSubjectExtraction": true,
  "exportAllowPartial": false,
  "providerFormat": "gemini",
  "apiKey": "YOUR_API_KEY",
  "apiBase": "https://your-api-base",
  "textModel": "gemini-3.1-pro-preview",
  "imageModel": "gemini-3.1-flash-image-preview",
  "imageCaptionModel": "gemini-3.1-pro-preview",
  "mineruToken": "YOUR_MINERU_TOKEN",
  "mineruApiBase": "https://mineru.net",
  "baiduApiKey": "YOUR_BAIDU_API_KEY",
  "oss": {
    "endpoint": "https://oss-cn-shanghai.aliyuncs.com",
    "accessKeyId": "YOUR_OSS_AK",
    "accessKeySecret": "YOUR_OSS_SK",
    "bucket": "your-bucket",
    "basePath": "",
    "uploadPath": "editable-pptx/"
  }
}
```

查询进度：

```http
GET /api/tasks/{taskId}
```

响应中的 `progress.messages` 会按阶段记录，不重复写入同一条进度。
