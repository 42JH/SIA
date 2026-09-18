"""등록 진단 좌표/비교 결과 저장. 영상은 저장하지 않고 기존 템플릿은 읽기만 한다."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def save_registration_diagnostic(registration, outcome, reason):
    cache_dir = getattr(registration.cache, 'cache_dir', None)
    if not isinstance(cache_dir, (str, Path)):
        return None
    folder = Path(cache_dir).parent / 'logs' / 'gesture_registration'
    folder.mkdir(parents=True, exist_ok=True)
    frame_rows, points, labels = [], [], []
    gestures, scores = [], []
    model_gestures, model_scores, verifications, world_points = [], [], [], []
    for take, frames in registration.take_frames.items():
        start = frames[0][0] if frames else 0
        for index, (t, hands) in enumerate(frames):
            # 미검출 프레임도 별도 테이블에 기록해 추적 공백을 재현한다.
            frame_rows.append((take, index, t - start, len(hands)))
            for hand in hands:
                points.append(np.asarray(hand['landmarks'], dtype=np.float32))
                labels.append(str(hand.get('handedness', 'Unknown')))
                gestures.append(str(hand.get('gesture') or 'None'))
                score = hand.get('score')
                scores.append(float(score) if score is not None else np.nan)
                model_gestures.append(str(hand.get('model_gesture', hand.get('gesture')) or 'None'))
                model_score = hand.get('model_score', score)
                model_scores.append(float(model_score) if model_score is not None else np.nan)
                verifications.append(hand.get('pose_verification', 'model'))
                world = hand.get('world_landmarks')
                world_points.append(world if world is not None else np.full((21, 3), np.nan))
    metadata = dict(version=3, created_at=datetime.now(timezone.utc).isoformat(),
                    tempId=registration.temp_id, motion=registration.motion,
                    outcome=outcome, reason=reason, threshold=registration.COLLISION_DIST,
                    comparisons=registration.comparison_diagnostics,
                    builtin_hits=registration.builtin_hits,
                    builtin_uncertain=getattr(registration, 'builtin_uncertain', 0),
                    sample_count=len(registration.samples))
    arrays = dict(metadata=np.array(json.dumps(metadata, ensure_ascii=False)),
                  frames=np.asarray(frame_rows, dtype=np.float64).reshape(-1, 4),
                  landmarks=np.asarray(points, dtype=np.float32).reshape(-1, 21, 2),
                  handedness=np.asarray(labels, dtype='U16'),
                  gestures=np.asarray(gestures, dtype='U32'),
                  gesture_scores=np.asarray(scores, dtype=np.float32),
                  model_gestures=np.asarray(model_gestures, dtype='U32'),
                  model_scores=np.asarray(model_scores, dtype=np.float32),
                  pose_verifications=np.asarray(verifications, dtype='U32'),
                  world_landmarks=np.asarray(world_points, dtype=np.float32).reshape(-1, 21, 3))
    for key, value in getattr(registration.custom_store, 'data', {}).items():
        arrays['reference_' + key] = value
    path = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:12] + '.npz')
    np.savez_compressed(path, **arrays)
    return path
