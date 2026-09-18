# -*- coding: utf-8 -*-
"""커스텀 제스처 등록 스튜디오 (v0, 기획서 6번).

등록:  python gesture_studio.py
목록:  python gesture_studio.py --list
삭제:  python gesture_studio.py --remove 이름
시험:  python gesture_studio.py --test    (라이브로 분류 결과 확인)

등록 흐름: 이름 입력 → 3초 카운트다운 → 손모양 유지한 채 샘플 30장 수집
→ 혼동도 검사(기존 커스텀·내장 제스처와 겹치면 경고) → 저장 (품질 검증용 로컬
템플릿만 만들며, 실행 매핑은 BE 제스처 등록 UI에서 별도로 지정한다).
"""
import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from hands import (CustomGestures, FingerSwipeDetector, GestureEngine, GestureStable,
                   PalmControlMode, PinchVolumeDetector, PointerControlDetector,
                   SCREEN_SWIPE_CONFIG, SwipeDetector, normalize_landmarks, weighted_distance)
from main import open_camera

from paths import asset_path, data_path

STORE = data_path("custom_gestures.npz")
SAMPLES = 30
CONFUSION_DIST = 0.45  # 기존 클래스와 최근접 거리가 이보다 가까우면 등록 거부 (classify thresh 0.35보다 커야 함)
BUILTIN_OVERLAP = 0.20  # 내장 제스처로 인식된 샘플 비율이 이 이상이면 등록 거부
# 등록 중 손의 방향·크기가 계속 달라지면 한 자세를 대표하는 템플릿이 되기 어렵다.
# 화면 정규화 좌표 기준이며, 정상적인 미세 흔들림은 허용하는 초기값이다.
MIN_PALM_SIZE = 0.055
MAX_PALM_SIZE_CV = 0.20
MAX_ORIENTATION_STD_DEG = 20.0


def hand_quality(landmarks):
    """등록 품질용 손바닥 크기·방향을 계산한다."""
    wrist = landmarks[0]
    middle_mcp = landmarks[9]
    dx = middle_mcp[0] - wrist[0]
    dy = middle_mcp[1] - wrist[1]
    return float(np.hypot(dx, dy)), float(np.arctan2(dy, dx))


def registration_quality(sizes, angles):
    """원형 통계로 손 크기·방향의 등록 중 흔들림을 반환한다."""
    sizes = np.asarray(sizes, dtype=float)
    angles = np.asarray(angles, dtype=float)
    mean_angle = float(np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()))
    delta = np.arctan2(np.sin(angles - mean_angle), np.cos(angles - mean_angle))
    return {
        "min_palm_size": float(sizes.min()),
        "palm_size_cv": float(sizes.std() / max(sizes.mean(), 1e-6)),
        "orientation_std_deg": float(np.degrees(delta.std())),
    }


def collect_samples(camera_idx, seconds_countdown=3):
    gest = GestureEngine(asset_path("models", "gesture_recognizer.task"))
    cap = open_camera(camera_idx)
    feats, builtin_hits = [], {}
    sizes, angles = [], []
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
                size, angle = hand_quality(hand["landmarks"])
                sizes.append(size)
                angles.append(angle)
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
    return np.array(feats), builtin_hits, registration_quality(sizes, angles)


