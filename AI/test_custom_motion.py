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
        store = CustomGestureStore(self.cache.combined_path)
        if motion == "DYNAMIC":
            # 실제 촬영 시간 저장을 검증한 뒤, 아래 실행 테스트의 1초 궤적에
            # 맞춰 시험용 템플릿만 재타이밍한다(위 촬영은 충돌 회피용 0.3초).
            np.testing.assert_allclose(store.data["durations"], 0.3, atol=1e-6)
            store.data["durations"][:] = 1.0
        return store

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
        # similarTo는 통칭이 아니라 BE 기본 제스처 이름과 그대로 일치하는
        # 구체적인 이벤트 이름이어야 FE가 실제 제스처를 찾아 보여줄 수 있다.
        self.assertEqual(payload["similarTo"], "Swipe_Right")
        # 감지기는 발동 여부만 볼 뿐 거리를 재는 구조가 아니라, 발동 직전 이동
        # 거리 ÷ 기준 거리로 유사도를 근사한다 — 0보다 크고 1 이하여야 한다.
        self.assertGreater(payload["similarity"], 0)
        self.assertLessEqual(payload["similarity"], 1)

    def test_one_hand_dynamic_swipe_collision_scales_with_camera_distance(self):
        """카메라에서 멀리 있어서 손이 작게 잡히는 사람이 화면 비율로는 작게(하지만
        자기 손 크기 대비로는 충분히 크게) 움직여도, 그게 실제로는 스와이프와
        똑같은 동작이면 등록 시점에 걸러야 한다 — 손 크기(size)로 스케일 보정하지
        않으면 화면 비율만으로는 절대 못 잡는 이동량이다."""
        small_palm = 0.03  # 화면의 3% — 카메라에서 멀리 있을 때의 손 크기
        # 물리적으로는 "손 크기의 1.5배" 스와이프지만, 화면 비율로는 0.045밖에
        # 안 돼 SCREEN_SWIPE_CONFIG의 dist(0.12)에 훨씬 못 미친다 — 보정이
        # 없으면 절대 안 걸린다.
        total = small_palm * 1.5
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        for t in np.linspace(0, 1, 21):
            h = dict(hand(0.3 + t * total), size=small_palm)
            reg._collect([h], t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertEqual(payload["similarTo"], "Swipe_Right")

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
        self.assertEqual(payload["similarTo"], "Swipe_Right")

    def test_two_hand_dynamic_allows_clapping_motion_despite_each_hand_resembling_swipe(self):
        """박수처럼 두 손이 서로를 향해 모이면, 손 하나만 떼어 보면 스와이프와
        똑같아 보여도 등록이 통과해야 한다 — 두 손 사이 거리가 뚜렷이 줄어드는
        중이면 "따로 움직인 스와이프"가 아니라 "서로 다가가는 동작"으로 본다."""
        pair = lambda t: [hand(0.2 + t * 0.2, "Left"), hand(0.65 - t * 0.2, "Right")]
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        for t in np.linspace(0, 1, 21):
            reg._collect(pair(t), t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])

    def test_two_hand_dynamic_allows_spreading_motion_despite_each_hand_resembling_swipe(self):
        """모아진 두 손을 양옆으로 펼치는 동작(박수의 반대)도 같은 이유로 통과해야
        한다 — 손 하나만 보면 스와이프처럼 보이지만, 두 손 사이 거리가 뚜렷이
        늘어나는 중이면 "서로 멀어지는 동작"으로 본다(방향과 무관하게 적용)."""
        pair = lambda t: [hand(0.45 - t * 0.2, "Left"), hand(0.45 + t * 0.2, "Right")]
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        for t in np.linspace(0, 1, 21):
            reg._collect(pair(t), t)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])

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

    def test_dynamic_registration_collides_with_existing_static_pose(self):
        """같은 손모양을 정적으로 이미 등록해뒀으면, 동적으로 다시 등록해도
        '너무 유사합니다'로 걸려야 한다 — motion 종류가 다르면 정적(legacy)과
        동적(self.data)이 완전히 분리된 저장소라 예전에는 이 경계를 못 봤다."""
        base = hand(0.3, "Left", shape=0)
        store = CustomGestureStore(self.root / "missing.npz")
        store.legacy.X = np.array([normalize_landmarks(base["landmarks"])])
        store.legacy.names = ["기존정적"]

        reg = GestureRegistration(self.link, self.cache, store)
        reg.start(dict(tempId="t1", motion="DYNAMIC", takes=1, takeDurationSec=1), now=0)
        reg.take = 1
        for i in range(20):
            h = dict(hand(0.3, "Left", shape=i * 0.01), gesture=None)
            reg._collect([h], i * 0.05)
        reg.hand_counts = [1] * 20
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("너무 유사합니다", payload["reason"])
        self.assertEqual(payload.get("similarTo"), "기존정적")

    def test_static_registration_collides_with_existing_dynamic_pose(self):
        """반대 방향도 마찬가지다 — 같은 손모양이 동적으로 이미 등록돼 있으면
        정적으로 다시 등록해도 '너무 유사합니다'로 걸려야 한다."""
        times = np.linspace(0, 1, 20)
        points = [ordered_landmarks([dict(hand(0.3, "Left", shape=t * 0.15), gesture=None)])
                  for t in times]
        seq = encode_sequence(times, points)
        store = CustomGestureStore(self.root / "missing.npz")
        store.data.update(sequences=np.array([seq]), sequence_names=np.array(["기존동적"]),
                          motions=np.array(["DYNAMIC"]), hand_counts=np.array([1], dtype=np.int32),
                          durations=np.array([1.0]))

        reg = GestureRegistration(self.link, self.cache, store)
        reg.start(dict(tempId="t1", motion="STATIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        for i in range(20):
            h = dict(hand(0.3, "Left", shape=0), gesture=None)
            reg._collect([h], i * 0.05)
        reg.hand_counts = [1] * 20
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("너무 유사합니다", payload["reason"])
        self.assertEqual(payload.get("similarTo"), "기존동적")

    def test_two_hand_static_registration_collides_with_existing_two_hand_dynamic(self):
        """2손도 마찬가지다 — 같은 두 손 모양이 동적으로 이미 등록돼 있으면
        정적으로 다시 등록해도 걸려야 한다(둘 다 self.data에 있지만 motion이
        다르면 sequence_comparisons가 원래 서로 못 본다)."""
        times = np.linspace(0, 1, 20)
        pair = lambda t: [dict(hand(0.3, "Left", shape=t * 0.1), gesture=None),
                          dict(hand(0.65, "Right", shape=t * 0.1), gesture=None)]
        points = [ordered_landmarks(pair(t)) for t in times]
        seq = encode_sequence(times, points)
        store = CustomGestureStore(self.root / "missing.npz")
        store.data.update(sequences=np.array([seq]), sequence_names=np.array(["기존양손동적"]),
                          motions=np.array(["DYNAMIC"]), hand_counts=np.array([2], dtype=np.int32),
                          durations=np.array([1.0]))

        reg = GestureRegistration(self.link, self.cache, store)
        reg.start(dict(tempId="t1", motion="STATIC", takes=1, countdownSec=0), now=0)
        reg.take = 1
        for i in range(20):
            reg._collect([dict(hand(0.3, "Left", shape=0), gesture=None),
                          dict(hand(0.65, "Right", shape=0), gesture=None)], i * 0.05)
        reg.hand_counts = [2] * 20
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("너무 유사합니다", payload["reason"])
        self.assertEqual(payload.get("similarTo"), "기존양손동적")

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

    def test_static_registration_tolerates_stray_extra_hand_frame(self):
        """정적 등록 중 다른 손이(배경·반대손) 잠깐 같이 잡혀도, 그 프레임만
        건너뛰고 나머지 깨끗한 1손 프레임으로 등록에 성공해야 한다 — 실제
        진단 로그에서 이런 촬영이 통째로 거부되던 문제를 재현한 회귀 테스트."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=3, countdownSec=0), now=0)
        for take in range(1, 4):
            reg.take = take
            for i in range(20):
                if take == 1 and i in (10, 11):
                    hands = [dict(hand(0.3, "Left"), gesture=None), dict(hand(0.6, "Right"), gesture=None)]
                else:
                    hands = [dict(hand(0.3, "Left"), gesture=None)]
                reg._collect(hands, take * 3 + i * 0.02)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])

    def test_static_registration_names_the_take_that_is_entirely_multi_hand(self):
        """어느 회차가 통째로 2손이었는지 정확히 짚어야 한다 — 정상인 다른
        회차를 '충분하지 않다'고 엉뚱하게 지목하면 안 된다."""
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="t1", motion="STATIC", takes=3, countdownSec=0), now=0)
        for take in range(1, 4):
            reg.take = take
            for i in range(20):
                if take == 2:
                    hands = [dict(hand(0.3, "Left"), gesture=None), dict(hand(0.6, "Right"), gesture=None)]
                else:
                    hands = [dict(hand(0.3, "Left"), gesture=None)]
                reg._collect(hands, take * 3 + i * 0.02)
        reg.phase = "WAIT_FINISH"
        reg.finish()
        event, payload = self.link.sent[-1]
        self.assertEqual(event, "reg_rejected", self.link.sent[-1])
        self.assertIn("2회차", payload["reason"])
        self.assertIn("손 개수", payload["reason"])

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
        self.assertTrue(any(d == "renamed" for _, d, _, _ in self.feed(store, lambda t: [hand(0.3 + t * 0.2)], duration=0.3)))
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

    @staticmethod
    def two_hand_tilt_pose(spread=0.3, global_tilt_deg=0.0, relative_tilt_deg=0.0, center=(0.5, 0.6)):
        """두 손 벌리기 자세 — global_tilt는 두 손이 '같이' 도는 전체 기울기,
        relative_tilt는 오른손만 자기 자리에서 추가로 도는 상대 회전이다."""
        def base():
            pts = np.array([[i % 4 * 0.02, -(i // 4) * 0.025] for i in range(21)], dtype=float)
            pts[0] = 0
            pts[9] = [0, -0.1]
            return pts

        def rot(deg):
            a = np.radians(deg)
            c, s = np.cos(a), np.sin(a)
            return np.array([[c, -s], [s, c]])

        left = base() + [-spread / 2, 0]
        right = base()
        if relative_tilt_deg:
            right = right @ rot(relative_tilt_deg).T
        right = right + [spread / 2, 0]
        both = np.vstack([left, right])
        if global_tilt_deg:
            both = both @ rot(global_tilt_deg).T
        both = both + center
        return [dict(landmarks=both[:21], handedness="Left"),
                dict(landmarks=both[21:], handedness="Right")]

    def encode_static_pose(self, hands):
        pts = ordered_landmarks(hands)
        return encode_sequence([0, 1], [pts, pts])

    def test_two_hand_global_tilt_is_normalized_away(self):
        """두 손이 '같이' 기우는 전체 기울기는 카메라 각도 잡음에 가까우므로,
        등록 때와 실행 때 몸이 조금 틀어져 있어도 같은 제스처로 인식돼야 한다."""
        base = self.encode_static_pose(self.two_hand_tilt_pose())
        tilted = self.encode_static_pose(self.two_hand_tilt_pose(global_tilt_deg=20))
        self.assertLess(distance(tilted, base, 2), 0.01)

    def test_two_hand_relative_rotation_is_preserved(self):
        """한 손만 다른 손 대비 도는 상대 회전은 실제로 다른 제스처를 뜻하므로,
        전체 기울기를 지워도 여전히 뚜렷하게 구분돼야 한다."""
        base = self.encode_static_pose(self.two_hand_tilt_pose())
        relative = self.encode_static_pose(self.two_hand_tilt_pose(relative_tilt_deg=20))
        self.assertGreater(distance(relative, base, 2), 0.1)

    def test_two_hand_opposite_facing_skips_rotation_safely(self):
        """두 손이 거의 정반대를 향하면(예: 손뼉 치기 직전) 기준 방향 자체가
        정의되지 않는다 — 에러 없이, 회전 보정을 건너뛴 값을 내야 한다."""
        def facing_pose(global_tilt_deg=0.0):
            pts = np.array([[i % 4 * 0.02, -(i // 4) * 0.025] for i in range(21)], dtype=float)
            pts[0] = 0
            pts[9] = [0, -0.1]
            a = np.radians(180)
            c, s = np.cos(a), np.sin(a)
            flipped = pts @ np.array([[c, -s], [s, c]]).T
            left = pts + [-0.15, 0]
            right = flipped + [0.15, 0]
            both = np.vstack([left, right])
            if global_tilt_deg:
                ga = np.radians(global_tilt_deg)
                gc, gs = np.cos(ga), np.sin(ga)
                both = both @ np.array([[gc, -gs], [gs, gc]]).T
            both = both + [0.5, 0.6]
            return [dict(landmarks=both[:21], handedness="Left"),
                    dict(landmarks=both[21:], handedness="Right")]

        base = self.encode_static_pose(facing_pose())
        self.assertTrue(np.isfinite(base).all())
        # 보정이 건너뛰어졌다면(회전 미보정) 전체를 돌린 버전은 여전히 다르게 보여야
        # 한다 — 일반 자세라면 0에 가까울 20도 기울임이 그대로 남는지로 확인한다.
        tilted = self.encode_static_pose(facing_pose(global_tilt_deg=20))
        self.assertTrue(np.isfinite(tilted).all())
        self.assertGreater(distance(tilted, base, 2), 0.05)

    @staticmethod
    def clap_hands(i, n=30, glitch_at=None):
        """두 손이 서서히 모이는(박수) 프레임들. glitch_at 프레임에서는 핸디드니스가
        둘 다 같은 쪽으로 오판된 것처럼 만든다(ordered_landmarks가 None을 내는 상황)."""
        left, right = hand(0.35 - i / n * 0.15, "Left"), hand(0.65 + i / n * 0.15, "Right")
        if glitch_at is not None and i == glitch_at:
            right = dict(right); right["handedness"] = "Left"
        return [left, right]

    def test_tracking_glitch_does_not_falsely_claim_when_nothing_registered(self):
        """등록된 제스처가 하나도 없으면, 핸디드니스가 한 프레임 오판돼도 claimed가
        거짓으로 True가 되면 안 된다 — 그러면 내장 동적 제스처(스와이프 등)가
        아무 이유 없이 억제된다."""
        store = CustomGestureStore(self.root / "missing.npz")
        t = 0.0
        claimed_log = []
        for i in range(20):
            t += 1 / 30
            _, _, claimed, _ = store.update(self.clap_hands(i, glitch_at=10), t)
            claimed_log.append(claimed)
        self.assertFalse(claimed_log[10])
        self.assertFalse(any(claimed_log))

    def test_tracking_glitch_bridges_when_matching_gesture_is_in_progress(self):
        """등록된 2손 동적 제스처(박수)를 추적하는 도중 핸디드니스가 한 프레임
        오판돼도, claimed가 끊기지 않고 결국 동작이 완성돼야 한다 — 안 그러면
        그 찰나에 커스텀 동작이 새어나간 raw 판정(내장 스와이프 등)으로 잘못
        해석될 수 있고, 누적 중이던 궤적도 지워져 인식 자체가 실패할 수 있다."""
        store = CustomGestureStore(self.root / "missing.npz")
        times = np.linspace(0, 1, 30)
        points = [ordered_landmarks(self.clap_hands(i, n=30)) for i in range(30)]
        seq = encode_sequence(list(times), points)
        store.data["sequences"] = np.stack([seq])
        store.data["sequence_names"] = np.array(["clap"])
        store.data["motions"] = np.array(["DYNAMIC"])
        store.data["hand_counts"] = np.array([2], dtype=np.int32)
        store.data["durations"] = np.array([1.0], dtype=np.float32)

        t = 0.0
        claimed_log, completed = [], None
        for i in range(30):
            t += 1 / 30
            _, motion_done, claimed, _ = store.update(self.clap_hands(i, glitch_at=15), t)
            claimed_log.append(claimed)
            completed = completed or motion_done
        self.assertTrue(claimed_log[15], "글리치 프레임에서 추적이 끊기면 안 된다")
        self.assertEqual(completed, "clap", "글리치를 넘기고 결국 인식에 성공해야 한다")

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
