# ASR 配置指南

项目当前使用 `faster-whisper` 做本地转录。

## 安装

```bash
uv sync
```

## 模型来源

有两种方式：

- 不配置本地目录，让 `faster-whisper` 首次运行时自动下载
- 提前下载模型，然后通过环境变量或 `asr_config.json` 指定本地目录

## 推荐配置

`.env` 示例：

```bash
ASR_ENGINE=faster-whisper
FASTWHISPER_DEVICE=cuda
FASTWHISPER_COMPUTE=float16
FASTWHISPER_BEAM_SIZE=3
FASTWHISPER_BEST_OF=1
FASTWHISPER_PATIENCE=1.0
FASTWHISPER_CONDITION_PREV=false
FASTWHISPER_VAD_FILTER=true
FASTWHISPER_MIN_SILENCE=500
TRANSCRIPT_MAX_CHARS=200000
```

如果你已经有本地模型，可以额外配置：

```bash
FASTWHISPER_LOCAL_DIR=/path/to/model-or-snapshot
```

也可以写进 `asr_config.json`：

```json
{
  "FASTWHISPER_LOCAL_DIR": "/path/to/model-or-snapshot"
}
```

## 测试转录

```bash
SAMPLE_AUDIO_PATH=/path/to/sample.m4a uv run python run_transcribe_test.py
```

可选输出目录：

```bash
TRANSCRIBE_OUTPUT_DIR=/path/to/output uv run python run_transcribe_test.py
```

## 常见问题

### 首次运行开始下载模型

这通常说明你没有配置 `FASTWHISPER_LOCAL_DIR`，或者配置路径不正确。

### CUDA 显存不足

可以尝试：

```bash
FASTWHISPER_DEVICE=cpu
FASTWHISPER_COMPUTE=int8
```

或者切换到更小的模型。

### 只想离线运行

确保：

- `FASTWHISPER_LOCAL_DIR` 指向已经存在的模型目录
- 仅下载和转录流程可以脱离 AI 笔记生成运行

## AI 笔记生成补充

当前默认配置是：

```bash
AI_PROVIDER=openai
```

常见最小配置：

```bash
AI_PROVIDER=openai
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gemini-3.1-pro-preview-thinking
```

如需接入自定义 OpenAI 兼容服务，再补充：

```bash
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
```

如果你确实要切回 Google：

```bash
AI_PROVIDER=google
GOOGLE_API_KEY=your_api_key_here
```
