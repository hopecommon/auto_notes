# Auto Notes API 文档

## 概述

本文档描述了 Auto Notes 系统的所有 API endpoint，包括新的解耦架构支持。

## 架构设计

### 核心流程

```
完整流程：下载音频 → 转录音频 → 生成笔记
         (可独立执行)  (可独立执行)  (可独立执行)
```

### 智能判断

```
用户点击"生成笔记"：
  → 检查文件状态 (/check-files)
  → 判断需要执行哪些步骤
  → 自动串联执行缺失步骤
  → 生成最终笔记
```

## API Endpoints

### 1. 文件检查 API

**Endpoint**: `POST /check-files`

**描述**: 检查指定课程和标题的文件是否存在及完整性

**请求体**:

```json
{
    "courseName": "程序语言与编译原理",
    "lessonTitle": "2025-10-17 08:55 程序语言与编译原理"
}
```

**响应**:

```json
{
    "audioExists": true,
    "audioSize": 52428800,
    "audioComplete": true,
    "subtitleExists": true,
    "srtExists": true,
    "txtExists": true,
    "noteExists": false,
    "formattedName": "程序语言与编译原理-1017-0855",
    "paths": {
        "audio": "D:\\Download\\SJTU_Courses\\程序语言与编译原理-1017-0855.m4a",
        "srt": "D:\\Download\\SJTU_Courses\\程序语言与编译原理-1017-0855.srt",
        "txt": "D:\\Download\\SJTU_Courses\\程序语言与编译原理-1017-0855.txt",
        "note": null
    }
}
```

**字段说明**:

-   `audioExists`: 音频文件是否存在
-   `audioSize`: 音频文件大小（字节）
-   `audioComplete`: 音频文件是否完整（>1MB）
-   `subtitleExists`: 字幕文件是否存在（SRT 或 TXT）
-   `srtExists`: SRT 文件是否存在
-   `txtExists`: TXT 文件是否存在
-   `noteExists`: 笔记文件是否存在
-   `formattedName`: 格式化后的文件名
-   `paths`: 各文件的完整路径

---

### 2. 下载 API（仅下载）

**Endpoint**: `POST /download`

**描述**: 仅下载音频或视频，**不再自动转录**

**请求体**:

```json
{
    "url": "https://live.sjtu.edu.cn/vod/xxx.mp4",
    "filename": "程序语言与编译原理-1017-0855",
    "type": "audio" // 或 "video"
}
```

**响应**:

```json
{
    "status": "success",
    "task_id": "uuid-xxxx-xxxx",
    "message": "任务已加入队列"
}
```

**任务状态更新**:

-   `status`: `queued` → `downloading` → `completed`
-   `progress`: 0% → 10% → 100%
-   `message`: 任务进度描述

**完成后任务状态**:

```json
{
    "status": "completed",
    "progress": 100,
    "message": "已保存至: D:\\Download\\SJTU_Courses\\xxx.m4a",
    "audioPath": "D:\\Download\\SJTU_Courses\\xxx.m4a" // 或 videoPath
}
```

---

### 3. 转录 API（仅转录）

**Endpoint**: `POST /transcribe-only`

**描述**: 仅转录音频文件，生成 SRT 和 TXT 字幕

**请求体**:

```json
{
    "courseName": "程序语言与编译原理",
    "lessonTitle": "2025-10-17 08:55 程序语言与编译原理",
    "audioPath": "D:\\Download\\SJTU_Courses\\xxx.m4a" // 可选，不提供则自动查找
}
```

**响应**:

```json
{
    "status": "success",
    "task_id": "uuid-xxxx-xxxx",
    "message": "转录任务已加入队列"
}
```

**任务状态更新**:

-   `status`: `queued` → `processing` → `completed`
-   `progress`: 0% → 10% → 100%

**完成后任务状态**:

```json
{
    "status": "completed",
    "progress": 100,
    "message": "转录完成！\n字幕: D:\\Download\\SJTU_Courses\\xxx.srt",
    "subtitlePath": "D:\\Download\\SJTU_Courses\\xxx.srt",
    "transcriptPath": "D:\\Download\\SJTU_Courses\\xxx.txt"
}
```

---

### 4. 笔记生成 API（仅生成）

**Endpoint**: `POST /generate-note-only`

**描述**: 仅使用已有字幕生成笔记，不执行下载和转录

**请求体**:

