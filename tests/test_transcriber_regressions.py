import unittest
from types import SimpleNamespace

import transcriber


class TranscriberRegressionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
