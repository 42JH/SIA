"""양손 등록과 실행에서 짧은 가림은 허용하고 긴 공백은 연결하지 않는다."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from custom_motion import CustomGestureStore, encode_sequence, ordered_landmarks
from gesture_be import GestureRegistration, GestureTemplateCache
from test_custom_motion import Link, hand


def pair(t):
    return [hand(0.3 + t*0.1, 'Left', shape=t*0.06),
            hand(0.7 - t*0.1, 'Right', shape=t*0.06)]


class OcclusionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def register(self, bad, kind='one'):
        link = Link()
        reg = GestureRegistration(link, GestureTemplateCache(self.root/'cache', self.root/'all.npz'),
                                  CustomGestureStore(self.root/'missing.npz'))
        with contextlib.redirect_stdout(io.StringIO()), patch('gesture_be.save_registration_diagnostic'):
            reg.start(dict(tempId='occlusion', motion='DYNAMIC', takes=3, takeDurationSec=1), now=0)
            for take in range(1, 4):
                reg.take = take
                for i, t in enumerate(np.linspace(0, 1, 31)):
                    hands = pair(t)
                    if i in bad:
                        if kind == 'one':
                            hands = hands[:1]
                        elif kind == 'none':
                            hands = []
                        else:
                            hands[1]['handedness'] = 'Left'
                    reg._collect(hands, take*3+t)
            reg.phase = 'WAIT_FINISH'
            reg.finish()
        return link

    def test_short_internal_occlusion_uploads_two_hand_template(self):
        for kind in ('one', 'none', 'ambiguous'):
            with self.subTest(kind=kind):
                link = self.register({15, 16}, kind)
                self.assertEqual(link.sent[-1][0], 'reg_captured', link.sent[-1])
                with np.load(io.BytesIO(link.payload), allow_pickle=False) as z:
                    np.testing.assert_array_equal(z['hand_counts'], [2, 2, 2])
                    self.assertEqual(z['sequences'].shape, (3, 24, 2, 21, 2))

    def test_frequent_brief_occlusion_gives_accurate_message_not_hand_count_changed(self):
        """박수처럼 두 손이 맞닿을 때마다 짧게(문법상 가려짐 허용 범위 안으로) 한 손만
        잡히는 순간이 회차마다 여러 번 반복되면, 그 각각은 다리를 놓아 줄 만큼 짧아도
        합쳐지면 전체 프레임의 30% 이상을 차지해 예전 방식(전체 프레임 단순 다수결)은
        두 손 촬영을 한 손으로 잘못 판정했다. 그 결과 회차별 가려짐 허용 로직이
        통째로 스킵되어, 실제로는 "두 손이 오래 가려졌다"가 원인인데도 엉뚱하게
        "손 개수가 바뀌었습니다"로 거부되는 문구 오류가 났다 — 두 손 판정 자체는
        짧은 가려짐을 감안해야 이 오류를 피할 수 있다.

        각 회차에 3프레임(약 0.1s, TRACKING_GRACE_S=0.15s 이내)짜리 가려짐을 4번
        흩어 넣는다 — 개별 구간은 다리를 놓을 수 있을 만큼 짧지만, 회차당 합계는
        12/31(약 39%)로 회차 판정 기준(80%) 자체는 넘지 못해 결국 거부돼야 한다.
        다만 그 거부 사유가 정확해야 한다.
        """
        bad = {3, 4, 5, 10, 11, 12, 17, 18, 19, 24, 25, 26}
        link = self.register(bad)
        self.assertEqual(link.sent[-1][0], 'reg_rejected', link.sent[-1])
        reason = link.sent[-1][1]['reason']
        self.assertNotIn('손 개수가 바뀌었습니다', reason)
        self.assertIn('오래 가려졌', reason)

    def test_long_edge_and_frequent_occlusion_rejected(self):
        for bad in ({0}, {30}, set(range(12, 18)), set(range(2, 29, 3))):
            with self.subTest(bad=bad):
                link = self.register(bad)
                self.assertEqual(link.sent[-1][0], 'reg_rejected')
                self.assertIsNone(link.payload)

    def store(self):
        store = CustomGestureStore(self.root/'missing.npz')
        times = np.linspace(0, 1, 31)
        seq = encode_sequence(times, [ordered_landmarks(pair(t)) for t in times])
        store.data.update(sequences=np.array([seq]), sequence_names=np.array(['clap']),
                          motions=np.array(['DYNAMIC']), hand_counts=np.array([2]), durations=np.array([1.0]))
        return store

    def test_runtime_one_hand_gap_preserves_candidate_and_completes(self):
        store = self.store()
        completed = []
        for i, t in enumerate(np.linspace(0, 1.05, 43)):
            hands = pair(min(t, 1))
            if i in (20, 21):
                hands = hands[:1]
            _, event, claimed, _ = store.update(hands, float(t))
            if i in (20, 21):
                self.assertTrue(claimed)
            if event:
                completed.append(event)
        self.assertEqual(completed, ['clap'])

    def test_runtime_long_gap_cannot_complete_old_motion(self):
        store = self.store()
        for t in np.linspace(0, 0.5, 21):
            store.update(pair(t), float(t))
        for t in np.linspace(0.525, 0.8, 12):
            self.assertIsNone(store.update(pair(t)[:1], float(t))[1])
        self.assertIsNone(store.update(pair(1), 1.0)[1])

    def test_no_template_does_not_claim_one_hand_gap(self):
        store = CustomGestureStore(self.root/'missing.npz')
        store.update(pair(0), 0)
        self.assertFalse(store.update(pair(0)[:1], 0.05)[2])


if __name__ == '__main__':
    unittest.main()