```json
{
    "courseName": "程序语言与编译原理",
    "lessonTitle": "2025-10-17 08:55 程序语言与编译原理",
    "subtitlePath": "D:\\Download\\SJTU_Courses\\xxx.txt", // 可选，不提供则自动查找
    "videoUrl": "https://live.sjtu.edu.cn/vod/xxx.mp4" // 可选，用于笔记元数据
}
```

**响应**:

```json
{
    "status": "success",
    "task_id": "uuid-xxxx-xxxx",
    "message": "笔记生成任务已加入队列"
}
```

**任务状态更新**:

-   `status`: `queued` → `processing` → `completed`
-   `progress`: 0% → 20% → 40% → 80% → 100%
-   阶段：读取字幕 → 调用 Gemini → 保存笔记

**完成后任务状态**:

```json
{
    "status": "completed",
    "progress": 100,
    "message": "笔记生成完成！\n笔记: D:\\OneDrive\\Obsidian\\xxx.md",
    "notePath": "D:\\OneDrive\\Obsidian\\xxx.md"
}
```

---

### 5. 完整流程 API（保留，兼容旧版）

**Endpoint**: `POST /process`

**描述**: 一键完成：下载 → 转录 → 生成笔记

**请求体**:

```json
{
    "urls": ["https://live.sjtu.edu.cn/vod/xxx.mp4"],
    "courseName": "程序语言与编译原理",
    "lessonTitle": "2025-10-17 08:55 程序语言与编译原理"
}
```

**响应**:

```json
{
    "status": "success",
    "task_id": "uuid-xxxx-xxxx",
    "message": "任务已加入队列"
}
```

**任务状态更新**:

-   `status`: `queued` → `processing` → `downloading` → `completed`
-   `progress`: 0% → 5% → 10% → 35% → 55% → 70% → 90% → 100%

---

### 6. 任务管理 API

#### 6.1 获取单个任务状态

**Endpoint**: `GET /tasks/<task_id>`

**响应**:

```json
{
    "status": "processing",
    "progress": 45,
    "message": "正在转录音频...",
    "created_at": 1700000000.123,
    "updated_at": 1700000045.678,
    "taskType": "transcribe",
    "actionLabel": "转录音频",
    "displayTitle": "程序语言与编译原理 · 2025-10-17 08:55"
}
```

#### 6.2 获取所有任务

**Endpoint**: `GET /tasks`

**响应**:

```json
{
    "task-id-1": {
        /* 任务详情 */
    },
    "task-id-2": {
        /* 任务详情 */
    }
}
```

#### 6.3 取消/删除任务

**Endpoint**: `DELETE /tasks/<task_id>`

**行为**:

-   如果任务正在运行：标记为 `cancelled`
-   如果任务已完成/失败：从列表中删除

**响应**:

```json
{
    "status": "success",
    "message": "任务已取消" // 或 "任务已删除"
}
```

#### 6.4 清空已完成任务

**Endpoint**: `POST /tasks/clear`

**响应**:

```json
{
    "status": "success",
    "message": "已清空 5 个任务",
    "removed_count": 5
}
```

---

### 7. 健康检查

**Endpoint**: `GET /ping`

**响应**: `pong`

---

## 前端使用示例

### 1. 智能下载音频

```javascript
async function handleDownloadAudio(metadata) {
    // 1. 检查文件状态
    const fileCheck = await checkFiles(metadata.courseName, metadata.lessonTitle);

    // 2. 如果已存在，询问是否重新下载
    if (fileCheck.audioExists && fileCheck.audioComplete) {
        const action = confirm("音频已存在，是否重新下载？");
        if (!action) {
            // 用户选择不下载，直接转录
            if (!fileCheck.subtitleExists) {
                await submitTask("/transcribe-only", {...});
            }
            return;
        }
    }

    // 3. 下载音频
    const downloadTaskId = await submitTask("/download", {...});

    // 4. 监听下载完成，自动触发转录
    waitForTaskCompletion(downloadTaskId, () => {
        submitTask("/transcribe-only", {...});
    });
}
```

### 2. 智能生成笔记

```javascript
async function handleGenerateNote(metadata) {
    const fileCheck = await checkFiles(metadata.courseName, metadata.lessonTitle);

    // 判断需要执行的步骤
    let needDownload = !fileCheck.audioComplete;
    let needTranscribe = !fileCheck.subtitleExists;

    if (needDownload) {
        // 下载 → 转录 → 生成笔记
        const downloadTaskId = await submitTask("/download", {...});
        waitForTaskCompletion(downloadTaskId, () => {
            const transcribeTaskId = await submitTask("/transcribe-only", {...});
            waitForTaskCompletion(transcribeTaskId, () => {
                submitTask("/generate-note-only", {...});
            });
        });
    } else if (needTranscribe) {
        // 仅转录 → 生成笔记
        const transcribeTaskId = await submitTask("/transcribe-only", {...});
        waitForTaskCompletion(transcribeTaskId, () => {
            submitTask("/generate-note-only", {...});
        });
    } else {
        // 直接生成笔记
        await submitTask("/generate-note-only", {...});
    }
}
```