def register(camera_idx):
    store = CustomGestures(STORE)
    name = input("제스처 이름 (영문/한글, 공백 없이): ").strip()
    if not name:
        sys.exit("이름이 비었습니다")
    if name in store.class_names():
        sys.exit(f"'{name}'은 이미 있습니다. --remove 후 다시 등록하세요.")
    print("카메라 앞에서 등록할 손모양을 만들고 유지하세요...")
    feats, builtin_hits, quality = collect_samples(camera_idx)

    if quality["min_palm_size"] < MIN_PALM_SIZE:
        sys.exit(f"등록 거부: 손이 너무 작게 잡혔습니다(min palm {quality['min_palm_size']:.3f} < "
                 f"{MIN_PALM_SIZE}). 카메라에 조금 더 가까이 손목까지 보여주세요.")
    if quality["palm_size_cv"] > MAX_PALM_SIZE_CV:
        sys.exit(f"등록 거부: 등록 중 손 크기 변화가 큽니다(size CV {quality['palm_size_cv']:.2f} > "
                 f"{MAX_PALM_SIZE_CV:.2f}). 손의 앞뒤 거리와 위치를 고정하고 다시 시도하세요.")
    if quality["orientation_std_deg"] > MAX_ORIENTATION_STD_DEG:
        sys.exit(f"등록 거부: 등록 중 손 방향 변화가 큽니다(angle std "
                 f"{quality['orientation_std_deg']:.1f}° > {MAX_ORIENTATION_STD_DEG:.1f}°). "
                 "손목을 돌리지 말고 같은 방향으로 유지하세요.")

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
    spread = float(weighted_distance(feats - feats.mean(axis=0)).mean())
    if spread > 0.25:
        sys.exit(f"샘플이 너무 흩어졌습니다(spread {spread:.2f}) — 손모양을 고정하고 다시 시도하세요.")

    print(f"[등록 품질] min_palm={quality['min_palm_size']:.3f} | "
          f"size_CV={quality['palm_size_cv']:.2f} | "
          f"angle_std={quality['orientation_std_deg']:.1f}deg | "
          f"spread={spread:.2f}")
    store.add(name, feats)
    # Local CLI registration is retained only as a data-quality tool. Execution
    # mappings are owned by BE, so do not write a second mapping into
    # gestures.json here. Register and assign the gesture through the BE/UI flow.
    print("[등록 완료] 로컬 품질 검증용 템플릿만 저장했습니다. "
          "실행 기능은 제스처 등록 UI에서 BE 매핑으로 지정하세요.")


