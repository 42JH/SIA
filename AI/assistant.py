# -*- coding: utf-8 -*-
"""시아 모드 — 커서를 건드리지 않는 시선+음성+제스처 비서.

동작 원리:
  [상시] 시선을 백그라운드 추적 (커서·화면에 아무 영향 없음)
  [상시] 마이크 대기 → 발화 감지 순간, 그때 응시하던 화면 영역을 캡처
  발화가 끝나면 오디오+전체화면+응시크롭을 Gemini 한 콜로 → 명령 판단·해석·실행
  호출어("시아야")로 명령이 한 번 통하면 90초 활성 세션 — 그동안은 호출어 없이 명령
  손 제스처 = 커맨드 단축키 (gestures.json, 컨텍스트 의존: 유튜브 활성 시 미디어 제어)
  파괴적 동작(창 닫기)은 되물은 뒤 "응/취소" 음성으로 확정

마우스는 평소처럼 직접 쓰면 된다. 이 프로그램은 커서를 절대 움직이지 않는다.

명령 예: "이거 저장해줘" / "이거 요약해줘"(긴 답은 우상단 패널) / "계산기 켜줘"
        "파이썬 데코레이터 검색해줘" / "보고서 파일 찾아줘" / "창 최대화" /
        "스크롤 내려" / "10초 뒤로" / "음소거" / "그만"(세션 종료)
실행:  python assistant.py          (시선을 쓰려면 먼저 python calibrate.py)
옵션:  --no-actions (실행 없이 판단만)  --check  --camera 1
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2

from dombridge import DomBridge
from gaze import Calibrator, GazeBuffer, make_engine
from hands import CustomGestures, GestureEngine, GestureStable, HoldToggle, SwipeDetector
from main import Camera, GazeWorker, open_camera

HERE = Path(__file__).parent

GESTURE_HOLD_S = 0.8   # 제스처 커맨드: 이 시간 유지해야 발동 (오작동 방지)
GESTURE_COOLDOWN_S = 1.2  # 연타 용도(10초 건너뛰기 반복)를 위해 짧게 — 홀드+재무장이 있어 안전
CROP_FRAC = 0.32       # 응시 영역 크롭 크기 = 화면 폭 × 이 비율 (해상도 무관하게 동작)
GAZE_LOOKBACK_S = 0.15  # 발화 시작 시점 응시 조회 (눈은 말하기 직전 대상 위에 있음)
BROWSERS = ("chrome", "whale", "edge", "firefox")  # 유튜브 컨텍스트 인정 브라우저 (창 제목 기준)

# 컨텍스트별 제스처 매핑 (기획서 4번: 같은 제스처도 상황 따라 다른 기능).
# 항목은 "run"(앱 실행) 또는 "key"(활성 창에 키 입력, 'shift+n' 형식 지원) 중 하나.
# Swipe_Left/Swipe_Right는 동적 제스처(손 쓸기) — 홀드 없이 즉시 발동.
DEFAULT_GESTURES = {
    "default": {
        "Victory": {"run": "notepad", "label": "메모장"},
        "Thumb_Up": {"run": "calc", "label": "계산기"},
        "ILoveYou": {"run": "chrome", "label": "크롬"},
    },
    "youtube": {
        "Closed_Fist": {"key": "k", "label": "재생/일시정지"},
        "Victory": {"key": "l", "label": "10초 앞으로"},
        "Pointing_Up": {"key": "j", "label": "10초 뒤로"},
        "Thumb_Up": {"key": "m", "label": "음소거"},
    },
}


def load_gestures():
    path = HERE / "gestures.json"
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_GESTURES, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "default" not in data:  # 구형(컨텍스트 없는 평면) 포맷 → 마이그레이션
        data = {"default": data, "youtube": DEFAULT_GESTURES["youtube"]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def capture_screen(fix_xy):
    """전체 스크린샷 + 응시 영역 크롭(PIL). fix_xy가 None이면 크롭도 None."""
    import pyautogui

    full = pyautogui.screenshot()
    crop = None
    if fix_xy is not None:
        size = int(full.width * CROP_FRAC)  # 화면 크기에 비례 — 사용자별 해상도 차이 흡수
        x, y = int(fix_xy[0]), int(fix_xy[1])
        half = size // 2
        left = max(0, min(full.width - size, x - half))
        top = max(0, min(full.height - size, y - half))
        crop = full.crop((left, top, left + size, top + size))
    return full, crop


def run_check(camera_idx):
    import sounddevice as sd

    from brain import MODEL, load_api_key

    mics = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
    print(f"마이크: {len(mics)}개 감지" if mics else "마이크 없음!")
    print(f"Gemini 키: {'있음' if load_api_key() else '없음 (음성 명령 비활성)'}  모델: {MODEL}")
    calib_path = HERE / "models" / "calib.npz"
    print(f"시선 캘리브레이션: {'있음' if calib_path.exists() else '없음 → python calibrate.py'}")
    cap = open_camera(camera_idx)
    ok, _ = cap.read()
    cap.release()
    print(f"카메라: {'OK' if ok else '실패'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-actions", action="store_true", help="판단만 하고 실행은 안 함")
    ap.add_argument("--no-speaker", action="store_true", help="화자 인증 끄기 (아무 목소리나 허용)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    if args.check:
        run_check(args.camera)
        return

    import pyautogui

    screen = tuple(pyautogui.size())

    # --- 시선 (없어도 동작: 지시어 해석력만 떨어짐) ---
    calib = None
    calib_path = HERE / "models" / "calib.npz"
    if calib_path.exists():
        try:
            calib = Calibrator.load(calib_path)
        except Exception as e:
            print(f"calib.npz 손상({e}) → 시선 없이 진행")
    if calib is not None and tuple(calib.screen) != screen:
        print("해상도가 캘리브레이션 때와 다름 → 시선 없이 진행 (calibrate.py 재실행 권장)")
        calib = None
    face = make_engine(HERE / "models")
    if calib is not None and calib.W.shape[0] != 1 + face.dim + face.dim * (face.dim + 1) // 2:
        print("특징 차원 변경(딥 모델 on/off) → 시선 없이 진행 (calibrate.py 재실행 권장)")
        calib = None
    if calib is None:
        print("시선 비활성 — '이거' 같은 지시어 해석이 약해집니다. 권장: python calibrate.py")

    from overlay import Overlay

    overlay = Overlay()
    overlay.set_state("IDLE")

    from brain import Brain
    from voice import VoiceListener

    speaker = None
    if not args.no_speaker:
        from speaker import SpeakerVerifier

        sv = SpeakerVerifier(HERE / "models" / "speaker.npz")
        if sv.enrolled:
            speaker = sv
            print(f"화자 인증 켜짐 — 등록된 목소리에만 반응 (임계 {sv.threshold}). 끄기: --no-speaker")
        else:
            print("화자 미등록 → 아무 목소리나 허용. 내 목소리만 반응시키려면: python voice_enroll.py")

    # BE 연결 계층 — runtime.json 있으면 WS/MCP 접속(백그라운드), 없거나 SIA_NO_BE 면
    # link=None 으로 오늘처럼 로컬 단독 동작. 실행/세션은 연결됐을 때만 BE 로 넘어간다.
    link = None
    if not os.environ.get("SIA_NO_BE"):
        try:
            from be_link import AgentLink

            link = AgentLink()
            print("BE 연결 계층 켜짐" + ("" if link.rt else " (runtime.json 없음 → 로컬 폴백)"))
            from calib_bridge import CalibSession

            link.calib = CalibSession(screen, face, link, HERE / "models" / "calib.npz")
        except Exception as e:
            print(f"BE 연결 계층 비활성: {e}")

    brain = Brain(overlay, act=not args.no_actions, speaker=speaker, link=link)
    brain.start()

    voice_events = collections.deque(maxlen=16)
    voice = VoiceListener(voice_events)
    voice.start()

    pyautogui.FAILSAFE = False  # 커서를 안 쓰는 모드 — 킬스위치는 ESC
    pyautogui.PAUSE = 0

    gest = GestureEngine(HERE / "models" / "gesture_recognizer.task")
    stable = GestureStable(min_frames=3)
    swiper = SwipeDetector()
    custom = CustomGestures(HERE / "custom_gestures.npz")
    if custom.n:
        print(f"커스텀 제스처 로드: {custom.class_names()} (등록: python gesture_studio.py)")
    bridge = DomBridge()
    bridge.start()  # BE 크롬 확장이 POST할 수신부 — 확장 없으면 스크린샷 폴백
    gesture_map = load_gestures()
    # 정적 제스처만 홀드 토글 대상 — 스와이프는 SwipeDetector가 자체 무장/재무장
    static_names = {n for ctx in gesture_map.values() for n in ctx if not n.startswith("Swipe")}
    gesture_toggles = {name: HoldToggle(hold_s=GESTURE_HOLD_S, cooldown_s=GESTURE_COOLDOWN_S)
                       for name in static_names}

    cap = open_camera(args.camera)
    camera = Camera(cap)
    camera.start()
    buffer = GazeBuffer()
    worker = None
    if calib is not None:
        worker = GazeWorker(face, calib, buffer, camera)
        worker.start()

    pending_capture = None  # 발화 시작 순간의 (full, crop) — 종료 시 오디오와 페어링
    seq = -1
    print("시아 모드 시작. 화면을 보며 말하면 됩니다. 미리보기 창에서 ESC = 종료.")
    try:
        while True:
            s, f = camera.latest(seq)
            if f is None:
                if not camera.running:
                    break
                time.sleep(0.003)
                continue
            seq = s
            frame = cv2.flip(f, 1)
            if link and link.calib and link.calib.active:
                link.calib.feed_frame(frame)  # 보정 중이면 시선 특징 수집(비활성 시 no-op)
            now = time.monotonic()

            # --- 음성 이벤트 처리 ---
            from brain import active_window_title, foreground_hwnd, press_keys

            while voice_events:
                ev = voice_events.popleft()
                if ev[0] == "onset":
                    # 말이 시작된 '그 순간'의 화면·응시 영역·대상 창을 즉시 확보
                    fix, _ = buffer.fixation_at(ev[1], lookback=GAZE_LOOKBACK_S, window=0.4)
                    pending_capture = (*capture_screen(fix), foreground_hwnd())
                elif ev[0] == "utter":
                    if pending_capture is None:
                        fix, _ = buffer.fixation_at(ev[1], lookback=GAZE_LOOKBACK_S, window=0.4)
                        pending_capture = (*capture_screen(fix), foreground_hwnd())
                    full, crop, hwnd = pending_capture
                    pending_capture = None
                    brain.submit(ev[2], full, crop, t_utter=ev[1], target_hwnd=hwnd,
                                 dom=bridge.context(max_age=10.0))

            # --- 제스처 커맨드 (컨텍스트 의존: 유튜브가 활성 창이면 미디어 제어) ---
            from brain import is_youtube

            def fire_entry(entry, name, kind):
                if args.no_actions:
                    overlay.toast(f"[시늉만] {kind}: {entry.get('label', name)}")
                elif "key" in entry:
                    press_keys(entry["key"])
                    overlay.toast(f"{kind}: {entry.get('label', name)}")
                else:
                    subprocess.Popen(["cmd", "/c", "start", "", entry["run"]])
                    overlay.toast(f"{kind}: {entry.get('label', name)}")
                print(f"{kind} {name} ({context}) → {entry}")

            hand = gest.hand(frame)
            raw_gesture = hand["gesture"] if hand else None
            # 내장 분류(7종)가 못 알아본 손모양만 커스텀 분류기가 2차 판정
            if hand and raw_gesture in (None, "None") and custom.n:
                raw_gesture = custom.classify(hand["landmarks"]) or "None"
            gesture = stable.update(raw_gesture)
            # 컨텍스트 판별: 키 입력은 '포커스된 창'으로 가므로, 브라우저가 포그라운드일
            # 때만 유튜브 컨텍스트로 전환한다. DOM video.present만 믿으면 백그라운드
            # 유튜브 때문에 앞의 워드 문서에 'm'이 찍히는 사고가 난다.
            fg_title = active_window_title()
            fg_is_browser = (is_youtube(fg_title)
                             or any(b in fg_title.lower() for b in BROWSERS))
            dom = bridge.context()
            dom_video = bool(dom and isinstance(dom.get("video"), dict)
                             and dom["video"].get("present"))
            context = "youtube" if (is_youtube(fg_title)
                                    or (dom_video and fg_is_browser)) else "default"
            # 컨텍스트 단위 폴백만 — 제스처 단위로 default를 부활시키면
            # 유튜브 섹션에서 지운 제스처가 영상 위에 앱을 띄우는 사고가 난다
            mapping = gesture_map[context] if context in gesture_map else gesture_map["default"]
            for name in static_names:
                entry = mapping.get(name)
                fired = gesture_toggles[name].update(gesture == name, now)
                if fired and entry:
                    fire_entry(entry, name, "제스처")
            swipe = swiper.update(hand["anchor"] if hand else None, now)
            if swipe:
                entry = mapping.get(swipe)
                if entry:
                    fire_entry(entry, swipe, "스와이프")

            # --- 상태 표시 (세션 남은 시간 포함) ---
            session_left = brain.session_left()
            if brain.busy:
                overlay.set_state("THINKING")
            elif voice.recording:
                overlay.set_state("LISTENING")
            elif session_left > 0:  # 활성 세션: 호출어 없이 명령 가능
                overlay.set_state("ACTIVE", f" {int(session_left)}s")
            else:
                overlay.set_state("IDLE")
            # 듣는 중엔 응시 링으로 "여길 보고 있다고 인식 중" 피드백
            if worker and (voice.recording or brain.busy):
                cur = buffer.current(now)
                if cur:
                    overlay.show_ring(*cur)
            else:
                overlay.hide_ring()

            # --- HUD 미리보기 ---
            hud = cv2.resize(frame, (480, 270))
            state = ("THINKING" if brain.busy else "LISTENING" if voice.recording
                     else f"ACTIVE {int(session_left)}s" if session_left > 0 else "IDLE")
            cv2.putText(hud, f"{state}  {gesture}", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 220, 80), 2)
            if worker and worker.last_px:
                gx = int(worker.last_px[0] / screen[0] * 480)
                gy = int(worker.last_px[1] / screen[1] * 270)
                cv2.circle(hud, (gx, gy), 6, (255, 212, 127), 2)
            if hand:
                for lx, ly in hand["landmarks"]:
                    cv2.circle(hud, (int(lx * 480), int(ly * 270)), 2, (80, 220, 80), -1)
            cv2.imshow("assistant (ESC=quit)", hud)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        camera.running = False
        voice.running = False
        if worker:
            worker.running = False
        if link:
            link.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
