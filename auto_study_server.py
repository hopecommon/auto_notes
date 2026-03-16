import os
import time
import logging
import uuid
import subprocess
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from threading import Thread, Lock
from queue import Queue
from pathlib import Path

# 引入核心模块
from core_processor import CoreProcessor, format_gemini_error
from stream_selector import select_best_stream

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AutoServer")

# 任务队列和状态管理
task_queue = Queue()
task_status = {}  # {task_id: {status, progress, message, result, cancelled}}
task_lock = Lock()
cancelled_tasks = set()  # 存储已取消的任务ID
SERIAL_TASK_EXECUTION = os.getenv("SERIAL_TASK_EXECUTION", "1") not in {"0", "false", "False"}
WORKER_COUNT = 1 if SERIAL_TASK_EXECUTION else int(os.getenv("WORKER_COUNT", "4"))
resource_locks = {}
resource_lock_guard = Lock()

ACTIVE_TASK_STATUSES = {"queued", "processing", "downloading"}
TERMINAL_TASK_STATUSES = {"completed", "error", "cancelled"}


def normalize_task_part(value):
    value = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "unknown"


def build_task_resource_key(task_type, course_name="", lesson_title="", file_type=""):
    """构建资源锁 key：同一课节的不同任务共用一把锁，避免并发写相同输出文件。"""
    course_key = normalize_task_part(course_name)
    lesson_key = normalize_task_part(lesson_title)
    return f"{course_key}::{lesson_key}"


def build_task_identity_key(task_type, course_name="", lesson_title="", file_type=""):
    """构建任务去重 key：同一课节、同一种任务只保留一个活动任务。"""
    resource_key = build_task_resource_key(task_type, course_name, lesson_title, file_type)
    type_key = normalize_task_part(task_type)
    file_type_key = normalize_task_part(file_type) if file_type else ""
    identity_parts = [type_key]
    if file_type_key and file_type_key != "unknown":
        identity_parts.append(file_type_key)
    identity_parts.append(resource_key)
    return "::".join(identity_parts)


def enqueue_managed_task(
    task_type,
    action_label,
    display_title,
    task_payload,
    extra=None,
    resource_key=None,
    task_identity=None,
):
    """创建任务。

    串行执行下允许同类任务继续排队，真正执行时再依据当前文件状态决定是否跳过/
    补做剩余步骤，而不是在入队阶段静默复用既有任务。
    """
    with task_lock:
        task_id = str(uuid.uuid4())
        task_status[task_id] = {
            "status": "queued",
            "progress": 0,
            "message": "任务已加入队列",
            "created_at": time.time(),
            "updated_at": time.time(),
            "taskType": task_type,
            "actionLabel": action_label,
            "displayTitle": display_title,
            **(extra or {}),
            "resourceKey": resource_key,
            "taskIdentity": task_identity,
        }

    task_payload = {
        **task_payload,
        "id": task_id,
        "type": task_type,
        "resourceKey": resource_key,
        "taskIdentity": task_identity,
    }
    task_queue.put(task_payload)
    return task_id


def get_resource_lock(resource_key):
    if not resource_key:
        return None
    with resource_lock_guard:
        if resource_key not in resource_locks:
            resource_locks[resource_key] = Lock()
        return resource_locks[resource_key]


def init_task_record(task_id, task_type, action_label, display_title, extra=None):
    """初始化任务状态，附带元信息以便前端恢复"""
    record = {
        "status": "queued",
        "progress": 0,
        "message": "任务已加入队列",
        "created_at": time.time(),
        "updated_at": time.time(),
        "taskType": task_type,
        "actionLabel": action_label,
        "displayTitle": display_title,
    }
    if extra:
        record.update(extra)
    with task_lock:
        task_status[task_id] = record

def update_task(task_id, status, progress, message=""):
    """更新任务状态"""
    if task_id is None:
        return
    with task_lock:
        if task_id in task_status:
            task_status[task_id].update({
                "status": status,
                "progress": progress,
                "message": message,
                "updated_at": time.time()
            })
            logger.info(f"[Task {task_id}] {status} - {progress}% - {message}")

def is_task_cancelled(task_id):
    """检查任务是否已被取消"""
    with task_lock:
        return task_id in cancelled_tasks


