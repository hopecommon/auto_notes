# 本地 ASR 转录配置指南

## 概述

本项目现已集成 `faster-whisper` 进行本地音视频转录，支持从本地模型加载，完全离线运行。

## 已完成功能

✅ **Faster-Whisper 集成**

-   使用 `faster-whisper` 库进行本地 ASR 转录
-   支持自动语言检测（中文、英文等）
-   自动 VAD（Voice Activity Detection）静音过滤
-   生成标准 SRT 字幕文件和 TXT 逐字稿

✅ **本地模型加载**

-   支持从本地目录加载预下载的 Whisper 模型
-   通过 `asr_config.json` 配置模型路径
-   避免每次运行时从 HuggingFace 下载模型

✅ **工作流集成**

-   下载音频后自动触发转录
-   转录完成后将字幕文本传给 Gemini 生成笔记
-   字幕文件和笔记一起保存到 Obsidian 目录

## 配置步骤

### 1. 安装依赖

```bash
pip install faster-whisper python-dotenv
```

### 2. 下载 Whisper 模型

推荐使用 `large-v3-turbo` 模型（更快且准确）：

**方式 A：手动从 HuggingFace 下载**

-   访问：https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo
-   下载整个仓库到本地（会自动创建 `snapshots/` 目录结构）

**方式 B：让 faster-whisper 自动下载**

-   首次运行时不配置 `FASTWHISPER_LOCAL_DIR`，会自动下载到 `.cache/faster-whisper/`
-   下载完成后，将路径配置到 `asr_config.json`

### 3. 配置本地模型路径

编辑 `Auto_Notes/asr_config.json`：

```json
{
    "FASTWHISPER_LOCAL_DIR": "D:\\path\\to\\your\\model\\snapshots\\<hash>"
}
```

**重要提示**：

-   路径必须指向 `snapshots/<hash>` 目录，而不是顶层目录
-   `<hash>` 是具体的 commit hash，例如 `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`
-   该目录下应包含：`config.json`, `model.bin`, `tokenizer.json`, `vocabulary.json`, `preprocessor_config.json`
-   Windows 路径使用双反斜杠 `\\` 或单正斜杠 `/`

**示例目录结构**：

```
D:\models\
└── models--mobiuslabsgmbh--faster-whisper-large-v3-turbo\
    ├── blobs\
    ├── refs\
    └── snapshots\
        └── 0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf\  ← 配置这个路径！
            ├── config.json (符号链接)
            ├── model.bin (符号链接)
            ├── tokenizer.json (符号链接)
            ├── vocabulary.json (符号链接)
            └── preprocessor_config.json (符号链接)
```

### 4. 测试转录功能

运行测试脚本：

```bash
cd Auto_Notes
python run_transcribe_test.py
```

**预期输出**：

-   日志显示 "使用本地 faster-whisper 模型目录: ..."
-   无 HuggingFace 下载进度条
-   自动检测语言（如 "Detected language 'zh' with probability 0.87"）
-   VAD 过滤静音段
-   生成 `.srt` 和 `.txt` 文件

## 环境变量配置（可选）

可以在 `Auto_Notes/.env` 中配置更多参数：

```bash
# ASR 引擎（目前仅支持 faster-whisper）
ASR_ENGINE=faster-whisper

# 模型路径（优先级：环境变量 > asr_config.json）
FASTWHISPER_LOCAL_DIR=D:\\path\\to\\model\\snapshots\\<hash>

# 设备选择（cuda, cpu）
FASTWHISPER_DEVICE=cuda

# 计算精度（float16, int8, int8_float16）
FASTWHISPER_COMPUTE=float16

# VAD 静音过滤（true, false）
FASTWHISPER_VAD_FILTER=true

# VAD 最小静音长度（毫秒）
FASTWHISPER_MIN_SILENCE=500

# Beam Search 大小
FASTWHISPER_BEAM_SIZE=5

# 采样温度（0=贪心，>0=采样）
FASTWHISPER_TEMPERATURE=0

# 初始提示词（可以提高特定词汇识别率）
FASTWHISPER_INITIAL_PROMPT=

# 字幕文本最大字符数（超出会截断）
TRANSCRIPT_MAX_CHARS=200000
```

## 使用方式

### 方式 1：浏览器脚本 + Flask 服务器

1. 启动服务器：

    ```bash
    cd Auto_Notes
    python auto_study_server.py
    ```

