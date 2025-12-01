import os
import time
import logging
import uuid
import subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS
from threading import Thread, Lock
from queue import Queue
from pathlib import Path

# 引入核心模块
from core_processor import CoreProcessor
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
WORKER_COUNT = int(os.getenv("WORKER_COUNT", "4"))


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

def worker():
    """后台任务处理线程"""
    processor = CoreProcessor()
    
    while True:
        task = task_queue.get()
        if task is None:
            break
        
        task_id = task['id']
        task_type = task['type']
        
        def should_cancel():
            return is_task_cancelled(task_id)
        
        # 检查任务是否已被取消
        if should_cancel():
            logger.info(f"[Task {task_id}] 已被取消，跳过执行")
            update_task(task_id, "cancelled", 0, "任务已取消")
            task_queue.task_done()
            continue
        
        try:
            # 定义通用回调函数（智能更新 actionLabel）
            def progress_callback(status, pct, msg):
                update_task(task_id, status, pct, msg)
                # 根据消息内容动态更新 actionLabel，让前端显示当前步骤
                with task_lock:
                    if task_id in task_status:
                        if "下载" in msg or "downloading" in status.lower():
                            task_status[task_id]["actionLabel"] = "下载音频 (步骤1/3)"
                        elif "转录" in msg or "transcribe" in msg.lower():
                            task_status[task_id]["actionLabel"] = "转录音频 (步骤2/3)"
                        elif "Gemini" in msg or "生成笔记" in msg or "生成中" in msg:
                            task_status[task_id]["actionLabel"] = "生成 AI 笔记 (步骤3/3)"
            
            if task_type == 'note':
                # ========== 生成笔记任务（完整流程：下载→转录→生成）==========
                urls = task['urls']
                course_name = task['courseName']
                lesson_title = task['lessonTitle']
                skip_existing = task.get('skipExisting', True)  # 默认跳过已存在的
                
                update_task(task_id, "processing", 5, "正在筛选最佳视频源...")
                
                target_url = select_best_stream(urls)
                if not target_url:
                    update_task(task_id, "error", 0, "未找到有效视频流")
                    continue
                    
                logger.info(f"筛选结果: {target_url}")
                
                # 调用 step_generate_note（内部会自动调用下载和转录）
                result = processor.step_generate_note(
                    url=target_url, 
                    course_name=course_name, 
                    lesson_title=lesson_title,
                    skip_existing=skip_existing,
                    progress_callback=progress_callback,
                    cancel_callback=should_cancel
                )

                _handle_step_result(task_id, result, 'note')

            elif task_type == 'transcribe':
                # ========== 转录任务（会先确保音频已下载）==========
                urls = task.get('urls', [])
                course_name = task['courseName']
                lesson_title = task['lessonTitle']
                skip_existing = task.get('skipExisting', True)
                audio_path = task.get('audioPath')  # 可能由 transcribe-only 传入
                
                # 获取 URL
                if urls:
                    target_url = select_best_stream(urls)
                else:
                    target_url = task.get('url', '')
                
                # 如果提供了 audioPath 且文件存在，直接转录，不需要 URL
                if audio_path and Path(audio_path).exists():
                    update_task(task_id, "processing", 10, "使用已有音频文件进行转录...")
                    result = processor.step_transcribe_from_audio(
                        audio_path=audio_path,
                        course_name=course_name,
                        lesson_title=lesson_title,
                        skip_existing=skip_existing,
                        progress_callback=progress_callback,
                        cancel_callback=should_cancel
                    )
                elif target_url:
                    # 调用 step_transcribe（内部会自动调用下载）
                    result = processor.step_transcribe(
                        url=target_url,
                        course_name=course_name,
                        lesson_title=lesson_title,
                        skip_existing=skip_existing,
                        progress_callback=progress_callback,
                        cancel_callback=should_cancel
                    )
                else:
                    update_task(task_id, "error", 0, "未提供视频链接或音频文件")
                    continue
                
                _handle_step_result(task_id, result, 'transcribe')
            
            elif task_type == 'download':
                # ========== 仅下载任务 ==========
                urls = task.get('urls', [])
                course_name = task.get('courseName', task.get('filename', 'download'))
                lesson_title = task.get('lessonTitle', task.get('filename', 'file'))
                skip_existing = task.get('skipExisting', False)  # 下载默认不跳过，询问用户
                
                # 获取 URL
                if urls:
                    target_url = select_best_stream(urls)
                else:
                    target_url = task.get('url', '')
                
                if not target_url:
                    update_task(task_id, "error", 0, "未提供下载链接")
                    continue
                
                result = processor.step_download(
                    url=target_url,
                    course_name=course_name,
                    lesson_title=lesson_title,
                    skip_existing=skip_existing,
                    progress_callback=progress_callback,
                    cancel_callback=should_cancel
                )
                
                _handle_step_result(task_id, result, 'download')

            elif task_type == 'generate-note':
                # ========== 仅生成笔记（需要字幕已存在）==========
                course_name = task['courseName']
                lesson_title = task['lessonTitle']
                subtitle_path = task.get('subtitlePath')
                video_url = task.get('videoUrl', '')
                skip_existing = task.get('skipExisting', True)
                
                update_task(task_id, "processing", 10, "检查文件状态...")
                
                # 如果提供了字幕路径，直接使用；否则检测已有文件
                existing = processor.check_existing_files(course_name, lesson_title)
                
                if not subtitle_path:
                    subtitle_path = existing.get('subtitle_path')
                
                if not subtitle_path or not os.path.exists(subtitle_path):
                    update_task(task_id, "error", 0, "字幕文件不存在，请先转录")
                    continue
                
                # 检查笔记是否已存在
                if existing['note_exists'] and skip_existing:
                    update_task(task_id, "completed", 100, f"笔记已存在，已跳过: {existing['note_path']}")
                    with task_lock:
                        if task_id in task_status:
                            task_status[task_id]["skipped"] = True
                            task_status[task_id]["notePath"] = existing['note_path']
                    continue
                
                # 读取字幕
                try:
                    with open(subtitle_path, 'r', encoding='utf-8') as f:
                        transcript_text = f.read()
                except Exception as e:
                    update_task(task_id, "error", 0, f"读取字幕失败: {e}")
                    continue
                
                update_task(task_id, "processing", 30, "Gemini 生成笔记中...")
                
                if should_cancel():
                    update_task(task_id, "cancelled", 0, "任务已取消")
                    continue
                
                try:
                    note_content = processor.process_with_gemini_text(transcript_text)
                except Exception as e:
                    update_task(task_id, "error", 0, f"Gemini 生成失败: {e}")
                    continue
                
                if should_cancel():
                    update_task(task_id, "cancelled", 0, "任务已取消")
                    continue
                
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
        # 如果是 exists 状态（需要用户确认）
        if result.get("exists") and not result.get("skipped"):
            update_task(task_id, "pending_confirm", 50, result.get("message", "文件已存在，等待确认"))
            with task_lock:
                if task_id in task_status:
                    task_status[task_id]["needConfirm"] = True
                    task_status[task_id]["existingPath"] = result.get("audio_path") or result.get("subtitle_path") or result.get("note_path")
        else:
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
            if result.get("subtitle_path"):
                task_status[task_id]["subtitlePath"] = result["subtitle_path"]
            if result.get("transcript_path"):
                task_status[task_id]["transcriptPath"] = result["transcript_path"]
            if result.get("note_path"):
                task_status[task_id]["notePath"] = result["note_path"]
    
    # 生成完成消息
    if step_type == 'download':
        if skipped:
            msg = f"音频已存在，已跳过: {result.get('audio_path')}"
        else:
            msg = f"下载完成: {result.get('audio_path')}"
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
    force_regenerate = data.get('forceRegenerate', False)  # 是否强制重新生成（不跳过已存在的）
    
    if not urls:
        return jsonify({"status": "error", "message": "未收到视频链接"}), 400

    task_id = str(uuid.uuid4())
    action_label = "生成 AI 笔记"
    display_title = f"{course_name} · {lesson_title}"
    init_task_record(
        task_id,
        task_type="note",
        action_label=action_label,
        display_title=display_title,
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "urlCount": len(urls),
            "forceRegenerate": force_regenerate
        }
    )
    
    task_queue.put({
        'id': task_id,
        'type': 'note',
        'urls': urls,
        'courseName': course_name,
        'lessonTitle': lesson_title,
        'skipExisting': not force_regenerate  # 强制重新生成时不跳过
    })
    
    return jsonify({"status": "success", "task_id": task_id, "message": "任务已加入队列"})

