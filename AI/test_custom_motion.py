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
        for take in range(1, 4):
            reg.take = take
            for t in np.linspace(0, 1 if motion == "DYNAMIC" else 0.35, 21):
                reg._collect(make_hands(t), take * 3 + t)
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
        for t in np.linspace(0.1, 1.15, 22):
            reg.tick(frame, [hand(0.3 + (t - 0.1) * 0.2)], now=t)
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
        for t in np.linspace(0, 1, 21):
            reg._collect([hand(0.3 + t * 0.2)], t)
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