2. 在浏览器中安装 `sjtu_video_helper.js` Tampermonkey 脚本

3. 访问课程网站，点击"下载音频"或"生成笔记"
    - **下载音频**：下载 → 自动转录 → 保存 SRT/TXT
    - **生成笔记**：下载 → 自动转录 → Gemini 处理 → 保存笔记 + SRT/TXT

### 方式 2：命令行批处理

编辑 `run_workflow.py`，添加视频 URL 列表：

```python
urls = [
    "https://your-course-video-url-1.mp4",
    "https://your-course-video-url-2.mp4",
]
```

运行：

```bash
python run_workflow.py
```

## 性能参考

**测试环境**：

-   模型：faster-whisper-large-v3-turbo
-   设备：NVIDIA GPU (CUDA)
-   精度：float16

**测试结果**：

-   音频时长：55 分钟
-   转录时间：约 1.5 分钟（beam_size=3，默认最优配置）
-   VAD 过滤：自动移除 14 分钟静音（26%）
-   语言检测：中文（概率 0.87）
-   输出质量：SRT 时间轴精确，中文识别准确
-   速度：324 字符/秒

## 故障排查

### 问题 1：仍然从 HuggingFace 下载模型

**原因**：

-   `asr_config.json` 路径配置错误
-   路径指向顶层目录而非 `snapshots/<hash>`
-   `snapshots/<hash>` 目录下缺少必需文件

**解决方案**：

1. 检查 `asr_config.json` 中的路径
2. 运行 `dir` (Windows) 或 `ls` (Linux/Mac) 确认目录存在
3. 确认目录下包含 `config.json`, `model.bin` 等文件

### 问题 2：CUDA out of memory

**解决方案**：

1. 切换到 CPU：`FASTWHISPER_DEVICE=cpu`
2. 降低精度：`FASTWHISPER_COMPUTE=int8`
3. 使用更小的模型（如 `large-v3` 改为 `medium`）

### 问题 3：中文识别不准确

**解决方案**：

1. 添加初始提示词：
    ```bash
    FASTWHISPER_INITIAL_PROMPT="这是一段中文课程音频。"
    ```
2. 确保使用 `large-v3` 或 `large-v3-turbo` 模型
3. 检查音频质量（采样率、背景噪音）

### 问题 4：字幕时间轴不准确

**解决方案**：

1. 禁用 VAD：`FASTWHISPER_VAD_FILTER=false`
2. 调整 VAD 参数：`FASTWHISPER_MIN_SILENCE=1000`
3. 增加 beam size：`FASTWHISPER_BEAM_SIZE=10`

## 技术细节

### 文件结构

-   `transcriber.py`：ASR 核心模块
-   `asr_config.json`：模型路径配置
-   `run_transcribe_test.py`：测试脚本
-   `core_processor.py`：工作流集成（下载 → 转录 → Gemini → Obsidian）
-   `auto_study_server.py`：Flask 后端服务器

### 输出文件

转录完成后会生成：

1. **SRT 字幕文件**：标准 SubRip 格式，包含时间轴

    ```
    1
    00:04:15,220 --> 00:04:17,220
    请大家注意提交,提交的截止时间要到

    2
    00:04:17,220 --> 00:05:40,270
    同学们提交了吧,是不是都提交了
    ```

2. **TXT 逐字稿**：纯文本格式，带时间戳

    ```
    [00:04:15,220] 请大家注意提交,提交的截止时间要到
    [00:04:17,220] 同学们提交了吧,是不是都提交了
    ```

3. **Obsidian 笔记**（如果触发笔记生成）：
    - 包含 Gemini 生成的结构化笔记
    - 包含原始视频链接
    - SRT/TXT 文件保存在同一课程目录下

## 下一步优化

-   [ ] 支持多线程并发转录多个音频
-   [ ] 添加实时转录进度反馈
-   [ ] 支持更多 ASR 引擎（Whisper.cpp, FunASR）
-   [ ] 优化超长音频的内存占用
-   [ ] 添加字幕后处理（断句优化、标点校正）

## 参考资源

-   [faster-whisper GitHub](https://github.com/SYSTRAN/faster-whisper)
-   [OpenAI Whisper 论文](https://arxiv.org/abs/2212.04356)
-   [HuggingFace 模型库](https://huggingface.co/models?search=faster-whisper)
