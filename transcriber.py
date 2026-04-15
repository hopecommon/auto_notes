import importlib
import hashlib
import logging
import os
import re
import shutil
import subprocess
import unicodedata
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

# 导入通用工具模块（自动加载 .env）
from utils import load_dotenv, get_config

# 确保环境变量已加载
load_dotenv()

logger = logging.getLogger("Transcriber")

ASR_ENGINE = os.getenv("ASR_ENGINE", "faster-whisper").lower()
FAST_WHISPER_MODEL = os.getenv("FASTWHISPER_MODEL", "large-v3")
FAST_WHISPER_LOCAL_DIR = os.getenv("FASTWHISPER_LOCAL_DIR")
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
SHERPA_ONNX_MODEL_TYPE = os.getenv("SHERPA_ONNX_MODEL_TYPE", "sense-voice").lower()
SHERPA_ONNX_MODEL_DIR = (os.getenv("SHERPA_ONNX_MODEL_DIR", "") or "").strip()
SHERPA_ONNX_MODEL_PATH = (os.getenv("SHERPA_ONNX_MODEL_PATH", "") or "").strip()
SHERPA_ONNX_ENCODER_PATH = (
    os.getenv("SHERPA_ONNX_ENCODER_PATH", "")
    or ""
).strip()
SHERPA_ONNX_DECODER_PATH = (
    os.getenv("SHERPA_ONNX_DECODER_PATH", "")
    or ""
).strip()
SHERPA_ONNX_TOKENS_PATH = (
    os.getenv("SHERPA_ONNX_TOKENS_PATH", "")
    or ""
).strip()
SHERPA_ONNX_VAD_MODEL = (os.getenv("SHERPA_ONNX_VAD_MODEL", "") or "").strip()
SHERPA_ONNX_PROVIDER = os.getenv("SHERPA_ONNX_PROVIDER", "cpu").lower()
SHERPA_ONNX_NUM_THREADS = int(os.getenv("SHERPA_ONNX_NUM_THREADS", "2"))
SHERPA_ONNX_SAMPLE_RATE = int(os.getenv("SHERPA_ONNX_SAMPLE_RATE", "16000"))
SHERPA_ONNX_FEATURE_DIM = int(os.getenv("SHERPA_ONNX_FEATURE_DIM", "80"))
SHERPA_ONNX_USE_ITN = os.getenv("SHERPA_ONNX_USE_ITN", "true").lower() == "true"
SHERPA_ONNX_VAD_THRESHOLD = float(os.getenv("SHERPA_ONNX_VAD_THRESHOLD", "0.2"))
SHERPA_ONNX_MIN_SILENCE = float(os.getenv("SHERPA_ONNX_MIN_SILENCE", "0.25"))
SHERPA_ONNX_MIN_SPEECH = float(os.getenv("SHERPA_ONNX_MIN_SPEECH", "0.25"))
SHERPA_ONNX_MAX_SPEECH = float(os.getenv("SHERPA_ONNX_MAX_SPEECH", "20"))
SHERPA_ONNX_VAD_BUFFER_SECONDS = float(
    os.getenv("SHERPA_ONNX_VAD_BUFFER_SECONDS", "120")
)
SHERPA_ONNX_CHUNK_SECONDS = float(os.getenv("SHERPA_ONNX_CHUNK_SECONDS", "30"))
FUNASR_MODEL_TYPE = os.getenv("FUNASR_MODEL_TYPE", "sensevoice").lower()
FUNASR_MODEL_DIR = (os.getenv("FUNASR_MODEL_DIR", "") or "").strip()
FUNASR_VAD_DIR = (os.getenv("FUNASR_VAD_DIR", "") or "").strip()
FUNASR_PUNC_DIR = (os.getenv("FUNASR_PUNC_DIR", "") or "").strip()
FUNASR_DEVICE = os.getenv("FUNASR_DEVICE", "cuda:0")
FUNASR_LANGUAGE = os.getenv("FUNASR_LANGUAGE", "auto")
FUNASR_USE_ITN = os.getenv("FUNASR_USE_ITN", "true").lower() == "true"
FUNASR_BATCH_SIZE_S = int(os.getenv("FUNASR_BATCH_SIZE_S", "60"))
FUNASR_MERGE_VAD = os.getenv("FUNASR_MERGE_VAD", "true").lower() == "true"
FUNASR_MERGE_LENGTH_S = int(os.getenv("FUNASR_MERGE_LENGTH_S", "15"))
FUNASR_DISABLE_UPDATE = os.getenv("FUNASR_DISABLE_UPDATE", "true").lower() == "true"
FUNASR_MAX_SINGLE_SEGMENT_MS = int(
    os.getenv("FUNASR_MAX_SINGLE_SEGMENT_MS", "30000")
)
FUNASR_HOTWORD = (os.getenv("FUNASR_HOTWORD", "") or "").strip()
FUNASR_HOTWORD_FILE = (os.getenv("FUNASR_HOTWORD_FILE", "") or "").strip()
FUNASR_HOTWORD_DIR = (os.getenv("FUNASR_HOTWORD_DIR", "") or "").strip()
FUNASR_SUBTITLE_MAX_WORDS = int(os.getenv("FUNASR_SUBTITLE_MAX_WORDS", "24"))
FUNASR_SUBTITLE_MAX_CHARS = int(os.getenv("FUNASR_SUBTITLE_MAX_CHARS", "64"))
FUNASR_FILTER_EDGE_NOISE = (
    os.getenv("FUNASR_FILTER_EDGE_NOISE", "false").lower() == "true"
)
FUNASR_SAVE_RAW = os.getenv("FUNASR_SAVE_RAW", "false").lower() == "true"
FUNASR_PYTHON = (os.getenv("FUNASR_PYTHON", "") or "").strip()
TRANSCRIPT_TERM_MAP_DIR = (os.getenv("TRANSCRIPT_TERM_MAP_DIR", "") or "").strip()
MAX_TRANSCRIPT_CHARS = int(os.getenv("TRANSCRIPT_MAX_CHARS", "200000"))
ASR_PREPROCESS_AUDIO = os.getenv("ASR_PREPROCESS_AUDIO", "false").lower() == "true"
ASR_PREPROCESS_FILTERS = (
    os.getenv("ASR_PREPROCESS_FILTERS", "highpass,lowpass,loudnorm,afftdn") or ""
).strip()
ASR_PREPROCESS_HIGHPASS_HZ = int(os.getenv("ASR_PREPROCESS_HIGHPASS_HZ", "80"))
ASR_PREPROCESS_LOWPASS_HZ = int(os.getenv("ASR_PREPROCESS_LOWPASS_HZ", "7600"))
ASR_PREPROCESS_LOUDNORM_I = os.getenv("ASR_PREPROCESS_LOUDNORM_I", "-23")
ASR_PREPROCESS_LOUDNORM_TP = os.getenv("ASR_PREPROCESS_LOUDNORM_TP", "-1")
ASR_PREPROCESS_LOUDNORM_LRA = os.getenv("ASR_PREPROCESS_LOUDNORM_LRA", "7")
ASR_PREPROCESS_AFFTDN_NR = os.getenv("ASR_PREPROCESS_AFFTDN_NR", "10")
ASR_PREPROCESS_AFFTDN_NF = os.getenv("ASR_PREPROCESS_AFFTDN_NF", "-40")
ASR_PREPROCESS_AFFTDN_TRACK_NOISE = (
    os.getenv("ASR_PREPROCESS_AFFTDN_TRACK_NOISE", "true").lower() == "true"
)
ASR_PREPROCESS_ANLMDN_STRENGTH = os.getenv("ASR_PREPROCESS_ANLMDN_STRENGTH", "0.0001")
ASR_PREPROCESS_ANLMDN_PATCH = os.getenv("ASR_PREPROCESS_ANLMDN_PATCH", "0.01")
ASR_PREPROCESS_ANLMDN_RESEARCH = os.getenv("ASR_PREPROCESS_ANLMDN_RESEARCH", "0.006")
ASR_PREPROCESS_ANLMDN_SMOOTH = os.getenv("ASR_PREPROCESS_ANLMDN_SMOOTH", "15")
ASR_PREPROCESS_ARNNDN_MODEL = (os.getenv("ASR_PREPROCESS_ARNNDN_MODEL", "") or "").strip()
ASR_PREPROCESS_ARNNDN_MIX = os.getenv("ASR_PREPROCESS_ARNNDN_MIX", "0.8")
ASR_PREPROCESS_SAMPLE_RATE = int(os.getenv("ASR_PREPROCESS_SAMPLE_RATE", "16000"))
ASR_PREPROCESS_CHANNELS = int(os.getenv("ASR_PREPROCESS_CHANNELS", "1"))
ASR_PREPROCESS_KEEP_FILES = (
    os.getenv("ASR_PREPROCESS_KEEP_FILES", "false").lower() == "true"
)

