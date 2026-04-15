import ctypes
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

"""
Deprecated experiment line.

Qwen3-ASR was kept for local A/B exploration, but it is not the recommended
mainline for this project because hour-long lecture audio is much slower than
the current FunASR / SenseVoiceSmall path on this machine.
"""


env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("RunQwenASRTest")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_AUDIO_PATH = PROJECT_ROOT / "data" / "samples" / "sample.m4a"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmarks" / "qwen-asr-test"
DEFAULT_MODEL_ROOT = PROJECT_ROOT / "data" / "models" / "qwen3-asr"
DEFAULT_MODEL_ID = "Qwen/Qwen3-ASR-0.6B"
DEFAULT_MODEL_DIR = DEFAULT_MODEL_ROOT / "Qwen3-ASR-0.6B"
DEFAULT_VENV_PYTHON = sys.executable


def _get_short_path(path: Path) -> str:
    path_str = str(path.resolve())
    if os.name != "nt":
        return path_str

    buffer_size = 4096
    buffer = ctypes.create_unicode_buffer(buffer_size)
    result = ctypes.windll.kernel32.GetShortPathNameW(path_str, buffer, buffer_size)
    if result == 0 or result > buffer_size:
        return path_str
    return buffer.value or path_str


def _resolve_dtype(dtype_name: str):
    import torch

    normalized = (dtype_name or "float16").strip().lower()
    mapping = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "half": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if normalized not in mapping:
        raise ValueError(f"不支持的 QWEN_ASR_DTYPE: {dtype_name}")
    return mapping[normalized]


def _ensure_model_dir(model_id: str, model_dir: Path, cache_dir: Path) -> Path:
    if model_dir.exists() and any(model_dir.iterdir()):
        logger.info("复用本地 Qwen3-ASR 模型目录: %s", model_dir)
        return model_dir

    logger.info("开始下载 Qwen3-ASR 模型: %s -> %s", model_id, model_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=model_id,
        local_dir=str(model_dir),
        cache_dir=str(cache_dir),
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    return model_dir


def _build_model(model_source: Path):
    import torch
    from qwen_asr import Qwen3ASRModel

    requested_device = os.environ.get("QWEN_ASR_DEVICE_MAP", "cuda:0").strip() or "cuda:0"
    if requested_device.startswith("cuda") and not torch.cuda.is_available():
        logger.warning("未检测到 CUDA，Qwen3-ASR 自动回退到 CPU")
        requested_device = "cpu"

    dtype = _resolve_dtype(os.environ.get("QWEN_ASR_DTYPE", "float16"))
    if requested_device == "cpu" and dtype in {torch.float16, torch.bfloat16}:
        dtype = torch.float32
    device_map = "auto" if requested_device.startswith("cuda") else requested_device

    max_batch_size = int(os.environ.get("QWEN_ASR_MAX_BATCH_SIZE", "4"))
    max_new_tokens = int(os.environ.get("QWEN_ASR_MAX_NEW_TOKENS", "512"))
    attn_implementation = (os.environ.get("QWEN_ASR_ATTN_IMPLEMENTATION", "") or "").strip()

    logger.info(
        "加载 Qwen3-ASR: model=%s device_map=%s dtype=%s max_batch_size=%d",
        model_source,
        device_map,
        dtype,
        max_batch_size,
    )
    kwargs: dict[str, Any] = {
        "dtype": dtype,
        "device_map": device_map,
        "low_cpu_mem_usage": True,
        "max_inference_batch_size": max_batch_size,
        "max_new_tokens": max_new_tokens,
    }
    if attn_implementation:
        kwargs["attn_implementation"] = attn_implementation

    return Qwen3ASRModel.from_pretrained(
        str(model_source),
        **kwargs,
    )


def _prepare_audio_for_test(sample_audio: Path, output_dir: Path) -> Path:
    test_seconds = int((os.environ.get("QWEN_ASR_TEST_SECONDS", "0") or "0").strip() or "0")
    if test_seconds <= 0:
        return sample_audio

    clip_path = output_dir / f"qwen-asr-test-{test_seconds}s.wav"
    safe_input = _get_short_path(sample_audio)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "0",
        "-t",
        str(test_seconds),
        "-i",
        safe_input,
        "-ar",
        "16000",
        "-ac",
        "1",
        str(clip_path),
    ]
    logger.info("裁剪测试音频片段: first %ss -> %s", test_seconds, clip_path)
    subprocess.run(cmd, check=True)
    return clip_path