def process_task(task, processor):
    task_id = task['id']
    task_type = task['type']

    def should_cancel():
        return is_task_cancelled(task_id)

    # 检查任务是否已被取消
    if should_cancel():
        logger.info(f"[Task {task_id}] 已被取消，跳过执行")
        update_task(task_id, "cancelled", 0, "任务已取消")
        return

    # 定义通用回调函数（智能更新 actionLabel）
    def progress_callback(status, pct, msg):
        update_task(task_id, status, pct, msg)
        with task_lock:
            if task_id in task_status:
                if task_type == "download":
                    file_type = task.get("fileType", "audio").lower()
                    label = "下载视频" if file_type == "video" else "下载音频"
                    task_status[task_id]["actionLabel"] = f"{label} (步骤1/1)"
                elif "下载" in msg or "downloading" in status.lower():
                    task_status[task_id]["actionLabel"] = "下载音频 (步骤1/3)"
                elif "转录" in msg or "transcribe" in msg.lower():
                    task_status[task_id]["actionLabel"] = "转录音频 (步骤2/3)"
                elif "Gemini" in msg or "生成笔记" in msg or "生成中" in msg:
                    task_status[task_id]["actionLabel"] = "生成 AI 笔记 (步骤3/3)"

    if task_type == 'note':
        urls = task['urls']
        course_name = task['courseName']
        lesson_title = task['lessonTitle']
        overwrite_existing = task.get('overwriteExisting', False)

        update_task(task_id, "processing", 5, "正在筛选最佳视频源...")

        target_url = select_best_stream(urls)
        if not target_url:
            update_task(task_id, "error", 0, "未找到有效视频流")
            return

        logger.info(f"筛选结果: {target_url}")

        result = processor.step_generate_note(
            url=target_url,
            course_name=course_name,
            lesson_title=lesson_title,
            skip_existing=not overwrite_existing,
            progress_callback=progress_callback,
            cancel_callback=should_cancel
        )
        _handle_step_result(task_id, result, 'note')

    elif task_type == 'transcribe':
        urls = task.get('urls', [])
        course_name = task['courseName']
        lesson_title = task['lessonTitle']
        overwrite_existing = task.get('overwriteExisting', False)
        audio_path = task.get('audioPath')

        if urls:
            target_url = select_best_stream(urls)
        else:
            target_url = task.get('url', '')

        if audio_path and Path(audio_path).exists():
            update_task(task_id, "processing", 10, "使用已有音频文件进行转录...")
            result = processor.step_transcribe_from_audio(
                audio_path=audio_path,
                course_name=course_name,
                lesson_title=lesson_title,
                skip_existing=not overwrite_existing,
                progress_callback=progress_callback,
                cancel_callback=should_cancel
            )
        elif target_url:
            result = processor.step_transcribe(
                url=target_url,
                course_name=course_name,
                lesson_title=lesson_title,
                skip_existing=not overwrite_existing,
                progress_callback=progress_callback,
                cancel_callback=should_cancel
            )
        else:
            update_task(task_id, "error", 0, "未提供视频链接或音频文件")
            return

        _handle_step_result(task_id, result, 'transcribe')

    elif task_type == 'download':
        urls = task.get('urls', [])
        course_name = task.get('courseName', task.get('filename', 'download'))
        lesson_title = task.get('lessonTitle', task.get('filename', 'file'))
        overwrite_existing = task.get('overwriteExisting', False)
        file_type = task.get('fileType', 'audio').lower()

        with task_lock:
            if task_id in task_status:
                task_status[task_id]["fileType"] = file_type

        if urls:
            target_url = select_best_stream(urls)
        else:
            target_url = task.get('url', '')

        if not target_url:
            update_task(task_id, "error", 0, "未提供下载链接")
            return

        result = processor.step_download(
            url=target_url,
            course_name=course_name,
            lesson_title=lesson_title,
            skip_existing=not overwrite_existing,
            media_type=file_type,
            progress_callback=progress_callback,
            cancel_callback=should_cancel
        )
        _handle_step_result(task_id, result, 'download')

    elif task_type == 'generate-note':
        course_name = task['courseName']
        lesson_title = task['lessonTitle']
        subtitle_path = task.get('subtitlePath')
        video_url = task.get('videoUrl', '')
        overwrite_existing = task.get('overwriteExisting', False)

        update_task(task_id, "processing", 10, "检查文件状态...")
        existing = processor.check_existing_files(course_name, lesson_title)

        if not subtitle_path:
            subtitle_path = existing.get('subtitle_path')

        if not subtitle_path or not os.path.exists(subtitle_path):
            update_task(task_id, "error", 0, "字幕文件不存在，请先转录")
            return

        if existing['note_exists'] and not overwrite_existing:
            update_task(task_id, "completed", 100, f"笔记已存在，已跳过: {existing['note_path']}")
            with task_lock:
                if task_id in task_status:
                    task_status[task_id]["skipped"] = True
                    task_status[task_id]["notePath"] = existing['note_path']
            return

        try:
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                transcript_text = f.read()
        except Exception as e:
            update_task(task_id, "error", 0, f"读取字幕失败: {e}")
            return

        update_task(task_id, "processing", 30, "Gemini 生成笔记中...")

        if should_cancel():
            update_task(task_id, "cancelled", 0, "任务已取消")
            return

        try:
            note_content = processor.process_with_gemini_text(transcript_text)
        except Exception as e:
            update_task(task_id, "error", 0, format_gemini_error(e))
            return

        if should_cancel():
            update_task(task_id, "cancelled", 0, "任务已取消")
            return

        update_task(task_id, "processing", 80, "保存笔记...")

        try:
            formatted_name = existing['formatted_name']
            note_path = processor.save_to_obsidian(
                course_name, lesson_title, video_url, note_content, formatted_name
            )
            update_task(task_id, "completed", 100, f"笔记生成完成: {note_path}")
            with task_lock:
                if task_id in task_status:
                    task_status[task_id]["notePath"] = str(note_path)
        except Exception as e:
            update_task(task_id, "error", 0, f"保存失败: {e}")