def live_test(camera_idx, distance="미기록", lighting="미기록", hand_side="미기록"):
    """라이브 분류 확인 + 실험 조건/추론 시간 콘솔 로그.

    거리·조명·사용 손은 단일 RGB 웹캠만으로 신뢰성 있게 자동 측정할 수 없으므로,
    실험자가 CLI 인자로 기록한다. 이 값은 결과를 해석하기 위한 실험 메타데이터다.
    """
    store = CustomGestures(STORE)
    gest = GestureEngine(asset_path("models", "gesture_recognizer.task"))
    cap = open_camera(camera_idx)
    print(f"등록된 커스텀 제스처: {store.class_names() or '없음'} — ESC로 종료")
    print(f"[실험 조건] 거리={distance} | 조명={lighting} | 사용 손={hand_side}")
    print("[기록] 라벨이 바뀔 때 추론 시간(ms)을 출력합니다. 이 값은 모델 처리 시간이며,"
          " 손모양을 만드는 시간은 포함하지 않습니다.")
    last_label = None
    infer_total = 0.0
    infer_count = 0
    stats_t = time.monotonic()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            t0 = time.perf_counter()
            hand = gest.hand(frame)
            infer_ms = (time.perf_counter() - t0) * 1000
            infer_total += infer_ms
            infer_count += 1
            label = "-"
            if hand:
                # assistant.py와 같은 우선순위: 등록 템플릿에 충분히 가까우면
                # 약한 내장 분류 결과보다 커스텀 라벨을 먼저 사용한다.
                custom_label, _ = store.classify_with_distance(hand["landmarks"])
                g = hand["gesture"]
                label = (f"{custom_label} (custom)" if custom_label
                         else (g if g and g != "None" else "-"))
            if label != last_label:
                print(f"[인식] {label} | 추론 {infer_ms:.1f}ms | "
                      f"거리={distance}, 조명={lighting}, 손={hand_side}")
                last_label = label
            now = time.monotonic()
            if now - stats_t >= 1.0:
                print(f"[1초 평균] 추론 {infer_total / max(infer_count, 1):.1f}ms "
                      f"({infer_count} frames)")
                infer_total, infer_count, stats_t = 0.0, 0, now
            hud = cv2.resize(frame, (640, 360))
            cv2.putText(hud, str(label), (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (80, 220, 80), 2)
            cv2.imshow("gesture test (ESC=quit)", hud)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def trial_test(camera_idx, target, trials, distance="미기록", lighting="미기록", hand_side="미기록"):
    """목표 제스처의 반복 실험.

    자동 인식만으로는 사용자가 '한 번 시도했다'는 사실을 알 수 없다. 따라서
    손모양을 만든 뒤 SPACE를 누르면 그 순간 화면의 라벨을 성공/실패로 확정한다.
    오른손 실험은 왼손으로 SPACE, 왼손 실험은 오른손으로 SPACE를 누르면 된다.
    """
    store = CustomGestures(STORE)
    gest = GestureEngine(asset_path("models", "gesture_recognizer.task"))
    cap = open_camera(camera_idx)
    success = failure = 0
    infer_samples = []
    last_label = None
    print(f"[반복 실험] 목표={target} | 횟수={trials} | 거리={distance} | "
          f"조명={lighting} | 사용 손={hand_side}")
    print("손모양을 유지해 목표 라벨을 확인한 뒤 SPACE를 누르세요. "
          "현재 라벨과 목표가 같으면 성공, 다르면 실패입니다. ESC=종료")
    try:
        while success + failure < trials:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            t0 = time.perf_counter()
            hand = gest.hand(frame)
            infer_ms = (time.perf_counter() - t0) * 1000
            infer_samples.append(infer_ms)
            label = "-"
            if hand:
                # 실서비스와 같은 kNN 우선 판정으로 측정한다.
                custom_label, _ = store.classify_with_distance(hand["landmarks"])
                g = hand["gesture"]
                label = (f"{custom_label} (custom)" if custom_label
                         else (g if g and g != "None" else "-"))
            if label != last_label:
                print(f"[현재 인식] {label} | 추론 {infer_ms:.1f}ms")
                last_label = label

            hud = cv2.resize(frame, (640, 360))
            count = success + failure
            cv2.putText(hud, f"target: {target}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (80, 220, 80), 2)
            cv2.putText(hud, f"detected: {label}", (10, 62), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (80, 220, 80), 2)
            cv2.putText(hud, f"trial {count}/{trials}  ok {success}  fail {failure}",
                        (10, 94), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 220, 80), 2)
            cv2.putText(hud, "SPACE=record  ESC=quit", (10, 126),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1)
            cv2.imshow("gesture trial (SPACE=record, ESC=quit)", hud)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key == 32:  # SPACE: 현재 시도를 사용자가 확정
                if label == target or label == f"{target} (custom)":
                    success += 1
                    result = "성공"
                else:
                    failure += 1
                    result = "실패"
                count = success + failure
                avg_ms = sum(infer_samples) / len(infer_samples)
                print(f"[기록 {count}/{trials}] {result} | 현재={label} | "
                      f"성공={success} 실패={failure} | 평균 추론={avg_ms:.1f}ms")
        count = success + failure
        if count:
            avg_ms = sum(infer_samples) / len(infer_samples)
            print(f"[최종 결과] 목표={target} | 시도={count} | 성공={success} | 실패={failure} | "
                  f"성공률={success / count * 100:.1f}% | 평균 추론={avg_ms:.1f}ms | "
                  f"조건={distance}/{lighting}/{hand_side}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def swipe_trial_test(camera_idx, target, trials, distance="미기록", lighting="미기록", hand_side="미기록",
                     finger_mode=False, pinch_mode=False, pointer_mode=False):
    """손 전체 또는 손목 고정형 스와이프 반복 인식 실험.

    손을 잠시 정지해 detector를 무장한 뒤 한 번 쓸고 SPACE로 시도를 확정한다.
    SPACE 전 마지막으로 발생한 스와이프가 목표 방향이면 성공, 반대면 방향 오인식,
    이벤트가 없으면 미인식이다. 실제 앱/BE 실행은 이 측정 모드의 범위 밖이다.
    """
    swipe_names = (("Screen_Next", "Screen_Prev", "Volume_Up", "Volume_Down") if pointer_mode else
                   ("Volume_Up", "Volume_Down") if pinch_mode else
                   ("Finger_Swipe_Left", "Finger_Swipe_Right") if finger_mode else
                   ("Swipe_Left", "Swipe_Right", "Swipe_Up", "Swipe_Down"))
    if target not in swipe_names:
        raise ValueError("유효한 스와이프 목표가 아닙니다.")
    gest = GestureEngine(asset_path("models", "gesture_recognizer.task"))
    swiper = (PointerControlDetector() if pointer_mode else
              PinchVolumeDetector(enabled=True) if pinch_mode else
              FingerSwipeDetector() if finger_mode else
              # 좌·우 화면 넘김 실측은 assistant.py와 동일한 threshold를 사용한다.
              SwipeDetector(**SCREEN_SWIPE_CONFIG) if target in ("Swipe_Left", "Swipe_Right")
              else SwipeDetector())
    cap = open_camera(camera_idx)
    success = wrong_direction = missed = 0
    infer_samples = []
    pending_event = None
    last_event = "-"
    mode_label = ("포인팅 제어" if pointer_mode else "핀치 볼륨" if pinch_mode else
                  "손목고정 스와이프" if finger_mode else "스와이프")
    print(f"[{mode_label} 실험] 목표={target} | 횟수={trials} | 거리={distance} | "
          f"조명={lighting} | 사용 손={hand_side}")
    if pointer_mode:
        print("검지만 펴고 0.25초 정지한 뒤 손 전체를 목표 방향으로 움직이세요. "
              "좌/우=화면 넘기기, 위/아래=볼륨. 볼륨은 포인팅 유지 시 반복되고, "
              "검지를 접으면 종료됩니다. SPACE를 눌러 기록하세요. "
              "반대 방향=오인식, 이벤트 없음=미인식. ESC=종료")
    elif pinch_mode:
        print("엄지와 검지를 붙여 0.2초 유지한 뒤, 붙인 손을 위/아래로 움직이세요. "
              "위=볼륨 증가, 아래=볼륨 감소. 손가락을 펴면 다음 시도를 재무장합니다. "
              "SPACE를 눌러 기록하세요. 반대 방향=오인식, 이벤트 없음=미인식. ESC=종료")
    elif finger_mode:
        print("손목은 거의 고정하고, 손바닥을 좌/우로 기울여 중지 끝만 움직이세요. "
              "같은 방향은 바로 반복하고, 반대 방향 전환은 시작 위치에서 0.5초 정지하세요. "
              "SPACE를 눌러 기록하세요. "
              "반대 방향=오인식, 이벤트 없음=미인식. ESC=종료")
    else:
        print("손을 0.3초 이상 정지한 뒤 목표 방향으로 한 번 쓸고 SPACE를 누르세요. "
              "Swipe_Up/Down은 손을 화면 밖으로 내린 뒤 다음 시도를 하세요. "
          "반대 방향=오인식, 이벤트 없음=미인식. ESC=종료")
    try:
        while success + wrong_direction + missed < trials:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            t0 = time.perf_counter()
            hand = gest.hand(frame)
            infer_ms = (time.perf_counter() - t0) * 1000
            infer_samples.append(infer_ms)
            now = time.monotonic()
            event = swiper.update(hand["landmarks"] if ((finger_mode or pinch_mode or pointer_mode) and hand) else
                                  hand["anchor"] if hand else None, now)
            if event:
                pending_event = event
                last_event = event
                print(f"[스와이프 감지] {event} | 추론 {infer_ms:.1f}ms")

            hud = cv2.resize(frame, (640, 360))
            count = success + wrong_direction + missed
            cv2.putText(hud, f"target: {target}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (80, 220, 80), 2)
            cv2.putText(hud, f"last event: {last_event}", (10, 62), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (80, 220, 80), 2)
            cv2.putText(hud, f"trial {count}/{trials} ok {success} wrong {wrong_direction} miss {missed}",
                        (10, 94), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 80), 2)
            guide = ("index point -> move target direction -> SPACE" if pointer_mode else
                     "pinch -> move up/down -> release -> SPACE" if pinch_mode else
                     "wrist fixed -> tilt hand (hold center 0.5s to reverse) -> SPACE" if finger_mode
                     else "still -> swipe -> SPACE (U/D: hand out before next)")
            cv2.putText(hud, guide + "   ESC=quit", (10, 126),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
            cv2.imshow("swipe trial (SPACE=record, ESC=quit)", hud)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key == 32:
                if pending_event == target:
                    success += 1
                    result = "성공"
                elif pending_event:
                    wrong_direction += 1
                    result = "반대방향 오인식"
                else:
                    missed += 1
                    result = "미인식"
                count = success + wrong_direction + missed
                avg_ms = sum(infer_samples) / len(infer_samples)
                print(f"[기록 {count}/{trials}] {result} | 이벤트={pending_event or '-'} | "
                      f"성공={success} 오인식={wrong_direction} 미인식={missed} | "
                      f"평균 추론={avg_ms:.1f}ms")
                pending_event = None
                last_event = "-"
        count = success + wrong_direction + missed
        if count:
            avg_ms = sum(infer_samples) / len(infer_samples)
            print(f"[최종 결과] 목표={target} | 시도={count} | 성공={success} | "
                  f"반대방향={wrong_direction} | 미인식={missed} | "
                  f"성공률={success / count * 100:.1f}% | 평균 추론={avg_ms:.1f}ms | "
                  f"조건={distance}/{lighting}/{hand_side}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def screen_repeat_trial_test(camera_idx, target, sets, distance="미기록", lighting="미기록", hand_side="미기록", youtube=False):
    """같은 방향 화면 넘김 2회를 하나의 세트로 측정한다.

    한 세트는 중앙 → 목표 방향 → 중앙 → 목표 방향이다. 복귀 동작이 반대
    이벤트로 실행되는지와, 같은 방향이 중복 실행되는지를 함께 기록한다.
    """
    # 일반 화면은 오른쪽=다음, 왼쪽=이전이다. YouTube는 사용자가 보는 화면
    # 방향 기준으로 오른쪽 쓸기=j(10초 뒤로), 왼쪽 쓸기=l(10초 앞으로)로 쓴다.
    raw_map = (
        {"Screen_Next": "Swipe_Left", "Screen_Prev": "Swipe_Right"}
        if youtube else
        {"Screen_Next": "Swipe_Right", "Screen_Prev": "Swipe_Left"}
    )
    target_event = raw_map.get(target)
    if target_event is None:
        raise ValueError("target은 Screen_Next 또는 Screen_Prev여야 합니다.")
    opposite_event = "Swipe_Left" if target_event == "Swipe_Right" else "Swipe_Right"
    direction = "오른쪽" if target_event == "Swipe_Right" else "왼쪽"
    gest = GestureEngine(asset_path("models", "gesture_recognizer.task"))
    swiper = SwipeDetector(**SCREEN_SWIPE_CONFIG)
    cap = open_camera(camera_idx)
    passed_sets = failed_sets = 0
    correct_actions = opposite_actions = missed_actions = duplicate_actions = 0
    infer_samples = []
    events = []

    context_label = "YouTube" if youtube else "일반 화면"
    print(f"[연속 화면 넘김 실험] 컨텍스트={context_label} | 목표={target} ({target_event}) | 세트={sets} | "
          f"기대 실행={sets * 2} | 거리={distance} | 조명={lighting} | 사용 손={hand_side}")
    print(f"한 세트: 중앙에서 0.3초 정지 → 화면 {direction}으로 쓸기 → 중앙 복귀 "
          f"→ 화면 {direction}으로 다시 쓸기 → SPACE. 복귀는 실행되지 않아야 합니다.")
    try:
        while passed_sets + failed_sets < sets:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            t0 = time.perf_counter()
            hand = gest.hand(frame)
            infer_ms = (time.perf_counter() - t0) * 1000
            infer_samples.append(infer_ms)
            now = time.monotonic()
            event = swiper.update(hand["anchor"] if hand else None, now)
            if event:
                events.append(event)
                print(f"[스와이프 감지] {event} | 추론 {infer_ms:.1f}ms")

            completed = passed_sets + failed_sets
            hud = cv2.resize(frame, (640, 360))
            cv2.putText(hud, f"target: {target}  expected: 2", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.72, (80, 220, 80), 2)
            cv2.putText(hud, f"events: {events or '-'}", (10, 62),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 80), 2)
            cv2.putText(hud, f"set {completed}/{sets} pass {passed_sets} fail {failed_sets}", (10, 94),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 80), 2)
            cv2.putText(hud, "center -> target -> center -> target -> SPACE", (10, 126),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230, 230, 230), 1)
            cv2.imshow("screen repeat trial (SPACE=record, ESC=quit)", hud)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key == 32:
                count_target = events.count(target_event)
                count_opposite = events.count(opposite_event)
                correct = min(count_target, 2)
                missed = 2 - correct
                duplicate = max(0, count_target - 2)
                correct_actions += correct
                missed_actions += missed
                opposite_actions += count_opposite
                duplicate_actions += duplicate
                passed = correct == 2 and count_opposite == 0 and duplicate == 0
                if passed:
                    passed_sets += 1
                    result = "성공"
                else:
                    failed_sets += 1
                    result = "실패"
                completed = passed_sets + failed_sets
                avg_ms = sum(infer_samples) / len(infer_samples)
                print(f"[세트 {completed}/{sets}] {result} | 이벤트={events or '-'} | "
                      f"정상={correct}/2 반대={count_opposite} 중복={duplicate} 미인식={missed} | "
                      f"평균 추론={avg_ms:.1f}ms")
                # 각 세트를 독립적으로 측정한다. 다음 세트는 정지 후 자동 재무장된다.
                swiper.update(None, now)
                events = []
        completed = passed_sets + failed_sets
        if completed:
            avg_ms = sum(infer_samples) / len(infer_samples)
            total_expected = completed * 2
            print(f"[최종 결과] 목표={target} | 세트={completed} | 기대 실행={total_expected} | "
                  f"정상 실행={correct_actions} | 반대방향={opposite_actions} | "
                  f"미인식={missed_actions} | 중복 실행={duplicate_actions} | "
                  f"세트 성공={passed_sets} | 세트 성공률={passed_sets / completed * 100:.1f}% | "
                  f"실행 성공률={correct_actions / total_expected * 100:.1f}% | "
                  f"평균 추론={avg_ms:.1f}ms | 조건={distance}/{lighting}/{hand_side}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def control_flow_trial_test(camera_idx, target, trials, distance="미기록", lighting="미기록", hand_side="미기록"):
    """제어 모드 진입 → 화면 넘김 → 손 내림 종료를 한 번에 측정한다.

    SPACE를 누른 순간 하나의 전체 흐름을 기록한다. 실제 키/앱 실행은 하지 않는다.
    """
    if target not in ("Screen_Next", "Screen_Prev"):
        raise ValueError("target은 Screen_Next 또는 Screen_Prev여야 합니다.")
    gest = GestureEngine(asset_path("models", "gesture_recognizer.task"))
    cap = open_camera(camera_idx)
    ok_count = fail_count = 0
    infer_samples = []

    def reset_trial():
        return GestureStable(min_frames=3), PalmControlMode(), SwipeDetector(
            dist=0.12, max_t=0.90, still_t=0.18, horizontal_ratio=1.0, vertical=False)

    stable, mode, swiper = reset_trial()
    entered = exited = False
    events = []
    last_event = "-"
    direction = "오른쪽" if target == "Screen_Next" else "왼쪽"
    print(f"[제어 흐름 실험] 목표={target} | 횟수={trials} | 거리={distance} | 조명={lighting} | 손={hand_side}")
    print(f"매 시도: 손바닥 0.5초 유지 → 화면에서 {direction}으로 편 손 이동 → 손을 내림 → SPACE. ESC=종료")
    try:
        while ok_count + fail_count < trials:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            t0 = time.perf_counter()
            hand = gest.hand(frame)
            infer_ms = (time.perf_counter() - t0) * 1000
            infer_samples.append(infer_ms)
            now = time.monotonic()
            gesture = stable.update(hand["gesture"] if hand else None)
            mode_event = mode.update(gesture, hand is not None, now)
            if mode_event == "entered":
                entered = True
                swiper.prime(hand["anchor"] if hand else None, now)
                print("[흐름] 제어 모드 진입")
            elif mode_event == "exited":
                exited = True
                print("[흐름] 제어 모드 종료")

            if mode.active:
                swipe = swiper.update(hand["anchor"] if hand else None, now)
                event = "Screen_Next" if swipe == "Swipe_Right" else "Screen_Prev" if swipe == "Swipe_Left" else None
                if event:
                    events.append(event)
                    last_event = event
                    print(f"[흐름] 감지={swipe} → 이벤트={event} | 추론 {infer_ms:.1f}ms")
            else:
                swiper.update(None, now)

            count = ok_count + fail_count
            hud = cv2.resize(frame, (640, 360))
            state = "ACTIVE" if mode.active else "WAIT_PALM"
            cv2.putText(hud, f"{state}  target={target}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.72, (80, 220, 80), 2)
            cv2.putText(hud, f"enter={entered} event={last_event} exit={exited}", (10, 62),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 220, 80), 2)
            cv2.putText(hud, f"trial {count}/{trials} success {ok_count} fail {fail_count}", (10, 94),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 220, 80), 2)
            cv2.putText(hud, "palm hold -> horizontal move -> hand down -> SPACE", (10, 128),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230, 230, 230), 1)
            cv2.imshow("control flow trial (SPACE=record, ESC=quit)", hud)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key == 32:
                valid_event = events.count(target) == 1 and len(events) == 1
                passed = entered and exited and valid_event
                if passed:
                    ok_count += 1
                    result = "성공"
                else:
                    fail_count += 1
                    reasons = []
                    if not entered:
                        reasons.append("진입 실패")
                    if not exited:
                        reasons.append("종료 실패")
                    if not events:
                        reasons.append("화면 넘김 미인식")
                    elif not valid_event:
                        reasons.append(f"이벤트={events}")
                    result = "실패: " + ", ".join(reasons)
                count = ok_count + fail_count
                avg_ms = sum(infer_samples) / len(infer_samples)
                print(f"[기록 {count}/{trials}] {result} | 진입={entered} 종료={exited} | "
                      f"이벤트={events or '-'} | 성공={ok_count} 실패={fail_count} | 평균 추론={avg_ms:.1f}ms")
                stable, mode, swiper = reset_trial()
                entered = exited = False
                events = []
                last_event = "-"
        count = ok_count + fail_count
        if count:
            avg_ms = sum(infer_samples) / len(infer_samples)
            print(f"[최종 결과] 목표={target} | 시도={count} | 성공={ok_count} | 실패={fail_count} | "
                  f"성공률={ok_count / count * 100:.1f}% | 평균 추론={avg_ms:.1f}ms | "
                  f"조건={distance}/{lighting}/{hand_side}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove", metavar="이름")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--distance", default="미기록", help="실험 거리. 예: 60cm, 1m")
    ap.add_argument("--lighting", default="미기록", help="조명 조건. 예: 밝음, 어두움")
    ap.add_argument("--hand", dest="hand_side", default="미기록",
                    help="사용 손. 예: 오른손, 왼손")
    ap.add_argument("--target", help="반복 측정할 목표 제스처 라벨. --test와 함께 사용")
    ap.add_argument("--trials", type=int, default=20, help="반복 측정 횟수 (기본 20)")
    ap.add_argument("--swipe-test", action="store_true",
                    help="Swipe_Left/Right/Up/Down 반복 인식 측정 모드")
    ap.add_argument("--finger-swipe-test", action="store_true",
                    help="손목 고정 Finger_Swipe_Left/Right 실험 측정 모드")
    ap.add_argument("--pinch-volume-test", action="store_true",
                    help="핀치 후 상/하 이동 Volume_Up/Down 반복 측정 모드")
    ap.add_argument("--control-flow-test", action="store_true",
                    help="control mode end-to-end trial")
    ap.add_argument("--pointer-test", action="store_true",
                    help="검지 포인팅 후 좌우 화면 넘기기·상하 볼륨 반복 측정 모드")
    ap.add_argument("--screen-repeat-test", action="store_true",
                    help="같은 방향 화면 넘김 2회 반복 세트 측정 모드")
    ap.add_argument("--youtube-context", action="store_true",
                    help="YouTube 방향 매핑(오른쪽=j 뒤로, 왼쪽=l 앞으로)으로 측정")
    args = ap.parse_args()
    if args.list:
        s = CustomGestures(STORE)
        print("등록된 커스텀 제스처:", s.class_names() or "없음",
              f"(샘플 총 {s.n}개)" if s.n else "")
    elif args.remove:
        s = CustomGestures(STORE)
        s.remove(args.remove)
        print(f"삭제됨: {args.remove} (BE 제스처 등록 UI의 매핑도 함께 정리하세요)")
    elif args.screen_repeat_test:
        if args.target not in ("Screen_Next", "Screen_Prev"):
            ap.error("--screen-repeat-test에는 --target Screen_Next 또는 Screen_Prev가 필요합니다.")
        if args.trials < 1:
            ap.error("--trials는 세트 수이며 1 이상이어야 합니다.")
        screen_repeat_trial_test(args.camera, args.target, args.trials,
                                 args.distance, args.lighting, args.hand_side,
                                 youtube=args.youtube_context)
    elif args.swipe_test:
        if args.target not in ("Swipe_Left", "Swipe_Right", "Swipe_Up", "Swipe_Down"):
            ap.error("--swipe-test에는 --target Swipe_Left/Right/Up/Down 중 하나가 필요합니다.")
        if args.trials < 1:
            ap.error("--trials는 1 이상이어야 합니다.")
        swipe_trial_test(args.camera, args.target, args.trials,
                         args.distance, args.lighting, args.hand_side)
    elif args.control_flow_test:
        if args.target not in ("Screen_Next", "Screen_Prev"):
            ap.error("--control-flow-test requires --target Screen_Next or Screen_Prev")
        if args.trials < 1:
            ap.error("--trials must be at least 1")
        control_flow_trial_test(args.camera, args.target, args.trials,
                                args.distance, args.lighting, args.hand_side)
    elif args.pointer_test:
        if args.target not in ("Screen_Next", "Screen_Prev", "Volume_Up", "Volume_Down"):
            ap.error("--pointer-test에는 --target Screen_Next, Screen_Prev, Volume_Up 또는 Volume_Down이 필요합니다.")
        if args.trials < 1:
            ap.error("--trials는 1 이상이어야 합니다.")
        swipe_trial_test(args.camera, args.target, args.trials,
                         args.distance, args.lighting, args.hand_side, pointer_mode=True)
    elif args.pinch_volume_test:
        if args.target not in ("Volume_Up", "Volume_Down"):
            ap.error("--pinch-volume-test에는 --target Volume_Up 또는 Volume_Down이 필요합니다.")
        if args.trials < 1:
            ap.error("--trials는 1 이상이어야 합니다.")
        swipe_trial_test(args.camera, args.target, args.trials,
                         args.distance, args.lighting, args.hand_side, pinch_mode=True)
    elif args.finger_swipe_test:
        if args.target not in ("Finger_Swipe_Left", "Finger_Swipe_Right"):
            ap.error("--finger-swipe-test에는 --target Finger_Swipe_Left 또는 Finger_Swipe_Right가 필요합니다.")
        if args.trials < 1:
            ap.error("--trials는 1 이상이어야 합니다.")
        swipe_trial_test(args.camera, args.target, args.trials,
                         args.distance, args.lighting, args.hand_side, finger_mode=True)
    elif args.test:
        if args.target:
            if args.trials < 1:
                ap.error("--trials는 1 이상이어야 합니다.")
            trial_test(args.camera, args.target, args.trials,
                       args.distance, args.lighting, args.hand_side)
        else:
            live_test(args.camera, args.distance, args.lighting, args.hand_side)
    else:
        register(args.camera)
