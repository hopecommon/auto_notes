# Auto Notes

`Auto Notes` 是一个面向 SJTU 课程视频场景的本地化学习助手：浏览器 userscript 负责在课程页面发起任务，本地 Flask 服务负责串行执行下载、转录和 AI 笔记生成。

项目目前默认以“后端任务队列为准”运行：

- 前端页面刷新或切换后，可从服务端恢复任务状态
- 默认串行执行，避免多任务同时占用显卡
- 同一课节的后续任务在真正执行时会根据现有文件状态做差量补全

## 功能

- 检测 SJTU 课程播放页中的视频流
- 下载音频或视频
- 使用 `funasr`、`faster-whisper` 或 `sherpa-onnx` 生成字幕文本
- 使用 OpenAI 兼容接口或 Google Gemini 基于字幕生成 Markdown 笔记
- 在浏览器面板中查看、取消、恢复任务

## 架构

- `sjtu_video_helper.js`: Tampermonkey userscript，负责页面检测、任务提交与状态显示
- `auto_study_server.py`: 本地 Flask 服务，负责任务排队、调度和状态持久化
- `core_processor.py`: 下载、转录、笔记生成核心流程
- `transcriber.py`: ASR 封装，支持 `funasr` / `faster-whisper` / `sherpa-onnx`

## 快速开始

### 1. 创建并同步环境

```bash
uv sync
```

默认只安装核心依赖。按需追加：

- faster-whisper 默认后端：`uv sync --extra asr-faster-whisper`
- FunASR 备选后端：`uv sync --extra asr-funasr`
- sherpa-onnx：`uv sync --extra asr-sherpa-onnx`
- Google Gemini SDK：`uv sync --extra ai-google`
- 本地浏览器自动化：`uv sync --extra browser-playwright`

如果你继续使用 `requirements.txt`，它现在只表示最小核心依赖。后端相关依赖以 `pyproject.toml` 里的 extras 为准。

### 2. 配置环境变量

```bash
cp env.example .env
```

至少需要配置一组 AI 提供方参数。

默认推荐：

- `AI_PROVIDER=openai`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

常见可选项：

- `OPENAI_BASE_URL`

可选回退：

- `AI_PROVIDER=google`
- `GOOGLE_API_KEY`

可选配置：

- `DOWNLOAD_DIR`
- `OBSIDIAN_VAULT_PATH`
- `TEMP_DIR`
- `FUNASR_MODEL_DIR`
- `FUNASR_VAD_DIR`
- `FUNASR_PUNC_DIR`
- `FUNASR_HOTWORD_FILE`
- `FUNASR_HOTWORD_DIR`
- `TRANSCRIPT_TERM_MAP_DIR`
- `ASR_PREPROCESS_AUDIO`
- `ASR_PREPROCESS_FILTERS`
- `FASTWHISPER_LOCAL_DIR`
- `SHERPA_ONNX_MODEL_DIR`
- `SHERPA_ONNX_VAD_MODEL`
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

启动时你应该能在日志里看到当前提供方，例如：

- `已启用 OpenAI 兼容模式: ...`
- 或 `已启用 Google Gemini 模式: ...`

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
- 当前默认文档口径以 `AI_PROVIDER=openai` 为主，Google Gemini 作为兼容选项保留。
- `OPENAI_BASE_URL` 不是固定供应商配置，可按你使用的 OpenAI 兼容服务自行填写。
- FunASR 分支会优先输出 `SRT + TXT`；只有拿不到时间戳时才回退为纯 `TXT`。
