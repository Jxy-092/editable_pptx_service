# editable_pptx_service

`editable_pptx_service` 是从 [banana-slides](https://github.com/Anionex/banana-slides) 的可编辑 PPTX 导出能力中拆分和改造出的独立后端服务。

服务基于 Flask 提供 HTTP API，支持将远程图片页面下载到本地后，通过 MinerU / OCR / 图像修复 / 文本样式识别等流程生成可编辑 `.pptx` 文件，并通过异步任务接口查询导出进度和下载结果。

## 项目结构

```text
editable_pptx_service/
├── app.py                         # Flask 应用入口，加载 .env、初始化数据库、注册路由
├── config.py                      # 统一配置读取，包含 OSS、AI Provider、MinerU、Baidu、日志、并发等配置
├── controllers/
│   └── editable_ppt_api.py         # 可编辑 PPTX 导出接口、任务查询接口
├── services/
│   ├── task_manager.py             # 异步任务调度与导出任务执行
│   ├── export_service.py           # PPTX 导出主流程
│   ├── file_service.py             # 文件路径与项目文件管理
│   ├── file_parser_service.py      # MinerU 文件解析相关逻辑
│   ├── image_editability/          # 图片可编辑化、元素提取、背景修复、文本属性识别
│   └── ai_providers/               # Gemini / OpenAI / Anthropic / OCR / 图像修复等 Provider
├── models/
│   ├── __init__.py                 # SQLAlchemy db 初始化
│   └── task.py                     # 异步任务模型
├── utils/
│   ├── oss_utils.py                # OSS 文件下载与上传
│   └── response_utils.py           # API 响应封装
├── migrations/                     # Flask-Migrate / Alembic 数据库迁移目录
├── requirements.txt                # Python 依赖
└── README.md

## 本地启动

### 1. 创建虚拟环境

Linux / macOS：

```bash
python -m venv .venv
source .venv/bin/activate

Windows CMD：
python -m venv .venv
.\.venv\Scripts\Activate.ps1

### 2.安装依赖
pip install -r requirements.txt

### 3.环境变量
editable_pptx_service/.env

### 4.启动服务
python app.py



## 使用 uv 启动

### 1. 安装 uv

Windows PowerShell：
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

### 2.创建 .venv 虚拟环境
uv venv
uv python install 3.13

### 3.安装依赖
uv pip install -r requirements.txt

### 4.启动服务
uv run python app.py



### Postman  测试JSON
/api/export/editable-pptx 导出接口
{
  "projectId": "{{projectId}}",
  "imagePaths": [
    "{{imageUrl}}"
  ],
  "filename": "XXX.pptx",
  "maxDepth": 1,
  "maxWorkers": 4,
  "exportExtractorMethod": "hybrid/mineru",
  "exportInpaintMethod": "hybrid/baidu"
}
/api/tasks/{{taskId}} 查询进度接口
