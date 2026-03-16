# API 文档

本地服务默认运行在 `http://localhost:5000`。

## 设计原则

- 浏览器前端只负责提交任务和展示状态
- 后端负责排队、串行执行和任务恢复
- 任务执行时会根据现有文件状态做差量补全

## `POST /check-files`

检查某个课节的现有文件状态。

请求体：

```json
{
  "courseName": "Course A",
  "lessonTitle": "2025-10-17 08:55 Lesson 1"
}
```

响应示例：

```json
{
  "audioExists": true,
  "audioComplete": true,
  "subtitleExists": true,
  "srtExists": true,
  "txtExists": true,
  "videoExists": false,
  "noteExists": false,
  "formattedName": "Course A-1017-0855",
  "paths": {
    "audio": "/path/to/downloads/Course A-1017-0855.m4a",
    "srt": "/path/to/downloads/Course A-1017-0855.srt",
    "txt": "/path/to/downloads/Course A-1017-0855.txt",
    "video": null,
    "note": null
  }
}
```

## `POST /download`

下载音频或视频。

请求体：

```json
{
  "url": "https://example.invalid/video.m3u8",
  "courseName": "Course A",
  "lessonTitle": "2025-10-17 08:55 Lesson 1",
  "filename": "Course A-1017-0855",
  "type": "audio",
  "overwriteExisting": false
}
```

说明：

- `type` 可选 `audio` 或 `video`
- `overwriteExisting=true` 时允许重下

## `POST /transcribe`

创建转录任务。服务端会优先复用已有音频。

请求体：

```json
{
  "urls": ["https://example.invalid/video.m3u8"],
  "courseName": "Course A",
  "lessonTitle": "2025-10-17 08:55 Lesson 1",
  "overwriteExisting": false
}
```

## `POST /transcribe-only`

直接转录指定音频文件。

请求体：

```json
{
  "courseName": "Course A",
  "lessonTitle": "2025-10-17 08:55 Lesson 1",
  "audioPath": "/path/to/downloads/Course A-1017-0855.m4a",
  "overwriteExisting": false
}
```

## `POST /process`

生成 AI 笔记的一体化流程。缺什么补什么。

请求体：

```json
{
  "urls": ["https://example.invalid/video.m3u8"],
  "courseName": "Course A",
  "lessonTitle": "2025-10-17 08:55 Lesson 1",
  "forceRegenerate": false
}
```

## `POST /generate-note-only`

使用已有字幕直接生成笔记。

请求体：

```json
{
  "courseName": "Course A",
  "lessonTitle": "2025-10-17 08:55 Lesson 1",
  "subtitlePath": "/path/to/downloads/Course A-1017-0855.txt",
  "videoUrl": "https://example.invalid/video.m3u8"
}
```

## `GET /tasks`

返回当前所有任务，用于页面恢复。

## `GET /tasks/<task_id>`

返回单个任务状态。

## `DELETE /tasks/<task_id>`

取消或删除任务：

- 进行中的任务会被标记为 `cancelled`
- 已完成或失败的任务会被移除

## `POST /tasks/clear`

批量清理终态任务：

- `completed`
- `error`
- `cancelled`

## 任务状态

常见状态：

- `queued`
- `downloading`
- `processing`
- `completed`
- `error`
- `cancelled`

## Curl 示例

```bash
curl -X POST http://localhost:5000/check-files \
  -H 'Content-Type: application/json' \
  -d '{"courseName":"Course A","lessonTitle":"2025-10-17 08:55 Lesson 1"}'
```
