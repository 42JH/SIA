# -*- coding: utf-8 -*-
"""멀티모달 AI 비서 — 데모 v0 (에어 트랙패드 + 시선 장거리 점프).

커서의 주도권은 손에 있다: Active 상태에선 손 이동 = 커서 이동 (에어 트랙패드,
픽셀 단위로 정확한 손 랜드마크 사용). 시선은 백그라운드에서만 추적되다가
핀치 순간 응시점이 커서에서 멀 때(WARP_MIN_DIST)만 장거리 점프를 보조한다 —
웹캠 시선의 오차(~200px)로는 정밀 타겟팅이 아니라 점프 생략이 맞는 역할.

파이프라인은 3스레드: 카메라 캡처 / 시선(얼굴+CNN) / 손+인터랙션(메인).
서로를 기다리지 않아 손 커서가 카메라 속도(~30fps)로 반응한다.

조작 (Active 상태에서):
  손 이동          커서 이동 (에어 트랙패드)
  손바닥 0.6초     Active/Passive 토글 (--auto-active면 손만 보여도 Active)
  핀치 짧게        현재 커서 위치 클릭 (빠르게 2번 = 더블클릭)
  핀치 0.35초 홀드 드래그 (창 이동, 텍스트 선택)
  먼 곳 보고 핀치  커서가 응시 지점 근처로 점프 후 위 규칙 그대로
  V사인 + 상하     응시 지점 스크롤
  따봉(엄지척)     응시 지점 우클릭
  ESC(미리보기 창) 종료 / 마우스를 좌상단 모서리로 던지면 즉시 중단(failsafe)
  화면 상단 배지   현재 상태 표시 (PASSIVE/ACTIVE/PINCH/DRAG)

실행:  python main.py            (먼저 python calibrate.py)
옵션:  --no-mouse  --check  --gaze-test  --no-recal  --auto-active  --camera 1
"""
import argparse
import collections
import math
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from gaze import Calibrator, ClickRecal, GazeBuffer, make_engine
from hands import GestureEngine, GestureStable, HoldToggle, OneEuro, PinchFSM

HERE = Path(__file__).parent

# --- 튜닝 노브 (환경마다 손맛이 다르니 여기서 조정) ---
DRAG_GAIN = 2.2        # 손 이동 → 커서 이동 배율 (에어 트랙패드)
SCROLL_GAIN = 60.0     # V사인 스크롤: 손 상하 → 휠 클릭 수
LOOKBACK_S = 0.25      # 트리거 직전 fixation 조회 시점
WARP_MIN_DIST = 300.0  # 시선 워프는 응시점이 커서에서 이보다 멀 때만 (장거리 점프 보조).
                       # 가까우면 손으로 조종한 위치를 신뢰한다. 0=항상 워프, 크게=워프 끔
AUTO_PASSIVE_S = 15.0  # 클러치 모드: 손이 안 보이면 자동 Passive
AUTO_ACTIVE_OFF_S = 2.0  # --auto-active 모드: 손이 사라진 뒤 Passive까지
PINCH_HOLD_S = 0.35    # 이보다 짧은 핀치 = 클릭, 길면 드래그 시작
STABLE_FRAMES = 3      # 제스처 분류가 이 프레임 수 연속일 때만 인정
EURO_MIN_CUTOFF, EURO_BETA = 1.0, 20.0  # One Euro: 낮을수록 부드럽고, beta가 반응성
# NOTE(한계): 1920x1080은 홍채 정밀도가 오르지만 이 CPU에서 FaceLandmarker가 8fps로
# 떨어져 실패. GPU delegate 또는 얼굴 주변 크롭 최적화를 붙이면 그때 올릴 것.
CAM_W, CAM_H = 1280, 720
SNAP_MAX_W, SNAP_MAX_H = 420, 160  # 이보다 큰 UI 요소엔 스냅 안 함 (컨테이너 중앙으로 튀는 것 방지)