# 全局模型缓存（避免重复加载）
_CACHED_MODEL = None
_CACHED_MODEL_PATH = None
_CACHED_SHERPA_RECOGNIZER = None
_CACHED_SHERPA_SIGNATURE = None
_CACHED_FUNASR_MODEL = None
_CACHED_FUNASR_SIGNATURE = None


@dataclass
class _SubtitleSegment:
    start: float
    end: float
    text: str


_FUNASR_TAG_RE = re.compile(r"<\|[^>]+\|>")
_FUNASR_TAGGED_CHUNK_RE = re.compile(r"((?:<\|[^>]+\|>)+)([^<]*)")
_FUNASR_EVENT_TEXT_RE = re.compile(
    r"\[(?:BGM|Breath|Cough|Sneeze|Laughter|Applause|Cry|Event_UNK|Noise|Music)\]",
    re.IGNORECASE,
)
_FUNASR_LEADING_ASCII_RE = re.compile(
    r"^(?P<prefix>[A-Za-z][A-Za-z.\-,'!? ]{0,24})(?=[\u4e00-\u9fff])"
)
_FUNASR_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+"
)
_FUNASR_ASCII_FILLERS = {
    "ah",
    "oh",
    "ok",
    "okay",
    "the",
    "yeah",
    "thank",
    "thanks",
}


def _normalize_noise_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower())


def _is_repeated_pattern_text(text: str) -> bool:
    compact = _normalize_noise_text(text)
    if len(compact) < 16:
        return False

    max_unit = min(12, len(compact) // 3)
    for unit_len in range(1, max_unit + 1):
        if len(compact) % unit_len != 0:
            continue
        unit = compact[:unit_len]
        repeats = len(compact) // unit_len
        if repeats >= 3 and unit * repeats == compact:
            return True
    return False


def _filter_faster_whisper_segments(segments: List[Any]) -> List[Any]:
    filtered: List[Any] = []
    previous_norm = ""
    repeated_count = 0

    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue

        normalized = _normalize_noise_text(text)
        if not normalized:
            continue

        if normalized == previous_norm:
            repeated_count += 1
        else:
            repeated_count = 1
            previous_norm = normalized

        if repeated_count >= 3 and len(normalized) >= 8:
            logger.info("过滤连续重复的 Faster-Whisper 段: %s", text[:80])
            continue

        if _is_repeated_pattern_text(text):
            logger.info("过滤疑似模式化复读段: %s", text[:80])
            continue

        filtered.append(seg)

    return filtered


def _count_cjk_chars(text: str) -> int:
    return sum(
        1
        for ch in text
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"
    )


def _repair_mojibake_text(text: str) -> str:
    """
    sherpa-onnx 在 Windows 上偶发中文编码错位，表现为“ÎÒÃÇ”这类文本。
    这里尝试把错误解码的 latin1 文本还原为 gbk 中文。
    """
    if not text:
        return text

    suspicious_chars = sum(1 for ch in text if 0x00A1 <= ord(ch) <= 0x00FF)
    if suspicious_chars < max(2, len(text) // 20):
        return text

    try:
        repaired = text.encode("latin1").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

    if _count_cjk_chars(repaired) > _count_cjk_chars(text):
        logger.info("检测到 sherpa-onnx 中文编码错位，已自动修复")
        return repaired
    return text


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
    effective_audio_path = _maybe_preprocess_audio_for_asr(
        audio_path_resolved,
        output_dir_obj,
    )
    should_cleanup_preprocessed = (
        effective_audio_path != audio_path_resolved and not ASR_PREPROCESS_KEEP_FILES
    )

    try:
        if ASR_ENGINE == "faster-whisper":
            return _transcribe_with_faster_whisper(
                effective_audio_path,
                output_dir_obj,
                language=language,
            )
        if ASR_ENGINE == "funasr":
            return _transcribe_with_funasr(
                effective_audio_path,
                output_dir_obj,
                language=language,
                use_cuda=use_cuda,
            )
        if ASR_ENGINE in {"sherpa-onnx", "sherpa_onnx"}:
            return _transcribe_with_sherpa_onnx(
                effective_audio_path,
                output_dir_obj,
                language=language,
            )
    finally:
        if should_cleanup_preprocessed:
            _cleanup_preprocessed_audio(effective_audio_path, output_dir_obj)

    raise RuntimeError(
        "不支持的 ASR_ENGINE="
        f"{ASR_ENGINE}，当前支持 faster-whisper / funasr / sherpa-onnx"
    )


def _normalize_funasr_model_type(model_type: str) -> str:
    normalized = (model_type or "sensevoice").strip().lower().replace("_", "-")
    if normalized in {"sensevoice", "sense-voice"}:
        return "sensevoice"
    if normalized == "paraformer":
        return "paraformer"
    raise RuntimeError(
        f"FUNASR_MODEL_TYPE 仅支持 sensevoice / paraformer，收到: {model_type}"
    )


def _normalize_sherpa_onnx_model_type(model_type: str) -> str:
    normalized = (model_type or "sense-voice").strip().lower().replace("_", "-")
    if normalized in {"sensevoice", "sense-voice"}:
        return "sense-voice"
    if normalized == "paraformer":
        return "paraformer"
    if normalized in {"firered", "fire-red", "fire-red-asr"}:
        return "fire-red-asr"
    if normalized in {"firered-ctc", "fire-red-ctc", "fire-red-asr-ctc"}:
        return "fire-red-asr-ctc"
    raise RuntimeError(
        "SHERPA_ONNX_MODEL_TYPE 仅支持 "
        "sense-voice / paraformer / fire-red-asr / fire-red-asr-ctc，"
        f"收到: {model_type}"
    )


def _resolve_path(path_value: str) -> Path | None:
    if not path_value:
        return None
    return Path(path_value).expanduser().resolve()


def _build_asr_preprocess_filter_chain() -> str:
    enabled = {
        item.strip().lower()
        for item in ASR_PREPROCESS_FILTERS.split(",")
        if item.strip()
    }
    if not enabled:
        return ""

    filters: List[str] = []
    if "highpass" in enabled:
        filters.append(f"highpass=f={max(20, ASR_PREPROCESS_HIGHPASS_HZ)}")
    if "lowpass" in enabled:
        filters.append(f"lowpass=f={max(1000, ASR_PREPROCESS_LOWPASS_HZ)}")
    if "loudnorm" in enabled:
        filters.append(
            "loudnorm="
            f"I={ASR_PREPROCESS_LOUDNORM_I}:"
            f"TP={ASR_PREPROCESS_LOUDNORM_TP}:"
            f"LRA={ASR_PREPROCESS_LOUDNORM_LRA}"
        )
    if "afftdn" in enabled:
        afftdn = [
            f"afftdn=nr={ASR_PREPROCESS_AFFTDN_NR}:nf={ASR_PREPROCESS_AFFTDN_NF}"
        ]
        if ASR_PREPROCESS_AFFTDN_TRACK_NOISE:
            afftdn[0] += ":tn=1"
        filters.extend(afftdn)
    if "anlmdn" in enabled:
        filters.append(
            "anlmdn="
            f"s={ASR_PREPROCESS_ANLMDN_STRENGTH}:"
            f"p={ASR_PREPROCESS_ANLMDN_PATCH}:"
            f"r={ASR_PREPROCESS_ANLMDN_RESEARCH}:"
            f"m={ASR_PREPROCESS_ANLMDN_SMOOTH}"
        )
    if "arnndn" in enabled:
        arnndn_model = _resolve_path(ASR_PREPROCESS_ARNNDN_MODEL)
        if arnndn_model is None or not arnndn_model.exists():
            raise FileNotFoundError(
                "启用 arnndn 预处理时需要设置 ASR_PREPROCESS_ARNNDN_MODEL，并确保模型文件存在"
            )
        arnndn_model_escaped = arnndn_model.as_posix().replace(":", "\\:")
        filters.append(
            f"arnndn=m='{arnndn_model_escaped}':mix={ASR_PREPROCESS_ARNNDN_MIX}"
        )
    return ",".join(filters)


def _maybe_preprocess_audio_for_asr(audio_path: Path, output_dir: Path) -> Path:
    if not ASR_PREPROCESS_AUDIO:
        return audio_path
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("启用 ASR_PREPROCESS_AUDIO 时需要可用的 ffmpeg")

    filter_chain = _build_asr_preprocess_filter_chain()
    if not filter_chain:
        logger.info("已启用 ASR 预处理，但未配置有效滤镜，跳过")
        return audio_path

    signature_source = "|".join(
        [
            filter_chain,
            str(ASR_PREPROCESS_SAMPLE_RATE),
            str(ASR_PREPROCESS_CHANNELS),
        ]
    )
    signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()[:10]
    preprocess_dir = output_dir / "_asr_preprocessed" / signature
    preprocess_dir.mkdir(parents=True, exist_ok=True)
    output_path = preprocess_dir / f"{audio_path.stem}.wav"

    if output_path.exists() and output_path.stat().st_mtime >= audio_path.stat().st_mtime:
        logger.info("复用已生成的 ASR 预处理音频: %s", output_path)
        return output_path

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-af",
        filter_chain,
        "-ar",
        str(ASR_PREPROCESS_SAMPLE_RATE),
        "-ac",
        str(ASR_PREPROCESS_CHANNELS),
        str(output_path),
    ]
    logger.info(
        "开始执行 ASR 音频预处理: input=%s output=%s filters=%s",
        audio_path,
        output_path,
        filter_chain,
    )
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        stderr_text = (proc.stderr or "").strip()
        raise RuntimeError(
            "ASR 音频预处理失败: "
            f"{stderr_text or f'退出码 {proc.returncode}'}"
        )
    logger.info("ASR 音频预处理完成: %s", output_path)
    return output_path


def _cleanup_preprocessed_audio(audio_path: Path, output_dir: Path) -> None:
    try:
        if audio_path.exists():
            audio_path.unlink()
        current_dir = audio_path.parent
        stop_dir = output_dir.resolve()
        while current_dir != stop_dir and current_dir.exists():
            try:
                current_dir.rmdir()
            except OSError:
                break
            current_dir = current_dir.parent
    except Exception as exc:
        logger.debug("清理 ASR 预处理文件失败: %s", exc)


def _resolve_funasr_paths() -> tuple[str, Path, Path | None, Path | None]:
    model_type = _normalize_funasr_model_type(FUNASR_MODEL_TYPE)
    model_dir = _resolve_path(FUNASR_MODEL_DIR)
    vad_dir = _resolve_path(FUNASR_VAD_DIR)
    punc_dir = _resolve_path(FUNASR_PUNC_DIR)

    if model_dir is None or not model_dir.exists():
        raise FileNotFoundError(
            "FunASR 模型目录不存在，请配置 FUNASR_MODEL_DIR"
        )
    if vad_dir is not None and not vad_dir.exists():
        raise FileNotFoundError(f"FunASR VAD 目录不存在: {vad_dir}")
    if punc_dir is not None and not punc_dir.exists():
        raise FileNotFoundError(f"FunASR 标点目录不存在: {punc_dir}")

    return model_type, model_dir, vad_dir if vad_dir else None, punc_dir if punc_dir else None


def _resolve_funasr_device(use_cuda: bool | None) -> str:
    if use_cuda is False:
        return "cpu"
    if use_cuda is True:
        return FUNASR_DEVICE

    try:
        import torch

        if FUNASR_DEVICE.startswith("cuda") and not torch.cuda.is_available():
            logger.warning("未检测到可用 CUDA，FunASR 自动回退到 CPU")
            return "cpu"
    except Exception:
        if FUNASR_DEVICE.startswith("cuda"):
            logger.warning("无法检测 torch.cuda 状态，FunASR 自动回退到 CPU")
            return "cpu"
    return FUNASR_DEVICE


def _build_funasr_model(use_cuda: bool | None):
    funasr = importlib.import_module("funasr")
    AutoModel = funasr.AutoModel

    model_type, model_dir, vad_dir, punc_dir = _resolve_funasr_paths()
    device = _resolve_funasr_device(use_cuda)
    kwargs: Dict[str, Any] = {
        "model": str(model_dir),
        "trust_remote_code": False,
        "device": device,
        "disable_update": FUNASR_DISABLE_UPDATE,
    }
    if vad_dir is not None:
        kwargs["vad_model"] = str(vad_dir)
        kwargs["vad_kwargs"] = {"max_single_segment_time": FUNASR_MAX_SINGLE_SEGMENT_MS}
    if punc_dir is not None and model_type == "paraformer":
        kwargs["punc_model"] = str(punc_dir)

    logger.info(
        "加载 FunASR 模型: type=%s model=%s vad=%s punc=%s device=%s",
        model_type,
        model_dir,
        vad_dir,
        punc_dir,
        device,
    )
    return AutoModel(**kwargs)


def _get_funasr_python_executable() -> Path | None:
    candidates = []
    if FUNASR_PYTHON:
        candidates.append(Path(FUNASR_PYTHON))

    project_root = Path(__file__).resolve().parent
    candidates.extend(
        [
            project_root / ".venv-funasr" / "Scripts" / "python.exe",
            project_root / ".venv" / "Scripts" / "python.exe",
        ]
    )

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.resolve() != Path(sys.executable).resolve():
                return candidate.resolve()
        except Exception:
            continue
    return None


def _collect_funasr_runtime_info(use_cuda: bool | None = None) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "python": sys.executable,
        "platform": sys.platform,
        "funasr_python": FUNASR_PYTHON or "",
        "requested_device": FUNASR_DEVICE,
        "use_cuda_arg": use_cuda,
    }
    try:
        import torch

        info["torch_version"] = getattr(torch, "__version__", "unknown")
        info["torch_cuda_version"] = getattr(torch.version, "cuda", None)
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["cuda_device_count"] = int(torch.cuda.device_count())
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            info["cuda_device_name"] = torch.cuda.get_device_name(0)
            info["cuda_current_device"] = int(torch.cuda.current_device())
    except Exception as exc:
        info["torch_error"] = str(exc)
    return info