def worker():
    """后台任务处理线程"""
    processor = CoreProcessor()
    
    while True:
        task = task_queue.get()
        if task is None:
            break
        
        task_id = task['id']
        try:
            resource_lock = get_resource_lock(task.get("resourceKey"))
            if resource_lock is None:
                process_task(task, processor)
            else:
                with resource_lock:
                    process_task(task, processor)

        except Exception as e:
            logger.error(f"任务执行异常 [{task_id}]: {e}")
            update_task(task_id, "error", 0, str(e))
        finally:
            task_queue.task_done()


def _handle_step_result(task_id, result, step_type):
    """处理步骤执行结果，更新任务状态"""
    if not result:
        update_task(task_id, "error", 0, "未知错误")
        return
    
    if result.get("cancelled"):
        update_task(task_id, "cancelled", 0, "任务已取消")
        return
    
    if not result.get("success"):
        error_msg = result.get("error", "执行失败")
        update_task(task_id, "error", 0, error_msg)
        return
    
    # 成功
    skipped = result.get("skipped", False)
    exists = result.get("exists", False)
    
    with task_lock:
        if task_id in task_status:
            task_status[task_id]["skipped"] = skipped
            task_status[task_id]["exists"] = exists
            
            if result.get("audio_path"):
                task_status[task_id]["audioPath"] = result["audio_path"]
            if result.get("video_path"):
                task_status[task_id]["videoPath"] = result["video_path"]
            if result.get("subtitle_path"):
                task_status[task_id]["subtitlePath"] = result["subtitle_path"]
            if result.get("transcript_path"):
                task_status[task_id]["transcriptPath"] = result["transcript_path"]
            if result.get("note_path"):
                task_status[task_id]["notePath"] = result["note_path"]
    
    # 生成完成消息
    if step_type == 'download':
        media_type = result.get("media_type", "audio")
        target_path = result.get("video_path") if media_type == "video" else result.get("audio_path")
        media_label = "视频" if media_type == "video" else "音频"
        if skipped:
            msg = f"{media_label}已存在，已跳过: {target_path}"
        else:
            msg = f"下载完成: {target_path}"
    elif step_type == 'transcribe':
        if skipped:
            msg = f"字幕已存在，已跳过: {result.get('subtitle_path')}"
        else:
            msg = f"转录完成: {result.get('subtitle_path')}"
    elif step_type == 'note':
        if skipped:
            msg = f"笔记已存在，已跳过: {result.get('note_path')}"
        else:
            msg = f"笔记生成完成: {result.get('note_path')}"
    else:
        msg = "完成"
    
    update_task(task_id, "completed", 100, msg)


# ================= 路由定义 =================