def snap_to_element(x, y):
    """응시 지점 아래 UI 요소가 클릭 가능한 크기면 그 중앙 좌표로 스냅.

    영역 수준 시선(오차 수백px)을 요소 수준 클릭으로 바꾸는 마지막 접착제 —
    시선이 버튼 안에만 들어가면 클릭은 정중앙에 꽂힌다. 실패하거나 요소가
    대형 컨테이너면 원좌표 그대로.
    """
    try:
        import uiautomation as uia

        r = uia.ControlFromPoint(int(x), int(y)).BoundingRectangle
        w, h = r.width(), r.height()
        if 8 <= w <= SNAP_MAX_W and 8 <= h <= SNAP_MAX_H:
            return float(r.left) + w / 2, float(r.top) + h / 2
    except Exception:
        pass
    return x, y


class Mouse:
    """pyautogui 래퍼. --no-mouse면 로그만 남긴다 (안전한 리허설용)."""

    def __init__(self, enabled):
        self.enabled = enabled
        import pyautogui

        pyautogui.FAILSAFE = True  # 좌상단 모서리 = 비상 정지
        pyautogui.PAUSE = 0
        self.pg = pyautogui
        self._acc = [0.0, 0.0]  # 1px 미만 드래그 잔여분 누적 (느린 드래그 보존)
        self.last_synth = -1e9  # 마지막 합성 클릭 시각 — 클릭 재보정에서 제외용

    def _do(self, label, fn):
        if self.enabled:
            fn()
        else:
            print(f"[no-mouse] {label}")

    def warp(self, x, y):
        self._do(f"warp ({x:.0f},{y:.0f})", lambda: self.pg.moveTo(x, y, _pause=False))

    def click(self):
        self.last_synth = time.monotonic()
        self._do("click", lambda: self.pg.click(_pause=False))

    def down(self):
        self.last_synth = time.monotonic()
        self._do("down", self.pg.mouseDown)

    def move_rel(self, dx, dy):
        self._acc[0] += dx
        self._acc[1] += dy
        ix, iy = int(self._acc[0]), int(self._acc[1])
        if ix == 0 and iy == 0:
            return
        self._acc[0] -= ix
        self._acc[1] -= iy
        self._do(f"drag ({ix:+d},{iy:+d})",
                 lambda: self.pg.moveTo(self.pg.position()[0] + ix,
                                        self.pg.position()[1] + iy, _pause=False))

    def up(self):
        self._do("up", self.pg.mouseUp)

    def emergency_release(self):
        """종료/예외 경로 전용. 커서가 failsafe 모서리에 있어도(비상정지 직후가
        정확히 그 상황) mouseUp이 또 FailSafeException을 던지지 않게 한다."""
        if not self.enabled:
            return
        old = self.pg.FAILSAFE
        self.pg.FAILSAFE = False
        try:
            self.pg.mouseUp()
        except Exception:
            pass
        finally:
            self.pg.FAILSAFE = old

    def right_click(self, x, y):
        self.last_synth = time.monotonic()
        self._do(f"right-click ({x:.0f},{y:.0f})",
                 lambda: self.pg.rightClick(x, y, _pause=False))

    def scroll(self, clicks):
        self._do(f"scroll {clicks:+d}", lambda: self.pg.scroll(clicks))


def open_camera(index):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        sys.exit("카메라를 열 수 없습니다. --camera 번호를 바꿔보세요.")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    return cap


class Camera(threading.Thread):
    """전용 캡처 스레드 — cap.read() 대기가 처리 루프를 막지 않게, 항상 최신 프레임만."""

    def __init__(self, cap):
        super().__init__(daemon=True)
        self.cap = cap
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0
        self.running = True

    def run(self):
        while self.running:
            ok, f = self.cap.read()
            if not ok:
                self.running = False
                break
            with self._lock:
                self._frame = f
                self._seq += 1

    def latest(self, last_seq=-1):
        """(seq, frame). last_seq 이후 새 프레임이 없으면 (last_seq, None)."""
        with self._lock:
            if self._seq == last_seq:
                return last_seq, None
            return self._seq, self._frame


