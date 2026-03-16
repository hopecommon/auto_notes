import unittest
from queue import Queue
from unittest.mock import Mock, patch

import auto_study_server as server


class ServerRegressionTests(unittest.TestCase):
    def setUp(self):
        server.task_status.clear()
        server.cancelled_tasks.clear()
        server.task_queue = Queue()

    def test_task_keys_share_resource_but_not_identity(self):
        resource_download = server.build_task_resource_key(
            "download", "Course A", "Lesson 1", "video"
        )
        resource_transcribe = server.build_task_resource_key(
            "transcribe", "Course A", "Lesson 1", "audio"
        )
        identity_download = server.build_task_identity_key(
            "download", "Course A", "Lesson 1", "video"
        )
        identity_transcribe = server.build_task_identity_key(
            "transcribe", "Course A", "Lesson 1", "audio"
        )

        self.assertEqual(resource_download, resource_transcribe)
        self.assertNotEqual(identity_download, identity_transcribe)

    def test_enqueue_managed_task_reuses_same_active_identity(self):
        payload = {
            "type": "note",
            "courseName": "Course A",
            "lessonTitle": "Lesson 1",
            "resourceKey": "course-a::lesson-1",
            "taskIdentity": "note::course-a::lesson-1",
        }

        with patch.object(server.task_queue, "put") as mocked_put:
            task_id_1, reused_1 = server.enqueue_managed_task(
                task_type="note",
                action_label="生成 AI 笔记",
                display_title="Course A · Lesson 1",
                task_payload=payload,
                extra={"courseName": "Course A", "lessonTitle": "Lesson 1"},
                resource_key=payload["resourceKey"],
                task_identity=payload["taskIdentity"],
            )
            task_id_2, reused_2 = server.enqueue_managed_task(
                task_type="note",
                action_label="生成 AI 笔记",
                display_title="Course A · Lesson 1",
                task_payload=payload,
                extra={"courseName": "Course A", "lessonTitle": "Lesson 1"},
                resource_key=payload["resourceKey"],
                task_identity=payload["taskIdentity"],
            )

        self.assertFalse(reused_1)
        self.assertTrue(reused_2)
        self.assertEqual(task_id_1, task_id_2)
        self.assertEqual(mocked_put.call_count, 1)
        self.assertEqual(
            server.task_status[task_id_1]["taskIdentity"], payload["taskIdentity"]
        )

    def test_process_task_download_uses_video_mode_and_overwrite_flag(self):
        processor = Mock()
        processor.step_download.return_value = {
            "success": True,
            "skipped": False,
            "exists": False,
            "video_path": "/tmp/sample.mp4",
            "media_type": "video",
        }

        task_id = "task-video-1"
        server.init_task_record(
            task_id,
            task_type="download",
            action_label="下载视频",
            display_title="Course A · Lesson 1",
        )

        server.process_task(
            {
                "id": task_id,
                "type": "download",
                "url": "https://example.com/video.m3u8",
                "courseName": "Course A",
                "lessonTitle": "Lesson 1",
                "fileType": "video",
                "overwriteExisting": True,
                "resourceKey": "course-a::lesson-1",
                "taskIdentity": "download::video::course-a::lesson-1",
            },
            processor,
        )

        processor.step_download.assert_called_once()
        kwargs = processor.step_download.call_args.kwargs
        self.assertEqual(kwargs["media_type"], "video")
        self.assertFalse(kwargs["skip_existing"])
        self.assertEqual(server.task_status[task_id]["status"], "completed")
        self.assertEqual(server.task_status[task_id]["fileType"], "video")
        self.assertEqual(server.task_status[task_id]["videoPath"], "/tmp/sample.mp4")

    def test_transcribe_route_forwards_overwrite_existing(self):
        client = server.app.test_client()

        with patch.object(server.task_queue, "put") as mocked_put:
            response = client.post(
                "/transcribe",
                json={
                    "urls": ["https://example.com/video.m3u8"],
                    "courseName": "Course A",
                    "lessonTitle": "Lesson 1",
                    "overwriteExisting": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        queued_task = mocked_put.call_args.args[0]
        self.assertTrue(queued_task["overwriteExisting"])


if __name__ == "__main__":
    unittest.main()