@app.route('/process', methods=['POST'])
def process_video():
    data = request.json
    urls = data.get('urls', [])
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    force_regenerate = data.get('forceRegenerate', data.get('overwriteExisting', False))
    
    if not urls:
        return jsonify({"status": "error", "message": "未收到视频链接"}), 400

    action_label = "生成 AI 笔记"
    display_title = f"{course_name} · {lesson_title}"
    resource_key = build_task_resource_key("note", course_name, lesson_title)
    task_identity = build_task_identity_key("note", course_name, lesson_title)

    task_id = enqueue_managed_task(
        task_type="note",
        action_label=action_label,
        display_title=display_title,
        task_payload={
            'urls': urls,
            'courseName': course_name,
            'lessonTitle': lesson_title,
            'overwriteExisting': force_regenerate,
        },
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "urlCount": len(urls),
            "overwriteExisting": force_regenerate,
        },
        resource_key=resource_key,
        task_identity=task_identity,
    )
    
    return jsonify({
        "status": "success",
        "task_id": task_id,
        "message": "任务已加入队列"
    })

@app.route('/download', methods=['POST'])
def download_local():
    data = request.json
    url = data.get('url')
    filename = data.get('filename', 'downloaded_file')
    file_type = data.get('type', 'video')
    course_name = data.get('courseName', filename)
    lesson_title = data.get('lessonTitle', filename)
    overwrite_existing = data.get('overwriteExisting', False)
    
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"}), 400
    
    action_label = "下载音频 (本地)" if file_type == 'audio' else "下载视频 (本地)"
    display_title = f"{course_name} · {lesson_title}"
    resource_key = build_task_resource_key("download", course_name, lesson_title, file_type)
    task_identity = build_task_identity_key("download", course_name, lesson_title, file_type)

    task_id = enqueue_managed_task(
        task_type="download",
        action_label=action_label,
        display_title=display_title,
        task_payload={
            'url': url,
            'filename': filename,
            'courseName': course_name,
            'lessonTitle': lesson_title,
            'fileType': file_type,
            'overwriteExisting': overwrite_existing,
        },
        extra={
            "fileType": file_type,
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "overwriteExisting": overwrite_existing,
        },
        resource_key=resource_key,
        task_identity=task_identity,
    )
    
    return jsonify({
        "status": "success",
        "task_id": task_id,
        "message": "任务已加入队列"
    })

@app.route('/tasks/<task_id>', methods=['GET'])
def get_task_status(task_id):
    with task_lock:
        if task_id in task_status:
            return jsonify(task_status[task_id])
        else:
            return jsonify({"status": "error", "message": "任务不存在"}), 404

@app.route('/tasks', methods=['GET'])
def get_all_tasks():
    """获取所有任务列表（支持页面刷新后恢复）"""
    with task_lock:
        # 返回所有任务，按创建时间倒序
        sorted_tasks = dict(sorted(
            task_status.items(), 
            key=lambda x: x[1].get('created_at', 0), 
            reverse=True
        ))
        return jsonify(sorted_tasks)

@app.route('/tasks/<task_id>', methods=['DELETE'])
def cancel_task(task_id):
    """取消/删除任务"""
    with task_lock:
        if task_id not in task_status:
            return jsonify({"status": "error", "message": "任务不存在"}), 404
        
        current_status = task_status[task_id]['status']
        
        # 如果任务还在队列中或正在处理，标记为取消
        if current_status in ACTIVE_TASK_STATUSES:
            cancelled_tasks.add(task_id)
            task_status[task_id]['status'] = 'cancelled'
            task_status[task_id]['message'] = '任务已取消'
            task_status[task_id]['updated_at'] = time.time()
            logger.info(f"[Task {task_id}] 已标记为取消")
            return jsonify({"status": "success", "message": "任务已取消"})
        
        # 如果任务已完成或已出错，直接从列表中删除
        elif current_status in TERMINAL_TASK_STATUSES:
            del task_status[task_id]
            if task_id in cancelled_tasks:
                cancelled_tasks.discard(task_id)
            logger.info(f"[Task {task_id}] 已从列表中删除")
            return jsonify({"status": "success", "message": "任务已删除"})
        
        return jsonify({"status": "error", "message": "无法取消该任务"}), 400

@app.route('/tasks/clear', methods=['POST'])
def clear_tasks():
    """清空所有已完成/已出错的任务"""
    with task_lock:
        # 只保留正在进行的任务
        tasks_to_remove = [
            tid for tid, info in task_status.items() 
            if info['status'] not in ACTIVE_TASK_STATUSES
        ]
        
        for tid in tasks_to_remove:
            del task_status[tid]
            if tid in cancelled_tasks:
                cancelled_tasks.discard(tid)
        
        logger.info(f"已清空 {len(tasks_to_remove)} 个已完成/出错的任务")
        return jsonify({
            "status": "success", 
            "message": f"已清空 {len(tasks_to_remove)} 个任务",
            "removed_count": len(tasks_to_remove)
        })

