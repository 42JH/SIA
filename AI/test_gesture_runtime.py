"""카메라와 서버 없이 인식기 수명 및 등록 실패 처리를 검증한다."""
import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tempfile
from urllib.error import URLError

import numpy as np

from hands import GestureEngine, MotionHandTracker, SwipeDetector, SCREEN_SWIPE_CONFIG
from gesture_be import GestureRegistration, GestureTemplateCache, sync_gesture_store


class GestureRuntimeTests(unittest.TestCase):
    def test_swipe_requires_return_or_stillness(self):
        for sign in (1, -1):
            with self.subTest(sign=sign):
                detector = SwipeDetector(**SCREEN_SWIPE_CONFIG)
                tick = 0

                def feed(xs):
                    nonlocal tick
                    events = []
                    for x in xs:
                        tick += 1
                        event = detector.update((.5 + sign * x, .5), tick * .05)
                        if event:
                            events.append(event)
                    return events

                forward = 'Swipe_Right' if sign == 1 else 'Swipe_Left'
                backward = 'Swipe_Left' if sign == 1 else 'Swipe_Right'
                self.assertEqual(feed([-.4] * 10), [])
                # 정지나 복귀 없이 길게 움직여도 한 번만 실행한다.
                self.assertEqual(feed([-.4 + i * .02 for i in range(1, 41)]), [forward])
                # 작은 흔들림은 재준비로 취급하지 않는다.
                self.assertEqual(feed([.39, .4] * 8), [])
                # 충분히 복귀한 후 같은 방향은 정지 없이 반복할 수 있다.
                self.assertEqual(feed([.4 - i * .04 for i in range(1, 11)]), [])
                self.assertEqual(feed([i * .03 for i in range(1, 9)]), [forward])
                # 복귀 없는 정지로도 새로운 반대 방향 명령을 받을 수 있다.
                self.assertEqual(feed([.24] * 12), [])
                self.assertEqual(feed([.24 - i * .03 for i in range(1, 9)]), [backward])

    def test_sync_readiness_only_after_success(self):
        link = SimpleNamespace(gesture_ready=False)
        cache = Mock(combined_path='unused')
        cache.sync.side_effect = lambda *args: self.assertFalse(link.gesture_ready)
        with patch('gesture_be.CustomGestureStore') as store:
            store.side_effect = lambda *args: self.assertFalse(link.gesture_ready) or Mock()
            sync_gesture_store(link, cache, [], start_recognition=True)
            self.assertTrue(link.gesture_ready)
            cache.sync.side_effect = URLError('offline')
            with self.assertRaises(URLError):
                sync_gesture_store(link, cache, [])
            self.assertFalse(link.gesture_ready)
            cache.sync.side_effect = None
            store.side_effect = ValueError('invalid template')
            with self.assertRaises(ValueError):
                sync_gesture_store(link, cache, [], start_recognition=True)
            self.assertFalse(link.gesture_ready)

    def test_empty_remote_list_stays_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = GestureTemplateCache(root / 'cache', root / 'remote.npz')
            # 기존 원격 캐시를 실제로 삭제한 뒤 빈 저장소가 로드되는지 확인한다.
            payload = cache.template_bytes('old', np.zeros((1, 42)))
            link = Mock(gesture_ready=True)
            link.get_gesture_npz.return_value = (payload, 'hash')
            populated = sync_gesture_store(link, cache, [{'id': 1, 'name': 'old', 'sha256': 'hash'}])
            self.assertEqual(populated.class_names(), ['old'])
            empty = sync_gesture_store(link, cache, [])
            self.assertEqual(empty.n, 0)
            self.assertEqual(empty.class_names(), [])
            self.assertTrue(link.gesture_ready)

    def test_finish_event_requires_current_registration_id(self):
        reg = GestureRegistration(Mock(), None, None)
        reg.start({'tempId': 'current'}, now=0)
        reg.finish = Mock()
        for temp_id in ('previous', None, ''):
            reg.finish_for(temp_id)
        reg.finish.assert_not_called()
        self.assertTrue(reg.active)
        reg.finish_for('current')
        reg.finish.assert_called_once()

    @staticmethod
    def hand(side, x):
        return {'handedness': side, 'anchor': (x, 0.5)}

    def motion_events(self, frames):
        tracker = MotionHandTracker()
        swipe = SwipeDetector(**SCREEN_SWIPE_CONFIG)
        events = []
        for i, hands in enumerate(frames):
            now = i * 0.05
            hand, changed = tracker.update(hands)
            if changed:
                swipe.update(None, now)
            event = swipe.update(hand['anchor'] if hand else None, now)
            if event:
                events.append(event)
        return events

    def test_stationary_hands_reordering_does_not_swipe(self):
        left, right = self.hand('Left', .2), self.hand('Right', .8)
        frames = [[left, right]] * 8 + [[right, left], [left, right]] * 10
        self.assertEqual(self.motion_events(frames), [])

    def test_reordered_moving_hand_still_swipes(self):
        left, right = self.hand('Left', .2), self.hand('Right', .8)
        frames = [[left, right]] * 8 + [[right, self.hand('Left', x)] for x in (.25, .3, .36)]
        self.assertEqual(self.motion_events(frames), ['Swipe_Right'])

    def test_replacement_loss_and_ambiguous_labels_reset_motion(self):
        left, right = self.hand('Left', .2), self.hand('Right', .8)
        for transition in ([right], [], [self.hand('Unknown', .8)],
                           [left, self.hand('Left', .8)]):
            with self.subTest(transition=transition):
                frames = [[left]] * 8 + [transition] + [[right]] * 8
                self.assertEqual(self.motion_events(frames), [])

    def test_remote_gesture_dispatch_respects_no_actions(self):
        # 앱을 실행하지 않고 실제 정적·동적 전송 분기를 추출해 실행한다.
        tree = ast.parse(Path(__file__).with_name('assistant.py').read_text(encoding='utf-8'))
        branches = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                    and ast.unparse(node.test) == 'link and link.gesture_ready and be_target']
        self.assertEqual(len(branches), 2)
        for branch in branches:
            code = compile(ast.Module(body=[branch], type_ignores=[]), 'assistant.py', 'exec')
            for no_actions in (True, False):
                for be_only in (True, False):
                    with self.subTest(line=branch.lineno, no_actions=no_actions, be_only=be_only):
                        link, overlay, foreground = Mock(), Mock(), Mock(return_value=123)
                        env = dict(link=link, overlay=overlay, foreground_hwnd=foreground,
                                   args=SimpleNamespace(no_actions=no_actions, be_gesture_only=be_only),
                                   be_target=('Victory', 'youtube'), name='Victory',
                                   dynamic_event='Screen_Next', context='youtube', now=10,
                                   usage_events=[], uuid=Mock(), custom_score=None,
                                   time=SimpleNamespace(time=lambda: 10), print=Mock())
                        exec(code, env)
                        if no_actions:
                            link.send_event.assert_not_called()
                            foreground.assert_not_called()
                            overlay.toast.assert_called_once()
                        else:
                            link.send_event.assert_called_once_with(
                                'gesture_exec', {'name': 'Victory', 'hwnd': 123, 'context': 'youtube'})

    def engine(self):
        engine = GestureEngine.__new__(GestureEngine)
        engine.recognizer = Mock()
        engine._closed = False
        engine._last_ts = 0
        return engine

    def test_close_once_and_reject_later_inference(self):
        engine = self.engine()
        engine.close()
        engine.close()
        engine.recognizer.close.assert_called_once()
        with self.assertRaises(RuntimeError):
            engine.hands(np.zeros((8, 8, 3), np.uint8))
        engine.recognizer.recognize_for_video.assert_not_called()

    def test_invalid_frames_never_reach_native_inference(self):
        engine = self.engine()
        for frame in (None, np.zeros((0, 8, 3), np.uint8),
                      np.zeros((8, 8), np.uint8), np.zeros((8, 8, 4), np.uint8),
                      np.zeros((8, 8, 3), np.float32)):
            with self.subTest(shape=getattr(frame, 'shape', None)):
                with self.assertRaises(ValueError):
                    engine.hands(frame)
        engine.recognizer.recognize_for_video.assert_not_called()

    def test_upload_failure_rejects_and_resets_registration(self):
        for error in (URLError('offline'), TimeoutError('timeout'), RuntimeError('no runtime')):
            with self.subTest(error=type(error).__name__):
                link = Mock()
                reg = GestureRegistration(link, None, None)
                reg.start({'tempId': 'failed-upload'}, now=0)
                reg.phase = 'WAIT_FINISH'
                reg._validate_and_upload = Mock(side_effect=error)
                reg.finish()
                self.assertFalse(reg.active)
                event, payload = link.send_event.call_args.args
                self.assertEqual(event, 'reg_rejected')
                self.assertEqual(payload['tempId'], 'failed-upload')
                # 원본 예외 문구(예: "<urlopen error offline>")가 아니라 사용자가
                # 알아볼 수 있는 안내 문구여야 한다.
                self.assertNotIn(str(error), payload['reason'])
                self.assertIn('네트워크', payload['reason'])


if __name__ == '__main__':
    unittest.main()
