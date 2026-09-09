# -*- coding: utf-8 -*-
"""저주기 MediaPipe Pose 보조 엔진.

손 제스처를 분류하지 않는다. 어깨·팔꿈치·손목이 화면에 잡히는지를
관찰하기 위한 보조 신호이며, 전체 제스처 루프의 FPS를 지키기 위해
축소 프레임에서 최대 지정 FPS로만 추론한다.
"""
from pathlib import Path
import time


class BodyPoseEngine:
    """PoseLandmarker(VIDEO) 래퍼. 실패 시 None을 반환한다."""

    def __init__(self, model_path, max_fps=10.0, max_width=640):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            PoseLandmarker,
            PoseLandmarkerOptions,
            RunningMode,
        )

        self._mp = mp
        self.max_fps = float(max_fps)
        self.max_width = int(max_width)
        self._min_interval = 1.0 / self.max_fps
        self._last_run = -float("inf")
        self._last_ts = 0
        self.last_landmarks = None
        self.last_infer_ms = 0.0

        # 한글 경로에서 네이티브 로더 문제가 나지 않도록 바이트로 전달한다.
        model_buf = Path(model_path).read_bytes()
        self.landmarker = PoseLandmarker.create_from_options(
            PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=model_buf),
                running_mode=RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=0.4,
                min_pose_presence_confidence=0.4,
                min_tracking_confidence=0.4,
                output_segmentation_masks=False,
            )
        )

    def update(self, frame_bgr, now=None):
        """최대 max_fps로만 Pose를 갱신하고, 가장 최근 결과를 반환한다."""
        import cv2

        now = time.monotonic() if now is None else now
        if now - self._last_run < self._min_interval:
            return self.last_landmarks
        self._last_run = now

        height, width = frame_bgr.shape[:2]
        if width > self.max_width:
            scale = self.max_width / width
            small = cv2.resize(frame_bgr, (self.max_width, max(1, int(height * scale))))
        else:
            small = frame_bgr

        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        timestamp_ms = max(int(now * 1000), self._last_ts + 1)
        self._last_ts = timestamp_ms
        start = time.perf_counter()
        result = self.landmarker.detect_for_video(image, timestamp_ms)
        self.last_infer_ms = (time.perf_counter() - start) * 1000

        if result.pose_landmarks:
            self.last_landmarks = [(p.x, p.y, p.visibility or 0.0)
                                   for p in result.pose_landmarks[0]]
        else:
            self.last_landmarks = None
        return self.last_landmarks

    def close(self):
        self.landmarker.close()