@app.route('/check-files', methods=['POST'])
def check_files():
    """检查文件是否存在及完整性"""
    data = request.json
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    
    processor = CoreProcessor()
    existing = processor.check_existing_files(course_name, lesson_title)

    audio_path = Path(existing["audio_path"]) if existing.get("audio_path") else None
    video_path = Path(existing["video_path"]) if existing.get("video_path") else None
    subtitle_path = Path(existing["subtitle_path"]) if existing.get("subtitle_path") else None
    txt_path = subtitle_path if subtitle_path and subtitle_path.suffix == ".txt" else None
    srt_path = subtitle_path if subtitle_path and subtitle_path.suffix == ".srt" else None
    note_path = Path(existing["note_path"]) if existing.get("note_path") else None
    
    return jsonify({
        "audioExists": bool(audio_path and audio_path.exists()),
        "audioSize": audio_path.stat().st_size if audio_path and audio_path.exists() else 0,
        "audioComplete": existing.get("audio_complete", False),
        "videoExists": bool(video_path and video_path.exists()),
        "videoSize": video_path.stat().st_size if video_path and video_path.exists() else 0,
        "videoComplete": existing.get("video_complete", False),
        "subtitleExists": bool(subtitle_path and subtitle_path.exists()),
        "srtExists": bool(srt_path and srt_path.exists()),
        "txtExists": bool(txt_path and txt_path.exists()),
        "txtRequired": not bool(txt_path and txt_path.exists()),
        "noteExists": bool(note_path and note_path.exists()),
        "formattedName": existing["formatted_name"],
        "paths": {
            "audio": str(audio_path) if audio_path else None,
            "video": str(video_path) if video_path else None,
            "srt": str(srt_path) if srt_path else None,
            "txt": str(txt_path) if txt_path else None,
            "note": str(note_path) if note_path else None
        }
    })

@app.route('/transcribe', methods=['POST'])
def transcribe():
    """转录音频（递进式：会自动下载音频如果不存在）"""
    data = request.json
    urls = data.get('urls', [])
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    overwrite_existing = data.get('overwriteExisting', False)
    
    # 如果没有提供 URL，尝试从已有音频转录
    if not urls:
        # 检查音频是否存在
        processor = CoreProcessor()
        existing = processor.check_existing_files(course_name, lesson_title)
        if not existing['audio_complete']:
            return jsonify({
                "status": "error",
                "message": "未提供视频链接且音频文件不存在"
            }), 400
    
    action_label = "转录音频"
    display_title = f"{course_name} · {lesson_title}"
    resource_key = build_task_resource_key("transcribe", course_name, lesson_title)
    task_identity = build_task_identity_key("transcribe", course_name, lesson_title)

    task_id = enqueue_managed_task(
        task_type="transcribe",
        action_label=action_label,
        display_title=display_title,
        task_payload={
            'urls': urls,
            'courseName': course_name,
            'lessonTitle': lesson_title,
            'overwriteExisting': overwrite_existing,
        },
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "urlCount": len(urls),
            "overwriteExisting": overwrite_existing,
        },
        resource_key=resource_key,
        task_identity=task_identity,
    )
    
    return jsonify({
        "status": "success",
        "task_id": task_id,
        "message": "转录任务已加入队列"
    })

