# ASR 配置指南

项目当前支持三套本地转录后端：

- `faster-whisper`：当前默认后端，综合速度、稳定性和下游模型可总结性更平衡
- `funasr`：中文场景可作为备选实验线，默认建议用 `SenseVoiceSmall`
- `sherpa-onnx`：更适合本地 ONNX 部署，可接入 SenseVoice / Paraformer / FireRed

## 安装

```bash
uv sync
```

默认只安装核心依赖。推荐按后端追加：

```bash
uv sync --extra asr-funasr
uv sync --extra asr-faster-whisper
uv sync --extra asr-sherpa-onnx
```

如果你要使用 Google Gemini SDK，再额外执行：

```bash
uv sync --extra ai-google
```

`requirements.txt` 现在只保留最小核心依赖；ASR 后端依赖以 `pyproject.toml` 里的 extras 为准。

如果你使用 `funasr`，`asr-funasr` extra 会带上默认的 `torch / torchaudio`。但如果你要真正启用 GPU，仍建议在 FunASR 专用虚拟环境里按你的 CUDA 版本重装对应的 torch wheel。

如果主进程不是在 FunASR 虚拟环境里启动的，也可以通过 `FUNASR_PYTHON` 指定已安装依赖的 Python 解释器，例如：

```bash
FUNASR_PYTHON=./.venv-funasr/Scripts/python.exe
```

只要显式设置了 `FUNASR_PYTHON`，当前项目就会优先把 FunASR 推理放到那个解释器里执行，而不是继续复用主进程环境。

## FunASR 备选配置

推荐优先尝试：

- `FUNASR_MODEL_TYPE=sensevoice`
- `FUNASR_LANGUAGE=auto`
- `FUNASR_MERGE_VAD=true`
- `FUNASR_USE_ITN=true`
- 混合中英课程先不要强制 `zh`

`.env` 示例：

```bash
ASR_ENGINE=funasr
FUNASR_MODEL_TYPE=sensevoice
FUNASR_MODEL_DIR=/path/to/SenseVoiceSmall
FUNASR_VAD_DIR=/path/to/speech_fsmn_vad
FUNASR_PUNC_DIR=/path/to/punc_ct-transformer
FUNASR_PYTHON=/path/to/your/funasr-venv/Scripts/python.exe
FUNASR_DEVICE=cuda:0
FUNASR_LANGUAGE=auto
FUNASR_USE_ITN=true
FUNASR_BATCH_SIZE_S=60
FUNASR_MERGE_VAD=true
FUNASR_MERGE_LENGTH_S=15
FUNASR_DISABLE_UPDATE=true
FUNASR_MAX_SINGLE_SEGMENT_MS=30000
FUNASR_SUBTITLE_MAX_WORDS=24
FUNASR_SUBTITLE_MAX_CHARS=64
FUNASR_FILTER_EDGE_NOISE=false
# 可选：保时长 ASR 前处理，默认关闭
ASR_PREPROCESS_AUDIO=false
ASR_PREPROCESS_FILTERS=highpass,lowpass,loudnorm,afftdn
# 可选：anlmdn 宽带降噪，速度明显更慢，建议只做抽样对比
# ASR_PREPROCESS_FILTERS=highpass,lowpass,loudnorm,anlmdn
# ASR_PREPROCESS_ANLMDN_STRENGTH=0.0001
# ASR_PREPROCESS_ANLMDN_PATCH=0.01
# ASR_PREPROCESS_ANLMDN_RESEARCH=0.006
# ASR_PREPROCESS_ANLMDN_SMOOTH=15
# 可选：arnndn 语音降噪，需要外部 .rnnn 模型文件
# ASR_PREPROCESS_FILTERS=highpass,lowpass,loudnorm,arnndn
# ASR_PREPROCESS_ARNNDN_MODEL=/path/to/ffmpeg-arnndn-models/std.rnnn
# ASR_PREPROCESS_ARNNDN_MIX=0.8
# 可选：直接写热词字符串
# FUNASR_HOTWORD=支持向量机 经验风险最小化
# 可选：每行一个课程热词，适合按课程维护
# FUNASR_HOTWORD_FILE=/path/to/course_hotwords.txt
# 可选：按课程名自动匹配热词文件，例如 hotwords/机器学习.txt
# FUNASR_HOTWORD_DIR=./hotwords
# 可选：按课程名自动匹配术语归一化规则，例如 term_maps/机器学习.json
# TRANSCRIPT_TERM_MAP_DIR=./term_maps
```

说明：

