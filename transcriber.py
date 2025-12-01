import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

# 导入通用工具模块（自动加载 .env）
from utils import load_dotenv, get_config

# 确保环境变量已加载
load_dotenv()

logger = logging.getLogger("Transcriber")

ASR_ENGINE = os.getenv("ASR_ENGINE", "faster-whisper").lower()
FAST_WHISPER_MODEL = os.getenv("FASTWHISPER_MODEL", "large-v3")
CONFIG_FILE = Path(__file__).resolve().parent / "asr_config.json"
_CONFIG_DATA: Dict[str, str] = {}


def _load_config():
    global _CONFIG_DATA
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                _CONFIG_DATA = json.load(f)
        except Exception as exc:
            logger.warning("读取 %s 失败：%s", CONFIG_FILE, exc)
    else:
        _CONFIG_DATA = {}


_load_config()

FAST_WHISPER_LOCAL_DIR = os.getenv(
    "FASTWHISPER_LOCAL_DIR", _CONFIG_DATA.get("FASTWHISPER_LOCAL_DIR")
)
if FAST_WHISPER_LOCAL_DIR:
    logger.info("使用本地 faster-whisper 模型目录: %s", FAST_WHISPER_LOCAL_DIR)
FAST_WHISPER_DEVICE = os.getenv("FASTWHISPER_DEVICE", "cuda")
FAST_WHISPER_COMPUTE = os.getenv(
    "FASTWHISPER_COMPUTE",
    "float16" if FAST_WHISPER_DEVICE.startswith("cuda") else "int8",
)
FAST_WHISPER_CACHE = Path(
    os.getenv("FASTWHISPER_CACHE_DIR", Path(".cache/faster-whisper"))
).resolve()
MAX_TRANSCRIPT_CHARS = int(os.getenv("TRANSCRIPT_MAX_CHARS", "200000"))

# 全局模型缓存（避免重复加载）
_CACHED_MODEL = None
_CACHED_MODEL_PATH = None


def transcribe_audio(
    audio_path: str,
    output_dir: str,
    language: str = "auto",
    model_name: str = "",
    use_cuda: bool | None = None,
    model_dir: str | None = None,
) -> Dict[str, Any]:
    """
    High-level transcription entrypoint used by CoreProcessor.
    """
    audio_path_obj = Path(audio_path)
    if not audio_path_obj.exists():
        raise FileNotFoundError(f"音频文件不存在: {audio_path_obj}")
    audio_path_resolved = audio_path_obj.resolve()

    output_dir_obj = Path(output_dir)
    output_dir_obj.mkdir(parents=True, exist_ok=True)

    if ASR_ENGINE != "faster-whisper":
        raise RuntimeError(
            f"当前仅实现 faster-whisper ASR，收到 ASR_ENGINE={ASR_ENGINE}"
        )

    return _transcribe_with_faster_whisper(
        audio_path_resolved,
        output_dir_obj,
        language=language,
    )


def _find_model_path(base_path: Path) -> Path:
    """
    查找实际的模型文件路径。
    
    Hugging Face 本地缓存结构可能是：
    - 直接包含 model.bin 的目录
    - 包含 snapshots/xxx/ 子目录，model.bin 在子目录中
    
    Returns:
        包含 model.bin 的实际目录路径
    """
    # 情况1：直接包含 model.bin
    if (base_path / "model.bin").exists():
        return base_path
    
    # 情况2：检查 snapshots 子目录
    snapshots_dir = base_path / "snapshots"
    if snapshots_dir.exists() and snapshots_dir.is_dir():
        # 遍历 snapshots 下的子目录，找到包含 model.bin 的
        for subdir in snapshots_dir.iterdir():
            if subdir.is_dir() and (subdir / "model.bin").exists():
                logger.info(f"在 snapshots 中找到模型: {subdir}")
                return subdir
    
    # 情况3：没找到，返回原路径（让后续报错更清晰）
    logger.warning(f"未在 {base_path} 中找到 model.bin，尝试使用原路径")
    return base_path


