# 性能优化说明

## 当前默认策略

公开仓库版本优先稳定性，不追求最大并发：

- 任务默认串行执行
- `faster-whisper` 默认启用 VAD
- 推荐 `beam_size=3`

## 推荐参数

```bash
FASTWHISPER_DEVICE=cuda
FASTWHISPER_COMPUTE=float16
FASTWHISPER_BEAM_SIZE=3
FASTWHISPER_BEST_OF=1
FASTWHISPER_PATIENCE=1.0
FASTWHISPER_CONDITION_PREV=false
FASTWHISPER_VAD_FILTER=true
FASTWHISPER_MIN_SILENCE=500
SERIAL_TASK_EXECUTION=1
```

## 为什么不默认并发

这个项目的瓶颈通常不是 HTTP 请求，而是：

- 音频/视频下载的磁盘写入
- `faster-whisper` 占用的 GPU 显存
- AI 接口请求和文件落盘

对日常使用来说，串行比并发更稳。

## 什么时候再考虑并发

只有在下面条件都满足时，才建议评估并发：

- GPU 显存充足
- 同时处理的多任务主要是下载而不是转录
- 已经验证不会写同一课节的同一组输出文件

如果要试验：

```bash
SERIAL_TASK_EXECUTION=0
WORKER_COUNT=2
```

## 模型相关建议

- `large-v3-turbo`: 默认推荐
- `medium`: 更快，占用更小
- `cpu + int8`: 适合无 GPU 环境，但速度会明显下降

## 排查思路

### 转录慢

- 检查是否意外落到了 CPU
- 检查 `FASTWHISPER_DEVICE`
- 检查 `FASTWHISPER_COMPUTE`

### 连续任务排太久

- 这是默认串行策略的预期行为
- 如果只是下载任务较多，可以单独评估是否要放开并发

### 生成笔记慢

- 检查当前 AI 提供方网络连通性
- 如果使用默认模式，优先检查 OpenAI 兼容接口连通性
- 检查字幕是否过长
- 检查是否触发了重新生成
