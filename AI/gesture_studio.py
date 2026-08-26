# -*- coding: utf-8 -*-
"""커스텀 제스처 등록 스튜디오 (v0, 기획서 6번).

등록:  python gesture_studio.py
목록:  python gesture_studio.py --list
삭제:  python gesture_studio.py --remove 이름
시험:  python gesture_studio.py --test    (라이브로 분류 결과 확인)

등록 흐름: 이름 입력 → 3초 카운트다운 → 손모양 유지한 채 샘플 30장 수집
→ 혼동도 검사(기존 커스텀·내장 제스처와 겹치면 경고) → 저장
→ 원하면 실행할 앱을 지정해 gestures.json에 바로 연결.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from hands import CustomGestures, GestureEngine, normalize_landmarks
from main import open_camera

HERE = Path(__file__).parent
STORE = HERE / "custom_gestures.npz"
SAMPLES = 30
CONFUSION_DIST = 0.45  # 기존 클래스와 최근접 거리가 이보다 가까우면 등록 거부 (classify thresh 0.35보다 커야 함)
BUILTIN_OVERLAP = 0.20  # 내장 제스처로 인식된 샘플 비율이 이 이상이면 등록 거부


def collect_samples(camera_idx, seconds_countdown=3):
    gest = GestureEngine(HERE / "models" / "gesture_recognizer.task")
    cap = open_camera(camera_idx)
    feats, builtin_hits = [], {}
    t0 = time.monotonic()
    win = "gesture studio (ESC=abort)"
    try:
        while len(feats) < SAMPLES:
            ok, frame = cap.read()
            if not ok:
                sys.exit("카메라 프레임 읽기 실패")
            frame = cv2.flip(frame, 1)
            hand = gest.hand(frame)
            elapsed = time.monotonic() - t0
            counting = elapsed < seconds_countdown
            if not counting and hand:
                feats.append(normalize_landmarks(hand["landmarks"]))
                g = hand["gesture"]
                if g and g != "None":
                    builtin_hits[g] = builtin_hits.get(g, 0) + 1
            hud = cv2.resize(frame, (640, 360))
            if hand:
                for lx, ly in hand["landmarks"]:
                    cv2.circle(hud, (int(lx * 640), int(ly * 360)), 2, (80, 220, 80), -1)
            msg = (f"Get ready... {seconds_countdown - elapsed:.0f}" if counting
                   else f"Hold the pose  {len(feats)}/{SAMPLES}")
            cv2.putText(hud, msg, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 220, 80), 2)
            cv2.imshow(win, hud)
            if cv2.waitKey(1) & 0xFF == 27:
                sys.exit("중단됨")
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return np.array(feats), builtin_hits


def register(camera_idx):
    store = CustomGestures(STORE)
    name = input("제스처 이름 (영문/한글, 공백 없이): ").strip()
    if not name:
        sys.exit("이름이 비었습니다")
    if name in store.class_names():
        sys.exit(f"'{name}'은 이미 있습니다. --remove 후 다시 등록하세요.")
    print("카메라 앞에서 등록할 손모양을 만들고 유지하세요...")
    feats, builtin_hits = collect_samples(camera_idx)

    # 혼동도 검사 1: 내장 제스처와 겹침. 런타임은 내장이 우선이고 3프레임이면
    # 발화하므로, 20%만 겹쳐도 홀드 중 내장 액션이 튀어나온다 → 기준을 20%로 엄격히.
    for g, cnt in builtin_hits.items():
        if cnt >= SAMPLES * BUILTIN_OVERLAP:
            sys.exit(f"등록 거부: 이 손모양이 내장 제스처 '{g}'와 겹칩니다({cnt}/{SAMPLES}). "
                     "내장 7종(주먹·V·따봉 등)과 뚜렷이 다른 모양을 쓰세요.")
    # 혼동도 검사 2: 기존 커스텀 제스처와 겹침
    near, dist = store.nearest_class(feats)
    if near and dist < CONFUSION_DIST:
        sys.exit(f"등록 거부: 기존 '{near}'와 너무 비슷합니다 (거리 {dist:.2f} < {CONFUSION_DIST}). "
                 "다른 모양을 쓰세요.")
    # 샘플 자체 일관성 (손이 흔들렸으면 재시도 권고)
    spread = float(np.linalg.norm(feats - feats.mean(axis=0), axis=1).mean())
    if spread > 0.25:
        sys.exit(f"샘플이 너무 흩어졌습니다(spread {spread:.2f}) — 손모양을 고정하고 다시 시도하세요.")

    store.add(name, feats)
    print(f"등록 완료: {name} (샘플 {len(feats)}개"
          + (f", 최근접 기존 클래스 '{near}' 거리 {dist:.2f})" if near else ")"))

    app = input("이 제스처로 실행할 앱 (chrome/notepad/calc 등, 엔터=연결 안 함): ").strip()
    if app:
        gj = HERE / "gestures.json"
        data = json.loads(gj.read_text(encoding="utf-8"))
        data.setdefault("default", {})[name] = {"run": app, "label": name}
        gj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"gestures.json에 연결됨: {name} → {app} (assistant 재시작 후 적용)")


def live_test(camera_idx):
    store = CustomGestures(STORE)
    gest = GestureEngine(HERE / "models" / "gesture_recognizer.task")
    cap = open_camera(camera_idx)
    print(f"등록된 커스텀 제스처: {store.class_names() or '없음'} — ESC로 종료")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            hand = gest.hand(frame)
            label = "-"
            if hand:
                g = hand["gesture"]
                label = g if g and g != "None" else (store.classify(hand["landmarks"]) or "-")
                if g in (None, "None") and label != "-":
                    label += " (custom)"
            hud = cv2.resize(frame, (640, 360))
            cv2.putText(hud, str(label), (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (80, 220, 80), 2)
            cv2.imshow("gesture test (ESC=quit)", hud)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove", metavar="이름")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()
    if args.list:
        s = CustomGestures(STORE)
        print("등록된 커스텀 제스처:", s.class_names() or "없음",
              f"(샘플 총 {s.n}개)" if s.n else "")
    elif args.remove:
        s = CustomGestures(STORE)
        s.remove(args.remove)
        print(f"삭제됨: {args.remove} (gestures.json의 연결은 직접 지우세요)")
    elif args.test:
        live_test(args.camera)
    else:
        register(args.camera)