def _transcribe_with_faster_whisper(
    audio_path: Path,
    output_dir: Path,
    language: str,
) -> Dict[str, Any]:
    """
    Transcribe audio using faster-whisper (https://github.com/SYSTRAN/faster-whisper).
    使用全局模型缓存，避免重复加载。
    """
    global _CACHED_MODEL, _CACHED_MODEL_PATH
    from faster_whisper import WhisperModel

    model_source = FAST_WHISPER_LOCAL_DIR.strip() if FAST_WHISPER_LOCAL_DIR else FAST_WHISPER_MODEL
    use_local = FAST_WHISPER_LOCAL_DIR is not None

    # 检查是否可以复用缓存的模型
    current_model_path = FAST_WHISPER_LOCAL_DIR if use_local else FAST_WHISPER_MODEL
    if _CACHED_MODEL is not None and _CACHED_MODEL_PATH == current_model_path:
        logger.info("使用已缓存的 Faster-Whisper 模型")
        model = _CACHED_MODEL
    else:
        # 需要加载新模型
        if use_local:
            source_path = Path(FAST_WHISPER_LOCAL_DIR).expanduser()
            if not source_path.exists():
                raise FileNotFoundError(f"本地 Faster-Whisper 模型目录不存在: {source_path}")
            
            # 查找实际包含 model.bin 的路径
            actual_model_path = _find_model_path(source_path)
            
            logger.info(
                "加载本地 Faster-Whisper 模型: path=%s device=%s compute=%s",
                actual_model_path,
                FAST_WHISPER_DEVICE,
                FAST_WHISPER_COMPUTE,
            )
            model = WhisperModel(
                str(actual_model_path),
                device=FAST_WHISPER_DEVICE,
                compute_type=FAST_WHISPER_COMPUTE,
                local_files_only=True,
            )
        else:
            FAST_WHISPER_CACHE.mkdir(parents=True, exist_ok=True)
            logger.info(
                "加载 Faster-Whisper 模型: size=%s device=%s compute=%s (缓存目录: %s)",
                FAST_WHISPER_MODEL,
                FAST_WHISPER_DEVICE,
                FAST_WHISPER_COMPUTE,
                FAST_WHISPER_CACHE,
            )
            model = WhisperModel(
                FAST_WHISPER_MODEL,
                device=FAST_WHISPER_DEVICE,
                compute_type=FAST_WHISPER_COMPUTE,
                download_root=str(FAST_WHISPER_CACHE),
            )
        
        # 缓存模型
        _CACHED_MODEL = model
        _CACHED_MODEL_PATH = current_model_path
        logger.info("模型已缓存，后续转录将复用")

    vad_filter = os.getenv("FASTWHISPER_VAD_FILTER", "true").lower() == "true"
    vad_min_silence = int(os.getenv("FASTWHISPER_MIN_SILENCE", "500"))
    beam_size = int(os.getenv("FASTWHISPER_BEAM_SIZE", "5"))  # 默认5（质量优先）
    temperature = float(os.getenv("FASTWHISPER_TEMPERATURE", "0"))
    language_arg = None if not language or language.lower() == "auto" else language
    initial_prompt = os.getenv("FASTWHISPER_INITIAL_PROMPT")
    
    # 加速参数
    best_of = int(os.getenv("FASTWHISPER_BEST_OF", "1"))  # 降低采样数
    patience = float(os.getenv("FASTWHISPER_PATIENCE", "1.0"))  # 提前停止
    condition_on_previous_text = os.getenv("FASTWHISPER_CONDITION_PREV", "false").lower() == "true"
    
    # 批处理加速（batched whisper）
    use_batched = os.getenv("FASTWHISPER_BATCHED", "true").lower() == "true"
    batch_size = int(os.getenv("FASTWHISPER_BATCH_SIZE", "16"))  # 批大小

    logger.info("开始执行 Faster-Whisper 转录: %s (beam_size=%d, batched=%s, batch_size=%d)", 
                audio_path, beam_size, use_batched, batch_size)
    
    # 使用 batched 模式加速（如果启用）
    if use_batched:
        try:
            from faster_whisper import BatchedInferencePipeline
            batched_model = BatchedInferencePipeline(model=model)
            segments, info = batched_model.transcribe(
                str(audio_path),
                batch_size=batch_size,
                language=language_arg,
                initial_prompt=initial_prompt,
                vad_filter=vad_filter,
                vad_parameters={"min_silence_duration_ms": vad_min_silence},
            )
            logger.info("使用 Batched 推理模式")
        except (ImportError, Exception) as e:
            logger.warning("Batched 模式不可用，回退到标准模式: %s", e)
            use_batched = False
    
    if not use_batched:
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=beam_size,
            best_of=best_of,
            patience=patience,
            temperature=temperature,
            language=language_arg,
            vad_filter=vad_filter,
            vad_parameters={"min_silence_duration_ms": vad_min_silence},
            initial_prompt=initial_prompt,
            condition_on_previous_text=condition_on_previous_text,
        )

    segment_list = list(segments)
    if not segment_list:
        raise RuntimeError("Faster-Whisper 未返回任何字幕内容，请检查音频是否为空或 FFmpeg 是否可用。")

    # 使用临时文件，成功后再重命名
    srt_path = output_dir / f"{audio_path.stem}.srt"
    txt_path = output_dir / f"{audio_path.stem}.txt"
    srt_tmp = output_dir / f"{audio_path.stem}.srt.tmp"
    txt_tmp = output_dir / f"{audio_path.stem}.txt.tmp"

    # 清理可能存在的残留临时文件
    for tmp in [srt_tmp, txt_tmp]:
        if tmp.exists():
            tmp.unlink()
            logger.debug(f"清理残留临时文件: {tmp}")

    try:
        _write_srt(segment_list, srt_tmp)
        transcript_text = _segments_to_text(segment_list)
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            transcript_text = (
                transcript_text[:MAX_TRANSCRIPT_CHARS]
                + "\n\n[... 字幕文本已截断，剩余内容请查看 SRT 文件 ...]"
            )
        txt_tmp.write_text(transcript_text, encoding="utf-8")

        # 写入成功，重命名为正式文件
        if srt_path.exists():
            srt_path.unlink()
        if txt_path.exists():
            txt_path.unlink()
        srt_tmp.rename(srt_path)
        txt_tmp.rename(txt_path)

        logger.info(
            "字幕已写入 %s (语言=%s, 时长=%.2f min)",
            srt_path,
            getattr(info, "language", "未知"),
            (getattr(info, "duration", 0) or 0) / 60 if hasattr(info, "duration") else 0,
        )

        return {
            "srt_path": str(srt_path),
            "txt_path": str(txt_path),
            "text": transcript_text,
        }
    except Exception as e:
        # 清理失败的临时文件
        for tmp in [srt_tmp, txt_tmp]:
            if tmp.exists():
                tmp.unlink()
        raise


def _write_srt(segments: Iterable, output_path: Path):
    with open(output_path, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, 1):
            start = _format_timestamp(seg.start)
            end = _format_timestamp(seg.end)
            text = (seg.text or "").strip()
            f.write(f"{idx}\n")
            f.write(f"{start} --> {end}\n")
            f.write(f"{text}\n\n")


def _segments_to_text(segments: Iterable) -> str:
    lines: List[str] = []
    for seg in segments:
        timestamp = _format_timestamp(seg.start)
        text = (seg.text or "").strip()
        lines.append(f"[{timestamp}] {text}")
    return "\n".join(lines)


def _format_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
