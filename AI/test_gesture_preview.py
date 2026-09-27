"""GesturePreview(cam_preview_*) 유닛테스트 — 워커 스레드·큐 백프레셔 포함.

카메라·BE 서버 없이 검증한다. 워커가 별도 스레드라 이벤트 전송을 즉시
관찰할 수 없으므로 wait_until로 폴링하거나 Event로 동기화한다.

주의: start()는 last_queued_at을 0.0으로 초기화하므로, 첫 tick의 now를
그대로 0.0으로 주면 "now - last_queued_at < FRAME_INTERVAL_S"가 참이 되어
스로틀에 걸린다(실전에서는 now가 항상 0이 아닌 경과시간이라 벌어지지 않음).
그래서 테스트 타임스탬프는 0이 아닌 BASE에서 시작한다.
"""
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from gesture_be import GesturePreview

BASE = 1000.0


class Link:
    """send_event 호출을 기록하는 테스트용 더블. 워커 스레드에서도 불린다."""

    def __init__(self):
        self.sent = []
        self._lock = threading.Lock()

    def send_event(self, event, data):
        with self._lock:
            self.sent.append((event, data))

    def events(self, event):
        with self._lock:
            return [data for ev, data in self.sent if ev == event]


def frame(fill=0):
    return np.full((8, 8, 3), fill, dtype=np.uint8)