def _log_funasr_runtime_info(prefix: str, use_cuda: bool | None = None) -> None:
    info = _collect_funasr_runtime_info(use_cuda)
    logger.info(
        "%s runtime: python=%s requested_device=%s use_cuda=%s torch=%s torch_cuda=%s cuda_available=%s cuda_count=%s cuda_name=%s funasr_python=%s",
        prefix,
        info.get("python"),
        info.get("requested_device"),
        info.get("use_cuda_arg"),
        info.get("torch_version", info.get("torch_error", "unavailable")),
        info.get("torch_cuda_version", "unknown"),
        info.get("cuda_available", "unknown"),
        info.get("cuda_device_count", "unknown"),
        info.get("cuda_device_name", "n/a"),
        info.get("funasr_python", ""),
    )


def _run_funasr_via_subprocess(
    audio_path: Path,
    output_dir: Path,
    language: str,
    use_cuda: bool | None,
) -> Dict[str, Any]:
    python_executable = _get_funasr_python_executable()
    project_root = Path(__file__).resolve().parent
    if python_executable is None:
        raise ModuleNotFoundError(
            "No module named 'funasr'，且未找到可用的 FunASR 虚拟环境 Python。"
            "请安装 funasr，或在 FUNASR_PYTHON 中指定可用的 python.exe。"
        )

    helper_code = f"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

project_root = Path({str(project_root)!r})
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def _eprint(message):
    print(message, file=sys.stderr, flush=True)

_eprint(f"[funasr-subprocess] python={{sys.executable}}")
_eprint(f"[funasr-subprocess] version={{sys.version.split()[0]}} platform={{sys.platform}}")
try:
    import torch
    _eprint(f"[funasr-subprocess] torch={{getattr(torch, '__version__', 'unknown')}} cuda={{getattr(torch.version, 'cuda', None)}} available={{torch.cuda.is_available()}} count={{torch.cuda.device_count()}}")
    if torch.cuda.is_available() and torch.cuda.device_count() > 0:
        _eprint(f"[funasr-subprocess] cuda_name={{torch.cuda.get_device_name(0)}} current_device={{torch.cuda.current_device()}}")
except Exception as exc:
    _eprint(f"[funasr-subprocess] torch_error={{exc}}")
_eprint(f"[funasr-subprocess] requested_device={FUNASR_DEVICE} funasr_python={FUNASR_PYTHON or ''}")

from transcriber import _transcribe_with_funasr

audio_path = Path(sys.argv[1])
output_dir = Path(sys.argv[2])
language = sys.argv[3]
use_cuda_arg = sys.argv[4]
if use_cuda_arg == "none":
    use_cuda = None
else:
    use_cuda = use_cuda_arg.lower() == "true"

