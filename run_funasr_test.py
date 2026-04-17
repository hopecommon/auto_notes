import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv


env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("RunFunASRTest")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_AUDIO_PATH = PROJECT_ROOT / "data" / "samples" / "sample.m4a"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmarks" / "funasr-test"
DEFAULT_MODEL_DIR = PROJECT_ROOT / "data" / "models" / "funasr" / "SenseVoiceSmall"
DEFAULT_VAD_DIR = PROJECT_ROOT / "data" / "models" / "funasr" / "speech_fsmn_vad"


def main():
    sample_audio = Path(os.environ.get("SAMPLE_AUDIO_PATH", str(DEFAULT_AUDIO_PATH)))
    model_dir = Path(os.environ.get("FUNASR_MODEL_DIR", str(DEFAULT_MODEL_DIR)))
    vad_dir = Path(os.environ.get("FUNASR_VAD_DIR", str(DEFAULT_VAD_DIR)))
    output_dir = Path(os.environ.get("FUNASR_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    language = os.environ.get("FUNASR_LANGUAGE", "auto")
    batch_size_s = int(os.environ.get("FUNASR_BATCH_SIZE_S", "60"))
    merge_length_s = int(os.environ.get("FUNASR_MERGE_LENGTH_S", "15"))

    if not sample_audio.exists():
        raise FileNotFoundError(f"音频文件不存在: {sample_audio}")
    if not model_dir.exists():
        raise FileNotFoundError(f"FunASR 模型目录不存在: {model_dir}")
    if not vad_dir.exists():
        raise FileNotFoundError(f"FunASR VAD 目录不存在: {vad_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    logger.info("加载 FunASR: model=%s vad=%s device=%s", model_dir, vad_dir, device)
    model = AutoModel(
        model=str(model_dir),
        vad_model=str(vad_dir),
        vad_kwargs={"max_single_segment_time": 30000},
        trust_remote_code=False,
        device=device,
    )

    logger.info("开始转录: %s", sample_audio)
    start = time.perf_counter()
    result = model.generate(
        input=str(sample_audio),
        cache={},
        language=language,
        use_itn=True,
        batch_size_s=batch_size_s,
        merge_vad=True,
        merge_length_s=merge_length_s,
    )
    elapsed = time.perf_counter() - start

    if not result:
        raise RuntimeError("FunASR 未返回任何结果")

    processed_text = rich_transcription_postprocess(result[0].get("text", ""))

    raw_path = output_dir / f"{sample_audio.stem}.funasr.raw.json"
    txt_path = output_dir / f"{sample_audio.stem}.funasr.txt"
    raw_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(processed_text, encoding="utf-8")

    logger.info("转录完成，用时 %.2fs", elapsed)
    logger.info("TXT: %s", txt_path)
    logger.info("RAW: %s", raw_path)
    logger.info("文本预览: %s", processed_text[:500])


if __name__ == "__main__":
    main()
