"""공개 손 사진/저장 촬영 좌표로 커스텀 등록을 재현한다. 서버/사용자 저장소에는 쓰지 않는다."""
import argparse
import contextlib
import io
import json
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from custom_motion import CustomGestureStore
from evaluate_builtin_finger_pose import grid_cells, padded, read_image
from gesture_be import GestureRegistration, GestureTemplateCache
from hands import GestureEngine


HERE = Path(__file__).resolve().parent


class LocalLink:
    def __init__(self):
        self.events = []
        self.payload = None

    def send_event(self, event, payload):
        self.events.append((event, payload))

    def put_gesture_npz(self, temp_id, payload):
        self.payload = payload


def register(takes, motion, store_path=None):
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        root = Path(tmp)
        link = LocalLink()
        reg = GestureRegistration(link, GestureTemplateCache(root/'cache', root/'all.npz'),
                                  CustomGestureStore(store_path or root/'empty.npz'))
        reg.start(dict(tempId='offline', motion=motion, takes=len(takes)), now=0)
        for index, frames in enumerate(takes, 1):
            reg.take = index
            for t, hands in frames:
                reg._collect(hands, float(t))
        reg.phase = 'WAIT_FINISH'
        reg.finish()
        event, data = link.events[-1]
        return dict(event=event, **data), link.payload


def replay_diagnostic(path):
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(data['metadata'].item())
        takes = {}
        cursor = 0
        for take, _, t, count in data['frames']:
            hands = []
            for i in range(int(count)):
                hands.append(dict(landmarks=data['landmarks'][cursor].copy(),
                                  handedness=str(data['handedness'][cursor]), gesture=None))
                cursor += 1
            takes.setdefault(int(take), []).append((float(t), hands))
        result, _ = register(list(takes.values()), meta['motion'])
        return dict(source=path.name, motion=meta['motion'], previous_outcome=meta['outcome'],
                    previous_reason=meta['reason'], result=result,
                    scope='saved 2D coordinates; original classifier labels unavailable')


def evaluate(assets, logs):
    photos = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, image in grid_cells(read_image(assets/'gestures.png')):
            engine = GestureEngine(HERE/'models/gesture_recognizer.task')
            try:
                frame = padded(image, round(len(image)*1.5))
                observations = [engine.hands(frame, i*33) for i in range(45)]
            finally:
                engine.close()
            takes = [[(i/30, hands) for i, hands in enumerate(observations[j:j+15])]
                     for j in range(0, 45, 15)]
            result, payload = register(takes, 'STATIC')
            row = dict(source=name, result=result,
                       raw_labels=dict(Counter(h['model_gesture'] for hs in observations for h in hs)),
                       labels=dict(Counter(h['gesture'] for hs in observations for h in hs)))
            if payload:
                path = root/(name+'.npz')
                path.write_bytes(payload)
                duplicate, _ = register(takes, 'STATIC', path)
                row['duplicate'] = duplicate
            photos.append(row)
    recordings = [replay_diagnostic(p) for p in sorted(logs.glob('*.npz'))]
    return dict(scope='offline real model on public photos + saved coordinate replay, local fake upload',
                photos=photos, recordings=recordings)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=HERE/'.gesture_research')
    parser.add_argument('--logs', type=Path, default=HERE/'logs/gesture_registration')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.assets, args.logs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in report['photos']:
        print(row['source'], row['result']['event'], ascii(row['result'].get('reason')), row['labels'])
    for row in report['recordings']:
        if row['previous_outcome'] == 'captured':
            print(row['source'], row['motion'], row['result']['event'], ascii(row['result'].get('reason')))
