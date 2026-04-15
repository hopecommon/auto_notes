import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)


def _probe_duration_seconds(audio_path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return float((proc.stdout or "").strip())


def _format_hhmmss(seconds: float) -> str:
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _extract_clip(source_audio: Path, clip_path: Path, start_seconds: float, duration_seconds: int) -> None:
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _format_hhmmss(start_seconds),
        "-t",
        str(duration_seconds),
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
    preprocess_filters: str,
    arnndn_model: str,
) -> dict:
    env = os.environ.copy()
    env["SAMPLE_AUDIO_PATH"] = str(audio_path)
    env["TRANSCRIBE_OUTPUT_DIR"] = str(output_dir)
    env["ASR_ENGINE"] = "funasr"
    env["ASR_PREPROCESS_AUDIO"] = "false" if not preprocess_filters else "true"
    env["ASR_PREPROCESS_FILTERS"] = preprocess_filters
    if arnndn_model:
        env["ASR_PREPROCESS_ARNNDN_MODEL"] = arnndn_model

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
        preview = txt_path.read_text(encoding="utf-8", errors="replace")[:1200]

    return {
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

    clip_duration_seconds = int(os.environ.get("ASR_COMPARE_CLIP_DURATION", "300"))
    duration_seconds = _probe_duration_seconds(source_audio)
    middle_start = max(0, (duration_seconds / 2) - (clip_duration_seconds / 2))
    end_start = max(0, duration_seconds - clip_duration_seconds)
    clip_specs = [
        ("start", 0.0),
        ("middle", middle_start),
        ("end", end_start),
    ]

    compare_root = Path(
        os.environ.get(
            "ASR_COMPARE_OUTPUT_DIR",
            source_audio.parent / "asr-denoise-compare",
        )
    )
    compare_root.mkdir(parents=True, exist_ok=True)

    arnndn_model = os.environ.get("ASR_COMPARE_ARNNDN_MODEL", os.environ.get("ASR_PREPROCESS_ARNNDN_MODEL", ""))
    variants = [
        ("raw", ""),
        ("eq-anlmdn", "highpass,lowpass,loudnorm,anlmdn"),
        ("eq-arnndn", "highpass,lowpass,loudnorm,arnndn"),
    ]

    clip_records = []
    for clip_label, start_seconds in clip_specs:
        clip_path = compare_root / "clips" / (
            f"{source_audio.stem}-{clip_label}-{_format_hhmmss(start_seconds).replace(':', '')}-{clip_duration_seconds}s.m4a"
        )
        _extract_clip(source_audio, clip_path, start_seconds, clip_duration_seconds)
        variant_results = []

        for variant_label, preprocess_filters in variants:
            output_dir = compare_root / variant_label / clip_label
            output_dir.mkdir(parents=True, exist_ok=True)
            result = _run_variant(
                python_exe=python_exe,
                audio_path=clip_path,
                output_dir=output_dir,
                preprocess_filters=preprocess_filters,
                arnndn_model=arnndn_model,
            )
            variant_results.append(
                {
                    "variant": variant_label,
                    "preprocess_filters": preprocess_filters,
                    **result,
                }
            )
            print(
                json.dumps(
                    {
                        "clip": clip_label,
                        "variant": variant_label,
                        "elapsed_seconds": result["elapsed_seconds"],
                        "returncode": result["returncode"],
                        "preview": result["preview"][:220],
                    },
                    ensure_ascii=False,
                )
            )

        clip_records.append(
            {
                "clip": clip_label,
                "clip_start": _format_hhmmss(start_seconds),
                "clip_path": str(clip_path),
                "results": variant_results,
            }
        )

    summary_path = compare_root / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "source_audio": str(source_audio),
                "duration_seconds": round(duration_seconds, 3),
                "clip_duration_seconds": clip_duration_seconds,
                "arnndn_model": arnndn_model,
                "clips": clip_records,
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