- `SenseVoiceSmall` 适合作为中文/中英混合课程的备选模型
- `paraformer-large` 是 FunASR 的大号中文离线 Paraformer 模型，普通话纯中文课上有时更稳，但更重，也更偏中文单语场景
- 当前项目会对 SenseVoice 输出做保守清洗，只去掉标签、emoji 和事件噪声，不会重写正文
- `FUNASR_FILTER_EDGE_NOISE` 默认关闭；只有你明确接受“首尾空档噪声过滤”时再打开，避免误伤老师课前/课后补充说明
- `ASR_PREPROCESS_AUDIO` 默认关闭；它适合做远场课堂录音的 A/B 实验，但主链里只建议使用“不改时间轴”的滤镜
- 当前默认的预处理滤镜链是 `highpass + lowpass + loudnorm + afftdn`，但不同后端收益不同，建议先对目标课程抽样验证
- `anlmdn` 是更正式的宽带降噪，但在 Windows 本地 CPU 上会明显拖慢预处理，不适合默认常开
- `arnndn` 是更偏语音的降噪方案，比 `anlmdn` 轻很多；但需要额外准备 `.rnnn` 模型文件，例如 `/path/to/ffmpeg-arnndn-models/std.rnnn`
- 课堂录音的开头/结尾如果本来就接近静音，任何降噪都可能把背景噪声“整理成可识别垃圾文本”，所以仍然建议按课程抽样 A/B，不要直接全量常开
- 不建议把 `silenceremove` 这类会改时间轴的滤镜直接用于主链 `SRT`
- 当前项目会尽量从 FunASR 结果中提取时间戳并输出 `SRT + TXT`；只有拿不到可用时间轴时才回退成纯 `TXT`
- `FUNASR_SUBTITLE_MAX_WORDS` / `FUNASR_SUBTITLE_MAX_CHARS` 用来控制 SenseVoice 词级时间戳拼字幕时的段长
- 热词建议按课程单独维护在 `FUNASR_HOTWORD_FILE`，不要做成全局大词库
- 如果设置了 `FUNASR_HOTWORD_DIR`，项目会按音频文件名自动匹配最长命中的课程热词文件，适合 `机器学习-0411-1055.m4a -> hotwords/机器学习.txt` 这种命名
- 如果你要做少量术语修正，可设置 `TRANSCRIPT_TERM_MAP_DIR`，用课程级 JSON 规则只修高频稳定误识别词；不建议把它当大规模正文清洗器
- 如果你想测试 `paraformer-large`，可切到 `FUNASR_MODEL_TYPE=paraformer` 并配置 `FUNASR_PUNC_DIR`

如果你只打算继续使用默认的 `faster-whisper`，上面的默认依赖即可。

如果你要使用 `sherpa-onnx`，建议按官方 CPU 方案安装 `sherpa-onnx + sherpa-onnx-bin`。如需 CUDA，请按 `sherpa-onnx` 官方说明安装对应 CUDA wheel。

## faster-whisper 模型来源

有两种方式：

- 不配置本地目录，让 `faster-whisper` 首次运行时自动下载
- 提前下载模型，然后通过环境变量指定本地目录

### faster-whisper 推荐配置

`.env` 示例：

```bash
ASR_ENGINE=faster-whisper
FASTWHISPER_DEVICE=cuda
FASTWHISPER_COMPUTE=float16
FASTWHISPER_BEAM_SIZE=3
FASTWHISPER_BEST_OF=1
FASTWHISPER_PATIENCE=1.0
FASTWHISPER_CONDITION_PREV=false
FASTWHISPER_REPETITION_PENALTY=1.08
FASTWHISPER_NO_REPEAT_NGRAM_SIZE=3
FASTWHISPER_COMPRESSION_RATIO_THRESHOLD=2.2
FASTWHISPER_LOG_PROB_THRESHOLD=-1.0
FASTWHISPER_NO_SPEECH_THRESHOLD=0.6
FASTWHISPER_HALLUCINATION_SILENCE_THRESHOLD=1.5
FASTWHISPER_DROP_REPEATED_NOISE=true
FASTWHISPER_VAD_FILTER=true
FASTWHISPER_MIN_SILENCE=500
TRANSCRIPT_MAX_CHARS=200000
```

补充：

- `FASTWHISPER_REPETITION_PENALTY` 和 `FASTWHISPER_NO_REPEAT_NGRAM_SIZE` 用来压制模型在噪声段里反复生成近似短语
- `FASTWHISPER_COMPRESSION_RATIO_THRESHOLD` / `FASTWHISPER_HALLUCINATION_SILENCE_THRESHOLD` 更偏向抑制“静音或弱语音里凭空编字”
- `FASTWHISPER_DROP_REPEATED_NOISE=true` 会在结果层额外去掉非常明显的连续重复噪声段；它是保守规则，不会主动清洗正常正文

如果你已经有本地模型，可以额外配置：

```bash
FASTWHISPER_LOCAL_DIR=/path/to/model-or-snapshot
```

## sherpa-onnx 推荐配置

推荐优先尝试：

- `SHERPA_ONNX_MODEL_TYPE=sense-voice`
- 模型目录内放置：
  - `model.int8.onnx` 或 `model.onnx`
  - `tokens.txt`
  - `silero_vad.onnx`

