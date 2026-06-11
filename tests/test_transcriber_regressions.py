import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import transcriber


class TranscriberRegressionTests(unittest.TestCase):
    def test_get_env_stripped_treats_blank_as_empty(self):
        with patch.dict("os.environ", {"FASTWHISPER_LOCAL_DIR": "   "}, clear=False):
            self.assertEqual(transcriber._get_env_stripped("FASTWHISPER_LOCAL_DIR"), "")

    def test_filter_faster_whisper_repeated_segments_keeps_first_two(self):
        segments = [
            SimpleNamespace(text="噪声噪声噪声测试", start=0.0, end=1.0),
            SimpleNamespace(text="噪声噪声噪声测试", start=1.0, end=2.0),
            SimpleNamespace(text="噪声噪声噪声测试", start=2.0, end=3.0),
            SimpleNamespace(text="正常正文", start=3.0, end=4.0),
        ]

        filtered = transcriber._filter_faster_whisper_segments(segments)

        self.assertEqual(
            [segment.text for segment in filtered],
            ["噪声噪声噪声测试", "噪声噪声噪声测试", "正常正文"],
        )

    def test_filter_faster_whisper_repeated_pattern_segment(self):
        segments = [
            SimpleNamespace(text="abcabcabcabcabcabc", start=0.0, end=1.0),
            SimpleNamespace(text="这是正常句子", start=1.0, end=2.0),
        ]

        filtered = transcriber._filter_faster_whisper_segments(segments)

        self.assertEqual([segment.text for segment in filtered], ["这是正常句子"])

    def test_normalize_sherpa_onnx_model_type_supports_fire_red_aliases(self):
        self.assertEqual(
            transcriber._normalize_sherpa_onnx_model_type("firered"),
            "fire-red-asr",
        )
        self.assertEqual(
            transcriber._normalize_sherpa_onnx_model_type("fire-red-ctc"),
            "fire-red-asr-ctc",
        )

    def test_segments_to_text_keeps_timestamps_per_segment(self):
        segments = [
            SimpleNamespace(text="第一段", start=1.234, end=2.0),
            SimpleNamespace(text="第二段", start=61.0, end=62.5),
        ]

        text = transcriber._segments_to_text(segments)

        self.assertEqual(
            text,
            "[00:00:01,234] 第一段\n[00:01:01,000] 第二段",
        )

    def test_write_srt_uses_standard_numbered_timestamp_blocks(self):
        segments = [
            SimpleNamespace(text="第一段", start=1.234, end=2.0),
            SimpleNamespace(text="第二段", start=61.0, end=62.5),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "sample.srt"
            transcriber._write_srt(segments, output_path)
            content = output_path.read_text(encoding="utf-8")

        self.assertEqual(
            content,
            "1\n"
            "00:00:01,234 --> 00:00:02,000\n"
            "第一段\n\n"
            "2\n"
            "00:01:01,000 --> 00:01:02,500\n"
            "第二段\n\n",
        )

    def test_normalize_subtitle_segments_splits_long_segments(self):
        segment = SimpleNamespace(
            text="稍微讲一下后面的安排我们冲掉一次课所以我们有三次课"
            "从下节课开始我们先讲基础内容然后再讲应用场景",
            start=0.0,
            end=100.0,
        )

        normalized = transcriber._normalize_subtitle_segments([segment])

        self.assertGreater(len(normalized), 1)
        self.assertEqual(normalized[0].start, 0.0)
        self.assertAlmostEqual(normalized[-1].end, 100.0)
        self.assertTrue(all(seg.text for seg in normalized))
        self.assertTrue(
            all((seg.end - seg.start) <= transcriber.SUBTITLE_MAX_SECONDS + 0.5 for seg in normalized)
        )
        text = transcriber._segments_to_text(normalized)
        self.assertIn("[00:00:00,000]", text)
        self.assertIn("[00:00:", text)

    def test_normalize_subtitle_segments_merges_adjacent_short_segments(self):
        segments = [
            SimpleNamespace(text="第一小段", start=0.0, end=1.0),
            SimpleNamespace(text="第二小段", start=1.2, end=2.0),
            SimpleNamespace(text="第三小段", start=2.1, end=3.0),
        ]

        normalized = transcriber._normalize_subtitle_segments(segments)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].start, 0.0)
        self.assertEqual(normalized[0].end, 3.0)
        self.assertEqual(normalized[0].text, "第一小段第二小段第三小段")


if __name__ == "__main__":
    unittest.main()