@app.route('/download', methods=['POST'])
def download_local():
    data = request.json
    url = data.get('url')
    filename = data.get('filename', 'downloaded_file')
    file_type = data.get('type', 'video')
    
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"}), 400
    
    task_id = str(uuid.uuid4())
    action_label = "下载音频 (本地)" if file_type == 'audio' else "下载视频 (本地)"
    display_title = filename
    init_task_record(
        task_id,
        task_type="download",
        action_label=action_label,
        display_title=display_title,
        extra={
            "fileType": file_type
        }
    )
    
    task_queue.put({
        'id': task_id,
        'type': 'download',
        'url': url,
        'filename': filename,
        'fileType': file_type
    })
    
    return jsonify({"status": "success", "task_id": task_id, "message": "任务已加入队列"})

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
        if current_status in ['queued', 'processing', 'downloading']:
            cancelled_tasks.add(task_id)
            task_status[task_id]['status'] = 'cancelled'
            task_status[task_id]['message'] = '任务已取消'
            task_status[task_id]['updated_at'] = time.time()
            logger.info(f"[Task {task_id}] 已标记为取消")
            return jsonify({"status": "success", "message": "任务已取消"})
        
        # 如果任务已完成或已出错，直接从列表中删除
        elif current_status in ['completed', 'error', 'cancelled']:
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
        active_statuses = ['queued', 'processing', 'downloading']
        tasks_to_remove = [
            tid for tid, info in task_status.items() 
            if info['status'] not in active_statuses
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
    formatted_name = processor.parse_metadata(course_name, lesson_title)
    
    from core_processor import DOWNLOAD_DIR, OBSIDIAN_VAULT_PATH
    
    audio_path = Path(DOWNLOAD_DIR) / f"{formatted_name}.m4a"
    srt_path = Path(DOWNLOAD_DIR) / f"{formatted_name}.srt"
    txt_path = Path(DOWNLOAD_DIR) / f"{formatted_name}.txt"
    note_dir = Path(OBSIDIAN_VAULT_PATH) / course_name
    note_path = note_dir / f"{formatted_name}.md"
    
    # 检查音频完整性（大于1MB认为完整）
    audio_complete = False
    if audio_path.exists():
        try:
            audio_size = audio_path.stat().st_size
            audio_complete = audio_size > 1024 * 1024  # 1MB
        except:
            pass
    
    return jsonify({
        "audioExists": audio_path.exists(),
        "audioSize": audio_path.stat().st_size if audio_path.exists() else 0,
        "audioComplete": audio_complete,
        "subtitleExists": srt_path.exists() or txt_path.exists(),
        "srtExists": srt_path.exists(),
        "txtExists": txt_path.exists(),
        "txtRequired": not txt_path.exists(),  # Gemini 需要 TXT 格式
        "noteExists": note_path.exists(),
        "formattedName": formatted_name,
        "paths": {
            "audio": str(audio_path),
            "srt": str(srt_path) if srt_path.exists() else None,
            "txt": str(txt_path) if txt_path.exists() else None,  # Gemini 需要这个
            "note": str(note_path) if note_path.exists() else None
        }
    })

@app.route('/transcribe', methods=['POST'])
def transcribe():
    """转录音频（递进式：会自动下载音频如果不存在）"""
    data = request.json
    urls = data.get('urls', [])
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    
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
    
    task_id = str(uuid.uuid4())
    action_label = "转录音频"
    display_title = f"{course_name} · {lesson_title}"
    init_task_record(
        task_id,
        task_type="transcribe",
        action_label=action_label,
        display_title=display_title,
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "urlCount": len(urls)
        }
    )
    
    task_queue.put({
        'id': task_id,
        'type': 'transcribe',
        'urls': urls,
        'courseName': course_name,
        'lessonTitle': lesson_title
    })
    
    return jsonify({"status": "success", "task_id": task_id, "message": "转录任务已加入队列"})