class GazeWorker(threading.Thread):
    """시선(얼굴+CNN) 전용 스레드 — 손 루프(메인)와 분리해 서로 지연을 안 만든다.

    결과는 GazeBuffer(내부 락)와 특징 히스토리에만 쓴다. 커서는 절대 안 건드림.
    """

    def __init__(self, face, calib, buffer, camera):
        super().__init__(daemon=True)
        self.face = face
        self.calib = calib
        self.buffer = buffer
        self.camera = camera
        self.last_px = None  # HUD 표시용 (원자적 rebind만 하므로 락 불필요)
        self.running = True
        self._flock = threading.Lock()
        self._feats = collections.deque(maxlen=40)  # (t, 특징) — 클릭 재보정용

    def run(self):
        seq = -1
        while self.running:
            s, f = self.camera.latest(seq)
            if f is None:
                time.sleep(0.002)
                continue
            seq = s
            frame = cv2.flip(f, 1)
            feats = self.face.features(frame)
            now = time.monotonic()
            if feats is None or self.calib is None:  # 보정 전(핫스왑 대기)엔 예측만 건너뛴다
                self.last_px = None
                continue
            px = self.calib.predict(feats)
            self.last_px = px
            self.buffer.push(now, *px)
            with self._flock:
                self._feats.append((now, feats))

    def feat_near(self, t, offset=0.15, tol=0.25):
        """t-offset 시점에 가장 가까운 특징. 눈은 클릭 전에 이미 대상 위에 있다."""
        with self._flock:
            items = list(self._feats)
        best = min(items, key=lambda p: abs(t - offset - p[0]), default=None)
        if best and abs(t - offset - best[0]) < tol:
            return best[1]
        return None


def run_check(camera_idx):
    """환경 점검: 모델 로드 + 카메라 + 파이프라인별 fps. 마우스는 건드리지 않는다."""
    face = make_engine(HERE / "models")
    gest = GestureEngine(HERE / "models" / "gesture_recognizer.task")
    cap = open_camera(camera_idx)
    n = 40
    face_hit = hand_hit = 0
    t0 = time.monotonic()
    for _ in range(n):
        ok, fr = cap.read()
        if not ok:
            sys.exit("카메라 프레임 읽기 실패")
        if face.features(cv2.flip(fr, 1)) is not None:
            face_hit += 1
    face_fps = n / (time.monotonic() - t0)
    t0 = time.monotonic()
    for _ in range(n):
        ok, fr = cap.read()
        if not ok:
            sys.exit("카메라 프레임 읽기 실패")
        if gest.hand(cv2.flip(fr, 1)) is not None:
            hand_hit += 1
    hand_fps = n / (time.monotonic() - t0)
    cap.release()
    print(f"OK — 시선 {face_fps:.1f}fps (얼굴 {face_hit}/{n}), 손 {hand_fps:.1f}fps (손 {hand_hit}/{n})")
    print("실행 시 두 파이프라인은 별도 스레드로 병렬 — 손 커서는 손 fps로 움직입니다.")