def _serialize_result(result: Any) -> dict[str, Any]:
    return {
        "language": getattr(result, "language", ""),
        "text": getattr(result, "text", ""),
        "time_stamps": getattr(result, "time_stamps", None),
    }


def main():
    sample_audio = Path(os.environ.get("SAMPLE_AUDIO_PATH", str(DEFAULT_AUDIO_PATH)))
    output_dir = Path(os.environ.get("QWEN_ASR_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    model_root = Path(os.environ.get("QWEN_ASR_MODEL_ROOT", str(DEFAULT_MODEL_ROOT)))
    model_id = os.environ.get("QWEN_ASR_MODEL_ID", DEFAULT_MODEL_ID)
    model_dir = Path(os.environ.get("QWEN_ASR_MODEL_DIR", str(DEFAULT_MODEL_DIR)))
    cache_dir = model_root / "hf-cache"
    language = os.environ.get("QWEN_ASR_LANGUAGE", "").strip() or None
    context = os.environ.get("QWEN_ASR_CONTEXT", "")

    if not sample_audio.exists():
        raise FileNotFoundError(f"音频文件不存在: {sample_audio}")

    output_dir.mkdir(parents=True, exist_ok=True)
    model_root.mkdir(parents=True, exist_ok=True)

    test_audio = _prepare_audio_for_test(sample_audio, output_dir)
    local_model_dir = _ensure_model_dir(model_id=model_id, model_dir=model_dir, cache_dir=cache_dir)
    logger.info("模型目录已就绪，开始加载模型")
    model = _build_model(local_model_dir)

    safe_audio_path = _get_short_path(test_audio)
    logger.info("开始转录: %s", test_audio)
    start = time.perf_counter()
    results = model.transcribe(
        audio=safe_audio_path,
        context=context,
        language=language,
        return_time_stamps=False,
    )
    elapsed = time.perf_counter() - start

    if not results:
        raise RuntimeError("Qwen3-ASR 未返回任何结果")

    result = results[0]
    text = (getattr(result, "text", "") or "").strip()
    if not text:
        raise RuntimeError("Qwen3-ASR 返回文本为空")

    stem = sample_audio.stem
    txt_path = output_dir / f"{stem}.qwen3-asr.txt"
    raw_path = output_dir / f"{stem}.qwen3-asr.raw.json"
    meta_path = output_dir / f"{stem}.qwen3-asr.meta.json"

    txt_path.write_text(text, encoding="utf-8")
    raw_path.write_text(
        json.dumps([_serialize_result(item) for item in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps(
            {
                "model_id": model_id,
                "model_dir": str(local_model_dir),
                "cache_dir": str(cache_dir),
                "language": getattr(result, "language", ""),
                "forced_language": language,
                "context": context,
                "elapsed_seconds": elapsed,
                "python": os.environ.get("QWEN_ASR_PYTHON", DEFAULT_VENV_PYTHON),
                "text_preview": text[:500],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info("转录完成，用时 %.2fs", elapsed)
    logger.info("TXT: %s", txt_path)
    logger.info("RAW: %s", raw_path)
    logger.info("META: %s", meta_path)
    logger.info("识别语言: %s", getattr(result, "language", ""))
    logger.info("文本预览: %s", text[:500])


if __name__ == "__main__":
    main()
