import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)


def _extract_clip(source_audio: Path, clip_path: Path, start: str, duration: str) -> None:
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        start,
        "-t",
        duration,
        "-i",
        str(source_audio),
        "-c:a",
        "aac",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(clip_path),
    ]
    subprocess.run(cmd, check=True)


def _run_variant(
    *,
    python_exe: Path,
    audio_path: Path,
    output_dir: Path,
    engine: str,
    preprocess: bool,
    preprocess_filters: str,
    fastwhisper_batched: bool,
) -> dict:
    env = os.environ.copy()
    env["SAMPLE_AUDIO_PATH"] = str(audio_path)
    env["TRANSCRIBE_OUTPUT_DIR"] = str(output_dir)
    env["ASR_ENGINE"] = engine
    env["ASR_PREPROCESS_AUDIO"] = "true" if preprocess else "false"
    env["ASR_PREPROCESS_FILTERS"] = preprocess_filters
    env["FASTWHISPER_BATCHED"] = "true" if fastwhisper_batched else "false"

    start = time.perf_counter()
    proc = subprocess.run(
        [str(python_exe), "run_transcribe_test.py"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - start

    txt_path = output_dir / f"{audio_path.stem}.txt"
    preview = ""
    if txt_path.exists():
        preview = txt_path.read_text(encoding="utf-8", errors="replace")[:800]

    return {
        "engine": engine,
        "preprocess": preprocess,
        "elapsed_seconds": round(elapsed, 2),
        "returncode": proc.returncode,
        "txt_path": str(txt_path),
        "preview": preview,
        "stdout_tail": (proc.stdout or "")[-1200:],
        "stderr_tail": (proc.stderr or "")[-1200:],
    }


def main() -> int:
    source_audio = Path(
        os.environ.get(
            "ASR_COMPARE_SOURCE_AUDIO",
            os.environ.get("SAMPLE_AUDIO_PATH", ""),
        )
    )
    if not source_audio.exists():
        raise FileNotFoundError(f"源音频不存在: {source_audio}")

    python_exe = Path(os.environ.get("ASR_COMPARE_PYTHON", sys.executable))
    if not python_exe.exists():
        raise FileNotFoundError(f"未找到可执行 Python: {python_exe}")

    compare_root = Path(
        os.environ.get(
            "ASR_COMPARE_OUTPUT_DIR",
            source_audio.parent / "asr-preprocess-compare",
        )
    )
    start = os.environ.get("ASR_COMPARE_CLIP_START", "00:05:30")
    duration = os.environ.get("ASR_COMPARE_CLIP_DURATION", "300")
    preprocess_filters = os.environ.get(
        "ASR_COMPARE_PREPROCESS_FILTERS",
        "highpass,lowpass,loudnorm,afftdn",
    )

    compare_root.mkdir(parents=True, exist_ok=True)
    clip_path = compare_root / f"{source_audio.stem}-clip-{start.replace(':', '')}-{duration}s.m4a"
    _extract_clip(source_audio, clip_path, start, duration)

    variants = [
        ("funasr", False, True),
        ("funasr", True, True),
        ("faster-whisper", False, False),
        ("faster-whisper", True, False),
    ]

    results = []
    for engine, preprocess, fastwhisper_batched in variants:
        label = f"{engine}-{'pre' if preprocess else 'raw'}"
        output_dir = compare_root / label
        output_dir.mkdir(parents=True, exist_ok=True)
        result = _run_variant(
            python_exe=python_exe,
            audio_path=clip_path,
            output_dir=output_dir,
            engine=engine,
            preprocess=preprocess,
            preprocess_filters=preprocess_filters,
            fastwhisper_batched=fastwhisper_batched,
        )
        results.append(result)
        print(
            json.dumps(
                {
                    "label": label,
                    "elapsed_seconds": result["elapsed_seconds"],
                    "returncode": result["returncode"],
                    "txt_path": result["txt_path"],
                    "preview": result["preview"][:200],
                },
                ensure_ascii=False,
            )
        )

    summary_path = compare_root / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "source_audio": str(source_audio),
                "clip_path": str(clip_path),
                "clip_start": start,
                "clip_duration_seconds": duration,
                "preprocess_filters": preprocess_filters,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"summary={summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
