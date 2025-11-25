import logging
from pathlib import Path

from dotenv import load_dotenv

from transcriber import transcribe_audio

# load environment variables from .env so FASTWHISPER_LOCAL_DIR is picked up
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
        logger.info("开始测试转录（会打印详细日志和异常堆栈）")
        result = transcribe_audio(
            audio_path=r"D:\Download\SJTU_Courses\程序语言与编译原理-1017-0855.m4a",
            output_dir=r"D:\Download\SJTU_Courses",
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

