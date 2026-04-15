import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

import transcriber


env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("BenchmarkTranscribe")


def _run_once(audio_path: Path, output_dir: Path, engine: str):
    original_engine = transcriber.ASR_ENGINE
    transcriber.ASR_ENGINE = engine
    start = time.perf_counter()
    try:
        result = transcriber.transcribe_audio(
            audio_path=str(audio_path),
            output_dir=str(output_dir),
            language="auto",
        )
        elapsed = time.perf_counter() - start
        return {
            "engine": engine,
            "elapsed": elapsed,
            "srt_path": result.get("srt_path"),
            "txt_path": result.get("txt_path"),
            "text": result.get("text", ""),
        }
    finally:
        transcriber.ASR_ENGINE = original_engine


if __name__ == "__main__":
    sample_audio = Path(
        os.environ.get("SAMPLE_AUDIO_PATH", "data/samples/sample.m4a")
    )
    output_dir = Path(
        os.environ.get("TRANSCRIBE_OUTPUT_DIR", "data/benchmarks")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    if not sample_audio.exists():
        raise FileNotFoundError(
            "缺少示例音频。请设置 SAMPLE_AUDIO_PATH，或将测试音频放到 "
            f"{sample_audio}。"
        )

    engines_raw = os.environ.get("BENCHMARK_ENGINES", "sherpa-onnx,faster-whisper")
    engines = [item.strip() for item in engines_raw.split(",") if item.strip()]
    results = []

    for engine in engines:
        logger.info("开始基准转录: engine=%s", engine)
        try:
            result = _run_once(sample_audio, output_dir, engine)
            results.append(result)
            logger.info(
                "完成: engine=%s elapsed=%.2fs txt=%s",
                engine,
                result["elapsed"],
                result["txt_path"],
            )
        except Exception as exc:
            logger.exception("转录失败: engine=%s error=%s", engine, exc)

    logger.info("基准测试结束，共成功 %d/%d 个引擎", len(results), len(engines))
    for result in results:
        preview = result["text"][:200].replace("\n", " ")
        logger.info(
            "[%s] %.2fs | %s | %s",
            result["engine"],
            result["elapsed"],
            result["txt_path"],
            preview,
        )
