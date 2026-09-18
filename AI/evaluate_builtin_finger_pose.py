"""공개 사진으로 실제 모델의 브이→검지 오류를 카메라/서버 없이 재현한다.

python evaluate_builtin_finger_pose.py --download --output report.json
사진은 .gesture_research에만 저장한다. 이후 --download 없이 오프라인 실행 가능.
변환 사진 수는 독립 인물 수가 아니며 실제 카메라 정확도로 해석하면 안 된다.
"""
import argparse
import contextlib
import hashlib
import io
import json
import tempfile
from collections import Counter
from pathlib import Path
from urllib.request import urlopen

import cv2
import numpy as np

from custom_motion import CustomGestureStore
from gesture_be import GestureRegistration, GestureTemplateCache
from hands import GestureEngine, GestureStable, HoldToggle, parse_hands


HERE = Path(__file__).resolve().parent
SOURCES = {
    **{name + '.jpg': 'https://storage.googleapis.com/mediapipe-assets/' + name + '.jpg'
       for name in ('victory', 'pointing_up', 'thumb_up', 'fist')},
    'gestures.png': 'https://raw.githubusercontent.com/hukenovs/hagrid/master/images/gestures.png',
}
GRID = [
    ['call', 'dislike', 'fist', 'four', 'like', 'mute', 'grabbing', 'grip'],
    ['ok', 'one', 'palm', 'peace', 'peace_inverted', 'rock', 'point', 'pinkie'],
    ['stop', 'stop_inverted', 'three', 'three2', 'two_up', 'two_up_inverted', 'middle_finger', 'three3'],
]


def read_image(path):
    image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Cannot decode {path}')
    return image


