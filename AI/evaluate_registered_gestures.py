"""저장 템플릿 좌표 재생 평가. 실제 카메라/BE 명령은 사용하지 않는다."""
import argparse
import contextlib
import hashlib
import io
import json
import time
from pathlib import Path

import numpy as np

from custom_motion import CustomGestureStore, EXTRA_KEYS
from hands import GestureEngine, GestureStable, HoldToggle, SwipeDetector, SCREEN_SWIPE_CONFIG


BUILTINS = ['Closed_Fist', 'Open_Palm', 'Pointing_Up', 'Thumb_Down', 'Thumb_Up', 'Victory', 'ILoveYou']


def replay(store, seq, count, duration, speed=1.0, mirror=False):
    store.reset_motion()
    events, costs = [], []
    span = float(duration) * speed
    # 최대 30Hz, 종료 후 0.3초 유지. 학습 좌표를 화면 좌표로 역변환한다.
    for t in np.arange(0, span + 0.3, 1/30):
        pos = min(t/span, 1) * (len(seq)-1)
        lo, hi = int(pos), min(int(pos)+1, len(seq)-1)
        points = (seq[lo, :count]*(hi-pos) + seq[hi, :count]*(pos-lo)
                  if hi != lo else seq[lo, :count].copy())
        if mirror:
            points = points.copy()
            points[0, :, 0] = 2*points[0, 0, 0]-points[0, :, 0]
        points = points * 0.12 + [0.5, 0.6]
        hands = [dict(landmarks=p, handedness=('Right' if mirror else 'Left') if count == 1 else ['Left','Right'][i]) for i,p in enumerate(points)]
        start=time.perf_counter()
        held,event,_,_=store.update(hands,float(t))
        costs.append((time.perf_counter()-start)*1000)
        if held and (not events or events[-1] != held): events.append(held)
        if event: events.append(event)
    return events, float(np.percentile(costs,95))


def evaluate(path):
    path=Path(path)
    original=path.read_bytes()
    store=CustomGestureStore(path)
    rows=[]
    for i,(seq,name,motion,count,duration) in enumerate(zip(*(store.data[k] for k in EXTRA_KEYS))):
        name=str(name); count=int(count)
        variants=[('original',1,False)]
        if motion == 'DYNAMIC': variants += [('duration_0.7',0.7,False),('duration_1.3',1.3,False)]
        if count == 1: variants += [('opposite_hand',1,True)]
        for variant,speed,mirror in variants:
            events,cost=replay(store,seq,count,duration,speed,mirror)
            rows.append(dict(name=name,template=i,motion=str(motion),variant=variant,
                             expected=name,events=events,passed=events==[name],p95_update_ms=round(cost,3)))
        # 저장 예시 자체를 맞히는 것과 구분하기 위해 해당 회차를 후보에서 제외한다.
        if sum(store.data['sequence_names']==name)>1:
            saved=store.data
            store.data={k:(v[np.arange(len(v)) != i] if k in EXTRA_KEYS else v) for k,v in saved.items()}
            try:
                events,cost=replay(store,seq,count,duration)
            finally:
                store.data=saved
            rows.append(dict(name=name,template=i,motion=str(motion),variant='leave_one_take_out',expected=name,
                             events=events,passed=events==[name],p95_update_ms=round(cost,3)))
    # 정적 레거시: 저장 특징을 역변환하고 좌우 각각 분류한다.
    for i,(feature,name) in enumerate(zip(store.legacy.X,store.legacy.names)):
        for mirror in (False,True):
            points=feature.reshape(21,2).copy()
            if mirror: points[:,0]*=-1
            predicted,score=store.classify_with_distance(points*0.12+[0.5,0.6])
            rows.append(dict(name=name,template=i,motion='STATIC_LEGACY',variant='opposite_hand' if mirror else 'original',
                             expected=name,events=[predicted] if predicted else [],passed=predicted==name,distance=float(score)))
    builtins=[]
    for label in BUILTINS:
        stable,hold=GestureStable(min_frames=3),HoldToggle(hold_s=0.6,cooldown_s=1.5)
        fired=sum(hold.update(stable.update(label,float(t))==label,float(t)) for t in np.linspace(0,1,31))
        builtins.append(dict(name=label,scope='injected_label_hold_only',passed=fired==1,events=fired,
                             camera_recognition='NOT_TESTED'))
    for sign,name in [(-1,'Swipe_Left'),(1,'Swipe_Right')]:
        for size in (0.06,0.12,0.18):
            detector=SwipeDetector(**SCREEN_SWIPE_CONFIG); events=[]
            for t in np.linspace(0,1,61):
                x=0.5+sign*size*2*np.clip((t-0.5)/0.3,0,1)
                event=detector.update((x,0.5),float(t),size=size)
                if event: events.append(event)
            builtins.append(dict(name=name,scope='synthetic_motion',size=size,passed=events==[name],events=events,
                                 camera_recognition='NOT_TESTED'))
    model_log=io.StringIO(); model={}
    engine=None
    try:
        with contextlib.redirect_stdout(model_log):
            engine=GestureEngine(Path(__file__).parent/'models'/'gesture_recognizer.task')
            detections=[engine.hands(np.zeros((480,640,3),np.uint8),i*33) for i in range(30)]
        model=dict(loaded=True,blank_frames=30,hand_detections=sum(map(len,detections)),
                   inference_errors=model_log.getvalue().count('[제스처 추론 오류'))
    except Exception as exc:
        model=dict(loaded=False,error=str(exc))
    finally:
        if engine: engine.close()
    assert path.read_bytes()==original, 'Evaluation must not modify user templates'
    return dict(template_file=str(path),sha256=hashlib.sha256(original).hexdigest(),
                scope='saved-coordinate replay, synthetic motion, injected labels; no real camera/BE/FE',
                model=model,builtins=builtins,custom=rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--templates',default=str(Path(__file__).parent/'be_custom_gestures.npz'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=evaluate(args.templates)
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in sorted({r['name'] for r in result['custom']}):
        rows=[r for r in result['custom'] if r['name']==name]
        print(ascii(name),sum(r['passed'] for r in rows),'/',len(rows))
    print('model=',result['model'])