---

## 错误处理

### 常见错误响应

**400 Bad Request**:

```json
{
    "status": "error",
    "message": "音频文件不存在: D:\\xxx.m4a"
}
```

**404 Not Found**:

```json
{
    "status": "error",
    "message": "任务不存在"
}
```

### 任务状态

-   `queued`: 任务已加入队列，等待执行
-   `downloading`: 正在下载
-   `processing`: 正在处理（转录/生成笔记）
-   `completed`: 任务完成
-   `error`: 任务失败
-   `cancelled`: 任务已取消

---

## 性能优化

### 1. 文件复用

-   下载前检查文件是否存在
-   转录前检查字幕是否存在
-   避免重复操作，节省时间和资源

### 2. 并发处理

-   支持 4 个并发 worker（可通过 `WORKER_COUNT` 环境变量调整）
-   多个任务可同时执行

### 3. 模型缓存

-   Faster-Whisper 模型首次加载后缓存在内存
-   后续转录直接复用，节省 3-5 秒

### 4. 智能判断

-   前端自动判断需要执行的步骤
-   避免不必要的 API 调用
-   提供更好的用户体验

---

## 配置说明

### Backend (.env)

```bash
# Google API Key
GOOGLE_API_KEY=your_api_key_here

# Worker 并发数
WORKER_COUNT=4

# Faster-Whisper 配置
FASTWHISPER_BEAM_SIZE=3  # 最优配置
FASTWHISPER_DEVICE=cuda
FASTWHISPER_COMPUTE=float16
```

### Frontend (Tampermonkey)

```javascript
const SERVER_URL = "http://localhost:5000";
```

---

## 测试流程

### 1. 测试文件检查

```bash
curl -X POST http://localhost:5000/check-files \
  -H "Content-Type: application/json" \
  -d '{"courseName":"测试课程","lessonTitle":"测试标题"}'
```

### 2. 测试下载

```bash
curl -X POST http://localhost:5000/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/video.mp4","filename":"test","type":"audio"}'
```

### 3. 测试转录

```bash
curl -X POST http://localhost:5000/transcribe-only \
  -H "Content-Type: application/json" \
  -d '{"courseName":"测试课程","lessonTitle":"测试标题"}'
```

### 4. 测试笔记生成

```bash
curl -X POST http://localhost:5000/generate-note-only \
  -H "Content-Type: application/json" \
  -d '{"courseName":"测试课程","lessonTitle":"测试标题"}'
```

---

## 版本历史

### v2.0 - 解耦架构

-   ✅ 新增 `/check-files` 文件检查 API
-   ✅ 新增 `/transcribe-only` 独立转录 API
-   ✅ 新增 `/generate-note-only` 独立笔记生成 API
-   ✅ 优化 `/download` 为仅下载模式
-   ✅ 前端智能流程控制
-   ✅ 文件复用机制
-   ✅ 保留 `/process` 一键流程（兼容）

### v1.0 - 初始版本

-   ✅ 一键下载 → 转录 → 生成笔记
-   ✅ 任务队列和状态管理
-   ✅ 浏览器脚本集成

---

## 常见问题

### Q1: 为什么需要解耦架构？

A: 解耦架构提供了更大的灵活性：

-   可以单独重新执行某一步（如重新转录）
-   避免重复下载/转录，节省时间
-   支持更复杂的工作流（如批量转录）
-   更好的错误恢复能力

### Q2: 旧版本的 `/process` 还能用吗？

A: 可以！`/process` 保持完全兼容，适合一键操作。

### Q3: 如何判断音频文件是否完整？

A: 目前简单判断：文件大小 > 1MB 认为完整。可根据实际需求调整阈值。

### Q4: 转录失败后如何重试？

A: 使用 `/transcribe-only` API 单独重试转录，无需重新下载。

### Q5: 如何批量处理多个课程？

A: 可以编写脚本循环调用 API，或使用 `run_workflow.py` 批处理脚本。

---

## 联系与支持

-   GitHub: [项目地址]
-   文档: 见 `Auto_Notes/` 目录
-   日志: 查看服务器控制台输出