@app.route('/transcribe-only', methods=['POST'])
def transcribe_only():
    """仅转录音频（需要音频文件已存在）- 已废弃，请使用 /transcribe"""
    data = request.json
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    audio_path = data.get('audioPath')  # 可选：指定音频路径
    overwrite_existing = data.get('overwriteExisting', False)
    
    processor = CoreProcessor()
    formatted_name = processor.parse_metadata(course_name, lesson_title)
    
    from core_processor import DOWNLOAD_DIR
    
    # 如果没有指定音频路径，使用默认路径
    if not audio_path:
        audio_path = str(Path(DOWNLOAD_DIR) / f"{formatted_name}.m4a")
    
    # 检查音频文件是否存在
    if not Path(audio_path).exists():
        return jsonify({
            "status": "error", 
            "message": f"音频文件不存在: {audio_path}"
        }), 400
    
    action_label = "转录音频"
    display_title = f"{course_name} · {lesson_title}"
    resource_key = build_task_resource_key("transcribe", course_name, lesson_title)
    task_identity = build_task_identity_key("transcribe", course_name, lesson_title)

    task_id = enqueue_managed_task(
        task_type="transcribe",
        action_label=action_label,
        display_title=display_title,
        task_payload={
            'courseName': course_name,
            'lessonTitle': lesson_title,
            'audioPath': audio_path,
            'outputDir': DOWNLOAD_DIR,
            'overwriteExisting': overwrite_existing,
        },
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "audioPath": audio_path,
            "overwriteExisting": overwrite_existing,
        },
        resource_key=resource_key,
        task_identity=task_identity,
    )
    
    return jsonify({
        "status": "success",
        "task_id": task_id,
        "message": "转录任务已加入队列"
    })

@app.route('/generate-note-only', methods=['POST'])
def generate_note_only():
    """仅生成笔记（需要字幕文件已存在）"""
    data = request.json
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    subtitle_path = data.get('subtitlePath')  # 可选：指定字幕路径
    video_url = data.get('videoUrl', '')  # 原始视频链接
    overwrite_existing = data.get('overwriteExisting', False)
    
    processor = CoreProcessor()
    formatted_name = processor.parse_metadata(course_name, lesson_title)
    
    from core_processor import DOWNLOAD_DIR
    
    # 如果没有指定字幕路径，尝试查找（优先 TXT，因为 Gemini 不接受 SRT）
    if not subtitle_path:
        txt_path = Path(DOWNLOAD_DIR) / f"{formatted_name}.txt"
        srt_path = Path(DOWNLOAD_DIR) / f"{formatted_name}.srt"
        
        # 优先使用 TXT（Gemini 接受纯文本）
        if txt_path.exists():
            subtitle_path = str(txt_path)
        elif srt_path.exists():
            # SRT 存在但 TXT 不存在，自动转换（读取 SRT 内容保存为 TXT）
            logger.info("检测到 SRT 文件，自动转换为 TXT 格式供 Gemini 使用")
            try:
                with open(srt_path, 'r', encoding='utf-8') as f:
                    srt_content = f.read()
                # 直接使用 SRT 内容（Gemini 可以理解）或者只保留文本部分
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(srt_content)
                subtitle_path = str(txt_path)
                logger.info(f"SRT 已转换为 TXT: {txt_path}")
            except Exception as e:
                logger.error(f"SRT 转 TXT 失败: {e}")
                return jsonify({
                    "status": "error",
                    "message": f"SRT 转 TXT 失败: {str(e)}"
                }), 400
        else:
            return jsonify({
                "status": "error",
                "message": f"字幕文件不存在，请先转录音频"
            }), 400
    
    # 检查字幕文件是否存在
    if not Path(subtitle_path).exists():
        return jsonify({
            "status": "error",
            "message": f"字幕文件不存在: {subtitle_path}"
        }), 400
    
    action_label = "生成 AI 笔记"
    display_title = f"{course_name} · {lesson_title}"
    resource_key = build_task_resource_key("generate-note", course_name, lesson_title)
    task_identity = build_task_identity_key("generate-note", course_name, lesson_title)

    task_id = enqueue_managed_task(
        task_type="generate-note",
        action_label=action_label,
        display_title=display_title,
        task_payload={
            'courseName': course_name,
            'lessonTitle': lesson_title,
            'subtitlePath': subtitle_path,
            'videoUrl': video_url,
            'overwriteExisting': overwrite_existing,
        },
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "subtitlePath": subtitle_path,
            "overwriteExisting": overwrite_existing,
        },
        resource_key=resource_key,
        task_identity=task_identity,
    )
    
    return jsonify({
        "status": "success",
        "task_id": task_id,
        "message": "笔记生成任务已加入队列"
    })

@app.route('/ping', methods=['GET'])
def ping():
    return "pong"

if __name__ == '__main__':
    # 简单检查依赖
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("错误: 未找到 ffmpeg。")
        exit(1)
    
    worker_threads = []
    for idx in range(WORKER_COUNT):
        thread = Thread(target=worker, daemon=True, name=f"worker-{idx+1}")
        thread.start()
        worker_threads.append(thread)
    
    print(f"服务已启动 (重构版)，正在监听 5000 端口...")
    app.run(port=5000)