@app.route('/transcribe-only', methods=['POST'])
def transcribe_only():
    """仅转录音频（需要音频文件已存在）- 已废弃，请使用 /transcribe"""
    data = request.json
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    audio_path = data.get('audioPath')  # 可选：指定音频路径
    
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
    
    task_id = str(uuid.uuid4())
    action_label = "转录音频"
    display_title = f"{course_name} · {lesson_title}"
    init_task_record(
        task_id,
        task_type="transcribe",
        action_label=action_label,
        display_title=display_title,
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "audioPath": audio_path
        }
    )
    
    task_queue.put({
        'id': task_id,
        'type': 'transcribe',
        'courseName': course_name,
        'lessonTitle': lesson_title,
        'audioPath': audio_path,
        'outputDir': DOWNLOAD_DIR
    })
    
    return jsonify({"status": "success", "task_id": task_id, "message": "转录任务已加入队列"})

@app.route('/generate-note-only', methods=['POST'])
def generate_note_only():
    """仅生成笔记（需要字幕文件已存在）"""
    data = request.json
    course_name = data.get('courseName', 'Default_Course')
    lesson_title = data.get('lessonTitle', 'Untitled_Lesson')
    subtitle_path = data.get('subtitlePath')  # 可选：指定字幕路径
    video_url = data.get('videoUrl', '')  # 原始视频链接
    
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
    
    task_id = str(uuid.uuid4())
    action_label = "生成 AI 笔记"
    display_title = f"{course_name} · {lesson_title}"
    init_task_record(
        task_id,
        task_type="generate-note",
        action_label=action_label,
        display_title=display_title,
        extra={
            "courseName": course_name,
            "lessonTitle": lesson_title,
            "subtitlePath": subtitle_path
        }
    )
    
    task_queue.put({
        'id': task_id,
        'type': 'generate-note',
        'courseName': course_name,
        'lessonTitle': lesson_title,
        'subtitlePath': subtitle_path,
        'videoUrl': video_url
    })
    
    return jsonify({"status": "success", "task_id": task_id, "message": "笔记生成任务已加入队列"})

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
