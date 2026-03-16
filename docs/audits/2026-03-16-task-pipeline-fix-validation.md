# 2026-03-16 Task Pipeline Fix Validation

## Scope

- 修复下载视频实际走音频下载的问题
- 修复重复提交/多页面切换导致的任务重复入队与并发覆盖
- 修复重新下载/重新转录的覆盖语义
- 修复前端重复轮询与面板重复创建
- 调整为后端默认串行执行
- 非课程视频页继续保留任务面板并从服务端续状态
- 修复仓库基础语法健康与环境管理细节

## Commands Run

```bash
UV_CACHE_DIR=.uv-cache uv run python -m unittest tests/test_server_regressions.py tests/test_core_processor_download.py -v
UV_CACHE_DIR=.uv-cache uv run python -m py_compile auto_study_server.py core_processor.py transcriber.py utils.py stream_selector.py run_workflow.py api_example.py run_transcribe_test.py
node --check sjtu_video_helper.js
git rm --cached .env
```

## Results

- `unittest`: 7 tests passed
- `py_compile`: passed
- `node --check sjtu_video_helper.js`: passed
- `.env` 已从 Git 跟踪中移除，本地文件保留
- 串行执行默认由 `SERIAL_TASK_EXECUTION=1` 控制，未关闭时只启用 1 个 worker

## Regression Coverage

- `tests/test_server_regressions.py`
  - 任务资源锁 key 与任务去重 key 行为
  - 相同活动任务复用而非重复入队
  - 下载任务正确走 `video` 模式并传递覆盖语义
  - `/transcribe` 路由正确转发 `overwriteExisting`
- `tests/test_core_processor_download.py`
  - `step_download(..., media_type="video")` 输出 `.mp4`
  - 已存在音频在 `skip_existing=True` 时正确跳过
  - `check_existing_files()` 正确返回 `video_path` / `video_complete`

## Behavioral Notes

- 前端面板现在可以在已匹配域名下的非视频页面继续显示任务状态，但只允许在课程视频上下文中新增任务
- 任务状态以后端 `/tasks` 为准，页面跳转后会重新恢复轮询显示

## Residual Risk

- `core_processor.py` 仍在使用已弃用的 `google.generativeai` SDK，当前功能未因此失效，但后续应迁移到 `google.genai`
- 面板唯一性修复目前是基于已知选择器清理旧/重复面板；如果浏览器里还有第三方脚本使用全新选择器制造重复 UI，仍需浏览器现场确认
