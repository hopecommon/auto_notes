import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from transcriber import transcribe_audio

# Load environment variables from .env for local developer overrides.
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path)

# 启用详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

if __name__ == "__main__":
    logger = logging.getLogger("TestTranscribe")
    try:
        sample_audio = Path(
            os.environ.get("SAMPLE_AUDIO_PATH", "data/samples/sample.m4a")
        )
        output_dir = Path(
            os.environ.get("TRANSCRIBE_OUTPUT_DIR", "data/downloads")
        )

        if not sample_audio.exists():
            raise FileNotFoundError(
                "缺少示例音频。请设置 SAMPLE_AUDIO_PATH，或将测试音频放到 "
                f"{sample_audio}。"
            )

        logger.info("开始测试转录（会打印详细日志和异常堆栈）")
        result = transcribe_audio(
            audio_path=str(sample_audio),
            output_dir=str(output_dir),
            language="auto",
        )
        logger.info("测试转录成功！结果: %s", result)
        logger.info("SRT文件: %s", result.get("srt_path"))
        logger.info("TXT文件: %s", result.get("txt_path"))
        logger.info("字幕内容前500字符: %s", result.get("text", "")[:500])
    except Exception as exc:
        logger.error("测试转录失败！")
        import traceback
        traceback.print_exc()
        raise
