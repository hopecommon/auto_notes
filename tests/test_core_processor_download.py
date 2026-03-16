import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import Mock, patch

import core_processor


class CoreProcessorDownloadTests(unittest.TestCase):
    def make_processor(self):
        processor = core_processor.CoreProcessor.__new__(core_processor.CoreProcessor)
        processor.download_media = Mock(return_value=True)
        processor.check_existing_files = Mock()
        return processor

    def test_step_download_writes_video_file_for_video_tasks(self):
        processor = self.make_processor()
        processor.check_existing_files.return_value = {
            "formatted_name": "lesson-1",
            "audio_complete": False,
            "audio_path": None,
            "video_complete": False,
            "video_path": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(core_processor, "DOWNLOAD_DIR", tmpdir):
                result = processor.step_download(
                    url="https://example.com/video.m3u8",
                    course_name="Course A",
                    lesson_title="Lesson 1",
                    skip_existing=False,
                    media_type="video",
                )

        self.assertTrue(result["success"])
        self.assertTrue(result["video_path"].endswith(".mp4"))
        processor.download_media.assert_called_once()
        args, kwargs = processor.download_media.call_args
        self.assertFalse(kwargs["audio_only"])
        self.assertTrue(args[1].endswith(".mp4"))

    def test_step_download_skips_existing_audio_when_requested(self):
        processor = self.make_processor()
        processor.check_existing_files.return_value = {
            "formatted_name": "lesson-1",
            "audio_complete": True,
            "audio_path": "/tmp/lesson-1.m4a",
            "video_complete": False,
            "video_path": None,
        }

        result = processor.step_download(
            url="https://example.com/video.m3u8",
            course_name="Course A",
            lesson_title="Lesson 1",
            skip_existing=True,
            media_type="audio",
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["audio_path"], "/tmp/lesson-1.m4a")
        processor.download_media.assert_not_called()

    def test_check_existing_files_reports_video_path(self):
        processor = core_processor.CoreProcessor.__new__(core_processor.CoreProcessor)
        processor.parse_metadata = Mock(return_value="lesson-1")
        processor.sanitize_filename = lambda name: name

        with tempfile.TemporaryDirectory() as download_dir, tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as vault_dir:
            video_path = Path(download_dir) / "lesson-1.mp4"
            video_path.write_bytes(b"x" * (1024 * 1024 + 10))

            with patch.object(core_processor, "DOWNLOAD_DIR", download_dir), patch.object(
                core_processor, "TEMP_DIR", temp_dir
            ), patch.object(core_processor, "OBSIDIAN_VAULT_PATH", vault_dir):
                result = processor.check_existing_files("Course A", "Lesson 1")

        self.assertTrue(result["video_complete"])
        self.assertEqual(result["video_path"], str(video_path))

    def test_process_with_gemini_text_uses_openai_provider_when_configured(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": "openai note body"}}]
        }

        session = Mock()
        session.post.return_value = response

        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://api.example.com/v1",
                "OPENAI_MODEL": "test-model",
                "OPENAI_MAX_RETRIES": "1",
                "OPENAI_DISABLE_PROXY": "1",
                "OPENAI_TIMEOUT": "12",
            },
            clear=False,
        ), patch.object(
            core_processor.CoreProcessor,
            "_cleanup_residual_tmp_files",
            lambda self: None,
        ), patch.object(core_processor.requests, "Session", return_value=session):
            processor = core_processor.CoreProcessor()
            result = processor.process_with_gemini_text("字幕内容")

        self.assertEqual(processor.ai_provider, "openai")
        self.assertEqual(result, "openai note body")
        session.post.assert_called_once()
        self.assertEqual(
            session.post.call_args.kwargs["json"]["model"], "test-model"
        )


if __name__ == "__main__":
    unittest.main()