def wait_until(condition, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


class GesturePreviewTests(unittest.TestCase):
    def test_encoding_error_does_not_kill_worker(self):
        link = Link()
        preview = GesturePreview(link)
        preview.start()
        with patch('gesture_be.encode_jpeg', side_effect=[ValueError('bad frame'), 'recovered']):
            preview.tick(frame(), BASE)
            self.assertTrue(wait_until(lambda: preview._preview_error))
            preview.tick(frame(), BASE + 1)
            self.assertTrue(wait_until(lambda: len(link.events('cam_preview_frame')) == 1))
        self.assertTrue(preview._thread.is_alive())
        self.assertEqual(link.events('cam_preview_frame')[0]['jpegB64'], 'recovered')
        self.assertEqual(link.events('cam_preview_state')[-1]['phase'], 'READY')

    def test_stop_restart_drops_inflight_old_preview(self):
        link = Link()
        preview = GesturePreview(link)
        started, release = threading.Event(), threading.Event()
        def encode(fr):
            if int(fr[0,0,0]) == 1:
                started.set()
                release.wait(2)
            return str(int(fr[0,0,0]))
        with patch('gesture_be.encode_jpeg', side_effect=encode):
            preview.start()
            preview.tick(frame(1), BASE)
            self.assertTrue(started.wait(2))
            preview.stop()
            preview.start()
            preview.tick(frame(2), BASE + 1)
            release.set()
            self.assertTrue(wait_until(lambda: len(link.events('cam_preview_frame')) == 1))
        self.assertEqual(link.events('cam_preview_frame'),
                         [{'seq': 1, 'jpegB64': '2', 'tsMs': int((BASE + 1) * 1000)}])

    def test_send_failure_is_retried_on_next_frame(self):
        link = Link()
        original = link.send_event
        failed = threading.Event()
        def send(event, data):
            if event == 'cam_preview_frame' and not failed.is_set():
                failed.set()
                return False
            return original(event, data)
        link.send_event = send
        preview = GesturePreview(link)
        preview.start()
        preview.tick(frame(), BASE)
        self.assertTrue(wait_until(lambda: preview._preview_error))
        preview.tick(frame(), BASE + 1)
        self.assertTrue(wait_until(lambda: len(link.events('cam_preview_frame')) == 1))
        self.assertTrue(preview._thread.is_alive())

    def test_start_sends_ready_and_resets_sequence(self):
        link = Link()
        preview = GesturePreview(link)
        preview.start()
        self.assertEqual(link.events("cam_preview_state"), [{"phase": "READY"}])
        self.assertEqual(preview._seq, 0)

    def test_stop_before_start_sends_nothing(self):
        link = Link()
        preview = GesturePreview(link)
        preview.stop()
        self.assertEqual(link.events("cam_preview_state"), [])

    def test_stop_is_idempotent(self):
        link = Link()
        preview = GesturePreview(link)
        preview.start()
        preview.stop()
        preview.stop()  # 두 번째는 무시돼야 한다 — STOPPED가 중복으로 안 나감
        self.assertEqual(link.events("cam_preview_state"),
                         [{"phase": "READY"}, {"phase": "STOPPED"}])

    def test_inactive_tick_never_queues_a_frame(self):
        link = Link()
        preview = GesturePreview(link)
        preview.tick(frame(), BASE)  # start() 전 — 무시돼야 한다
        time.sleep(0.05)
        self.assertEqual(link.events("cam_preview_frame"), [])

    def test_tick_streams_frames_with_increasing_sequence(self):
        link = Link()
        preview = GesturePreview(link)
        preview.start()
        preview.tick(frame(), BASE)
        self.assertTrue(wait_until(lambda: len(link.events("cam_preview_frame")) >= 1))
        preview.tick(frame(), BASE + 1.0)  # FRAME_INTERVAL_S 이상 지남 — 큐에 올라가야 함
        self.assertTrue(wait_until(lambda: len(link.events("cam_preview_frame")) >= 2))
        seqs = [d["seq"] for d in link.events("cam_preview_frame")]
        self.assertEqual(seqs, [1, 2])
        self.assertEqual([d['tsMs'] for d in link.events('cam_preview_frame')],
                         [int(BASE * 1000), int((BASE + 1.0) * 1000)])
        self.assertTrue(all("jpegB64" in d and d["jpegB64"] for d in link.events("cam_preview_frame")))

    def test_tick_throttles_within_frame_interval(self):
        link = Link()
        preview = GesturePreview(link)
        preview.start()
        preview.tick(frame(), BASE)
        preview.tick(frame(), BASE + 0.001)  # FRAME_INTERVAL_S(1/12초) 미만 — 버려져야 함
        self.assertTrue(wait_until(lambda: len(link.events("cam_preview_frame")) >= 1))
        time.sleep(0.05)
        self.assertEqual(len(link.events("cam_preview_frame")), 1)

    def test_backpressure_drops_stale_frame_keeps_latest(self):
        """워커가 밀리면(maxsize=1) 큐에서 밀려난 프레임은 인코딩 시도조차 안 된다.

        타이밍을 sleep으로 어림잡지 않고 Event로 정확히 동기화한다 — 워커가
        frame1을 막 붙잡아 인코딩을 시작한 "그 순간"(큐가 확실히 빈 순간)을
        processing_started로 확인한 뒤에만 frame2/frame3를 큐에 올린다.
        """
        link = Link()
        preview = GesturePreview(link)
        preview.start()
        processing_started = threading.Event()
        release = threading.Event()
        processed = []

        def slow_encode(fr, *args, **kwargs):
            processed.append(int(fr[0, 0, 0]))
            processing_started.set()
            release.wait(timeout=2.0)
            return f"jpeg-{fr[0, 0, 0]}"

        with patch("gesture_be.encode_jpeg", side_effect=slow_encode):
            preview.tick(frame(1), BASE)
            self.assertTrue(processing_started.wait(timeout=2.0),
                            "워커가 frame1을 붙잡지 못함")
            # 이 시점에서 워커는 frame1 인코딩(slow_encode) 안에 멈춰 있고 큐는 비어있다.
            preview.tick(frame(2), BASE + 1.0)   # 큐에 올라감
            preview.tick(frame(3), BASE + 2.0)   # frame2를 밀어내고 큐를 차지 — frame2는 버려짐
            release.set()  # frame1 인코딩을 마저 완료시킴 → 워커가 다음으로 frame3을 집는다
            self.assertTrue(wait_until(lambda: len(link.events("cam_preview_frame")) >= 2, timeout=3.0))

        self.assertEqual(processed, [1, 3])  # frame2는 인코딩 단계까지도 못 감
        self.assertEqual([d['tsMs'] for d in link.events('cam_preview_frame')],
                         [int(BASE * 1000), int((BASE + 2.0) * 1000)])


if __name__ == "__main__":
    unittest.main()
