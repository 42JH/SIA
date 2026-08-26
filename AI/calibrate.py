# -*- coding: utf-8 -*-
"""시선 캘리브레이션 (기본 4x3 그리드 x 2라운드, 약 1분).

전체화면에 점을 순서대로 띄우고, 각 점을 응시하는 동안 특징을 수집해서
2차 ridge 회귀를 학습한다. 2라운드는 자세를 살짝 바꿔서 진행 — 머리 위치
변화에 대한 보정을 회귀가 배우게 하는 것이 목적. 학습 후 처음 보는 5개
지점으로 실제 오차(px)를 측정해 리포트한다. 결과는 models/calib.npz.

실행:  python calibrate.py        (ESC로 중단)
옵션:  --grid 3x3  --rounds 1  --camera 1
"""
import argparse
import os
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from gaze import Calibrator, make_engine
from main import open_camera  # 해상도 설정 포함 — 캘리브레이션과 런타임이 반드시 같은 카메라 조건

HERE = Path(__file__).parent
SETTLE_S = 0.8   # 점 이동 후 눈이 도착할 시간
COLLECT_S = 0.9  # 샘플 수집 시간


def grid_points(cols, rows, w, h, margin=0.08):
    xs = np.linspace(margin, 1 - margin, cols) * w
    ys = np.linspace(margin, 1 - margin, rows) * h
    return [(int(x), int(y)) for y in ys for x in xs]


