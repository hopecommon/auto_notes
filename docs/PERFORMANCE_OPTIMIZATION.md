# ASR 转录性能优化指南

## 已实现的优化

### 1. 模型缓存机制 ✅

**问题**：每次转录都重新加载模型（需要 3-5 秒）

**解决**：

-   实现全局模型缓存 `_CACHED_MODEL`
-   首次加载后保存在内存中
-   后续转录直接复用，节省 3-5 秒

**效果**：

-   第一次转录：正常加载（约 5 秒）
-   后续转录：立即开始（0 秒加载）

### 2. 降低 Beam Search 大小 ✅

**问题**：默认 `beam_size=5` 会搜索 5 条候选路径，速度慢

**解决**：

-   默认改为 `beam_size=1`（贪心模式）
-   可通过环境变量 `FASTWHISPER_BEAM_SIZE` 调整

**实测速度对比**（55 分钟音频）：
| Beam Size | 转录时间 | 速度（字符/秒） | 准确度 |
|-----------|----------|----------------|--------|
| 3（推荐 ✅） | 91.7 秒 | 324.62 | 高 |
| 1（贪心） | 93.6 秒 | 316.88 | 良好 |
| 5（精确） | 113.1 秒 | 261.92 | 最高 |

**推荐配置**：

```bash
# 最优平衡模式（默认，速度最快+准确度高）✅
FASTWHISPER_BEAM_SIZE=3

# 贪心模式（略慢但更简单）
FASTWHISPER_BEAM_SIZE=1

# 高精度模式（适合专业术语/重要文档）
FASTWHISPER_BEAM_SIZE=5
```

### 3. 优化采样参数 ✅

新增参数控制：

```bash
# Best of 采样数（默认 1）
FASTWHISPER_BEST_OF=1

# 提前停止耐心值（默认 1.0）
FASTWHISPER_PATIENCE=1.0

# 是否基于前文生成（默认 false，更快）
FASTWHISPER_CONDITION_PREV=false
```

### 4. VAD 静音过滤 ✅

**效果**：自动移除静音段，减少 20-30% 处理时间

**示例**（55 分钟音频）：

-   原始音频：55:00
-   过滤后：40:39（移除 14:21 静音）
-   节省：26% 处理时间

**配置**：

```bash
# 启用 VAD
FASTWHISPER_VAD_FILTER=true

# 最小静音长度（毫秒）
FASTWHISPER_MIN_SILENCE=500
```

## 性能基准测试

使用 `benchmark_transcribe.py` 进行性能测试：

```bash
cd Auto_Notes
python benchmark_transcribe.py
```

**测试环境**：

-   GPU: NVIDIA RTX 3060
-   模型: faster-whisper-large-v3-turbo
-   精度: float16
-   音频: 55 分钟中文课程

**实测结果**（2024 年 11 月测试）：

| 配置       | Beam Size | 耗时   | 速度（字符/秒） | 推荐度          |
| ---------- | --------- | ------ | --------------- | --------------- |
| 平衡模式   | 3         | 1m 32s | 324.62          | ⭐⭐⭐⭐⭐ 默认 |
| 贪心模式   | 1         | 1m 34s | 316.88          | ⭐⭐⭐⭐        |
| 高精度模式 | 5         | 1m 53s | 261.92          | ⭐⭐⭐          |

> **结论**：`beam_size=3` 是实测最优配置，已设为默认值。

## 进一步优化建议

### 1. 使用更小的模型

如果准确度要求不高，可以使用更小的模型：

```json
// asr_config.json
{
    "FASTWHISPER_LOCAL_DIR": "D:\\path\\to\\faster-whisper-medium"
}
```

| 模型           | 大小  | 速度 | 准确度 |
| -------------- | ----- | ---- | ------ |
| large-v3-turbo | 3GB   | 基准 | 最高   |
| large-v3       | 3GB   | 0.8x | 最高   |
| medium         | 1.5GB | 2x   | 高     |
| small          | 500MB | 4x   | 中等   |

### 2. 切换到 CPU（不推荐）

如果没有 GPU，可以使用 CPU：

```bash
FASTWHISPER_DEVICE=cpu
FASTWHISPER_COMPUTE=int8
```

⚠️ **注意**：CPU 速度约为 GPU 的 1/10

### 3. 多进程并发转录

对于批量处理多个音频，可以利用多进程：

**当前实现**：`auto_study_server.py` 已支持多线程（4 个 worker）

**优化方向**：

-   每个 worker 独立加载模型（避免模型锁）
-   使用 `multiprocessing` 替代 `threading`（绕过 GIL）

**预期提升**：4 核 CPU 可达到 3-4x 并发吞吐

### 4. 音频预处理

**优化方向**：

-   转换为 16kHz 单声道（Whisper 原生格式）
-   使用 `ffmpeg` 提前提取音频轨道
-   移除背景噪音（使用 `noisereduce`）

**实现示例**：

```python
import subprocess

def preprocess_audio(input_path, output_path):
    """使用 ffmpeg 预处理音频"""
    subprocess.run([
        "ffmpeg", "-i", input_path,
        "-ar", "16000",  # 16kHz 采样率
        "-ac", "1",       # 单声道
        "-c:a", "pcm_s16le",  # PCM 格式
        output_path
    ])
```