result = _transcribe_with_funasr(
    audio_path,
    output_dir,
    language,
    use_cuda,
    allow_subprocess_fallback=False,
)
print(json.dumps(result, ensure_ascii=False))
""".strip()

    cmd = [
        str(python_executable),
        "-c",
        helper_code,
        str(audio_path),
        str(output_dir),
        language,
        "none" if use_cuda is None else ("true" if use_cuda else "false"),
    ]
    logger.info("FunASR 当前解释器缺少依赖，改用虚拟环境运行: %s", python_executable)
    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(project_root),
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    stderr_text = (process.stderr or "").strip()
    if stderr_text:
        logger.info("FunASR 子进程信息:\n%s", stderr_text)
    if process.returncode != 0:
        stderr_text = (stderr_text or process.stdout or "").strip()
        raise RuntimeError(
            "FunASR 虚拟环境执行失败: "
            f"{stderr_text or f'退出码 {process.returncode}'}"
        )

    stdout_text = (process.stdout or "").strip()
    if not stdout_text:
        raise RuntimeError("FunASR 虚拟环境未返回结果")

    try:
        return json.loads(stdout_text.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"无法解析 FunASR 虚拟环境输出: {stdout_text}") from exc


def _should_prefer_configured_funasr_python() -> bool:
    if not FUNASR_PYTHON:
        return False

    configured = _resolve_path(FUNASR_PYTHON)
    if configured is None or not configured.exists():
        return False

    try:
        return configured.resolve() != Path(sys.executable).resolve()
    except Exception:
        return False


def _get_cached_funasr_model(use_cuda: bool | None):
    global _CACHED_FUNASR_MODEL, _CACHED_FUNASR_SIGNATURE

    model_type, model_dir, vad_dir, punc_dir = _resolve_funasr_paths()
    device = _resolve_funasr_device(use_cuda)
    signature = (
        model_type,
        str(model_dir),
        str(vad_dir) if vad_dir else "",
        str(punc_dir) if punc_dir else "",
        device,
        FUNASR_DISABLE_UPDATE,
        FUNASR_MAX_SINGLE_SEGMENT_MS,
    )
    if _CACHED_FUNASR_MODEL is not None and _CACHED_FUNASR_SIGNATURE == signature:
        logger.info("使用已缓存的 FunASR 模型")
        return _CACHED_FUNASR_MODEL

    model = _build_funasr_model(use_cuda)
    _CACHED_FUNASR_MODEL = model
    _CACHED_FUNASR_SIGNATURE = signature
    logger.info("FunASR 模型已缓存")
    return model


def _extract_sensevoice_speech_text(raw_text: str) -> str:
    if not raw_text:
        return ""

    chunks: List[str] = []
    for match in _FUNASR_TAGGED_CHUNK_RE.finditer(raw_text):
        tags = match.group(1) or ""
        content = (match.group(2) or "").strip()
        if not content:
            continue
        if "<|Speech|>" not in tags:
            continue
        chunks.append(content)

    if chunks:
        return " ".join(chunks)
    return raw_text


def _strip_non_printing(text: str) -> str:
    return "".join(
        ch for ch in text if unicodedata.category(ch) not in {"Cf", "Cc", "Cs"}
    )


def _trim_leading_noise(text: str) -> str:
    match = re.search(r"[\u4e00-\u9fff][\u4e00-\u9fff，。！？；：、“”‘’\s]{10,}", text)
    if not match:
        return text

    prefix = text[: match.start()]
    prefix_cjk = _count_cjk_chars(prefix)
    prefix_latin = sum(1 for ch in prefix if ch.isascii() and ch.isalpha())
    if prefix and len(prefix) <= 48 and prefix_cjk <= 4 and prefix_latin >= 2:
        return text[match.start() :].lstrip()
    return text


def _normalize_funasr_text_line(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("▁", "")
    text = re.sub(r"\s+([，。！？；：,.!?、）)\]])", r"\1", text)
    text = re.sub(r"([（(\[])(\s+)", r"\1", text)
    return text.strip()


def _trim_leading_ascii_interjection(text: str) -> str:
    text = _normalize_funasr_text_line(text)
    if not text:
        return ""

    match = _FUNASR_LEADING_ASCII_RE.match(text)
    if not match:
        return text

    prefix = match.group("prefix").strip()
    normalized_words = re.findall(r"[A-Za-z]+", prefix.lower())
    if not normalized_words:
        return text

    if all(word in _FUNASR_ASCII_FILLERS for word in normalized_words):
        trimmed = text[match.end() :].lstrip()
        return _normalize_funasr_text_line(trimmed)
    return text


def _is_low_signal_ascii_segment(text: str) -> bool:
    normalized = _normalize_funasr_text_line(text)
    if not normalized or _count_cjk_chars(normalized) > 0:
        return False

    words = re.findall(r"[A-Za-z]+", normalized.lower())
    if not words:
        return False
    if all(word in _FUNASR_ASCII_FILLERS for word in words):
        if len(words) <= 2:
            return True
        if len(words) <= 16 and len(set(words)) <= 2 and len(normalized) <= 96:
            return True
    return False


def _clean_funasr_subtitle_segment_text(text: str) -> str:
    text = _trim_leading_ascii_interjection(text)
    text = _normalize_funasr_text_line(text)
    if _is_low_signal_ascii_segment(text):
        return ""
    return text


def _filter_low_signal_funasr_segments(
    segments: List[_SubtitleSegment],
) -> List[_SubtitleSegment]:
    if not FUNASR_FILTER_EDGE_NOISE:
        return segments

    if not segments:
        return segments

    filtered: List[_SubtitleSegment] = []
    total = len(segments)
    for idx, seg in enumerate(segments):
        text = (seg.text or "").strip()
        if not text:
            continue

        normalized = text.strip(" .。!！?？,，;；:：")
        cjk_count = _count_cjk_chars(normalized)
        ascii_letters = sum(1 for ch in normalized if ch.isascii() and ch.isalpha())
        duration = max(0.0, float(seg.end) - float(seg.start))

        previous_end = segments[idx - 1].end if idx > 0 else None
        next_start = segments[idx + 1].start if idx + 1 < total else None
        previous_gap = (
            max(0.0, float(seg.start) - float(previous_end))
            if previous_end is not None
            else None
        )
        next_gap = (
            max(0.0, float(next_start) - float(seg.end))
            if next_start is not None
            else None
        )

        sparse_edge_segment = (
            len(normalized) <= 2
            and cjk_count <= 1
            and ascii_letters == 0
            and duration <= 2.5
            and (
                (previous_gap is not None and previous_gap >= 20.0)
                or (next_gap is not None and next_gap >= 20.0)
                or idx == 0
                or idx == total - 1
            )
        )
        sparse_ascii_filler = _is_low_signal_ascii_segment(text) and (
            duration <= 3.0
            or (previous_gap is not None and previous_gap >= 5.0)
            or (next_gap is not None and next_gap >= 5.0)
            or idx == 0
            or idx == total - 1
        )

        if sparse_edge_segment or sparse_ascii_filler:
            continue
        filtered.append(seg)

    return filtered


def _is_funasr_punctuation_token(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    return all(unicodedata.category(ch).startswith("P") for ch in token)


def _is_funasr_meaningful_token(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    if _is_funasr_punctuation_token(token):
        return False
    return any(ch.isascii() and ch.isalnum() for ch in token) or _count_cjk_chars(token) > 0


def _join_funasr_tokens(tokens: Iterable[str]) -> str:
    pieces: List[str] = []
    last_kind = None

    def token_kind(token: str) -> str:
        if _is_funasr_punctuation_token(token):
            return "punct"
        if _count_cjk_chars(token) > 0:
            return "cjk"
        if any(ch.isascii() and ch.isalnum() for ch in token):
            return "latin"
        return "other"

    for raw_token in tokens:
        token = _normalize_funasr_text_line(str(raw_token))
        if not token:
            continue
        kind = token_kind(token)

        if kind == "punct":
            if not pieces:
                continue
            pieces[-1] = pieces[-1].rstrip() + token
            last_kind = "punct"
            continue

        if not pieces:
            pieces.append(token)
        else:
            prev = pieces[-1]
            if last_kind == "latin" and kind == "latin":
                pieces.append(" " + token)
            elif last_kind == "latin" and kind in {"cjk", "other"}:
                pieces.append(" " + token)
            elif last_kind in {"cjk", "other"} and kind == "latin":
                pieces.append(" " + token)
            else:
                pieces.append(token)
        last_kind = kind

    text = "".join(pieces)
    text = _normalize_funasr_text_line(text)
    text = re.sub(r"\s*([。！？!?；;，,、])\s*", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _read_funasr_hotword_lines(hotword_path: Path) -> List[str]:
    hotword_lines: List[str] = []
    for raw_line in hotword_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        hotword_lines.append(line)
    return hotword_lines


def _resolve_course_sidecar_match(
    audio_path: Path | None,
    directory_value: str,
    suffix: str,
    label: str,
) -> Path | None:
    if not directory_value or audio_path is None:
        return None

    sidecar_dir = _resolve_path(directory_value)
    if sidecar_dir is None or not sidecar_dir.exists():
        raise FileNotFoundError(f"{label}目录不存在: {directory_value}")
    if not sidecar_dir.is_dir():
        raise NotADirectoryError(f"{label}目录不是文件夹: {sidecar_dir}")

    audio_stem = audio_path.stem.casefold()
    matches: List[tuple[int, Path]] = []
    for sidecar_file in sidecar_dir.glob(f"*{suffix}"):
        course_name = sidecar_file.stem.strip().casefold()
        if not course_name:
            continue
        if course_name == audio_stem or course_name in audio_stem:
            matches.append((len(course_name), sidecar_file))

    if not matches:
        return None

    matches.sort(key=lambda item: (-item[0], item[1].name))
    matched = matches[0][1]
    logger.info("%s自动匹配文件: %s <- %s", label, matched, audio_path.name)
    return matched


def _resolve_funasr_hotword_match(audio_path: Path | None) -> Path | None:
    return _resolve_course_sidecar_match(
        audio_path,
        FUNASR_HOTWORD_DIR,
        ".txt",
        "FunASR 热词",
    )


def _resolve_funasr_hotword(audio_path: Path | None = None) -> str:
    hotword_lines: List[str] = []
    seen_lines: set[str] = set()

    def add_lines(lines: Iterable[str]) -> None:
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line in seen_lines:
                continue
            seen_lines.add(line)
            hotword_lines.append(line)

    if FUNASR_HOTWORD:
        add_lines(FUNASR_HOTWORD.splitlines())

    if FUNASR_HOTWORD_FILE:
        hotword_path = _resolve_path(FUNASR_HOTWORD_FILE)
        if hotword_path is None or not hotword_path.exists():
            raise FileNotFoundError(f"FunASR 热词文件不存在: {FUNASR_HOTWORD_FILE}")
        add_lines(_read_funasr_hotword_lines(hotword_path))

    matched_hotword_path = _resolve_funasr_hotword_match(audio_path)
    if matched_hotword_path is not None:
        add_lines(_read_funasr_hotword_lines(matched_hotword_path))

    return "\n".join(hotword_lines).strip()


def _load_transcript_term_map_rules(term_map_path: Path) -> List[tuple[re.Pattern[str], str]]:
    try:
        raw_rules = json.loads(term_map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"术语映射文件不是合法 JSON: {term_map_path}") from exc

    if not isinstance(raw_rules, list):
        raise RuntimeError(f"术语映射文件格式错误，应为数组: {term_map_path}")

    compiled_rules: List[tuple[re.Pattern[str], str]] = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern", "") or "").strip()
        replace = str(item.get("replace", "") or "")
        flags_text = str(item.get("flags", "") or "").upper()
        if not pattern:
            continue
        flags = 0
        if "I" in flags_text:
            flags |= re.IGNORECASE
        compiled_rules.append((re.compile(pattern, flags), replace))
    return compiled_rules


def _apply_course_term_map(audio_path: Path, text: str) -> str:
    if not TRANSCRIPT_TERM_MAP_DIR or not text:
        return text

    term_map_path = _resolve_course_sidecar_match(
        audio_path,
        TRANSCRIPT_TERM_MAP_DIR,
        ".json",
        "术语映射",
    )
    if term_map_path is None:
        return text

    normalized = text
    for pattern, replace in _load_transcript_term_map_rules(term_map_path):
        normalized = pattern.sub(replace, normalized)
    return normalized


def _infer_funasr_timestamp_scale(timestamp_pairs: Iterable[tuple[float, float]]) -> float:
    durations: List[float] = []
    max_value = 0.0
    all_integral = True

    for start, end in timestamp_pairs:
        start_value = float(start)
        end_value = float(end)
        max_value = max(max_value, start_value, end_value)
        duration = end_value - start_value
        if duration > 0:
            durations.append(duration)
        if not start_value.is_integer() or not end_value.is_integer():
            all_integral = False

    if not durations:
        return 1.0

    durations.sort()
    median_duration = durations[len(durations) // 2]

    # FunASR 常见返回是毫秒整数；若直接按秒写入，会得到几十分钟甚至几小时的错误时间轴。
    if all_integral and max_value >= 1000 and median_duration >= 20:
        return 0.001
    return 1.0


def _funasr_timestamp_segments_from_words(
    words: List[str], timestamps: List[List[float]]
) -> List[_SubtitleSegment]:
    if not words or not timestamps:
        return []

    segments: List[_SubtitleSegment] = []
    current_words: List[str] = []
    current_start: float | None = None
    current_end: float | None = None

    sentence_break_tokens = {"。", "！", "？", "!", "?", "；", ";", "\n"}
    max_words_per_segment = max(1, FUNASR_SUBTITLE_MAX_WORDS)
    max_chars_per_segment = max(1, FUNASR_SUBTITLE_MAX_CHARS)
    timestamp_pairs = [
        (float(ts[0]), float(ts[1]))
        for ts in timestamps
        if isinstance(ts, list) and len(ts) >= 2
    ]
    time_scale = _infer_funasr_timestamp_scale(timestamp_pairs)

    def flush_segment() -> None:
        nonlocal current_words, current_start, current_end
        if current_start is None or current_end is None or not current_words:
            current_words = []
            current_start = None
            current_end = None
            return

        text = _clean_funasr_subtitle_segment_text(_join_funasr_tokens(current_words))
        if text and _is_funasr_meaningful_token(text):
            segments.append(
                _SubtitleSegment(
                    start=float(current_start),
                    end=float(current_end),
                    text=text,
                )
            )

        current_words = []
        current_start = None
        current_end = None

    for word, ts in zip(words, timestamps):
        if not ts or len(ts) < 2:
            continue
        token = _normalize_funasr_text_line(str(word))
        if not token:
            continue

        if _is_funasr_punctuation_token(token) and not current_words:
            continue

        start, end = float(ts[0]) * time_scale, float(ts[1]) * time_scale
        if current_start is None:
            current_start = start
        current_end = end
        current_words.append(token)

        current_text = _join_funasr_tokens(current_words)
        should_break = (
            (token in sentence_break_tokens and _is_funasr_meaningful_token(current_text))
            or len(current_words) >= max_words_per_segment
            or len(current_text) >= max_chars_per_segment
        )
        if should_break:
            flush_segment()

    flush_segment()
    return segments


def _funasr_segments_from_result(result_item: Dict[str, Any], model_type: str) -> List[_SubtitleSegment]:
    sentence_info = result_item.get("sentence_info")
    if isinstance(sentence_info, list) and sentence_info:
        sentence_pairs = []
        for item in sentence_info:
            if not isinstance(item, dict):
                continue
            start = item.get("start")
            end = item.get("end")
            if start is None or end is None:
                continue
            try:
                sentence_pairs.append((float(start), float(end)))
            except (TypeError, ValueError):
                continue

        time_scale = _infer_funasr_timestamp_scale(sentence_pairs)
        segments: List[_SubtitleSegment] = []
        for item in sentence_info:
            if not isinstance(item, dict):
                continue
            text = item.get("text", "")
            if isinstance(text, list):
                text = _join_funasr_tokens(str(x) for x in text)
            text = _clean_funasr_subtitle_segment_text(str(text))
            start = item.get("start")
            end = item.get("end")
            if text and _is_funasr_meaningful_token(text) and start is not None and end is not None:
                segments.append(
                    _SubtitleSegment(
                        start=float(start) * time_scale,
                        end=float(end) * time_scale,
                        text=text,
                    )
                )
        if segments:
            return segments

    if model_type == "sensevoice":
        words = result_item.get("words")
        timestamps = result_item.get("timestamp")
        if isinstance(words, list) and isinstance(timestamps, list):
            segments = _funasr_timestamp_segments_from_words(words, timestamps)
            if segments:
                return segments

    return []


def _segments_to_srt_like_text(segments: Iterable[_SubtitleSegment]) -> str:
    lines: List[str] = []
    for idx, seg in enumerate(segments, 1):
        lines.append(str(idx))
        lines.append(
            f"{_format_timestamp(seg.start)} --> {_format_timestamp(seg.end)}"
        )
        lines.append((seg.text or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_subtitle_outputs(
    audio_path: Path,
    output_dir: Path,
    segments: List[_SubtitleSegment],
) -> Dict[str, Any]:
    srt_path = output_dir / f"{audio_path.stem}.srt"
    txt_path = output_dir / f"{audio_path.stem}.txt"
    srt_tmp = output_dir / f"{audio_path.stem}.srt.tmp"
    txt_tmp = output_dir / f"{audio_path.stem}.txt.tmp"

    for tmp in [srt_tmp, txt_tmp]:
        if tmp.exists():
            tmp.unlink()

    normalized_segments = [
        _SubtitleSegment(
            start=seg.start,
            end=seg.end,
            text=_apply_course_term_map(audio_path, seg.text or ""),
        )
        for seg in segments
    ]
    plain_text = _apply_course_term_map(audio_path, _segments_to_text(normalized_segments))

    try:
        _write_srt(normalized_segments, srt_tmp)
        txt_tmp.write_text(plain_text, encoding="utf-8")

        if srt_path.exists():
            srt_path.unlink()
        if txt_path.exists():
            txt_path.unlink()
        srt_tmp.rename(srt_path)
        txt_tmp.rename(txt_path)
    except Exception:
        for tmp in [srt_tmp, txt_tmp]:
            if tmp.exists():
                tmp.unlink()
        raise

    return {
        "srt_path": str(srt_path),
        "txt_path": str(txt_path),
        "text": plain_text,
    }


def _clean_funasr_text(raw_text: str, model_type: str) -> str:
    text = raw_text or ""
    if model_type == "sensevoice":
        text = _extract_sensevoice_speech_text(text)

    text = _FUNASR_TAG_RE.sub(" ", text)
    text = _FUNASR_EVENT_TEXT_RE.sub(" ", text)
    text = _FUNASR_EMOJI_RE.sub(" ", text)
    text = _strip_non_printing(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([，。！？；：,.!?])", r"\1", text)
    text = re.sub(r"([（(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([）)\]])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _trim_leading_noise(text)

    cleaned_lines = []
    for line in text.splitlines():
        line = _trim_leading_ascii_interjection(line)
        if _is_low_signal_ascii_segment(line):
            continue
        normalized = line.strip(" .。!！?？,，;；:：")
        if not normalized:
            continue
        cleaned_lines.append(line.strip())
    text = "\n".join(cleaned_lines).strip()
    return text


def _write_text_only_output(
    audio_path: Path,
    output_dir: Path,
    transcript_text: str,
) -> Dict[str, Any]:
    txt_path = output_dir / f"{audio_path.stem}.txt"
    txt_tmp = output_dir / f"{audio_path.stem}.txt.tmp"

    if txt_tmp.exists():
        txt_tmp.unlink()

    normalized_text = _apply_course_term_map(audio_path, transcript_text)

    try:
        txt_tmp.write_text(normalized_text, encoding="utf-8")
        if txt_path.exists():
            txt_path.unlink()
        txt_tmp.rename(txt_path)
    except Exception:
        if txt_tmp.exists():
            txt_tmp.unlink()
        raise

    return {
        "srt_path": None,
        "txt_path": str(txt_path),
        "text": normalized_text,
    }


def _transcribe_with_funasr(
    audio_path: Path,
    output_dir: Path,
    language: str,
    use_cuda: bool | None,
    allow_subprocess_fallback: bool = True,
) -> Dict[str, Any]:
    if allow_subprocess_fallback and _should_prefer_configured_funasr_python():
        logger.info(
            "检测到显式配置的 FUNASR_PYTHON，优先使用独立 FunASR 环境: %s",
            FUNASR_PYTHON,
        )
        return _run_funasr_via_subprocess(audio_path, output_dir, language, use_cuda)

    model_type = _normalize_funasr_model_type(FUNASR_MODEL_TYPE)
    try:
        model = _get_cached_funasr_model(use_cuda)
    except ModuleNotFoundError as exc:
        if allow_subprocess_fallback and "funasr" in str(exc).lower():
            return _run_funasr_via_subprocess(audio_path, output_dir, language, use_cuda)
        raise
    language_arg = language if language and language.lower() != "auto" else FUNASR_LANGUAGE

    generate_kwargs: Dict[str, Any] = {
        "input": str(audio_path),
        "cache": {},
        "batch_size_s": FUNASR_BATCH_SIZE_S,
    }
    hotword = _resolve_funasr_hotword(audio_path)
    if language_arg:
        generate_kwargs["language"] = language_arg
    if FUNASR_USE_ITN:
        generate_kwargs["use_itn"] = True
    if FUNASR_MERGE_VAD:
        generate_kwargs["merge_vad"] = True
        generate_kwargs["merge_length_s"] = FUNASR_MERGE_LENGTH_S
    if hotword:
        generate_kwargs["hotword"] = hotword
    if model_type == "sensevoice":
        generate_kwargs["output_timestamp"] = True

    logger.info(
        "开始执行 FunASR 转录: %s (type=%s, language=%s, batch_size_s=%d, hotword=%s, subtitle_words=%d, subtitle_chars=%d)",
        audio_path,
        model_type,
        language_arg,
        FUNASR_BATCH_SIZE_S,
        "on" if hotword else "off",
        max(1, FUNASR_SUBTITLE_MAX_WORDS),
        max(1, FUNASR_SUBTITLE_MAX_CHARS),
    )
    result = model.generate(**generate_kwargs)
    if not result:
        raise RuntimeError("FunASR 未返回任何字幕内容，请检查模型目录、音频文件和环境依赖")

    raw_text = str(result[0].get("text", "") or "")
    transcript_text = _clean_funasr_text(raw_text, model_type)
    if not transcript_text:
        raise RuntimeError("FunASR 返回结果为空，清洗后没有可用文本")

    if FUNASR_SAVE_RAW:
        raw_path = output_dir / f"{audio_path.stem}.funasr.raw.json"
        raw_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("FunASR 原始输出已写入 %s", raw_path)

    subtitle_segments = _funasr_segments_from_result(result[0], model_type)
    subtitle_segments = _filter_low_signal_funasr_segments(subtitle_segments)
    if subtitle_segments:
        output = _write_subtitle_outputs(audio_path, output_dir, subtitle_segments)
        logger.info("FunASR 字幕已写入 %s", output["srt_path"])
        return output

    if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
        transcript_text = transcript_text[:MAX_TRANSCRIPT_CHARS] + "\n\n[... 字幕文本已截断 ...]"

    logger.warning("FunASR 未返回可用时间戳，回退为纯文本输出")
    output = _write_text_only_output(audio_path, output_dir, transcript_text)
    logger.info("FunASR 文本已写入 %s", output["txt_path"])
    return output


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


def _resolve_sherpa_onnx_file(path_value: str) -> Path | None:
    if not path_value:
        return None
    return Path(path_value).expanduser().resolve()


def _resolve_sherpa_onnx_assets() -> Dict[str, Path]:
    model_type = _normalize_sherpa_onnx_model_type(SHERPA_ONNX_MODEL_TYPE)
    model_dir = _resolve_sherpa_onnx_file(SHERPA_ONNX_MODEL_DIR)
    model_path = _resolve_sherpa_onnx_file(SHERPA_ONNX_MODEL_PATH)
    encoder_path = _resolve_sherpa_onnx_file(SHERPA_ONNX_ENCODER_PATH)
    decoder_path = _resolve_sherpa_onnx_file(SHERPA_ONNX_DECODER_PATH)
    tokens_path = _resolve_sherpa_onnx_file(SHERPA_ONNX_TOKENS_PATH)
    vad_path = _resolve_sherpa_onnx_file(SHERPA_ONNX_VAD_MODEL)

    if model_type == "fire-red-asr":
        if model_dir is None:
            if encoder_path is None or decoder_path is None:
                raise RuntimeError(
                    "fire-red-asr 需要配置 SHERPA_ONNX_MODEL_DIR，或同时配置 "
                    "SHERPA_ONNX_ENCODER_PATH / SHERPA_ONNX_DECODER_PATH"
                )
        if encoder_path is None and model_dir is not None:
            encoder_candidates = [
                model_dir / "encoder.int8.onnx",
                model_dir / "encoder.onnx",
            ]
            encoder_candidates.extend(
                sorted(
                    p
                    for p in model_dir.glob("*encoder*.onnx")
                    if p.is_file() and "vad" not in p.name.lower()
                )
            )
            encoder_path = next(
                (p.resolve() for p in encoder_candidates if p.exists()), None
            )
        if decoder_path is None and model_dir is not None:
            decoder_candidates = [
                model_dir / "decoder.int8.onnx",
                model_dir / "decoder.onnx",
            ]
            decoder_candidates.extend(
                sorted(
                    p
                    for p in model_dir.glob("*decoder*.onnx")
                    if p.is_file() and "vad" not in p.name.lower()
                )
            )
            decoder_path = next(
                (p.resolve() for p in decoder_candidates if p.exists()), None
            )
        if encoder_path is None or decoder_path is None:
            raise FileNotFoundError(
                "未找到 fire-red-asr 所需的 encoder/decoder ONNX 文件"
            )
    else:
        if model_path is None:
            if model_dir is None:
                raise RuntimeError(
                    "sherpa-onnx 需要配置 SHERPA_ONNX_MODEL_DIR 或 SHERPA_ONNX_MODEL_PATH"
                )

            candidates = [
                model_dir / "model.int8.onnx",
                model_dir / "model.onnx",
            ]
            candidates.extend(
                sorted(
                    p
                    for p in model_dir.glob("*.onnx")
                    if p.is_file()
                    and "vad" not in p.name.lower()
                    and "encoder" not in p.name.lower()
                    and "decoder" not in p.name.lower()
                )
            )
            model_path = next((p.resolve() for p in candidates if p.exists()), None)
            if model_path is None:
                raise FileNotFoundError(f"未在 {model_dir} 中找到 sherpa-onnx 模型文件")

    if tokens_path is None:
        search_dirs: List[Path] = []
        for candidate in [model_path, encoder_path, decoder_path]:
            if candidate is not None and candidate.parent not in search_dirs:
                search_dirs.append(candidate.parent)
        if model_dir is not None and model_dir not in search_dirs:
            search_dirs.append(model_dir)
        for base_dir in search_dirs:
            candidate = base_dir / "tokens.txt"
            if candidate.exists():
                tokens_path = candidate.resolve()
                break
    if tokens_path is None or not tokens_path.exists():
        raise FileNotFoundError(
            "未找到 tokens.txt，请配置 SHERPA_ONNX_TOKENS_PATH 或将 tokens.txt 放到模型目录"
        )

    if vad_path is None:
        search_dirs = []
        for candidate in [model_path, encoder_path, decoder_path]:
            if candidate is not None and candidate.parent not in search_dirs:
                search_dirs.append(candidate.parent)
        if model_dir is not None and model_dir not in search_dirs:
            search_dirs.append(model_dir)
        for base_dir in search_dirs:
            candidate = base_dir / "silero_vad.onnx"
            if candidate.exists():
                vad_path = candidate.resolve()
                break
    if vad_path is None or not vad_path.exists():
        raise FileNotFoundError(
            "未找到 VAD 模型，请配置 SHERPA_ONNX_VAD_MODEL 指向 silero_vad.onnx"
        )

    assets: Dict[str, Path] = {
        "tokens": tokens_path,
        "vad": vad_path,
    }
    if model_path is not None:
        assets["model"] = model_path
    if encoder_path is not None:
        assets["encoder"] = encoder_path
    if decoder_path is not None:
        assets["decoder"] = decoder_path
    return assets


def _create_sherpa_recognizer():
    sherpa_onnx = importlib.import_module("sherpa_onnx")

    model_type = _normalize_sherpa_onnx_model_type(SHERPA_ONNX_MODEL_TYPE)
    assets = _resolve_sherpa_onnx_assets()
    kwargs: Dict[str, Any] = {
        "tokens": str(assets["tokens"]),
        "num_threads": SHERPA_ONNX_NUM_THREADS,
        "debug": False,
    }
    if model_type == "sense-voice":
        factory = sherpa_onnx.OfflineRecognizer.from_sense_voice
        kwargs.update(
            {
                "model": str(assets["model"]),
                "use_itn": SHERPA_ONNX_USE_ITN,
            }
        )
    elif model_type == "paraformer":
        factory = sherpa_onnx.OfflineRecognizer.from_paraformer
        kwargs.update(
            {
                "paraformer": str(assets["model"]),
                "sample_rate": SHERPA_ONNX_SAMPLE_RATE,
                "feature_dim": SHERPA_ONNX_FEATURE_DIM,
                "decoding_method": "greedy_search",
            }
        )
    elif model_type == "fire-red-asr":
        factory = sherpa_onnx.OfflineRecognizer.from_fire_red_asr
        kwargs.update(
            {
                "encoder": str(assets["encoder"]),
                "decoder": str(assets["decoder"]),
                "decoding_method": "greedy_search",
            }
        )
    elif model_type == "fire-red-asr-ctc":
        factory = sherpa_onnx.OfflineRecognizer.from_fire_red_asr_ctc
        kwargs.update(
            {
                "model": str(assets["model"]),
                "decoding_method": "greedy_search",
            }
        )
    else:
        raise RuntimeError(
            "SHERPA_ONNX_MODEL_TYPE 仅支持 "
            "sense-voice / paraformer / fire-red-asr / fire-red-asr-ctc，"
            f"收到: {SHERPA_ONNX_MODEL_TYPE}"
        )

    try:
        return factory(provider=SHERPA_ONNX_PROVIDER, **kwargs)
    except TypeError:
        logger.warning(
            "当前 sherpa-onnx 版本不支持 provider 参数，回退到默认 provider"
        )
        return factory(**kwargs)


def _get_cached_sherpa_recognizer():
    global _CACHED_SHERPA_RECOGNIZER, _CACHED_SHERPA_SIGNATURE
    model_type = _normalize_sherpa_onnx_model_type(SHERPA_ONNX_MODEL_TYPE)
    assets = _resolve_sherpa_onnx_assets()
    signature = (
        model_type,
        str(assets.get("model", "")),
        str(assets.get("encoder", "")),
        str(assets.get("decoder", "")),
        str(assets["tokens"]),
        str(assets["vad"]),
        SHERPA_ONNX_PROVIDER,
        SHERPA_ONNX_NUM_THREADS,
        SHERPA_ONNX_USE_ITN,
        SHERPA_ONNX_SAMPLE_RATE,
        SHERPA_ONNX_FEATURE_DIM,
    )
    if _CACHED_SHERPA_RECOGNIZER is not None and _CACHED_SHERPA_SIGNATURE == signature:
        logger.info("使用已缓存的 sherpa-onnx 识别器")
        return _CACHED_SHERPA_RECOGNIZER

    recognizer = _create_sherpa_recognizer()
    _CACHED_SHERPA_RECOGNIZER = recognizer
    _CACHED_SHERPA_SIGNATURE = signature
    logger.info("sherpa-onnx 识别器已缓存")
    return recognizer


def _build_vad():
    sherpa_onnx = importlib.import_module("sherpa_onnx")

    vad_path = _resolve_sherpa_onnx_assets()["vad"]
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(vad_path)
    config.silero_vad.threshold = SHERPA_ONNX_VAD_THRESHOLD
    config.silero_vad.min_silence_duration = SHERPA_ONNX_MIN_SILENCE
    config.silero_vad.min_speech_duration = SHERPA_ONNX_MIN_SPEECH
    config.silero_vad.max_speech_duration = SHERPA_ONNX_MAX_SPEECH
    config.sample_rate = SHERPA_ONNX_SAMPLE_RATE
    window_size = config.silero_vad.window_size
    vad = sherpa_onnx.VoiceActivityDetector(
        config,
        buffer_size_in_seconds=SHERPA_ONNX_VAD_BUFFER_SECONDS,
    )
    return vad, window_size


def _run_ffmpeg_pcm_stream(audio_path: Path) -> subprocess.Popen:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("未找到 ffmpeg，sherpa-onnx 后端需要 ffmpeg 做音频重采样")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(SHERPA_ONNX_SAMPLE_RATE),
        "-",
    ]
    logger.info("启动 ffmpeg 音频重采样: %s", audio_path)
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _decode_vad_segments(recognizer, vad, sample_rate: int) -> List[_SubtitleSegment]:
    segment_list: List[_SubtitleSegment] = []
    streams = []
    segments: List[_SubtitleSegment] = []

    while not vad.empty():
        speech = vad.front
        segments.append(
            _SubtitleSegment(
                start=speech.start / sample_rate,
                end=(speech.start + len(speech.samples)) / sample_rate,
                text="",
            )
        )
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, speech.samples)
        streams.append(stream)
        vad.pop()

    for stream in streams:
        recognizer.decode_stream(stream)

    for seg, stream in zip(segments, streams):
        text = _repair_mojibake_text((stream.result.text or "").strip())
        if not text or text in {".", "The."}:
            continue
        seg.text = text
        segment_list.append(seg)

    return segment_list


def _transcribe_with_sherpa_onnx(
    audio_path: Path,
    output_dir: Path,
    language: str,
) -> Dict[str, Any]:
    import numpy as np

    recognizer = _get_cached_sherpa_recognizer()
    vad, window_size = _build_vad()
    process = _run_ffmpeg_pcm_stream(audio_path)
    chunk_samples = max(1, int(SHERPA_ONNX_SAMPLE_RATE * SHERPA_ONNX_CHUNK_SECONDS))
    buffer = np.array([], dtype=np.float32)
    all_segments: List[_SubtitleSegment] = []

    logger.info(
        "开始执行 sherpa-onnx 转录: %s (model_type=%s, provider=%s, sample_rate=%d)",
        audio_path,
        SHERPA_ONNX_MODEL_TYPE,
        SHERPA_ONNX_PROVIDER,
        SHERPA_ONNX_SAMPLE_RATE,
    )

    try:
        while True:
            data = process.stdout.read(chunk_samples * 2)
            if not data:
                if buffer.size:
                    vad.accept_waveform(buffer)
                    buffer = np.array([], dtype=np.float32)
                vad.flush()
                break

            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
            if samples.size == 0:
                continue
            buffer = np.concatenate([buffer, samples])

            while buffer.size > window_size:
                vad.accept_waveform(buffer[:window_size])
                buffer = buffer[window_size:]

            all_segments.extend(
                _decode_vad_segments(
                    recognizer,
                    vad,
                    SHERPA_ONNX_SAMPLE_RATE,
                )
            )

        all_segments.extend(
            _decode_vad_segments(
                recognizer,
                vad,
                SHERPA_ONNX_SAMPLE_RATE,
            )
        )
    except Exception:
        if process.poll() is None:
            process.kill()
        raise
    finally:
        if process.stdout:
            process.stdout.close()
        stderr_output = ""
        if process.stderr:
            stderr_output = process.stderr.read().decode("utf-8", errors="ignore")
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(
                "ffmpeg 音频预处理失败: "
                f"{stderr_output.strip() or f'退出码 {return_code}'}"
            )

    if not all_segments:
        raise RuntimeError(
            "sherpa-onnx 未返回任何字幕内容，请检查音频是否为空、VAD 模型是否正确"
        )

    srt_path = output_dir / f"{audio_path.stem}.srt"
    txt_path = output_dir / f"{audio_path.stem}.txt"
    srt_tmp = output_dir / f"{audio_path.stem}.srt.tmp"
    txt_tmp = output_dir / f"{audio_path.stem}.txt.tmp"

    for tmp in [srt_tmp, txt_tmp]:
        if tmp.exists():
            tmp.unlink()

    try:
        _write_srt(all_segments, srt_tmp)
        transcript_text = _segments_to_text(all_segments)
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            transcript_text = (
                transcript_text[:MAX_TRANSCRIPT_CHARS]
                + "\n\n[... 字幕文本已截断，剩余内容请查看 SRT 文件 ...]"
            )
        txt_tmp.write_text(transcript_text, encoding="utf-8")

        if srt_path.exists():
            srt_path.unlink()
        if txt_path.exists():
            txt_path.unlink()
        srt_tmp.rename(srt_path)
        txt_tmp.rename(txt_path)
    except Exception:
        for tmp in [srt_tmp, txt_tmp]:
            if tmp.exists():
                tmp.unlink()
        raise

    logger.info("sherpa-onnx 字幕已写入 %s", srt_path)
    return {
        "srt_path": str(srt_path),
        "txt_path": str(txt_path),
        "text": transcript_text,
    }


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

    # 解码与稳定性参数
    best_of = int(os.getenv("FASTWHISPER_BEST_OF", "1"))
    patience = float(os.getenv("FASTWHISPER_PATIENCE", "1.0"))
    condition_on_previous_text = (
        os.getenv("FASTWHISPER_CONDITION_PREV", "false").lower() == "true"
    )
    repetition_penalty = float(os.getenv("FASTWHISPER_REPETITION_PENALTY", "1.08"))
    no_repeat_ngram_size = int(os.getenv("FASTWHISPER_NO_REPEAT_NGRAM_SIZE", "3"))
    compression_ratio_threshold = float(
        os.getenv("FASTWHISPER_COMPRESSION_RATIO_THRESHOLD", "2.2")
    )
    log_prob_threshold = float(os.getenv("FASTWHISPER_LOG_PROB_THRESHOLD", "-1.0"))
    no_speech_threshold = float(os.getenv("FASTWHISPER_NO_SPEECH_THRESHOLD", "0.6"))
    hallucination_silence_threshold_raw = (
        os.getenv("FASTWHISPER_HALLUCINATION_SILENCE_THRESHOLD", "1.5").strip()
    )
    hallucination_silence_threshold = (
        float(hallucination_silence_threshold_raw)
        if hallucination_silence_threshold_raw
        else None
    )
    drop_repeated_noise = (
        os.getenv("FASTWHISPER_DROP_REPEATED_NOISE", "true").lower() == "true"
    )

    # 批处理加速（batched whisper）
    use_batched = os.getenv("FASTWHISPER_BATCHED", "true").lower() == "true"
    batch_size = int(os.getenv("FASTWHISPER_BATCH_SIZE", "16"))  # 批大小

    logger.info(
        "开始执行 Faster-Whisper 转录: %s (beam_size=%d, batched=%s, batch_size=%d)",
        audio_path,
        beam_size,
        use_batched,
        batch_size,
    )

    # 使用 batched 模式加速（如果启用）
    if use_batched:
        try:
            from faster_whisper import BatchedInferencePipeline

            batched_model = BatchedInferencePipeline(model=model)
            batched_kwargs = {
                "beam_size": beam_size,
                "best_of": best_of,
                "patience": patience,
                "repetition_penalty": repetition_penalty,
                "no_repeat_ngram_size": no_repeat_ngram_size,
                "temperature": temperature,
                "compression_ratio_threshold": compression_ratio_threshold,
                "log_prob_threshold": log_prob_threshold,
                "no_speech_threshold": no_speech_threshold,
                "language": language_arg,
                "vad_filter": vad_filter,
                "vad_parameters": {"min_silence_duration_ms": vad_min_silence},
                "hallucination_silence_threshold": hallucination_silence_threshold,
                "initial_prompt": initial_prompt,
                "condition_on_previous_text": condition_on_previous_text,
            }
            try:
                segments, info = batched_model.transcribe(
                    str(audio_path),
                    batch_size=batch_size,
                    **batched_kwargs,
                )
            except TypeError as exc:
                logger.warning(
                    "Batched 模式当前版本不支持完整参数集，回退到兼容参数: %s",
                    exc,
                )
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
            repetition_penalty=repetition_penalty,
            no_repeat_ngram_size=no_repeat_ngram_size,
            temperature=temperature,
            compression_ratio_threshold=compression_ratio_threshold,
            log_prob_threshold=log_prob_threshold,
            no_speech_threshold=no_speech_threshold,
            language=language_arg,
            vad_filter=vad_filter,
            vad_parameters={"min_silence_duration_ms": vad_min_silence},
            hallucination_silence_threshold=hallucination_silence_threshold,
            initial_prompt=initial_prompt,
            condition_on_previous_text=condition_on_previous_text,
        )

    segment_list = list(segments)
    if drop_repeated_noise:
        segment_list = _filter_faster_whisper_segments(segment_list)
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


def _join_text_fragments(fragments: List[str]) -> str:
    pieces: List[str] = []
    for fragment in fragments:
        text = (fragment or "").strip()
        if not text:
            continue
        if not pieces:
            pieces.append(text)
            continue

        prev = pieces[-1]
        prev_last = prev[-1]
        curr_first = text[0]
        need_space = (
            prev_last.isascii()
            and prev_last.isalnum()
            and curr_first.isascii()
            and curr_first.isalnum()
        )
        if need_space:
            pieces.append(" " + text)
        else:
            pieces.append(text)
    return "".join(pieces).strip()


def _segments_to_text(segments: Iterable) -> str:
    paragraphs: List[str] = []
    current_fragments: List[str] = []
    current_chars = 0
    previous_end: float | None = None

    def flush_paragraph() -> None:
        nonlocal current_fragments, current_chars, previous_end
        paragraph = _join_text_fragments(current_fragments)
        if paragraph:
            paragraphs.append(paragraph)
        current_fragments = []
        current_chars = 0
        previous_end = None

    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            start = getattr(seg, "start", None)
            end = getattr(seg, "end", None)

            should_break = False
            if current_fragments:
                gap = None
                if previous_end is not None and start is not None:
                    gap = float(start) - float(previous_end)
                if gap is not None and gap >= 3.0:
                    should_break = True
                elif current_chars >= 220:
                    should_break = True

            if should_break:
                flush_paragraph()

            current_fragments.append(text)
            current_chars += len(text)
            if end is not None:
                previous_end = float(end)

    flush_paragraph()
    return "\n\n".join(paragraphs).strip()


def _format_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