def run_gaze_test(camera):
    """시선만 따로 검증하는 전체화면 모드: 화면을 보면 점이 따라오는지 눈으로 확인.
    회색 점 = 실시간 추정(원래 떨림), 원 = fixation(초록=확정). 마우스는 안 건드린다."""
    calib_path = HERE / "models" / "calib.npz"
    if not calib_path.exists():
        sys.exit("캘리브레이션이 없습니다. 먼저:  python calibrate.py")
    calib = Calibrator.load(calib_path)
    sw, sh = calib.screen
    face = make_engine(HERE / "models")
    if calib.W.shape[0] != 1 + face.dim + face.dim * (face.dim + 1) // 2:
        sys.exit("특징 차원이 바뀌었습니다(딥 모델 on/off) → 먼저:  python calibrate.py")
    buffer = GazeBuffer()
    cap = open_camera(camera)
    win = "gaze test (ESC=quit)"
    cv2.namedWindow(win, cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)
        now = time.monotonic()
        f = face.features(frame)
        if f is not None:
            buffer.push(now, *calib.predict(f))
        canvas = np.zeros((sh, sw, 3), dtype=np.uint8)
        for i in range(1, 3):  # 3x3 그리드
            cv2.line(canvas, (sw * i // 3, 0), (sw * i // 3, sh), (50, 50, 50), 1)
            cv2.line(canvas, (0, sh * i // 3), (sw, sh * i // 3), (50, 50, 50), 1)
        if f is None:
            cv2.putText(canvas, "NO FACE - check lighting / camera angle", (40, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 60, 230), 2)
        raw = buffer.current(now)
        fix, is_fix = buffer.fixation_at(now, lookback=0.0)
        if raw:
            cv2.circle(canvas, (int(raw[0]), int(raw[1])), 6, (150, 150, 150), -1)
        if fix:
            color = (80, 220, 80) if is_fix else (80, 160, 255)
            cv2.circle(canvas, (int(fix[0]), int(fix[1])), 30, color, 3)
            cx, cy = int(fix[0] * 3 // sw), int(fix[1] * 3 // sh)
            cv2.rectangle(canvas, (sw * cx // 3, sh * cy // 3),
                          (sw * (cx + 1) // 3, sh * (cy + 1) // 3), color, 2)
        cv2.putText(canvas, "Look around - circle should follow your gaze. Green = fixation",
                    (40, sh - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (160, 160, 160), 2)
        cv2.imshow(win, canvas)
        if cv2.waitKey(1) & 0xFF == 27:
            break
    cap.release()
    cv2.destroyAllWindows()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mouse", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--gaze-test", action="store_true")
    ap.add_argument("--no-recal", action="store_true", help="클릭 기반 상시 재보정 끄기")
    ap.add_argument("--auto-active", action="store_true",
                    help="손이 보이면 자동 Active (클러치 생략 — 데모 편의용, 오작동 여지 증가)")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    if args.check:
        run_check(args.camera)
        return
    if args.gaze_test:
        run_gaze_test(args.camera)
        return

    mouse = Mouse(enabled=not args.no_mouse)
    screen = tuple(mouse.pg.size())

    calib_path = HERE / "models" / "calib.npz"
    calib = None
    if calib_path.exists():
        try:
            calib = Calibrator.load(calib_path)
        except Exception as e:  # 손상된 파일로 시작조차 못 하는 상태 방지
            print(f"calib.npz 손상({e}) → 시선 비활성. calibrate.py를 다시 실행하세요.")
    if calib is not None and tuple(calib.screen) != screen:
        print(f"캘리브레이션 당시 해상도 {tuple(calib.screen)} ≠ 현재 {screen} → 시선 비활성.")
        print("해상도가 바뀌면 다시:  python calibrate.py")
        calib = None
    if calib is None:
        print("시선 워프 비활성 (핀치는 현재 커서 위치에서 동작). 시선을 쓰려면: python calibrate.py")

    face = make_engine(HERE / "models")
    if calib is not None and calib.W.shape[0] != 1 + face.dim + face.dim * (face.dim + 1) // 2:
        print("특징 차원이 바뀜(딥 모델 on/off) → 시선 비활성. calibrate.py를 다시 실행하세요.")
        calib = None
    gest = GestureEngine(HERE / "models" / "gesture_recognizer.task")
    buffer = GazeBuffer()
    pinch = PinchFSM()
    clutch = HoldToggle(hold_s=0.6, cooldown_s=1.5)
    stable = GestureStable(min_frames=STABLE_FRAMES)
    euro = OneEuro(EURO_MIN_CUTOFF, EURO_BETA)

    # --- 클릭 기반 상시 재보정: 실물 클릭 = 공짜 정답 라벨 ---
    # 리스너(전역 마우스 훅 스레드)는 좌표만 큐에 넣는다. 특징 조회·재학습·저장은
    # 전부 메인 루프에서 — 훅 안에서 하면 시스템 커서가 멈추고, 공유 자료구조를
    # 두 스레드가 만지면 경쟁조건으로 리스너가 죽는다.
    click_queue = collections.deque(maxlen=8)  # (t, x, y) — 리스너→메인 단방향
    recal = None
    if calib is not None and not args.no_recal:
        if calib.X0 is None:
            print("구형 calib 형식 → 클릭 재보정 비활성. calibrate.py를 한 번 다시 돌리면 켜집니다.")
        else:
            try:
                from pynput import mouse as pmouse

                recal = ClickRecal(calib, calib_path, HERE / "models" / "clicks.npz")

                def on_click(x, y, button, pressed):
                    if pressed and button == pmouse.Button.left:
                        click_queue.append((time.monotonic(), x, y))

                listener = pmouse.Listener(on_click=on_click)
                listener.daemon = True
                listener.start()
                print(f"클릭 재보정 켜짐 (누적 클릭샘플 {len(recal.X)}개) — 평소처럼 마우스를 쓰면 점점 정확해집니다.")
            except ImportError:
                print("pynput 없음 → 클릭 재보정 비활성:  .venv\\Scripts\\pip install pynput")

    from overlay import Overlay

    overlay = Overlay()

    try:
        import uiautomation  # noqa: F401 — 첫 import가 느려서(COM 초기화) 미리 예열
    except ImportError:
        pass

    cap = open_camera(args.camera)
    camera = Camera(cap)
    camera.start()
    worker = None
    if calib is not None:
        worker = GazeWorker(face, calib, buffer, camera)
        worker.start()

    active = False
    pinch_downed = False   # 핀치 홀드가 드래그로 전환돼 mouseDown이 나간 상태
    pinch_t0 = 0.0
    last_hand_t = -1e9
    prev_anchor = None
    prev_stable = "None"
    scroll_accum = 0.0
    scroll_mode_until = 0.0
    last_right_click = -1e9
    seq = -1
    fps_t, fps_n, fps = time.monotonic(), 0, 0.0

    def force_release():
        """어떤 이유로든 비활성화될 때 드래그를 잡은 채 남기지 않는다."""
        nonlocal pinch_downed
        pinch.reset()
        if pinch_downed:
            mouse.up()
            pinch_downed = False

    mode = "자동 Active(손 감지)" if args.auto_active else "손바닥 0.6초 = Active"
    print(f"시작. {mode}. 미리보기 창에서 ESC = 종료, a = 수동 토글.")
    try:
        while True:
            s, f = camera.latest(seq)
            if f is None:
                if not camera.running:
                    break
                time.sleep(0.002)
                continue
            seq = s
            frame = cv2.flip(f, 1)
            now = time.monotonic()
            gaze_px = worker.last_px if worker else None

            # --- 큐에 쌓인 실물 클릭 → 재보정 샘플 (메인 스레드에서만 처리) ---
            while recal is not None and click_queue:
                try:
                    tc, cx, cy = click_queue.popleft()
                except IndexError:
                    break
                if tc - mouse.last_synth < 0.4:
                    continue  # 데모가 만든 합성 클릭 — 배우면 피드백 루프
                feat = worker.feat_near(tc)
                if feat is not None:
                    rms = recal.add(feat, cx, cy)
                    if rms is not None:
                        print(f"클릭 재보정: 클릭샘플 {len(recal.X)}개, 학습 잔차 {rms:.0f}px")

            # --- 손 ---
            hand = gest.hand(frame)
            gesture = stable.update(hand["gesture"] if hand else None)
            if hand:
                last_hand_t = now
                anchor = euro(hand["anchor"], now)
            else:
                euro.reset()
                anchor = None

            # --- Active 상태 결정 ---
            if args.auto_active:
                want = now - last_hand_t < AUTO_ACTIVE_OFF_S
                if want != active:
                    active = want
                    if not active:
                        force_release()
                    print("ACTIVE (자동)" if active else "PASSIVE (자동)")
            else:
                # 클러치는 손이 없는 프레임에도 갱신해야 타이머가 리셋된다
                if clutch.update(gesture == "Open_Palm", now):
                    active = not active
                    if not active:
                        force_release()
                    print("ACTIVE" if active else "PASSIVE")
                if active and now - last_hand_t > AUTO_PASSIVE_S:
                    active = False
                    force_release()
                    print("PASSIVE (자동)")

            if active:
                # 응시 링 (Vision Pro식 피드백)
                cur = buffer.current(now)
                if cur:
                    overlay.show_ring(*cur)
                else:
                    overlay.hide_ring()

                # 에어 트랙패드: 커서는 손을 항상 따라다닌다 (핀치 여부 무관).
                # 손 랜드마크는 픽셀 단위로 정확한 신호 — 커서의 주도권은 손에 있다.
                if hand and prev_anchor is not None:
                    d = anchor - prev_anchor
                    mouse.move_rel(d[0] * screen[0] * DRAG_GAIN, d[1] * screen[1] * DRAG_GAIN)

                # 핀치: 짧게 = 현재 커서 위치 클릭 / 0.35초 홀드 = 드래그.
                # 시선 워프는 응시점이 멀 때만 발동하는 장거리 점프 보조.
                ev = pinch.update(hand["pinch_ratio"] if hand else None, now)
                if ev == "down":
                    fix, is_fix = buffer.fixation_at(now, lookback=LOOKBACK_S)
                    if fix and is_fix:
                        cx, cy = mouse.pg.position()
                        if math.hypot(fix[0] - cx, fix[1] - cy) > WARP_MIN_DIST:
                            mouse.warp(*snap_to_element(*fix))
                    pinch_t0, pinch_downed = now, False
                elif ev == "up":
                    if pinch_downed:
                        mouse.up()
                        pinch_downed = False
                    else:
                        mouse.click()  # 커서는 손이 조종해 온 위치 — 그대로 클릭
                elif ev == "lost":  # 손 소실 강제 해제 — 클릭은 절대 안 함
                    if pinch_downed:
                        mouse.up()
                        pinch_downed = False
                elif pinch.held:
                    if not pinch_downed and now - pinch_t0 >= PINCH_HOLD_S:
                        mouse.down()  # 여기서부터 드래그
                        pinch_downed = True

                # V사인 스크롤 (응시 지점에서)
                if hand and gesture == "Victory" and not pinch.held:
                    if now > scroll_mode_until:  # 스크롤 모드 진입
                        fix, is_fix = buffer.fixation_at(now, lookback=LOOKBACK_S)
                        if fix and is_fix:
                            mouse.warp(*fix)  # 응시 불확실이면 현재 커서 위치에서 스크롤
                        scroll_accum = 0.0
                    elif prev_anchor is not None:
                        scroll_accum += -(anchor[1] - prev_anchor[1]) * SCROLL_GAIN
                        clicks = int(scroll_accum)
                        if clicks:
                            mouse.scroll(clicks)
                            scroll_accum -= clicks
                    scroll_mode_until = now + 0.3  # 분류가 잠깐 끊겨도 모드 유지

                # 따봉 = 우클릭 (에지 트리거: 내렸다 다시 들어야 재발동, 핀치 중 금지)
                if (gesture == "Thumb_Up" and prev_stable != "Thumb_Up"
                        and not pinch.held and now - last_right_click > 1.2):
                    fix, is_fix = buffer.fixation_at(now, lookback=LOOKBACK_S)
                    if fix and is_fix:
                        mouse.right_click(*snap_to_element(*fix))
                        last_right_click = now
            else:
                overlay.hide_ring()
                force_release()

            prev_anchor = anchor
            prev_stable = gesture
            overlay.set_state("DRAG" if pinch_downed else "PINCH" if pinch.held
                              else "ACTIVE" if active else "PASSIVE")

            # --- HUD 미리보기 ---
            fps_n += 1
            if now - fps_t >= 1.0:
                fps, fps_n, fps_t = fps_n / (now - fps_t), 0, now
            hud = cv2.resize(frame, (480, 270))
            state = "ACTIVE" if active else "PASSIVE"
            color = (80, 220, 80) if active else (140, 140, 140)
            cv2.putText(hud, f"{state}  {gesture}  fps {fps:.0f}", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            if hand:  # 손 스켈레톤 — 검출 여부/품질을 눈으로 확인
                for lx, ly in hand["landmarks"]:
                    cv2.circle(hud, (int(lx * 480), int(ly * 270)), 2, (80, 220, 80), -1)
                cv2.putText(hud, f"HAND pinch {hand['pinch_ratio']:.2f}", (10, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 220, 80), 1)
            else:
                cv2.putText(hud, "NO HAND", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 230), 1)
            if gaze_px:
                gx = int(gaze_px[0] / screen[0] * 480)
                gy = int(gaze_px[1] / screen[1] * 270)
                cv2.circle(hud, (gx, gy), 6, (255, 212, 127), 2)
            if pinch.held:
                cv2.putText(hud, "DRAG" if pinch_downed else "PINCH", (10, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 160, 255), 2)
            cv2.imshow("demo (ESC=quit, a=toggle active)", hud)
            k = cv2.waitKey(1) & 0xFF
            if k == 27:
                break
            if k == ord("a"):  # 손 인식이 안 될 때 수동 토글 (디버그용)
                active = not active
                if not active:
                    force_release()
                print("ACTIVE (수동)" if active else "PASSIVE (수동)")
    finally:
        # 어떤 경로로 죽든(ESC, failsafe, 예외) 마우스 버튼을 잡은 채 남기지 않는다
        camera.running = False
        if worker:
            worker.running = False
        if pinch_downed or pinch.held:
            mouse.emergency_release()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 한글·em-dash 출력 크래시 방지
    except Exception:
        pass
    main()
