# Auto Notes

`Auto Notes` 是一个面向 SJTU 课程视频场景的本地化学习助手：浏览器 userscript 负责在课程页面发起任务，本地 Flask 服务负责串行执行下载、转录和 AI 笔记生成。

项目目前默认以“后端任务队列为准”运行：

- 前端页面刷新或切换后，可从服务端恢复任务状态
- 默认串行执行，避免多任务同时占用显卡
- 同一课节的后续任务在真正执行时会根据现有文件状态做差量补全

## 功能

- 检测 SJTU 课程播放页中的视频流
- 下载音频或视频
- 使用 `faster-whisper` 生成 `srt` 和 `txt`
- 使用 Gemini 基于字幕生成 Markdown 笔记
- 在浏览器面板中查看、取消、恢复任务

## 架构

- `sjtu_video_helper.js`: Tampermonkey userscript，负责页面检测、任务提交与状态显示
- `auto_study_server.py`: 本地 Flask 服务，负责任务排队、调度和状态持久化
- `core_processor.py`: 下载、转录、笔记生成核心流程
- `transcriber.py`: `faster-whisper` 封装

## 快速开始

### 1. 创建并同步环境

```bash
uv sync
```

### 2. 配置环境变量

```bash
cp env.example .env
```

至少需要配置：

- `GOOGLE_API_KEY`

可选配置：

- `DOWNLOAD_DIR`
- `OBSIDIAN_VAULT_PATH`
- `TEMP_DIR`
- `FASTWHISPER_LOCAL_DIR`
- `SERIAL_TASK_EXECUTION`

默认情况下，项目会将生成文件放在仓库内的：

- `data/downloads`
- `data/notes`
- `data/temp`

### 3. 启动本地服务

```bash
uv run python auto_study_server.py
```

服务默认监听 `http://localhost:5000`。

### 4. 安装 userscript

1. 安装 Tampermonkey
2. 新建脚本并粘贴 `sjtu_video_helper.js`
3. 保存后访问 SJTU 课程播放页

## 常用验证

```bash
UV_CACHE_DIR=.uv-cache uv run python -m unittest tests/test_server_regressions.py tests/test_core_processor_download.py -v
UV_CACHE_DIR=.uv-cache uv run python -m py_compile auto_study_server.py core_processor.py transcriber.py utils.py stream_selector.py run_workflow.py api_example.py run_transcribe_test.py
node --check sjtu_video_helper.js
```

## 文档

- [使用指南](docs/USAGE_GUIDE.md)
- [API 文档](docs/API_DOCUMENTATION.md)
- [任务管理说明](docs/TASK_MANAGEMENT_GUIDE.md)
- [ASR 配置指南](docs/ASR_SETUP_GUIDE.md)
- [面板冲突处理](docs/CONFLICT_RESOLUTION.md)

## 说明

- 本项目不是 SJTU 官方产品，也不与 Canvas 或校内视频平台存在官方关系。
- 请自行确认使用行为符合课程平台、学校和地区的相关政策。
- 不要提交 `.env`、本地模型目录或个人下载内容。
