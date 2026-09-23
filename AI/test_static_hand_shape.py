import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from static_hand_shape import hand_shape, shape_distances
from hands import normalize_landmarks
from custom_motion import CustomGestureStore, read_templates, template_bytes
from gesture_be import GestureRegistration, GestureTemplateCache
from test_custom_motion import Link

CASES = {r['source']: r for r in json.loads(
    (Path(__file__).parent/'testdata/builtin_finger_poses.json').read_text())['cases']}


class StaticShapeTests(unittest.TestCase):
    def payload(self, name='custom', source='rock'):
        row = CASES[source]
        xy = np.asarray(row['landmarks'][0])[:, :2]
        shape = hand_shape(row['world'][0])
        return GestureTemplateCache.template_bytes(name, [normalize_landmarks(xy)]*5, shapes=[shape]*5)

    def test_mirror_rotation_scale_translation_invariance(self):
        for row in CASES.values():
            w = np.asarray(row['world'][0])
            a = hand_shape(w)
            self.assertIsNotNone(a)
            for matrix in [np.diag([-1,1,1]), np.diag([-1,1,-1]),
                           np.array([[0,0,1],[0,1,0],[-1,0,0]])]:
                b = hand_shape((w@matrix)*3 + 4)
                self.assertLess(float(shape_distances(a,b)), 1e-5)

    def test_different_finger_shapes_not_merged(self):
        names = ['peace','one','rock','two_up','middle_finger','three2',
                 'fist','palm','call','grip','four']
        for i,a in enumerate(names):
            for b in names[i+1:]:
                with self.subTest(a=a,b=b):
                    self.assertGreater(float(shape_distances(hand_shape(CASES[a]['world'][0]),
                        hand_shape(CASES[b]['world'][0]))), .45)

    def test_up_down_direction_is_not_erased(self):
        w = np.asarray(CASES['like']['world'][0])
        self.assertGreater(float(shape_distances(hand_shape(w), hand_shape(w*[1,-1,-1]))), .45)

    def test_runtime_and_duplicate_use_same_score_after_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'all.npz'
            p.write_bytes(template_bytes(read_templates(self.payload(), name='custom')))
            store = CustomGestureStore(p)
            w = np.asarray(CASES['rock']['world'][0])*[-1,1,-1]
            xy = np.asarray(CASES['rock']['landmarks'][0])[:, :2]
            runtime = store.classify_with_distance(xy, world_landmarks=w)
            duplicate = store.nearest_class([normalize_landmarks(xy)], shapes=[hand_shape(w)])
            self.assertEqual(runtime[0], 'custom')
            self.assertEqual(runtime, duplicate)
            self.assertIsNone(store.classify_with_distance(xy, disabled=['custom'], world_landmarks=w)[0])

    def test_legacy_compatibility_and_missing_world(self):
        xy = np.asarray(CASES['rock']['landmarks'][0])[:, :2]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'legacy.npz'
            p.write_bytes(GestureTemplateCache.template_bytes('legacy',[normalize_landmarks(xy)]*5))
            store = CustomGestureStore(p)
            self.assertFalse(store.legacy.static_shape_valid.any())
            self.assertEqual(store.classify_with_distance(xy)[0], 'legacy')
        self.assertIsNone(hand_shape(np.zeros((21,3))))
        self.assertIsNone(hand_shape(None))

    def register(self, root, replace=False):
        p = root/'all.npz'; p.write_bytes(self.payload())
        link = Link()
        reg = GestureRegistration(link, GestureTemplateCache(root/'cache', p), CustomGestureStore(p))
        row = CASES['rock']
        xy = np.asarray(row['landmarks'][0])[:, :2]
        with contextlib.redirect_stdout(io.StringIO()), patch('gesture_be.save_registration_diagnostic',return_value=None):
            reg.start(dict(tempId='test',motion='STATIC',takes=3),now=0)
            if replace: reg.replace_gesture_name='custom'
            for take in range(1,4):
                reg.take=take
                for t in np.linspace(0,.4,12):
                    w=np.asarray(row['world'][0])*([-1,1,-1] if take%2 else [1,1,1])
                    reg._collect([dict(landmarks=xy,world_landmarks=w,handedness='Left',gesture=None)],take*4+t)
            reg.phase='WAIT_FINISH';reg.finish()
        return link

    def test_duplicate_rejected_and_self_replacement_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            link=self.register(Path(tmp))
            self.assertEqual(link.sent[-1][0],'reg_rejected')
            self.assertEqual(link.sent[-1][1].get('similarTo'),'custom')
            self.assertIsNone(link.payload)
        with tempfile.TemporaryDirectory() as tmp:
            link=self.register(Path(tmp),replace=True)
            self.assertEqual(link.sent[-1][0],'reg_captured',link.sent[-1])
            self.assertTrue(read_templates(link.payload)['static_shape_valid'].all())


if __name__=='__main__': unittest.main()