def padded(image, side):
    h, w = image.shape[:2]
    frame = np.full((side, side, 3), 255, np.uint8)
    frame[(side-h)//2:(side-h)//2+h, (side-w)//2:(side-w)//2+w] = image
    return frame


def transform(base, angle, mirror, scale=1):
    side = len(base)
    frame = cv2.warpAffine(base, cv2.getRotationMatrix2D((side/2, side/2), angle, scale),
                           (side, side), borderValue=(255, 255, 255))
    return cv2.flip(frame, 1) if mirror else frame


def grid_cells(image):
    for y, names in enumerate(GRID):
        for x, name in enumerate(names):
            x0 = round((130 + 225.2*x) * image.shape[1]/2048)
            y0 = round((72 + 276*y) * image.shape[0]/1118)
            size = round(211 * image.shape[1]/2048)
            yield name, image[y0:y0+size, x0:x0+size]


def image_variants(assets):
    for name in ('victory', 'pointing_up', 'thumb_up', 'fist'):
        image = read_image(assets/(name+'.jpg'))
        base = padded(image, int(np.hypot(*image.shape[:2])))
        for angle in (-90, -60, -30, 0, 30, 60, 90, 180):
            for mirror in (False, True):
                for scale in (.4, .7, 1.):
                    yield dict(group='mediapipe', source=name, angle=angle, mirror=mirror, scale=scale), transform(base, angle, mirror, scale)
    for name, image in grid_cells(read_image(assets/'gestures.png')):
        base = padded(image, round(len(image)*1.5))
        for angle in (-90, -60, -30, 0, 30, 60, 90):
            for mirror in (False, True):
                yield dict(group='hagrid', source=name, angle=angle, mirror=mirror), transform(base, angle, mirror)
    # 정면 사진의 가로 압축은 실제 측면 촬영과 같지 않다. 별도 스트레스 검사다.
    image = read_image(assets/'victory.jpg')
    h, w = image.shape[:2]
    for squeeze in (.25, .4, .6, .8, 1.):
        for angle in (-60, -45, -30, -15, 0, 15, 30, 45, 60):
            for mirror in (False, True):
                for scale in (1., .4):
                    resized = cv2.resize(image, (int(w*squeeze*scale), int(h*scale)))
                    yield dict(group='stress', source='victory', angle=angle, mirror=mirror,
                               scale=scale, squeeze=squeeze), transform(padded(resized, 600), angle, mirror)


def register_frames(observations, raw):
    class Link:
        def __init__(self):
            self.events = []
            self.uploaded = False

        def send_event(self, event, data):
            self.events.append((event, data))

        def put_gesture_npz(self, *args):
            self.uploaded = True

    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        root = Path(tmp)
        link = Link()
        reg = GestureRegistration(link, GestureTemplateCache(root/'cache', root/'all.npz'),
                                  CustomGestureStore(root/'empty.npz'))
        reg.start(dict(tempId='offline-repro', motion='STATIC', takes=3), now=0)
        for i, hands in enumerate(observations):
            reg.take = i//15 + 1
            if raw:
                hands = [dict(h, gesture=h['model_gesture'], score=h['model_score'],
                              pose_verification='model') for h in hands]
            reg._collect(hands, reg.take*3 + (i % 15)/30)
        reg.phase = 'WAIT_FINISH'
        reg.finish()
        return dict(event=link.events[-1][0], payload=link.events[-1][1], uploaded=link.uploaded)


def evaluate(assets):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import GestureRecognizer, GestureRecognizerOptions, RunningMode

    model = HERE/'models/gesture_recognizer.task'
    rows = []
    options = GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_buffer=model.read_bytes()),
        running_mode=RunningMode.IMAGE, num_hands=2,
        min_hand_detection_confidence=.3, min_hand_presence_confidence=.3, min_tracking_confidence=.3)
    with GestureRecognizer.create_from_options(options) as recognizer:
        for metadata, frame in image_variants(assets):
            result = recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB,
                                                   data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
            hands = parse_hands(result)
            rows.append(dict(**metadata, before=[h['model_gesture'] for h in hands],
                             after=[h['gesture'] for h in hands],
                             model_scores=[h['model_score'] for h in hands],
                             decisions=[h['pose_verification'] for h in hands]))

    # IMAGE mode뿐 아니라 실제 앱의 VIDEO→파서→등록/홀드 판정도 실행한다.
    crop = dict(grid_cells(read_image(assets/'gestures.png')))['peace_inverted']
    frame = transform(padded(crop, round(len(crop)*1.5)), -30, True)
    engine = GestureEngine(model)
    try:
        observations = [engine.hands(frame, i*33) for i in range(45)]
    finally:
        engine.close()
    video = dict(
        frames=45,
        before=dict(Counter(h['model_gesture'] for hands in observations for h in hands)),
        after=dict(Counter(h['gesture'] for hands in observations for h in hands)),
        registration_before=register_frames(observations, raw=True),
        registration_after=register_frames(observations, raw=False))
    stable = GestureStable(min_frames=3)
    toggles = {label: HoldToggle(hold_s=.7, cooldown_s=2) for label in ('Victory', 'Pointing_Up')}
    events = []
    for i, hands in enumerate(observations):
        now = i/30
        label = stable.update(hands[0]['gesture'] if hands else 'None', now)
        events.extend(name for name, toggle in toggles.items() if toggle.update(name == label, now))
    video['execution_events'] = events
    video['passed'] = (video['before'] == {'Pointing_Up': 45} and video['after'] == {'Victory': 45}
                       and video['registration_before']['payload'].get('similarTo') == 'Pointing_Up'
                       and video['registration_after']['payload'].get('similarTo') == 'Victory'
                       and events == ['Victory'])
    return dict(
        scope='Public example photos + deterministic transforms, not camera/population accuracy',
        mediapipe_version=mp.__version__, model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        sources={name: dict(url=url, sha256=hashlib.sha256((assets/name).read_bytes()).hexdigest())
                 for name, url in SOURCES.items()},
        image_cases=len(rows), changes=[r for r in rows if r['before'] != r['after']],
        video=video, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=HERE/'.gesture_research')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.assets.mkdir(parents=True, exist_ok=True)
    if args.download:
        for name, url in SOURCES.items():
            if not (args.assets/name).exists():
                with urlopen(url, timeout=30) as response:
                    (args.assets/name).write_bytes(response.read())
    report = evaluate(args.assets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(image_cases=report['image_cases'], changes=len(report['changes']),
                          video=report['video']), ensure_ascii=True, indent=2))
    return 0 if report['video']['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
