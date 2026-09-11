# -*- coding: utf-8 -*-
"""시아 모드 — 커서를 건드리지 않는 시선+음성+제스처 비서.

동작 원리:
  [상시] 시선을 백그라운드 추적 (커서·화면에 아무 영향 없음)
  [상시] 마이크 대기 → 발화 감지 순간, 그때 응시하던 화면 영역을 캡처
  발화가 끝나면 오디오+전체화면+응시크롭을 Gemini 한 콜로 → 명령 판단·해석·실행
  호출어("시아야")로 명령이 한 번 통하면 90초 활성 세션 — 그동안은 호출어 없이 명령
  손 제스처 = 커맨드 단축키 (정적/커스텀은 BE 매핑, 동적은 dynamic_gesture_fallbacks.json;
  컨텍스트 의존: 유튜브 활성 시 미디어 제어)
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
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2

from dombridge import DomBridge
from gesture_be import (
    GestureRegistration,
    GestureTemplateCache,
    registration_blocks_gesture_execution,
    sync_gesture_store,
)
from body_pose import BodyPoseEngine
from custom_motion import CustomGestureStore, static_execution_allowed
from gaze import Calibrator, GazeBuffer, make_engine
from hands import (GestureEngine, GestureStable, HoldToggle,
                   PalmScrollDetector, PinchVolumeDetector, SCREEN_SWIPE_CONFIG,
                   SwipeDetector, TwoHandSpreadDetector)
from main import Camera, GazeWorker, open_camera

HERE = Path(__file__).parent

GESTURE_HOLD_S = 0.8   # 제스처 커맨드: 이 시간 유지해야 발동 (오작동 방지)
GESTURE_COOLDOWN_S = 1.2  # 연타 용도(10초 건너뛰기 반복)를 위해 짧게 — 홀드+재무장이 있어 안전
# 정적 제스처는 동적 제스처보다 보수적으로 처리한다. 토글 성격의 명령은
# 잠깐의 트래킹 손실만으로 재무장되지 않도록 neutral/release 시간을 길게 둔다.
STATIC_TRIGGER_POLICY = {
    "Closed_Fist": {"hold_s": 0.80, "cooldown_s": 2.0, "grace_s": 0.55},
    "Open_Palm": {"hold_s": 0.80, "cooldown_s": 2.2, "grace_s": 0.60},
    "Victory": {"hold_s": 0.80, "cooldown_s": 2.2, "grace_s": 0.60},
    # Pointing_Up is visually distinctive but the built-in model is more
    # angle-sensitive than fist/palm poses, so use a shorter activation hold.
    "Pointing_Up": {"hold_s": 0.70, "cooldown_s": 2.0, "grace_s": 0.55},
    # 볼륨은 향후 Pinch_Up/Down으로 교체 예정이므로, 임시로만 짧은 반복을 허용한다.
    "Thumb_Up": {"hold_s": 0.70, "cooldown_s": 0.9, "grace_s": 0.40},
    "Thumb_Down": {"hold_s": 0.70, "cooldown_s": 0.9, "grace_s": 0.40},
}
SCROLL_WHEEL_MULTIPLIER = 3  # 편 손 연속 스크롤의 휠 단계 증폭값
POSE_MAX_FPS = 10.0          # Pose는 보조 신호이므로 손 제스처보다 낮은 주기로 실행
POSE_MAX_WIDTH = 640         # Pose 입력 축소 폭. 카메라 전체 해상도는 유지한다.
CROP_FRAC = 0.32       # 응시 영역 크롭 크기 = 화면 폭 × 이 비율 (해상도 무관하게 동작)
GAZE_LOOKBACK_S = 0.15  # 발화 시작 시점 응시 조회 (눈은 말하기 직전 대상 위에 있음)
BROWSERS = ("chrome", "whale", "edge", "firefox")  # 유튜브 컨텍스트 인정 브라우저 (창 제목 기준)
EBOOK_TITLE_TOKENS = ("ebook", "e-book", "epub", "kindle", "calibre", "리디", "밀리의 서재",
                      "교보", "yes24", "알라딘")
WEBEX_TITLE_TOKENS = ("webex",)

# BE 기본 제스처 테이블과의 계약. ``youtube``는 AI 내부 컨텍스트이고,
# BE는 영상 공통 기능을 ``video`` 컨텍스트로 등록해 두었다. 여기 없는
# 이벤트(Screen_Next/Prev 등)는 의미가 다른 BE 도구로 억지 변환하지 않고
# dynamic_gesture_fallbacks.json의 로컬 fallback으로 실행한다.
# 실행 매핑의 기준은 Backend/DefaultMappings.java와 BE DB다. 아래 집합은
# 단축키/도구를 정의하지 않고, AI 컨텍스트를 BE 컨텍스트로 번역하기만 한다.
# Full gesture mode. Static/custom gestures with a BE mapping are delegated to
# BE; dynamic gestures use the local context fallback until BE owns them too.
AI_ENABLED_GESTURES = {
    "Closed_Fist", "Open_Palm", "Pointing_Up", "Thumb_Up", "Thumb_Down",
    "Victory", "ILoveYou",
}
ENABLE_DYNAMIC_GESTURES = True

BE_DEFAULT_GESTURES = {"Open_Palm", "Thumb_Up", "Thumb_Down", "Closed_Fist"}
BE_VIDEO_GESTURES = {"Open_Palm", "Victory", "Thumb_Up", "Thumb_Down"}
BE_YOUTUBE_ONLY_GESTURES = {"Pointing_Up"}
BUILTIN_STATIC_GESTURES = {
    "Closed_Fist", "Open_Palm", "Pointing_Up", "Thumb_Up", "Thumb_Down",
    "Victory", "ILoveYou",
}
DYNAMIC_PREFIXES = ("Swipe", "Screen_", "Volume_", "Scroll_")
DYNAMIC_FALLBACK_PATH = HERE / "dynamic_gesture_fallbacks.json"


def be_gesture_target(name, context, custom_names=()):
    """BE가 소유한 정적/커스텀 제스처의 (name, context)를 반환한다.

    동적 제스처는 아직 BE 기본 매핑이 없으므로 None을 반환한다. 여기에는
    단축키나 로컬 실행 의미를 두지 않는다.
    """
    if name in custom_names:
        return name, (None if context == "default" else context)
    if context == "youtube":
        if name in BE_VIDEO_GESTURES:
            return name, "video"
        if name in BE_YOUTUBE_ONLY_GESTURES:
            return name, "youtube"
    if name in BE_DEFAULT_GESTURES:
        return name, None
    return None


def is_powerpoint(title):
    return "powerpoint" in (title or "").lower()


def is_ebook(title):
    t = (title or "").lower()
    return any(token in t for token in EBOOK_TITLE_TOKENS)


def is_webex(title):
    t = (title or "").lower()
    return any(token in t for token in WEBEX_TITLE_TOKENS)


def load_dynamic_fallbacks():
    """BE에 없는 동적 제스처의 로컬 fallback만 불러온다 (dynamic_gesture_fallbacks.json).

    정적/커스텀 제스처 매핑은 BE가 소유하므로 여기서는 읽지 않는다.
    """
    if DYNAMIC_FALLBACK_PATH.exists():
        data = json.loads(DYNAMIC_FALLBACK_PATH.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("default", {})
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
    ap.add_argument("--no-pose", action="store_true", help="Pose 보조 추론 끄기")
    ap.add_argument("--two-hand-preview", action="store_true",
                    help="양손 벌리기/모으기 후보만 표시하고 기존 제스처 액션은 차단")
    ap.add_argument("--be-gesture-only", action="store_true",
                    help="실측용: BE 매핑이 없는 로컬 키·휠 fallback을 차단")
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
        print("시선 비활성 - '이거' 같은 지시어 해석이 약해집니다. 앱에서 시선 보정을 마치면 재시작 없이 켜집니다.")

    from overlay import Overlay

    overlay = Overlay()
    overlay.set_state("IDLE")

    from brain import Brain
    from voice import VoiceListener

    speaker = None
    if not args.no_speaker:
        from speaker import SpeakerVerifier

        # 미등록이어도 넘긴다 — brain 은 enrolled 를 매번 확인하므로 FE 등록(65) 뒤 재시작 없이 게이트가 켜진다
        speaker = SpeakerVerifier(HERE / "models" / "speaker.npz")
        if speaker.enrolled:
            print(f"화자 인증 켜짐 — 등록된 목소리에만 반응 (임계 {speaker.threshold}). 끄기: --no-speaker")
        else:
            print("화자 미등록 → 아무 목소리나 허용. 내 목소리만 반응시키려면: 앱의 보이스 등록 또는 python voice_enroll.py")

    # BE 연결 계층 — runtime.json 있으면 WS/MCP 접속(백그라운드), 없거나 SIA_NO_BE 면
    # link=None 으로 오늘처럼 로컬 단독 동작. 실행/세션은 연결됐을 때만 BE 로 넘어간다.
    link = None
    if not os.environ.get("SIA_NO_BE"):
        try:
            from be_link import AgentLink
            from voice_bridge import VoiceProfileSync

            voice_sync = VoiceProfileSync(speaker, HERE / "models" / "speaker.npz") if speaker else None
            link = AgentLink(voice_sync=voice_sync)
            print("BE 연결 계층 켜짐" + ("" if link.rt else " (runtime.json 없음 → 로컬 폴백)"))
            from calib_bridge import CalibSession

            link.calib = CalibSession(screen, face, link, HERE / "models" / "calib.npz")
            from voice_bridge import WakeEnroll

            link.wake = WakeEnroll(link)        # 온보딩 이름 불러보기(206) — 화자 인증을 꺼도 FE 진행바는 채워야 한다
            if speaker is not None:
                from voice_bridge import VoiceSession

                link.voice = VoiceSession(link, speaker, HERE / "models" / "speaker.npz")
        except Exception as e:
            print(f"BE 연결 계층 비활성: {e}")

    brain = Brain(overlay, act=not args.no_actions, speaker=speaker, link=link)
    brain.start()

    voice_events = collections.deque(maxlen=16)
    voice = VoiceListener(voice_events, on_reset=brain.reset_audio)
    voice.start()

    pyautogui.FAILSAFE = False  # 커서를 안 쓰는 모드 — 킬스위치는 ESC
    pyautogui.PAUSE = 0

    gest = GestureEngine(HERE / "models" / "gesture_recognizer.task")
    pose = None
    pose_path = HERE / "models" / "pose_landmarker_full.task"
    if not args.no_pose:
        try:
            pose = BodyPoseEngine(pose_path, max_fps=POSE_MAX_FPS, max_width=POSE_MAX_WIDTH)
            print(f"Pose 보조 추론 켜짐: 최대 {POSE_MAX_FPS:.0f} FPS, 입력 폭 {POSE_MAX_WIDTH}px")
        except Exception as e:
            print(f"Pose 보조 추론 비활성({type(e).__name__}: {e})")
    # A short tracking dropout must not turn a held media toggle into a second
    # command. Pose changes still reset immediately in GestureStable.
    stable = GestureStable(min_frames=3, missing_grace_s=0.45)
    # 제스처 실행 게이트는 Open_Palm이 아니라 음성 호출로 열린 ACTIVE 세션이다.
    palm_motion = SwipeDetector(**SCREEN_SWIPE_CONFIG)
    palm_scroll = PalmScrollDetector()
    pinch_volume = PinchVolumeDetector()
    two_hand_motion = TwoHandSpreadDetector()
    custom = CustomGestureStore(HERE / "custom_gestures.npz")
    active_custom = custom
    disabled_gestures = set()
    # BE가 연결되면 사용자별 커스텀 제스처 템플릿을 이 캐시에 동기화한다.
    # 연결 전에는 위의 로컬 템플릿을 그대로 사용한다.
    remote_cache = GestureTemplateCache(HERE / ".gesture_cache", HERE / "be_custom_gestures.npz")
    registration = GestureRegistration(link, remote_cache, active_custom) if link else None
    remote_refs = {}
    if custom.n:
        print(f"커스텀 제스처 로드: {custom.class_names()} (등록: python gesture_studio.py)")
    last_usage_flush = time.monotonic()
    bridge = DomBridge()
    bridge.start()  # BE 크롬 확장이 POST할 수신부 — 확장 없으면 스크린샷 폴백
    # Static/custom mappings are owned by BE. This file only owns dynamic fallback.
    # Dynamic fallback mappings are intentionally not loaded in the
    # Closed_Fist-only MVP, so no local mapping file is generated at runtime.
    gesture_map = load_dynamic_fallbacks() if ENABLE_DYNAMIC_GESTURES else {"default": {}}
    # 정적 제스처만 홀드 토글 대상 — 스와이프는 SwipeDetector가 자체 무장/재무장
    # Only gestures explicitly enabled for this MVP may reach the executor.
    static_names = set(BUILTIN_STATIC_GESTURES & AI_ENABLED_GESTURES)
    def make_static_toggle(name):
        """Return the safety gate for one static/custom gesture.

        Custom gestures retain the conservative default. Built-ins with a
        toggle-like side effect use their explicit policy above.
        """
        policy = STATIC_TRIGGER_POLICY.get(name, {
            "hold_s": GESTURE_HOLD_S,
            "cooldown_s": GESTURE_COOLDOWN_S,
            "grace_s": 0.45,
        })
        return HoldToggle(**policy)

    gesture_toggles = {name: make_static_toggle(name) for name in static_names}

    def ensure_static_gesture_names(store):
        """BE에서 내려온 커스텀 정적 라벨(1손 kNN + 2손 NPZ v2)만 hold/cooldown 대상에
        편입한다. 동적 커스텀(모션)은 완성 시 한 번 발동하는 즉발 이벤트라
        static_names에 넣지 않는다 — dynamic_event 경로로 별도 처리한다.
        """
        dynamic = {str(n) for n, m in zip(store.data["sequence_names"], store.data["motions"])
                   if m == "DYNAMIC"}
        for name in store.class_names():
            if name in BUILTIN_STATIC_GESTURES and name not in AI_ENABLED_GESTURES:
                continue
            if name.startswith(DYNAMIC_PREFIXES) or name in dynamic:
                continue
            static_names.add(name)
            gesture_toggles.setdefault(name, make_static_toggle(name))

    cap = open_camera(args.camera)
    camera = Camera(cap)
    camera.start()
    buffer = GazeBuffer()
    # calib 이 없어도 스레드는 띄운다 — 보정 전엔 predict 만 건너뛰고, 활성 보정이 오면(calib_changed)
    # CalibSession.on_reload 가 worker.calib 을 갈아끼워 재시작 없이 시선이 켜진다(-245).
    worker = GazeWorker(face, calib, buffer, camera)
    worker.start()
    if link and link.calib:
        link.calib.on_reload = lambda c: setattr(worker, "calib", c)

    pending_capture = None  # 발화 시작 순간의 (full, crop) — 종료 시 오디오와 페어링
    # DOM에서 플레이어 볼륨을 읽지는 못하므로, 이 값은 AI가 보낸 볼륨 키 입력을
    # 기준으로 표시하는 HUD용 추정치다. 실제 재생기 볼륨과는 다를 수 있다.
    hud_volume = 50
    hud_feedback = ""
    hud_feedback_until = 0.0
    dynamic_hud_event = ""
    dynamic_hud_until = 0.0
    was_gesture_active = False
    loop_fps = 0.0
    loop_frames = 0
    loop_fps_started = time.monotonic()
    hand_infer_ms = 0.0
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
            loop_frames += 1
            fps_elapsed = now - loop_fps_started
            if fps_elapsed >= 0.5:
                loop_fps = loop_frames / fps_elapsed
                loop_frames = 0
                loop_fps_started = now

            if link:
                for event_type, data in link.take_events():
                    if event_type == "model_load":
                        model_name = data.get("name", "")
                        model_path = Path(data.get("path", ""))
                        if model_path.is_file() or (HERE / "models" / model_path.name).is_file():
                            link.send_event("model_loaded", {"name": model_name})
                        else:
                            link.send_event("model_load_failed", {"name": model_name,
                                                                     "reason": "모델 파일을 찾을 수 없습니다"})
                    elif event_type in ("hello_ack", "recognition_start", "settings_changed"):
                        if voice.set_settings(data.get("settings")):
                            pending_capture = None
                        blobs = data.get("blobs", {}) if isinstance(data, dict) else {}
                        refs = blobs.get("gestures", []) if isinstance(blobs, dict) else []
                        remote_refs = {str(item["id"]): item for item in refs
                                       if isinstance(item, dict) and item.get("id") is not None}
                        if "disabledGestures" in data:
                            disabled_gestures = set(data.get("disabledGestures") or [])
                        try:
                            remote_custom = sync_gesture_store(link, remote_cache, list(remote_refs.values()))
                            active_custom = remote_custom if remote_custom.n else custom
                            ensure_static_gesture_names(active_custom)
                            if registration:
                                registration.custom_store = active_custom
                            print(f"[BE] 제스처 설정 동기화: {active_custom.class_names()}")
                            if event_type == "recognition_start":
                                link.send_event("recognition_started", {})
                        except Exception as exc:
                            print(f"[BE] 제스처 템플릿 동기화 실패: {exc}")
                    elif event_type == "gesture_toggled":
                        name = data.get("name")
                        if name:
                            if data.get("enabled", True):
                                disabled_gestures.discard(name)
                            else:
                                disabled_gestures.add(name)
                    elif event_type == "gesture_renamed" and data.get("id") is not None:
                        ref = remote_refs.get(str(data["id"]))
                        if ref:
                            ref["name"] = data.get("newName", ref.get("name"))
                            try:
                                remote_custom = sync_gesture_store(link, remote_cache, list(remote_refs.values()))
                                active_custom = remote_custom if remote_custom.n else custom
                                ensure_static_gesture_names(active_custom)
                            except Exception as exc:
                                print(f"[BE] 이름 변경 동기화 실패: {exc}")
                    elif event_type == "gesture_registered" and data.get("id") is not None:
                        remote_refs[str(data["id"])] = {"id": data["id"], "name": data.get("name"),
                                                        "sha256": data.get("sha256")}
                        try:
                            remote_custom = sync_gesture_store(link, remote_cache, list(remote_refs.values()))
                            active_custom = remote_custom if remote_custom.n else custom
                            ensure_static_gesture_names(active_custom)
                            if registration:
                                registration.custom_store = active_custom
                        except Exception as exc:
                            print(f"[BE] 신규 제스처 동기화 실패: {exc}")
                    elif event_type == "gesture_removed":
                        name = data.get("name")
                        remote_refs = {gid: ref for gid, ref in remote_refs.items() if ref.get("name") != name}
                        try:
                            remote_custom = sync_gesture_store(link, remote_cache, list(remote_refs.values()))
                            active_custom = remote_custom if remote_custom.n else custom
                            ensure_static_gesture_names(active_custom)
                            if registration:
                                registration.custom_store = active_custom
                        except Exception as exc:
                            print(f"[BE] 삭제 제스처 동기화 실패: {exc}")
                    elif event_type == "reg_mode_start" and registration:
                        registration.start(data, now)
                    elif event_type == "reg_finish" and registration:
                        registration.finish()
                    elif event_type == "gesture_result":
                        hud_feedback = data.get("message", "제스처 실행 결과")
                        hud_feedback_until = now + 1.5
                        print(f"[BE RESULT] name={data.get('name', '-')} | "
                              f"ok={data.get('ok', False)} | message={hud_feedback}")

            if link and link.voice_sync and link.voice_sync.apply_pending(voice.reset_audio):
                pending_capture = None

            # --- 음성 이벤트 처리 ---
            from brain import active_window_title, foreground_hwnd, press_keys

            while (ev := voice.take_event()) is not None:
                if ev[0] == "reset":
                    pending_capture = None
                elif ev[0] == "notice":
                    if link:
                        link.notice(ev[1])
                    overlay.toast(ev[1])
                elif ev[0] == "onset":
                    # 말이 시작된 '그 순간'의 화면·응시 영역·대상 창을 즉시 확보
                    fix, _ = buffer.fixation_at(ev[1], lookback=GAZE_LOOKBACK_S, window=0.4)
                    pending_capture = (*capture_screen(fix), foreground_hwnd())
                elif ev[0] == "utter":
                    # 등록·온보딩 수집 중이면 그쪽으로. 둘 다 켜져 있으면 나중에 시작한 쪽 — 화자 등록을 끝내지 않고
                    # 이름 불러보기로 되돌아가면 BE 가 등록을 접지 않아, 순서를 고정하면 "시아야" 가 낭독 문장으로 먹힌다
                    open_ = [s for s in (link.voice, link.wake) if s and s.active] if link else []
                    enroll = max(open_, key=lambda s: s.started_at, default=None)
                    if enroll:
                        pending_capture = None
                        enroll.on_utter(ev[2], ev[1])  # 샘플로만 쓰고 명령 처리는 안 한다. ev[1]은 발화 시작 시각 — "이 문장 다시" 판정용
                        continue
                    if pending_capture is None:
                        fix, _ = buffer.fixation_at(ev[1], lookback=GAZE_LOOKBACK_S, window=0.4)
                        pending_capture = (*capture_screen(fix), foreground_hwnd())
                    full, crop, hwnd = pending_capture
                    pending_capture = None
                    brain.submit(ev[2], full, crop, t_utter=ev[1], target_hwnd=hwnd,
                                 dom=bridge.context(max_age=10.0))

            # --- 제스처 커맨드 (컨텍스트 의존: 유튜브가 활성 창이면 미디어 제어) ---
            from brain import is_youtube

            def fire_entry(entry, name, kind, wheel_steps=1):
                if args.no_actions:
                    overlay.toast(f"[시늉만] {kind}: {entry.get('label', name)}")
                elif "wheel" in entry:
                    pyautogui.scroll(int(entry["wheel"]) * wheel_steps * SCROLL_WHEEL_MULTIPLIER,
                                     _pause=False)
                elif "key" in entry:
                    press_keys(entry["key"])
                    overlay.toast(f"{kind}: {entry.get('label', name)}")
                else:
                    subprocess.Popen(["cmd", "/c", "start", "", entry["run"]])
                    overlay.toast(f"{kind}: {entry.get('label', name)}")
                print(f"{kind} {name} ({context}) → {entry}")

            session_left = brain.session_left()
            # 제스처 실행은 음성 ACTIVE 세션에서만 허용한다. 양손 미리보기는 예외로
            # 감지 후보만 보여주며 실제 액션은 별도 가드에서 차단한다.
            gesture_active = args.two_hand_preview or session_left > 0
            if gesture_active != was_gesture_active:
                palm_motion.update(None, now)
                palm_scroll.reset()
                pinch_volume.update(None, now)
                was_gesture_active = gesture_active
                print("[제스처] ACTIVE 세션 진입" if gesture_active else "[제스처] PASSIVE 세션 진입")

            hand_start = time.perf_counter()
            hands = gest.hands(frame)
            hand = hands[0] if hands else None
            hand_infer_ms = (time.perf_counter() - hand_start) * 1000
            pose_landmarks = pose.update(frame, now) if pose else None
            raw_gesture = hand["gesture"] if hand else None
            # 통계 전송용 신뢰도 — 내장은 MediaPipe score, 커스텀은 kNN 거리를
            # exp(-dist)로 변환(gesture_be.py의 기존 관례와 동일). 발동값은
            # GestureStable로 안정화되지만 점수는 현재 프레임 기준이라 드물게
            # 어긋날 수 있다(허용 가능한 근사치).
            raw_score = hand["score"] if hand else None
            # 내장 분류(7종)가 못 알아본 손모양만 커스텀 분류기가 2차 판정
            if hand and active_custom.n:
                # Registered templates passed collision checks during capture.
                # A close kNN match therefore takes precedence over a weak
                # built-in guess; otherwise Promise is never evaluated when
                # MediaPipe assigns a borderline built-in label first.
                custom_label, dist = active_custom.classify_with_distance(hand["landmarks"])
                if custom_label:
                    raw_gesture = custom_label
                    raw_score = round(float(math.exp(-dist)), 3)
                elif raw_gesture in (None, "None"):
                    raw_gesture = "None"
            registration_active = registration_blocks_gesture_execution(registration)
            # 양손 정적/동적 커스텀 — 시작 궤적이 일치하는 후보가 있으면(claimed)
            # 완성 전까지 내장·1손 정적 제스처 실행을 보류한다(정지한 손모양만으로는
            # 보류하지 않는다). 완성되면 custom_motion_event로 즉발 처리한다.
            if gesture_active and not registration_active:
                custom_pose, custom_motion_event, custom_claimed, custom_dist = active_custom.update(
                    hands, now, disabled_gestures
                )
                # 양손 정적/동적 커스텀도 1손 커스텀과 같은 exp(-거리) 관례로 신뢰도를
                # 낸다 — 정적 매치는 raw_score를 덮어써 static_names 발동부에서 그대로
                # 쓰고, 동적 완성은 custom_score를 dynamic_event 발동부에서 쓴다.
                custom_score = round(float(math.exp(-custom_dist)), 3) if custom_dist is not None else None
                if custom_pose and custom_score is not None:
                    raw_score = custom_score
            else:
                active_custom.update([], now, disabled_gestures)
                custom_pose = custom_motion_event = None
                custom_claimed = False
                custom_score = None
            gesture = stable.update((custom_pose or "None") if custom_claimed else raw_gesture, now)
            if registration_active:
                registration.tick(frame, hands, now)
            # 양손 벌리기/모으기는 우선 HUD·터미널 후보만 출력한다. 실측 후에만
            # 전체화면 같은 실제 액션 매핑을 추가한다.
            two_hand_event = two_hand_motion.update(
                hands if gesture_active and not registration_active else [], now
            )
            if two_hand_event:
                hud_feedback = two_hand_event
                hud_feedback_until = now + 1.2
                print(f"[TWO_HAND CANDIDATE] event={two_hand_event}")
            # 컨텍스트 판별: 키 입력은 '포커스된 창'으로 가므로, 브라우저가 포그라운드일
            # 때만 유튜브 컨텍스트로 전환한다. DOM video.present만 믿으면 백그라운드
            # 유튜브 때문에 앞의 워드 문서에 'm'이 찍히는 사고가 난다.
            fg_title = active_window_title()
            fg_is_browser = (is_youtube(fg_title)
                             or any(b in fg_title.lower() for b in BROWSERS))
            dom = bridge.context()
            dom_video = bool(dom and isinstance(dom.get("video"), dict)
                             and dom["video"].get("present"))
            if is_youtube(fg_title) or (dom_video and fg_is_browser):
                context = "youtube"
            elif is_webex(fg_title):
                context = "webex"
            elif is_powerpoint(fg_title):
                context = "powerpoint"
            elif is_ebook(fg_title):
                context = "ebook"
            elif any(browser in fg_title.lower() for browser in BROWSERS):
                context = "browser"
            else:
                context = "default"
            # 컨텍스트 단위 폴백만 — 제스처 단위로 default를 부활시키면
            # 유튜브 섹션에서 지운 제스처가 영상 위에 앱을 띄우는 사고가 난다
            # Context-specific entries override the common defaults. This lets
            # a general command (for example, opening File Explorer) remain
            # available in browser/e-book contexts without duplicating it.
            mapping = {**gesture_map["default"], **gesture_map.get(context, {})}
            # Two-hand gestures are local fallbacks for now: they do not have a
            # BE default mapping yet, but use the same context map as swipes.
            if (two_hand_event and gesture_active and not registration_active and not args.two_hand_preview
                    and two_hand_event not in disabled_gestures):
                entry = mapping.get(two_hand_event)
                if entry and not args.be_gesture_only:
                    hud_feedback = entry.get("label", two_hand_event)
                    hud_feedback_until = now + 0.9
                    print(f"[TWO_HAND→LOCAL] event={two_hand_event} | context={context}")
                    fire_entry(entry, two_hand_event, "양손 제스처")
            for name in static_names:
                entry = mapping.get(name)
                # 등록 중이거나 커스텀 동작 후보를 추적 중이면(claimed, 그리고 이
                # 이름이 그 후보가 아니면) false를 넣어 홀드 상태도 해제한다.
                # 등록 완료 직후 직전 손모양이 명령으로 발동하는 것도 이걸로 막는다.
                allowed = static_execution_allowed(gesture_active, registration_active,
                                                    custom_claimed, custom_pose, name)
                fired = gesture_toggles[name].update(allowed and gesture == name, now)
                if fired and name not in disabled_gestures and not args.two_hand_preview:
                    be_target = be_gesture_target(
                        name, context, {ref.get("name") for ref in remote_refs.values()}
                    )
                    if link and link.gesture_ready and be_target:
                        be_name, be_context = be_target
                        if args.no_actions:
                            overlay.toast(f"[시늉만] 제스처→BE: {name}")
                        else:
                            print(f"[GESTURE→BE] detected={name} | name={be_name} | context={be_context or 'default'}")
                            link.send_event("gesture_exec", {"name": be_name, "hwnd": foreground_hwnd(),
                                                              "context": be_context})
                        hud_feedback = name
                        hud_feedback_until = now + 0.9
                    elif entry and not args.be_gesture_only:
                        if link and link.gesture_ready:
                            print(f"[GESTURE→LOCAL] no BE mapping: {name} ({context})")
                        fire_entry(entry, name, "제스처")
                    if link:
                        link.queue_usage("gesture",
                                         sessionId=link.be_session_id,
                                         action=name,
                                         context=context,
                                         accuracy=raw_score,
                                         payload={"source": "static", "occurredAt": int(time.time() * 1000)})
            if gesture_active and not registration_active:
                pinch_event = pinch_volume.update(hand["landmarks"] if hand else None, now)
                motion_event = palm_motion.update(
                    hand["anchor"] if hand and not pinch_volume._pinched else None, now)
                scroll_steps = palm_scroll.update(
                    hand["anchor"] if hand and not pinch_volume._pinched else None, now)
                if custom_motion_event:
                    # 완성된 커스텀 동작이 최우선 — 같은 손 움직임이 우연히
                    # 스와이프/스크롤로도 읽혀 이중 발동하는 것을 막는다.
                    dynamic_event = custom_motion_event
                elif pinch_event:
                    dynamic_event = pinch_event
                elif motion_event == "Swipe_Right":
                    dynamic_event = "Screen_Next"
                elif motion_event == "Swipe_Left":
                    dynamic_event = "Screen_Prev"
                elif scroll_steps > 0:
                    dynamic_event = "Scroll_Up"
                elif scroll_steps < 0:
                    dynamic_event = "Scroll_Down"
                else:
                    dynamic_event = None
            else:
                palm_motion.update(None, now)
                palm_scroll.reset()
                pinch_volume.update(None, now)
                dynamic_event = None
                scroll_steps = 0
            # 동적 제스처는 순간 이벤트라 정적 손모양 HUD와 별도 표시한다.
            # 실행이 비활성화됐어도 감지 자체는 확인할 수 있어 실측에 유용하다.
            if dynamic_event:
                dynamic_hud_event = dynamic_event
                dynamic_hud_until = now + 0.9
            if (ENABLE_DYNAMIC_GESTURES and not registration_active and dynamic_event
                    and dynamic_event not in disabled_gestures
                    and not args.two_hand_preview):
                entry = mapping.get(dynamic_event)
                be_target = be_gesture_target(
                    dynamic_event, context, {ref.get("name") for ref in remote_refs.values()}
                )
                if link and link.gesture_ready and be_target:
                    be_name, be_context = be_target
                    if args.no_actions:
                        overlay.toast(f"[시늉만] 제스처→BE: {dynamic_event}")
                    else:
                        print(f"[GESTURE→BE] detected={dynamic_event} | name={be_name} | context={be_context or 'default'}")
                        link.send_event("gesture_exec", {"name": be_name, "hwnd": foreground_hwnd(),
                                                          "context": be_context})
                    hud_feedback = dynamic_event
                    hud_feedback_until = now + 0.9
                    link.queue_usage("gesture",
                                     sessionId=link.be_session_id,
                                     action=dynamic_event,
                                     context=context,
                                     # 내장 Swipe/Scroll/Pinch는 FSM 판정이라 신뢰도가
                                     # 없다(None → 자동 생략). 커스텀 동작 완성이면
                                     # custom_score(exp(-거리))가 실린다.
                                     accuracy=custom_score,
                                     payload={"source": "dynamic", "occurredAt": int(time.time() * 1000)})
                elif entry and not args.be_gesture_only:
                    if link and link.gesture_ready:
                        print(f"[GESTURE→LOCAL] no BE mapping: {dynamic_event} ({context})")
                    # 핀치 슬라이더의 즉시 피드백. YouTube에서는 위/아래 화살표가
                    # 보통 5% 단위의 실제 볼륨 제어로 전달된다.
                    if dynamic_event == "Volume_Up":
                        hud_volume = min(100, hud_volume + 5)
                    elif dynamic_event == "Volume_Down":
                        hud_volume = max(0, hud_volume - 5)
                    hud_feedback = entry.get("label", dynamic_event)
                    hud_feedback_until = now + 0.9
                    print(f"[제스처 제어] 명령={dynamic_event} | "
                          f"키={entry.get('key', '-')} | 표시={entry.get('label', dynamic_event)}")
                    fire_entry(entry, dynamic_event, "제스처", wheel_steps=abs(scroll_steps) or 1)
                    if link:
                        link.queue_usage("gesture",
                                         sessionId=link.be_session_id,
                                         action=dynamic_event,
                                         context=context,
                                         payload={"source": "dynamic", "occurredAt": int(time.time() * 1000)})

            # --- 상태 표시 (세션 남은 시간 포함) ---
            if link and now - last_usage_flush >= 5.0:
                link.flush_usage()
                last_usage_flush = now

            if brain.busy:
                overlay.set_state("THINKING")
            elif voice.recording:
                overlay.set_state("LISTENING")
            elif gesture_active:
                suffix = f" {int(session_left)}s"
                overlay.set_state("ACTIVE", suffix)
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
                     else f"ACTIVE {int(session_left)}s" if gesture_active
                     else "IDLE")
            # 상태, 정적 손모양, 동적 이벤트를 같은 형식의 독립된 줄로 보여 준다.
            # 예: ACTIVE 12s / STATIC: Victory / DYNAMIC: Screen_Next
            cv2.putText(hud, state, (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 220, 80), 2)
            if gesture_active and not registration_active and gesture not in (None, "None"):
                cv2.putText(hud, f"STATIC: {gesture}", (10, 48),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (80, 220, 80), 1)
            pose_text = (f"LOOP {loop_fps:.1f} FPS | HAND {hand_infer_ms:.1f}ms"
                         + (f" | POSE {pose.last_infer_ms:.1f}ms/{POSE_MAX_FPS:.0f}Hz" if pose else ""))
            if now < dynamic_hud_until:
                cv2.putText(hud, f"DYNAMIC: {dynamic_hud_event}", (10, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (70, 210, 255), 2)
            cv2.putText(hud, pose_text, (10, 92),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 220, 255), 1)
            if pose_landmarks:
                # 팔 관절만 표시: 왼/오른 어깨(11,12), 팔꿈치(13,14), 손목(15,16)
                for a, b in ((11, 13), (13, 15), (12, 14), (14, 16)):
                    ax, ay, av = pose_landmarks[a]
                    bx, by, bv = pose_landmarks[b]
                    if min(av, bv) >= 0.4:
                        cv2.line(hud, (int(ax * 480), int(ay * 270)),
                                 (int(bx * 480), int(by * 270)), (255, 170, 80), 1)
            if worker and worker.last_px:
                gx = int(worker.last_px[0] / screen[0] * 480)
                gy = int(worker.last_px[1] / screen[1] * 270)
                cv2.circle(hud, (gx, gy), 6, (255, 212, 127), 2)
            if hand:
                hx = int(hand["anchor"][0] * 480)
                hy = int(hand["anchor"][1] * 270)
                if gesture_active:
                    # 손을 중심으로 한 간단한 JARVIS 스타일 제어 링
                    cv2.circle(hud, (hx, hy), 28, (255, 210, 70), 2)
                    cv2.circle(hud, (hx, hy), 34, (100, 180, 255), 1)
                    cv2.putText(hud, "CTRL", (hx - 19, hy + 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 210, 70), 1)

                    # 핀치 중에는 손 옆에 세로 볼륨 슬라이더를 표시한다.
                    # 손이 화면 가장자리에 있어도 슬라이더가 잘리지 않게 좌표를 제한한다.
                    if pinch_volume._pinched:
                        bar_x = min(450, max(16, hx + 43))
                        bar_top = min(170, max(48, hy - 62))
                        bar_bottom = bar_top + 124
                        fill_top = int(bar_bottom - (bar_bottom - bar_top) * hud_volume / 100)
                        cv2.rectangle(hud, (bar_x, bar_top), (bar_x + 12, bar_bottom),
                                      (45, 45, 45), -1)
                        cv2.rectangle(hud, (bar_x, bar_top), (bar_x + 12, bar_bottom),
                                      (230, 230, 230), 1)
                        cv2.rectangle(hud, (bar_x + 2, fill_top), (bar_x + 10, bar_bottom - 2),
                                      (70, 210, 255), -1)
                        cv2.putText(hud, f"VOL {hud_volume}%", (bar_x - 20, bar_top - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (70, 210, 255), 1)
                    elif now < hud_feedback_until:
                        cv2.putText(hud, hud_feedback, (max(8, hx - 55), min(255, hy + 54)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (70, 210, 255), 2)
                for lx, ly in hand["landmarks"]:
                    cv2.circle(hud, (int(lx * 480), int(ly * 270)), 2, (80, 220, 80), -1)
            cv2.imshow("assistant (ESC=quit)", hud)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        camera.running = False
        voice.stop()
        voice.join(timeout=4)
        if worker:
            worker.running = False
        if link:
            link.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 한글·em-dash 출력 크래시 방지
    except Exception:
        pass
    main()