def show_message(win, sw, sh, lines, seconds):
    """전체화면에 안내 문구를 잠깐 표시. ESC면 종료."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        canvas = np.zeros((sh, sw, 3), dtype=np.uint8)
        for i, line in enumerate(lines):
            cv2.putText(canvas, line, (sw // 8, sh // 2 + i * 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        cv2.imshow(win, canvas)
        if cv2.waitKey(30) & 0xFF == 27:
            sys.exit("중단됨")


def collect_point(cap, face, win, sw, sh, px, py, label, on_sample):
    """점 하나를 띄우고 SETTLE 후 COLLECT 동안 프레임마다 on_sample(features) 호출.
    수집된 프레임 수를 반환. ESC면 종료."""
    t0 = time.monotonic()
    collected = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            sys.exit("카메라 프레임 읽기 실패")
        frame = cv2.flip(frame, 1)  # main.py와 동일하게 미러링 (일관성 필수)
        f = face.features(frame)

        elapsed = time.monotonic() - t0
        canvas = np.zeros((sh, sw, 3), dtype=np.uint8)
        collecting = elapsed >= SETTLE_S
        if collecting and f is not None:
            on_sample(f)
            collected += 1
        # 점: 수집 중이면 초록, 대기 중이면 줄어드는 흰 원
        r = 14 if collecting else int(30 - 16 * min(1.0, elapsed / SETTLE_S))
        color = (80, 220, 80) if collecting else (255, 255, 255)
        cv2.circle(canvas, (px, py), r, color, -1)
        # cv2.putText는 한글 미지원 → 영문 안내
        cv2.putText(canvas, f"{label}  Look at the dot (ESC to abort)",
                    (40, sh - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (160, 160, 160), 2)
        cv2.imshow(win, canvas)
        if cv2.waitKey(1) & 0xFF == 27:
            sys.exit("중단됨")
        if elapsed >= SETTLE_S + COLLECT_S:
            return collected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="4x3", help="예: 3x3, 4x3, 5x3")
    ap.add_argument("--rounds", type=int, default=2, help="라운드 수 (라운드마다 자세를 살짝 바꿈)")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()
    cols, rows = (int(v) for v in args.grid.split("x"))

    import pyautogui

    sw, sh = pyautogui.size()
    face = make_engine(HERE / "models")  # 런타임과 동일 엔진 — 특징 차원 일치 필수
    cap = open_camera(args.camera)

    win = "calibration"
    cv2.namedWindow(win, cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    points = grid_points(cols, rows, sw, sh)
    feats, targets = [], []

    total = len(points) * args.rounds
    done = 0
    for rnd in range(args.rounds):
        if rnd == 0:
            show_message(win, sw, sh,
                         ["Sit comfortably. Follow the dots with your eyes.",
                          "Keep your head still-ish during a round."], 2.5)
        else:
            show_message(win, sw, sh,
                         [f"Round {rnd + 1}: shift your posture slightly",
                          "(lean a bit, or move your head a little)"], 3.0)
        order = points[:]
        random.shuffle(order)  # 순서 효과 제거
        for px, py in order:
            done += 1
            n = collect_point(cap, face, win, sw, sh, px, py, f"{done}/{total}",
                              lambda f, p=(px, py): (feats.append(f), targets.append(p)))
            if n < 5:
                print(f"경고: {done}번 점에서 얼굴 검출 {n}회뿐 — 조명/카메라 각도 확인")

    if len(feats) < 30:
        cap.release()
        cv2.destroyAllWindows()
        sys.exit(f"수집된 샘플이 {len(feats)}개뿐이라 학습 불가 — 조명을 밝게 하고 "
                 "카메라가 얼굴을 정면으로 보게 한 뒤 다시 실행하세요.")

    calib = Calibrator(sw, sh)
    # fit_base: 샘플을 calib.npz에 함께 보관 → 이후 클릭 재보정이 합산 학습에 사용
    rms = calib.fit_base(np.array(feats), np.array(targets))

    # --- 검증: 학습에 안 쓴 5개 지점에서 실제 오차 측정 ---
    show_message(win, sw, sh, ["Validation: 5 more dots", "to measure real accuracy"], 2.0)
    val_points = [(int(sw * x), int(sh * y))
                  for x, y in [(0.25, 0.25), (0.75, 0.25), (0.5, 0.5), (0.25, 0.75), (0.75, 0.75)]]
    errors = []
    for i, (px, py) in enumerate(val_points):
        preds = []
        collect_point(cap, face, win, sw, sh, px, py, f"check {i + 1}/5",
                      lambda f: preds.append(calib.predict(f)))
        if preds:
            med = np.median(np.array(preds), axis=0)
            errors.append(float(np.hypot(med[0] - px, med[1] - py)))

    cap.release()
    cv2.destroyAllWindows()

    # 저장은 검증까지 끝난 뒤 — 이전 캘리브레이션은 백업으로 보존 (망친 재캘리브레이션 복구용)
    out = HERE / "models" / "calib.npz"
    if out.exists():
        os.replace(out, HERE / "models" / "calib_backup.npz")
        print("이전 캘리브레이션 → models/calib_backup.npz (되돌리려면 파일명을 calib.npz로)")
    calib.save(out)
    clicks = HERE / "models" / "clicks.npz"
    if clicks.exists():
        clicks.unlink()  # 옛 지오메트리(자세·카메라 각도)의 클릭 샘플은 새 캘리브레이션을 오염시킨다
        print("누적 클릭 샘플 초기화 (새 캘리브레이션 기준으로 다시 쌓임)")

    print(f"저장: {out}")
    print(f"교차검증 예상 오차: {rms:.0f}px (λ={calib.lam:g}) — 아래 검증 오차와 비슷해야 정상")
    if errors:
        mean_err = float(np.mean(errors))
        cell = min(sw / 3, sh / 3) / 2  # 3x3 영역 판별에 필요한 반경
        print("검증 오차(px): " + ", ".join(f"{e:.0f}" for e in errors) + f"  → 평균 {mean_err:.0f}px")
        if mean_err < cell * 0.6:
            print(f"양호 — 3x3 영역 판별 기준({cell:.0f}px)을 여유 있게 통과. 데모 가능.")
        elif mean_err < cell:
            print(f"보통 — 영역 판별 기준({cell:.0f}px) 언저리. 워프 후 손 미세조정 전제로 사용 가능.")
        else:
            print(f"미달 — 기준({cell:.0f}px) 초과. 조명·카메라 위치(모니터 상단 중앙)를 고치고 재시도.")
    else:
        print("검증 실패: 얼굴 검출이 안 됐습니다.")


if __name__ == "__main__":
    main()