`.env` 示例：

```bash
ASR_ENGINE=sherpa-onnx
SHERPA_ONNX_MODEL_TYPE=sense-voice
SHERPA_ONNX_MODEL_DIR=/path/to/sense-voice-model
SHERPA_ONNX_VAD_MODEL=/path/to/silero_vad.onnx
SHERPA_ONNX_PROVIDER=cpu
SHERPA_ONNX_NUM_THREADS=2
SHERPA_ONNX_USE_ITN=true
SHERPA_ONNX_VAD_THRESHOLD=0.2
SHERPA_ONNX_MIN_SILENCE=0.25
SHERPA_ONNX_MIN_SPEECH=0.25
SHERPA_ONNX_MAX_SPEECH=20
```

说明：

- 当前项目内的下载产物默认是 `.m4a`
- `sherpa-onnx` 分支会自动调用 `ffmpeg` 转成 `16k/mono PCM` 再做识别和 VAD
- 为了继续兼容原有流程，输出仍然是 `.srt + .txt`

如需 Paraformer，可改为：

```bash
SHERPA_ONNX_MODEL_TYPE=paraformer
```

如需测试 FireRed，可分成两类：

- `fire-red-asr`：AED 版，需要 `encoder*.onnx + decoder*.onnx + tokens.txt`
- `fire-red-asr-ctc`：CTC 版，需要 `model*.onnx + tokens.txt`

示例：

```bash
ASR_ENGINE=sherpa-onnx
SHERPA_ONNX_MODEL_TYPE=fire-red-asr
SHERPA_ONNX_MODEL_DIR=/path/to/sherpa-onnx-fire-red-asr2
SHERPA_ONNX_VAD_MODEL=/path/to/silero_vad.onnx
SHERPA_ONNX_PROVIDER=cpu
SHERPA_ONNX_NUM_THREADS=4
```

或者：

```bash
ASR_ENGINE=sherpa-onnx
SHERPA_ONNX_MODEL_TYPE=fire-red-asr-ctc
SHERPA_ONNX_MODEL_DIR=/path/to/sherpa-onnx-fire-red-asr2-ctc
SHERPA_ONNX_VAD_MODEL=/path/to/silero_vad.onnx
SHERPA_ONNX_PROVIDER=cpu
SHERPA_ONNX_NUM_THREADS=4
```

补充：

- FireRed 当前在本项目里仍然视为实验线，不作为默认后端
- `fire-red-asr` 也支持显式配置 `SHERPA_ONNX_ENCODER_PATH` / `SHERPA_ONNX_DECODER_PATH`
- 从这次课堂录音实测看，FireRed 通过 sherpa-onnx 已能稳定跑通长音频 VAD 工作流，但质量暂未明显超过当前主线

## 测试转录

```bash
SAMPLE_AUDIO_PATH=/path/to/sample.m4a uv run python run_transcribe_test.py
```

可选输出目录：

```bash
TRANSCRIBE_OUTPUT_DIR=/path/to/output uv run python run_transcribe_test.py
```

如需做三段抽样降噪对比，可使用：

```bash
ASR_COMPARE_SOURCE_AUDIO=/path/to/sample.m4a \
ASR_COMPARE_ARNNDN_MODEL=/path/to/ffmpeg-arnndn-models/std.rnnn \
uv run python run_asr_denoise_compare.py
```

## 常见问题

### 首次运行开始下载模型

这通常说明你没有配置 `FASTWHISPER_LOCAL_DIR`，或者配置路径不正确。

### sherpa-onnx 提示缺少 tokens 或 VAD

请检查：

- `SHERPA_ONNX_MODEL_DIR` 是否正确
- `tokens.txt` 是否和 ONNX 模型放在同一目录，或已单独配置 `SHERPA_ONNX_TOKENS_PATH`
- `silero_vad.onnx` 是否存在，或已配置 `SHERPA_ONNX_VAD_MODEL`

### CUDA 显存不足

可以尝试：

```bash
FASTWHISPER_DEVICE=cpu
FASTWHISPER_COMPUTE=int8
```

或者切换到更小的模型。

对于 `sherpa-onnx`，如果当前 wheel 不支持 CUDA，也请先退回：

```bash
SHERPA_ONNX_PROVIDER=cpu
```

### FunASR 配了 `cuda:0` 但日志里还是 `device=cpu`

这通常不是代码问题，而是当前解释器里安装的是 CPU 版 `torch`。先检查：

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

如果输出类似 `2.x+cpu / None / False`，说明当前环境没有 GPU 版 torch。此时：

- 如果主进程不想换环境，继续用 `FUNASR_PYTHON` 指向独立的 FunASR 虚拟环境
- 在那个虚拟环境里按你的 CUDA 版本重装 `torch / torchaudio`
- 保持 `.env` 里的 `FUNASR_DEVICE=cuda:0`

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