### 5. 使用量化模型

`faster-whisper` 支持 INT8 量化：

```bash
# INT8 量化（速度 1.5-2x，准确度略降）
FASTWHISPER_COMPUTE=int8

# 混合精度（平衡）
FASTWHISPER_COMPUTE=int8_float16
```

### 6. 批处理优化

对于超长音频（>1 小时），可以分段处理：

```python
def transcribe_long_audio(audio_path, segment_duration=600):
    """
    分段转录长音频
    segment_duration: 每段时长（秒），默认 10 分钟
    """
    # 使用 ffmpeg 分段
    # 每段并行转录
    # 合并结果
    pass
```

## Server 集成验证

### 下载任务流程

```
用户点击"下载音频"
  → Flask 接收请求
  → 创建任务（状态: queued）
  → Worker 开始下载（状态: downloading 10%）
  → 下载完成（状态: processing 60%）
  → 自动调用 transcribe_audio()
  → 生成 SRT + TXT（状态: processing 90%）
  → 保存到 DOWNLOAD_DIR（状态: completed 100%）
  → 返回音频路径 + 字幕路径
```

### 笔记生成流程

```
用户点击"生成笔记"
  → Flask 接收请求
  → 创建任务（状态: queued）
  → Worker 开始下载（状态: downloading 10%）
  → 下载完成（状态: processing 35%）
  → 自动调用 transcribe_audio()
  → 生成字幕（状态: processing 55%）
  → 调用 Gemini 处理字幕文本（状态: processing 70%）
  → Gemini 生成笔记（状态: processing 90%）
  → 保存到 Obsidian（状态: completed 100%）
  → 保存 SRT/TXT 到笔记目录
  → 返回笔记路径 + 字幕路径
```

### 验证方法

1. **启动服务器**：

    ```bash
    cd Auto_Notes
    python auto_study_server.py
    ```

2. **浏览器测试**：

    - 安装 `sjtu_video_helper.js` Tampermonkey 脚本
    - 访问课程网站
    - 点击"下载音频"或"生成笔记"
    - 观察任务状态和进度

3. **日志验证**：

    ```
    2025-11-24 17:xx:xx - INFO - [Task xxx] 开始下载...
    2025-11-24 17:xx:xx - INFO - [Task xxx] 下载完成，开始转录...
    2025-11-24 17:xx:xx - INFO - 使用已缓存的 Faster-Whisper 模型
    2025-11-24 17:xx:xx - INFO - 开始执行 Faster-Whisper 转录 (beam_size=1)
    2025-11-24 17:xx:xx - INFO - 字幕已生成: SRT=..., TXT=...
    2025-11-24 17:xx:xx - INFO - [Task xxx] completed - 100%
    ```

4. **检查输出文件**：
    - 音频：`D:\Download\SJTU_Courses\课程名-日期.m4a`
    - 字幕：`D:\Download\SJTU_Courses\课程名-日期.srt`
    - 逐字稿：`D:\Download\SJTU_Courses\课程名-日期.txt`
    - 笔记：`D:\OneDrive\Obsidian\课程名\课程名-日期.md`

## 常见问题

### Q1: 模型缓存是否会占用过多内存？

A: `large-v3-turbo` 模型在 GPU 上约占用 3-4GB 显存。如果内存不足，可以：

-   使用更小的模型（`medium`, `small`）
-   禁用模型缓存（每次重新加载）
-   降低 `compute_type` 为 `int8`

### Q2: 转录速度仍然很慢怎么办？

A: 依次检查：

1. 确认使用 GPU（`FASTWHISPER_DEVICE=cuda`）
2. 降低 `beam_size` 为 1
3. 启用 VAD 过滤（`FASTWHISPER_VAD_FILTER=true`）
4. 检查 GPU 驱动和 CUDA 版本
5. 考虑使用更小的模型

### Q3: 如何平衡速度和准确度？

A: 推荐配置：

-   **日常课程**：`beam_size=1`，速度优先
-   **重要会议**：`beam_size=3`，平衡
-   **专业领域**：`beam_size=5` + `initial_prompt`，准确度优先

### Q4: 多任务并发时会互相影响吗？

A: 当前实现的模型缓存是全局共享的，多线程会串行使用同一个模型实例。这是安全的，但不会加速单个任务。要实现真正的并发加速，需要每个 worker 独立加载模型（但会增加内存占用）。

## 性能优化 Checklist

-   [x] 实现模型缓存
-   [x] 降低默认 beam_size
-   [x] 添加 VAD 静音过滤
-   [x] 优化 Server 集成逻辑
-   [x] 创建性能基准测试脚本
-   [ ] 实现音频预处理
-   [ ] 支持分段转录长音频
-   [ ] 多进程并发处理
-   [ ] 实时进度回调

## 参考资源

-   [faster-whisper 文档](https://github.com/SYSTRAN/faster-whisper)
-   [Whisper 论文](https://arxiv.org/abs/2212.04356)
-   [CTranslate2 优化指南](https://github.com/OpenNMT/CTranslate2)
