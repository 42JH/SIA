"""Camera-free registration/cache/runtime regression tests. No live BE actions."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from custom_motion import (CustomGestureStore, distance, encode_sequence,
                           ordered_landmarks, read_templates, static_execution_allowed)
from gesture_be import GestureRegistration, GestureTemplateCache
from hands import normalize_landmarks, GestureStable, HoldToggle


def hand(x=0.3, side="Left", shape=0):
    points = np.array([[i % 4 * 0.02, -(i // 4) * 0.025] for i in range(21)], dtype=float)
    points[0] = 0
    points[9] = [0, -0.1]
    points[4] += [shape, shape]
    points += [x, 0.6]
    return dict(landmarks=points, handedness=side, gesture="Open_Palm")


class Link:
    def __init__(self):
        self.sent, self.payload = [], None

    def send_event(self, event, data):
        self.sent.append((event, data))

    def put_gesture_npz(self, temp_id, payload):
        self.payload = payload

    def get_gesture_npz(self, gid, etag=None):
        return self.payload, "hash"


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = GestureTemplateCache(self.root / "cache", self.root / "combined.npz")
        self.link = Link()

    def register(self, motion, make_hands, name="custom"):
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion=motion, takes=3, takeDurationSec=1), now=0)
        # 위치(모양)는 t=0..1 그대로 쓰되, 실제 타임스탬프만 0.3배로 압축한다 —
        # 같은 이동 거리를 더 짧은 시간에 한 것으로 만들어, 내장 스와이프 감지기의
        # "느리게 움직이면 무장됨" 조건에 안 걸리게 한다(등록 시 내장 스와이프
        # 충돌검사가 새로 생겨서, 이 테스트 데이터 자체가 진짜 스와이프처럼
        # 느리게 움직이면 등록이 거부된다). 저장되는 모양(정규화된 궤적)은
        # 시간축이 고정 프레임 수로 재보간되므로 이 압축과 무관하게 동일하다.
        time_scale = 0.3 if motion == "DYNAMIC" else 1.0
        for take in range(1, 4):
            reg.take = take
            for t in np.linspace(0, 1 if motion == "DYNAMIC" else 0.35, 21):
                reg._collect(make_hands(t), take * 3 + t * time_scale)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])
        self.cache.sync(self.link, [dict(id=1, name=name, sha256="hash")])
        return CustomGestureStore(self.cache.combined_path)

    def feed(self, store, make_hands, duration=1, offset=0):
        return [store.update(make_hands(t / duration), offset + t)
                for t in np.linspace(0, duration, 21)]

    def test_direction_timing_and_rearm(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        self.assertEqual(store.class_names(), ["custom"])
        events = self.feed(store, lambda t: [hand(0.3 + t * 0.2)])
        self.assertEqual([d for _, d, _, _ in events if d], ["custom"])
        self.assertTrue(store.update([hand(0.5)], 1.1)[2])
        self.assertIsNone(store.update([hand(0.5)], 1.2)[1])
        store.update([], 1.3)
        store.update([], 1.7)
        self.assertFalse(store.latched)
        events = self.feed(store, lambda t: [hand(0.5 - t * 0.2)], offset=2)
        self.assertFalse(any(d for _, d, _, _ in events))
        store.reset_motion()
        self.assertTrue(any(d for _, d, _, _ in self.feed(store, lambda t: [hand(0.4 + t * 0.2)], duration=1.3)))

    def test_motion_not_a_held_pose(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        self.assertFalse(any(d for _, d, _, _ in self.feed(store, lambda t: [hand()])))
        self.assertIsNone(store.classify_with_distance(hand()["landmarks"])[0])

    def test_two_hand_static_and_detector_reordering(self):
        pair = lambda t: [hand(), hand(0.65, "Right", 0.08)]
        store = self.register("STATIC", pair)
        self.assertEqual(self.link.sent[-1][1]["hands"], 2)
        self.assertEqual(store.update(list(reversed(pair(0))), 0)[0], "custom")
        self.assertIsNone(store.update([hand()], 0.1)[0])
        self.assertIsNone(store.update([hand(), hand(0.65, "Right", -0.12)], 0.2)[0])
        self.assertIsNone(store.update([hand(), hand(0.9, "Right", 0.08)], 0.3)[0])

    def tick_until_wait_finish(self, reg, make_hands, step=0.05):
        """register()와 달리 _collect를 직접 부르지 않고 실제 tick() 타이밍으로 진행한다.

        STATIC이 RECORDING 진입 즉시 1장만 모으고 넘어가던 옛 버그는 register()
        헬퍼(수동으로 _collect를 여러 번 호출)로는 재현되지 않았다 — tick()을
        실제로 구동해야만 회차당 몇 프레임이 실제로 모이는지 검증할 수 있다.
        """
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        now = 0.0
        while reg.active and reg.phase != "WAIT_FINISH":
            now += step
            reg.tick(frame, make_hands(), now=now)

    def test_registration_rejects_hand_clipped_outside_frame(self):
        """손 일부가 화면 밖으로 나가면(카메라에 너무 가까이 등) 거부해야 한다 —
        MediaPipe는 안 보이는 부분의 랜드마크를 [0,1] 밖으로 추정해 낸다."""
        def clipped():
            pts = np.array([[i % 4 * 0.02, -(i // 4) * 0.025] for i in range(21)], dtype=float)
            pts[0] = 0
            pts[9] = [0, -0.1]
            pts += [-0.05, 0.6]  # x가 음수 — 화면 왼쪽 밖
            return [dict(landmarks=pts, handedness="Left", gesture=None)]

        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        for i in range(20):
            reg._collect(clipped(), i * 0.05)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("화면 밖", payload["reason"])

    @staticmethod
    def tilted_hand(x, angle_deg, side="Left"):
        """스와이프처럼 팔을 휘두르며 손목이 자연스럽게 기우는 상황을 흉내낸다."""
        pts = np.array([[i % 4 * 0.02, -(i // 4) * 0.025] for i in range(21)], dtype=float)
        pts[0] = 0
        a = np.radians(angle_deg)
        pts[9] = [0.1 * np.sin(a), -0.1 * np.cos(a)]
        pts += [x, 0.6]
        return dict(landmarks=pts, handedness=side, gesture=None)

    def test_dynamic_registration_tolerates_natural_wrist_tilt(self):
        """동적 등록은 스와이프 중 손목이 크게 기울어도(60도) 거부되면 안 된다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        for i in range(20):
            reg._collect([self.tilted_hand(0.2 + i * 0.02, -30 + i * 3)], i * 0.05)
        reg.hand_counts = [1] * 20
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])

    def test_static_registration_still_rejects_wobbly_hold(self):
        """정적 등록은 계속 흔들림을 걸러야 한다(동적만 예외로 뺀 것) —
        어느 품질검사에 걸리든(방향 변화든 샘플 퍼짐이든) 통과하면 안 된다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        for i in range(20):
            reg._collect([self.tilted_hand(0.3, -30 + i * 3)], i * 0.05)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_rejected", self.link.sent[-1])

    def test_two_hand_static_rejects_when_only_second_hand_wobbles(self):
        """왼손은 완전히 고정, 오른손만 프레임마다 크게 흔들리는 경우도 거부돼야 한다 —
        평균 자세와의 손모양 편차(spread)가 두 손 다 반영돼야 이 케이스를 잡는다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        left = self.tilted_hand(0.2, 0, "Left")
        for i in range(20):
            right = self.tilted_hand(0.65, 35 if i % 2 == 0 else -35, "Right")
            reg._collect([left, right], i * 0.05)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("흔들렸습니다", payload["reason"])

    def test_one_hand_dynamic_rejects_when_it_matches_builtin_swipe(self):
        """1손 동적 등록 동작이 내장 스와이프(Swipe_Left/Right)와 똑같이 움직이면
        거부돼야 한다 — 안 그러면 실행 시 커스텀 동작 추적이 우선순위를 가져가
        내장 스와이프가 조용히 가려진다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        # 실제 스와이프처럼 천천히(초당 0.2, still_speed=0.25 미만) 꾸준히 이동 —
        # SwipeDetector가 "정지"로 보고 무장한 뒤 누적 변위로 발동하는 패턴.
        for t in np.linspace(0, 1, 21):
            reg._collect([hand(0.3 + t * 0.2)], t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("스와이프", payload["reason"])

    def test_one_hand_dynamic_allows_scroll_like_motion(self):
        """스크롤·핀치볼륨은 서비스가 기본 제공하는 9종(정적 7 + 스와이프 좌/우)에
        안 들어가는, 아직 사용자에게 노출된 적 없는(enabled=False) 기능이라
        BUILTIN_DYNAMIC_DETECTORS에서 뺐다 — "내장 스크롤과 비슷합니다"는 사용자가
        이해할 수 없는 사유이기 때문. 그래서 스크롤과 똑같이 움직여도 통과해야
        한다(나중에 스크롤이 실제로 켜지면 이 목록에 다시 넣는다)."""
        def vertical(t, side="Left"):
            pts = np.array([[i % 4 * 0.02, -(i // 4) * 0.025] for i in range(21)], dtype=float)
            pts[0] = 0
            pts[9] = [0, -0.1]
            pts += [0.4, 0.5 + t * 0.3]
            return dict(landmarks=pts, handedness=side, gesture=None)

        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        for t in np.linspace(0, 1, 21):
            reg._collect([vertical(t)], t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])

    def test_two_hand_dynamic_rejects_when_either_hand_matches_builtin_swipe(self):
        """양손이 같은(느린 수평) 움직임을 해도, 한 손만 놓고 보면 내장 스와이프와
        똑같은 동작이면 거부돼야 한다 — 실행 중 2손 인식이 그 프레임만 실패하면
        (핸드니스 오판 등) 그 손 하나의 raw 판정만으로 내장 스와이프가 새어
        발동할 수 있기 때문에, 손마다 독립적으로 검사한다."""
        pair = lambda t: [hand(0.2 + t * 0.2, "Left"), hand(0.65 + t * 0.2, "Right")]
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        for t in np.linspace(0, 1, 21):
            reg._collect(pair(t), t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("스와이프", payload["reason"])

    def test_two_hand_dynamic_allows_motion_neither_hand_alone_resembles(self):
        """두 손이 서로 반대로 제자리에서 회전만 하는(손목 이동은 거의 없는) 동작은
        어느 손만 따로 봐도 내장 동작(스와이프/스크롤/핀치)과 안 겹치므로 통과해야
        한다 — 손별 독립 검사가 진짜 2손 전용 동작까지 과하게 막으면 안 된다."""
        pair = lambda i: [self.tilted_hand(0.2, -40 + i * 4, "Left"),
                          self.tilted_hand(0.65, 40 - i * 4, "Right")]
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        for i in range(20):
            reg._collect(pair(i), i * 0.05)
        reg.hand_counts = [2] * 20
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])

    def test_two_hand_static_quality_ignores_detection_order_flip(self):
        """MediaPipe 감지 순서가 프레임마다 바뀌어도(왼/오 뒤바뀜), 각 손이 개별적으로는
        안정적이면 통과해야 한다. 왼손·오른손을 서로 다른(각자는 고정된) 각도로 두고
        순서만 뒤집는다 — hands[0]만 보던 예전 코드라면 두 각도 사이를 오가는 것처럼
        보여 "방향 변화가 큽니다"로 거부됐을 상황이다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        left, right = self.tilted_hand(0.2, 25, "Left"), self.tilted_hand(0.65, -25, "Right")
        for i in range(20):
            pair = [left, right] if i % 2 == 0 else [right, left]  # 감지 순서가 프레임마다 뒤집힘
            reg._collect(pair, i * 0.05)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event = self.link.sent[-1][0]
        self.assertEqual(event, "reg_captured", self.link.sent[-1])

    def test_hand_count_change_mid_take_gives_clean_rejection(self):
        """회차 도중 손 개수가 바뀌면(가려짐 등) raw numpy 예외가 아니라 안내 문구로 거부돼야 한다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        pair = lambda t, x=0.65: [hand(), hand(x, "Right", 0.08)]
        for i in range(5):
            reg._collect(pair(i * 0.1), i * 0.1)
        for i in range(5, 10):  # 오른손을 놓친 것처럼 한 손만 남김
            reg._collect([hand()], i * 0.1)
        reg.hand_counts = [2] * 5 + [1] * 5
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected")
        self.assertIn("손 개수", payload["reason"])

    def test_large_tracking_gap_is_rejected_not_interpolated(self):
        """중간을 오래 놓치면 encode_sequence가 조용히 직선 보간하지 못하게 거부해야 한다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        reg._collect([hand(0.3)], 0.0)
        reg._collect([hand(0.32)], 0.1)
        reg._collect([hand(0.7)], 1.9)   # 그 사이 1.8초(take_s=2.0의 90%) 공백
        reg._collect([hand(0.72)], 2.0)
        reg.hand_counts = [1, 1, 1, 1]
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected")
        self.assertIn("놓쳤습니다", payload["reason"])

    def test_static_capture_collects_several_frames_per_take(self):
        # gesture=None: 기본 hand()의 "Open_Palm" 라벨은 내장 제스처 유사도 검사에 걸린다 —
        # 여기서는 그 검사가 아니라 프레임 수집 개수 자체를 검증한다.
        make_hands = lambda: [dict(hand(), gesture=None)]
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=3, countdownSec=0.01), now=0)
        self.tick_until_wait_finish(reg, make_hands)
        # 회차당 1장만 모였다면(옛 버그) 3회차 합쳐도 3장뿐 — 최소 기준(8)을 못 넘긴다.
        self.assertGreaterEqual(len(reg.samples), GestureRegistration.MIN_STATIC_SAMPLES)
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])

    def test_two_hand_static_capture_succeeds_via_real_tick_timing(self):
        pair = lambda: [hand(), hand(0.65, "Right", 0.08)]
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=3, countdownSec=0.01), now=0)
        self.tick_until_wait_finish(reg, pair)
        reg.finish()
        # 옛 버그는 회차당 프레임이 1장뿐이라 encode_sequence가 요구하는 2장을
        # 못 채워 "회차 촬영이 충분하지 않습니다"로 항상 거부됐다.
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])
        self.assertEqual(self.link.sent[-1][1]["hands"], 2)

    def test_two_hand_dynamic_tracks_second_hand(self):
        pair = lambda t: [hand(), hand(0.6 + t * 0.2, "Right")]
        store = self.register("DYNAMIC", pair)
        events = self.feed(store, lambda t: list(reversed(pair(t))))
        self.assertTrue(any(d for _, d, _, _ in events))
        store.reset_motion()
        self.assertFalse(any(d for _, d, _, _ in self.feed(store, lambda t: [hand()])))

    def test_legacy_cache_coexists_and_rename_delete(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        legacy = self.cache.template_bytes("old", [normalize_landmarks(hand()["landmarks"])])
        (self.cache.cache_dir / "g2.npz").write_bytes(legacy)
        self.cache._rebuild({"1": {"name": "renamed"}, "2": {"name": "old"}})
        store = CustomGestureStore(self.cache.combined_path)
        self.assertEqual(store.class_names(), ["old", "renamed"])
        self.assertEqual(store.classify_with_distance(hand()["landmarks"])[0], "old")
        self.assertTrue(any(d == "renamed" for _, d, _, _ in self.feed(store, lambda t: [hand(0.3 + t * 0.2)])))
        self.cache._rebuild({"2": {"name": "old"}})
        self.assertEqual(CustomGestureStore(self.cache.combined_path).class_names(), ["old"])

    def test_gap_cannot_complete_motion(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        for t in np.linspace(0, 0.4, 9):
            store.update([hand(0.3 + t * 0.2)], t)
        for t in np.linspace(0.8, 1, 5):
            self.assertIsNone(store.update([hand(0.3 + t * 0.2)], t)[1])

    def test_reject_stationary_dynamic_and_incomplete_take(self):
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing"))
        reg.start(dict(tempId="bad", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        for t in np.linspace(0, 1, 21):
            reg._collect([hand()], t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_rejected")
        self.assertIsNone(self.link.payload)

    def test_sequence_retains_order(self):
        times = np.linspace(0, 1, 21)
        points = [ordered_landmarks([hand(0.3 + t * 0.2)]) for t in times]
        a = encode_sequence(times, points)
        b = encode_sequence(times, points[::-1])
        self.assertGreater(distance(a, b, 1), 1)
        self.assertIsNone(ordered_landmarks([hand(side="Unknown"), hand(0.6, "Unknown")]))

    def test_capture_tick_upload_download_roundtrip(self):
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing"))
        reg.start(dict(tempId="tick", motion="DYNAMIC", takes=1,
                       countdownSec=0.1, takeDurationSec=1), now=0)
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        # 0.2 대신 0.5 — 내장 스와이프 감지기의 "느리게 움직이면 무장됨" 조건보다
        # 빠르게 움직여서, 등록 시 새로 생긴 스와이프 충돌검사에 안 걸리게 한다.
        for t in np.linspace(0.1, 1.15, 22):
            reg.tick(frame, [hand(0.3 + (t - 0.1) * 0.5)], now=t)
        self.assertEqual(reg.phase, "WAIT_FINISH")
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured")
        payload = read_templates(self.link.payload)
        self.assertEqual(payload["sequences"].shape, (1, 24, 2, 21, 2))
        self.assertEqual(len(payload["X"]), 0)
        self.assertTrue(any(event == "reg_frame" for event, _ in self.link.sent))

    def test_duplicate_motion_rejected_after_reload(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)], name="existing")
        self.link.payload = None
        reg = GestureRegistration(self.link, self.cache, store)
        reg.start(dict(tempId="duplicate", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        # 타임스탬프를 0.3배로 압축 — register() 헬퍼와 같은 이유(내장 스와이프
        # 충돌검사 회피). 여기서 검증하려는 건 "기존 제스처와 겹쳐서" 거부되는
        # 것이지 "내장 스와이프와 겹쳐서" 거부되는 게 아니다.
        for t in np.linspace(0, 1, 21):
            reg._collect([hand(0.3 + t * 0.2)], t * 0.3)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_rejected")
        self.assertEqual(self.link.sent[-1][1]["similarTo"], "existing")
        self.assertIsNone(self.link.payload)

    def test_missing_entire_take_rejected(self):
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing"))
        reg.start(dict(tempId="missing-take", motion="DYNAMIC", takes=2, takeDurationSec=1), now=0)
        for t in np.linspace(0, 1, 21):
            reg._collect([hand(0.3 + t * 0.2)], t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_rejected")
        self.assertIsNone(self.link.payload)

    def test_custom_prefix_blocks_builtin_before_completion(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        store.data["durations"] *= 2
        stable = GestureStable(min_frames=3, missing_grace_s=0.45)
        hold = HoldToggle(hold_s=0.8, cooldown_s=2.2, grace_s=0.6)
        builtin, custom, pending = [], [], []
        for t in np.linspace(0, 2, 41):
            pose, event, claimed, _dist = store.update([hand(0.3 + t * 0.1)], float(t))
            label = stable.update(pose or "None" if claimed else "Open_Palm", float(t))
            allowed = static_execution_allowed(True, False, claimed, pose, "Open_Palm")
            if hold.update(allowed and label == "Open_Palm", float(t)):
                builtin.append(t)
            if event:
                custom.append(event)
            if claimed and not event:
                pending.append(t)
        self.assertFalse(builtin)
        self.assertEqual(custom, ["custom"])
        self.assertLess(min(pending), 0.8)

    def test_stationary_builtin_remains_available(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        self.assertFalse(any(claimed for _, _, claimed, _ in self.feed(store, lambda t: [hand()])))

    def test_abandoned_prefix_releases_execution(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        store.data["durations"] *= 2
        for t in np.linspace(0, 0.5, 11):
            store.update([hand(0.3 + t * 0.1)], float(t))
        results = [store.update([hand(0.35)], float(t)) for t in np.linspace(0.55, 4, 70)]
        self.assertFalse(any(event for _, event, _, _ in results))
        self.assertFalse(results[-1][2])

    def test_disabled_template_never_reserves_execution(self):
        store = self.register("DYNAMIC", lambda t: [hand(0.3 + t * 0.2)])
        for t in np.linspace(0, 1, 21):
            self.assertEqual(store.update([hand(0.3 + t * 0.2)], float(t), {"custom"}), (None, None, False, None))
        store.reset_motion()
        self.feed(store, lambda t: [hand(0.3 + t * 0.2)])
        self.assertTrue(store.latched)
        self.assertFalse(store.update([hand(0.5)], 1.1, {"custom"})[2])


if __name__ == "__main__":
    unittest.main()
