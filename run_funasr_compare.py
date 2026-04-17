import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("RunFunASRCompare")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_AUDIO_PATH = PROJECT_ROOT / "data" / "samples" / "sample.m4a"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmarks" / "funasr-compare"
DEFAULT_SENSEVOICE_DIR = PROJECT_ROOT / "data" / "models" / "funasr" / "SenseVoiceSmall"
DEFAULT_PARAFORMER_DIR = PROJECT_ROOT / "data" / "models" / "funasr" / "paraformer-large"
DEFAULT_VAD_DIR = PROJECT_ROOT / "data" / "models" / "funasr" / "speech_fsmn_vad"
DEFAULT_PUNC_DIR = PROJECT_ROOT / "data" / "models" / "funasr" / "punc_ct-transformer"


@dataclass
class CompareConfig:
    name: str
    model_dir: Path
    vad_dir: Path | None = None
    punc_dir: Path | None = None
    language: str | None = None
    use_itn: bool = True
    merge_vad: bool = False
    merge_length_s: int = 15
    batch_size_s: int = 60
    hotword: str | None = None
    is_sensevoice: bool = False


def _sanitize_label(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-")


def _write_result(output_dir: Path, audio_stem: str, config: CompareConfig, result: list[dict[str, Any]], text: str, elapsed: float):
    label = _sanitize_label(config.name)
    txt_path = output_dir / f"{audio_stem}.{label}.txt"
    raw_path = output_dir / f"{audio_stem}.{label}.raw.json"
    meta_path = output_dir / f"{audio_stem}.{label}.meta.json"

    txt_path.write_text(text, encoding="utf-8")
    raw_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps(
            {
                "name": config.name,
                "elapsed_seconds": elapsed,
                "model_dir": str(config.model_dir),
                "vad_dir": str(config.vad_dir) if config.vad_dir else None,
                "punc_dir": str(config.punc_dir) if config.punc_dir else None,
                "language": config.language,
                "use_itn": config.use_itn,
                "merge_vad": config.merge_vad,
                "merge_length_s": config.merge_length_s,
                "batch_size_s": config.batch_size_s,
                "hotword": config.hotword,
                "text_preview": text[:500],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "name": config.name,
        "elapsed_seconds": elapsed,
        "txt_path": str(txt_path),
        "raw_path": str(raw_path),
        "meta_path": str(meta_path),
        "text_preview": text[:300],
    }


def _build_model(config: CompareConfig, device: str):
    from funasr import AutoModel

    kwargs: dict[str, Any] = {
        "model": str(config.model_dir),
        "trust_remote_code": False,
        "device": device,
        "disable_update": True,
    }
    if config.vad_dir:
        kwargs["vad_model"] = str(config.vad_dir)
        kwargs["vad_kwargs"] = {"max_single_segment_time": 30000}
    if config.punc_dir:
        kwargs["punc_model"] = str(config.punc_dir)
    return AutoModel(**kwargs)


def _run_config(sample_audio: Path, output_dir: Path, config: CompareConfig):
    import torch

    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    logger.info("开始模型对比: %s device=%s", config.name, device)
    model = _build_model(config, device)

    generate_kwargs: dict[str, Any] = {
        "input": str(sample_audio),
        "cache": {},
        "batch_size_s": config.batch_size_s,
    }
    if config.language:
        generate_kwargs["language"] = config.language
    if config.use_itn:
        generate_kwargs["use_itn"] = True
    if config.merge_vad:
        generate_kwargs["merge_vad"] = True
        generate_kwargs["merge_length_s"] = config.merge_length_s
    if config.hotword:
        generate_kwargs["hotword"] = config.hotword

    start = time.perf_counter()
    result = model.generate(**generate_kwargs)
    elapsed = time.perf_counter() - start

    if not result:
        raise RuntimeError(f"{config.name} 未返回任何结果")

    raw_text = result[0].get("text", "")
    text = rich_transcription_postprocess(raw_text) if config.is_sensevoice else raw_text
    if isinstance(text, list):
        text = "\n".join(str(item) for item in text)
    text = str(text).strip()

    output = _write_result(output_dir, sample_audio.stem, config, result, text, elapsed)
    logger.info(
        "完成模型对比: %s elapsed=%.2fs txt=%s",
        config.name,
        elapsed,
        output["txt_path"],
    )
    return output


def main():
    sample_audio = Path(os.environ.get("SAMPLE_AUDIO_PATH", str(DEFAULT_AUDIO_PATH)))
    output_dir = Path(os.environ.get("FUNASR_COMPARE_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    output_dir.mkdir(parents=True, exist_ok=True)

    if not sample_audio.exists():
        raise FileNotFoundError(f"音频文件不存在: {sample_audio}")

    sensevoice_dir = Path(os.environ.get("FUNASR_MODEL_DIR", str(DEFAULT_SENSEVOICE_DIR)))
    paraformer_dir = Path(os.environ.get("FUNASR_PARAFORMER_DIR", str(DEFAULT_PARAFORMER_DIR)))
    vad_dir = Path(os.environ.get("FUNASR_VAD_DIR", str(DEFAULT_VAD_DIR)))
    punc_dir = Path(os.environ.get("FUNASR_PUNC_DIR", str(DEFAULT_PUNC_DIR)))
    hotword = os.environ.get("FUNASR_HOTWORD", "").strip() or None

    configs = [
        CompareConfig(
            name="sensevoice-small",
            model_dir=sensevoice_dir,
            vad_dir=vad_dir,
            language=os.environ.get("FUNASR_SENSEVOICE_LANGUAGE", "auto"),
            use_itn=True,
            merge_vad=True,
            merge_length_s=int(os.environ.get("FUNASR_SENSEVOICE_MERGE_LENGTH_S", "15")),
            batch_size_s=int(os.environ.get("FUNASR_SENSEVOICE_BATCH_SIZE_S", "60")),
            is_sensevoice=True,
        ),
        CompareConfig(
            name="paraformer-large",
            model_dir=paraformer_dir,
            vad_dir=vad_dir,
            punc_dir=punc_dir,
            use_itn=True,
            batch_size_s=int(os.environ.get("FUNASR_PARAFORMER_BATCH_SIZE_S", "300")),
            hotword=hotword,
        ),
    ]

    summary: list[dict[str, Any]] = []
    for config in configs:
        if not config.model_dir.exists():
            raise FileNotFoundError(f"模型目录不存在: {config.model_dir}")
        if config.vad_dir and not config.vad_dir.exists():
            raise FileNotFoundError(f"VAD 目录不存在: {config.vad_dir}")
        if config.punc_dir and not config.punc_dir.exists():
            raise FileNotFoundError(f"PUNC 目录不存在: {config.punc_dir}")
        summary.append(_run_config(sample_audio, output_dir, config))

    summary_path = output_dir / f"{sample_audio.stem}.compare.summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("对比完成，汇总文件: %s", summary_path)


if __name__ == "__main__":
    main()
