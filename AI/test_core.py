# -*- coding: utf-8 -*-
"""카메라 없이 도는 핵심 로직 스모크 테스트:  python test_core.py"""
import threading

import numpy as np
from types import SimpleNamespace

from gaze import FEATURE_DIM, Calibrator, ClickRecal, GazeBuffer
from hands import GestureStable, HoldToggle, OneEuro, PinchFSM
from gesture_be import GestureRegistration, registration_blocks_gesture_execution


def test_registration_execution_gate():
    """FR-065: 등록 중에는 기존 제스처 명령 실행을 차단한다."""
    class Registration:
        def __init__(self, active):
            self.active = active

    assert not registration_blocks_gesture_execution(None)
    assert not registration_blocks_gesture_execution(Registration(False))
    assert registration_blocks_gesture_execution(Registration(True))


def test_registration_timing_contract():
    """BE 촬영 계획을 쓰며, 조기 reg_finish를 품질 실패로 오인하지 않는다."""
    class Link:
        def __init__(self):
            self.sent = []

        def send_event(self, event_type, data):
            self.sent.append((event_type, data))

    link = Link()
    reg = GestureRegistration(link, template_cache=None, custom_store=None)
    reg.start({"tempId": "t1", "takes": 12, "countdownSec": 15.0,
               "takeDurationSec": 12.5}, now=10.0)
    assert (reg.takes, reg.countdown_s, reg.take_s) == (12, 15.0, 12.5)
    assert reg.tick(None, None, now=24.99)["phase"] == "COUNTDOWN"
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    assert reg.tick(frame, None, now=25.0)["phase"] == "RECORDING"

    reg.finish()  # RECORDING 중 reg_finish → 품질 검사 대신 명시적 중단
    assert not reg.active
    assert link.sent[-1][0] == "reg_rejected"
    assert "촬영이 완료되기 전" in link.sent[-1][1]["reason"]


def test_calibrator():
    rng = np.random.default_rng(0)
    X = rng.uniform(-0.5, 0.5, size=(200, FEATURE_DIM))
    # 실제와 비슷한 매끈한 비선형 매핑
    Y = np.stack([
        960 + 800 * X[:, 0] + 300 * X[:, 0] * X[:, 3] + 100 * X[:, 4],
        540 + 450 * X[:, 1] + 200 * X[:, 1] ** 2 + 80 * X[:, 5],
    ], axis=1)
    c = Calibrator(1920, 1080)
    rms = c.fit(X, Y)
    assert rms < 10, f"학습 잔차가 너무 큼: {rms}"
    px, py = c.predict(X[0])
    assert abs(px - Y[0, 0]) < 30 and abs(py - Y[0, 1]) < 30
    # 화면 밖 → 모서리 2px 안쪽으로 clamp (pyautogui failsafe 모서리 회피)
    ox, oy = c.predict(np.ones(FEATURE_DIM) * 9)
    assert 2 <= ox <= 1917 and 2 <= oy <= 1077
    ox, oy = c.predict(np.ones(FEATURE_DIM) * -9)
    assert 2 <= ox <= 1917 and 2 <= oy <= 1077


def test_gaze_buffer():
    b = GazeBuffer()
    for i in range(20):  # 0.0~0.95초: (500,500) 응시
        b.push(i * 0.05, 500 + (i % 3), 500 - (i % 3))
    for i in range(6):   # 이후 눈이 떠남 (트리거 직전 상황)
        b.push(1.0 + i * 0.05, 1500, 200)
    pt, is_fix = b.fixation_at(1.2, lookback=0.3, window=0.3)
    # 1.2-0.3=0.9 시점 근처 → 떠나기 전 (500,500) fixation을 잡아야 함
    assert is_fix and abs(pt[0] - 500) < 20 and abs(pt[1] - 500) < 20, (pt, is_fix)
    pt, _ = b.fixation_at(1.3, lookback=0.0, window=0.2)
    assert abs(pt[0] - 1500) < 20  # 현재 시선은 새 위치


def test_gaze_buffer_stale():
    # 얼굴 추적이 끊겨 push가 멈추면, 오래된 샘플로 절대 트리거하면 안 된다
    b = GazeBuffer()
    for i in range(10):
        b.push(i * 0.05, 800, 800)
    pt, is_fix = b.fixation_at(31.0, lookback=0.25)  # 30초 뒤 핀치
    assert pt is None and not is_fix, (pt, is_fix)
    pt, is_fix = b.fixation_at(1.0, lookback=0.25)   # 신선할 땐 정상
    assert pt is not None and is_fix
    # 폴백 샘플이 1개뿐이면 분산이 0이어도 '확정 응시'로 인정하면 안 됨
    b2 = GazeBuffer()
    b2.push(0.0, 800, 800)
    pt, is_fix = b2.fixation_at(0.9, lookback=0.25)
    assert pt is not None and not is_fix


def test_pinch_fsm():
    p = PinchFSM(release_grace_s=0.1)
    assert p.update(0.30, t=0.0) is None    # 무장 전 — 오므린 채 등장한 손은 무시
    assert p.update(0.60, t=0.1) is None    # 벌림 → 무장
    assert p.update(0.30, t=0.2) == "down"
    assert p.update(0.40, t=0.24) is None   # 히스테리시스 구간 → 유지
    assert p.update(0.48, t=0.25) is None   # 한 프레임 스파이크 — 유예로 흡수
    assert p.update(0.30, t=0.28) is None and p.held
    assert p.update(None, t=0.30) is None   # 한 프레임 검출 끊김 — 유예로 흡수
    assert p.update(0.30, t=0.33) is None and p.held
    assert p.update(0.60, t=0.40) is None   # 실제 벌림 시작
    assert p.update(0.60, t=0.55) == "up"   # 유예 경과 → 해제 확정 (클릭 후보)
    assert p.update(0.30, t=0.60) == "down"  # 벌려서 놓았으면 재무장 상태
    assert p.update(None, t=0.70) is None
    assert p.update(None, t=0.85) == "lost"  # 손 소실 → lost (클릭 금지)
    assert p.update(0.30, t=0.90) is None    # lost 후엔 다시 벌려야 down 가능
    p.update(0.60, t=1.00)
    assert p.update(0.30, t=1.10) == "down"
    p.reset()
    assert not p.held


def test_hold_toggle():
    h = HoldToggle(hold_s=0.5, cooldown_s=1.0)
    assert not h.update(True, t=0.0)
    assert not h.update(True, t=0.3)
    assert h.update(True, t=0.6)            # 0.5초 유지 → 발동
    assert not h.update(True, t=0.8)        # 래치: 계속 들고 있으면
    assert not h.update(True, t=10.0)       # 아무리 오래 있어도 재발동 없음
    assert not h.update(False, t=11.0)      # 내리면 재장전
    assert not h.update(True, t=11.1)
    assert h.update(True, t=11.7)
    # 짧은 손바닥 → 손 사라짐(False 호출) → 한참 뒤 한 프레임 손바닥: 발동 금지
    h2 = HoldToggle(hold_s=0.5, cooldown_s=1.0)
    h2.update(True, t=0.0)
    h2.update(False, t=0.3)                 # 손이 안 보이는 프레임도 False로 호출됨
    assert not h2.update(True, t=20.0)      # 타이머가 새로 시작해야 함
    # grace 이내의 한 프레임 검출 끊김은 홀드를 유지해야 함
    h3 = HoldToggle(hold_s=0.5, cooldown_s=1.0, grace_s=0.25)
    h3.update(True, t=0.0)
    assert not h3.update(False, t=0.1)      # 깜빡임 — grace 이내
    assert h3.update(True, t=0.55)          # 홀드 이어짐 → 발동


def test_gesture_stable():
    g = GestureStable(min_frames=3)
    assert g.update("Thumb_Up") == "None"   # 한 프레임 오분류 무시
    assert g.update("Thumb_Up") == "None"
    assert g.update("Thumb_Up") == "Thumb_Up"
    assert g.update("Victory") == "None"    # 바뀌면 카운트 리셋
    assert g.update(None) == "None"


def test_click_recal(tmp_dir=None):
    """바이어스 있는 캘리브레이션이 클릭 샘플(진짜 정답)로 재학습되며 개선되는지."""
    import tempfile
    from pathlib import Path

    rng = np.random.default_rng(1)
    X = rng.uniform(-0.5, 0.5, size=(150, FEATURE_DIM))

    def true_map(X):
        return np.stack([960 + 800 * X[:, 0] + 120 * X[:, 4],
                         540 + 450 * X[:, 1] + 90 * X[:, 5]], axis=1)

    c = Calibrator(1920, 1080)
    c.fit_base(X, true_map(X) + np.array([120, 80]))  # 캘리브레이션에 바이어스가 낀 상황

    Xtest = rng.uniform(-0.4, 0.4, size=(50, FEATURE_DIM))
    def mean_err():
        pred = np.array([c.predict(x) for x in Xtest])
        return float(np.linalg.norm(pred - true_map(Xtest), axis=1).mean())

    before = mean_err()
    d = Path(tempfile.mkdtemp())
    recal = ClickRecal(c, d / "calib.npz", d / "clicks.npz", refit_every=5, weight=3.0)
    # 정합성 게이트: 예측과 화면 반쯤 어긋난 클릭(딴 데 보며 클릭)은 거부돼야 함
    far = true_map(Xtest[:1])[0] + np.array([1500, 0])
    assert recal.add(Xtest[0], *far) is None and len(recal.X) == 0
    Xc = rng.uniform(-0.4, 0.4, size=(30, FEATURE_DIM))
    Yc = true_map(Xc)  # 클릭은 진짜 정답 (바이어스 144px는 게이트 통과)
    rms = None
    for xf, yp in zip(Xc, Yc):
        r = recal.add(xf, *yp)
        rms = r if r is not None else rms
    after = mean_err()
    assert rms is not None                      # refit_every마다 재학습이 돌았는지
    assert after < before * 0.6, (before, after)  # 바이어스가 크게 줄어야 함
    assert (d / "calib.npz").exists() and (d / "clicks.npz").exists()  # 영속화
    # 저장본을 다시 읽어도 기본 샘플이 유지되는지 (다음 세션에서 재보정 계속)
    c2 = Calibrator.load(d / "calib.npz")
    assert c2.X0 is not None and len(c2.X0) == 150


def test_vad_segmenter():
    import voice
    from voice import BLOCK, VadSegmenter

    seg = VadSegmenter()
    quiet = np.full(BLOCK, 120, dtype=np.int16)
    loud = np.full(BLOCK, 4000, dtype=np.int16)
    # floor 를 안 주면 MIC_FLOOR 로 시작한다. 윈도우 볼륨을 올려도 임계에 못 닿는 장치가 있어
    # (블루투스 헤드셋) 환경변수로 내릴 수 있어야 한다 — noise 도 같이 따라가야 threshold 가 안 터진다.
    assert seg.floor == seg.noise == voice.MIC_FLOOR
    assert VadSegmenter(floor=120.0).floor == 120.0   # 명시 인자가 환경변수보다 우선
    t = 0.0
    events = []

    def feed(block, n):
        nonlocal t
        for _ in range(n):
            t += seg.block_dur
            ev = seg.feed(block, t)
            if ev:
                events.append(ev)

    feed(quiet, 40)                    # 노이즈 바닥 학습
    assert not events
    feed(loud, 1)                      # 한 블록(30ms) 소음 — 시작 조건(2블록) 미달
    feed(quiet, 40)
    assert not events
    feed(loud, 3)                      # 짧은 소음(90ms) — onset은 나도 발화로 확정 안 됨
    feed(quiet, 40)
    assert all(e[0] != "utter" for e in events), events
    events.clear()
    feed(loud, 30)                     # 0.9초 발화
    assert events and events[0][0] == "onset"
    onset_t = events[0][1]
    feed(quiet, 40)                    # 0.75초 침묵 → 발화 종료
    assert events[-1][0] == "utter"
    _, t_onset, audio = events[-1]
    assert abs(t_onset - onset_t) < 1e-6
    assert len(audio) >= 30 * BLOCK    # 발화 본체 + 프리롤 포함
    assert not seg.recording

    # 유지 임계 + 꼬리: 바닥 300 → 시작 임계 450, 유지 임계 350. 400 짜리 블록은 시작 못 열지만
    # 녹음 중 직전 유성 뒤 0.3 s(10블록) 안에서는 침묵으로 안 세고, 그 밖에서는 침묵으로 센다.
    seg = VadSegmenter()
    noise = np.full(BLOCK, 300, dtype=np.int16)
    mid = np.full(BLOCK, 400, dtype=np.int16)
    events.clear()
    feed(noise, 200)                   # 바닥 창(40 s)에 유성·꼬리 블록이 섞여도 p80 이 300 에 머물 만큼
    assert seg.threshold_lo < 400 < seg.threshold  # 400 은 유지 임계와 시작 임계 사이
    feed(mid, 10)
    assert not events                  # 유지 임계만 넘는 소리로는 녹음이 안 열린다
    feed(loud, 30)
    assert events[-1][0] == "onset"
    feed(mid, seg.tail_blocks)         # 꼬리 안 — 침묵 계수 0 유지
    assert seg.recording and seg._quiet == 0
    speech_before = seg._speech
    feed(mid, seg.end_blocks + 5)      # 꼬리 밖 — 침묵으로 세어 종료
    assert events[-1][0] == "utter" and not seg.recording
    assert seg._speech == speech_before  # 유지 임계 블록은 유성 계수에 안 들어간다
    _, _, audio = events[-1]
    assert len(audio) >= (seg.preroll_n + 30) * BLOCK  # 프리롤 2.0 s(66블록) + 발화 본체
    assert seg.preroll_n == int(2.0 / seg.block_dur)


def test_swipe_detector():
    from hands import SwipeDetector

    s = SwipeDetector()
    t = 0.0

    def feed(xs):
        nonlocal t
        out = []
        for x in xs:
            t += 1 / 30
            r = s.update((x, 0.5), t)
            if r:
                out.append(r)
        return out

    assert feed([0.5] * 15) == []                                  # 정지 → 무장
    assert feed([0.5 + i * 0.04 for i in range(1, 9)]) == ["Swipe_Right"]
    assert feed([0.82 - i * 0.04 for i in range(1, 9)]) == []      # 되돌아오는 손 — 무시
    # Any neutral position can re-arm after the short return-motion lock.
    assert feed([0.2] * 15) == []
    assert feed([0.2 - i * 0.04 for i in range(1, 8)]) == ["Swipe_Left"]

    # A fast reversal is the return motion, not a second command.
    guarded = SwipeDetector()
    gt = 0.0

    def guarded_feed(xs):
        nonlocal gt
        out = []
        for x in xs:
            gt += 1 / 30
            event = guarded.update((x, 0.5), gt)
            if event:
                out.append(event)
        return out

    assert guarded_feed([0.5] * 15) == []
    assert guarded_feed([0.5 + i * 0.04 for i in range(1, 9)]) == ["Swipe_Right"]
    assert guarded_feed([0.82 - i * 0.04 for i in range(1, 9)]) == []
    # Any stable position, rather than the original center, re-arms it.
    assert guarded_feed([0.2] * 15) == []
    assert guarded_feed([0.2 - i * 0.04 for i in range(1, 8)]) == ["Swipe_Left"]

    # A same-direction repeat does not need a neutral hold.  The return path
    # is ignored, then the next rightward sweep is accepted from its turn point.
    rapid = SwipeDetector()
    rt = 0.0

    def rapid_feed(xs):
        nonlocal rt
        out = []
        for x in xs:
            rt += 1 / 30
            event = rapid.update((x, 0.5), rt)
            if event:
                out.append(event)
        return out

    assert rapid_feed([0.5] * 15) == []
    assert rapid_feed([0.5 + i * 0.04 for i in range(1, 9)]) == ["Swipe_Right"]
    assert rapid_feed([0.82 - i * 0.04 for i in range(1, 10)]) == []
    assert rapid_feed([0.46 + i * 0.04 for i in range(1, 8)]) == ["Swipe_Right"]
    # 수직 이동은 스와이프가 아니다
    s2 = SwipeDetector(vertical=False)
    t2 = 0.0
    for _ in range(15):
        t2 += 1 / 30
        s2.update((0.5, 0.5), t2)
    for i in range(1, 9):
        t2 += 1 / 30
        assert s2.update((0.5 + i * 0.02, 0.5 + i * 0.05), t2) is None
    # 손 사라짐 → 리셋 (재등장 즉시 스와이프 불가)
    s.update(None, t)
    assert s.update((0.9, 0.5), t + 0.03) is None


def test_scale_by_hand_size():
    """스와이프 등의 이동량 기준은 화면 비율(절대값)이라, 카메라와의 거리에
    따라 같은 물리적 동작도 다르게 판정된다 — 손 크기로 스케일 보정하면
    카메라 거리와 무관하게 같은 결과가 나와야 한다."""
    from hands import SCREEN_SWIPE_CONFIG, SwipeDetector, scale_by_hand_size

    def run(palm_size, physical_multiple, use_scale):
        det = SwipeDetector(**SCREEN_SWIPE_CONFIG)
        t = 0.0
        events = []
        for _ in range(6):  # 정지 상태로 무장
            t += 0.05
            anchor = (0.5, 0.5)
            events.append(det.update(scale_by_hand_size(anchor, palm_size) if use_scale else anchor, t))
        total = physical_multiple * palm_size  # "손 크기의 N배"만큼의 물리적 이동
        for i in range(1, 7):
            t += 0.05
            anchor = (0.5 + total * i / 6, 0.5)
            events.append(det.update(scale_by_hand_size(anchor, palm_size) if use_scale else anchor, t))
        return [e for e in events if e]

    far_palm, close_palm, physical_multiple = 0.06, 0.24, 1.5
    # 보정 없이(화면 비율 그대로) 같은 물리적 스와이프를 하면, 카메라에 가까울
    # 때만 발동하고 멀 때는 안 걸린다 — 이게 지금 고치려는 문제 상황이다.
    assert run(far_palm, physical_multiple, use_scale=False) == []
    assert run(close_palm, physical_multiple, use_scale=False) == ["Swipe_Right"]
    # 손 크기로 보정하면 카메라 거리와 무관하게 똑같이 발동해야 한다.
    assert run(far_palm, physical_multiple, use_scale=True) == ["Swipe_Right"]
    assert run(close_palm, physical_multiple, use_scale=True) == ["Swipe_Right"]


def test_custom_gestures():
    import math as m
    import tempfile
    from pathlib import Path

    from hands import CustomGestures, normalize_landmarks

    rng = np.random.default_rng(2)

    def hand_shape(seed):  # 가짜 손모양: 손목(0)+MCP(9) 고정, 나머지 랜덤 배치
        r = np.random.default_rng(seed)
        a = r.uniform(-0.5, 0.5, size=(21, 2))
        a[0] = (0.0, 0.0)
        a[9] = (0.0, -0.4)
        return a

    base = hand_shape(1)
    f0 = normalize_landmarks(base)
    # 위치·크기·회전 불변성: 이동+2배 확대+37도 회전해도 같은 특징 벡터
    ang = m.radians(37)
    R = np.array([[m.cos(ang), -m.sin(ang)], [m.sin(ang), m.cos(ang)]])
    moved = (base @ R.T) * 2.0 + np.array([3.3, -1.7])
    assert np.linalg.norm(normalize_landmarks(moved) - f0) < 1e-6

    d = Path(tempfile.mkdtemp())
    store = CustomGestures(d / "cg.npz")
    # 등록: 손모양 A(노이즈 낀 샘플 30개), 손모양 B
    A = [normalize_landmarks(base + rng.normal(0, 0.01, (21, 2))) for _ in range(30)]
    B = [normalize_landmarks(hand_shape(9) + rng.normal(0, 0.01, (21, 2))) for _ in range(30)]
    store.add("shakaA", A)
    store.add("shakaB", B)
    assert store.classify(base + rng.normal(0, 0.01, (21, 2))) == "shakaA"
    label, distance = store.classify_with_distance(base + rng.normal(0, 0.01, (21, 2)))
    assert label == "shakaA" and distance < store.thresh
    assert store.classify(hand_shape(9)) == "shakaB"
    assert store.classify(hand_shape(77)) is None  # 미등록 손모양 → 기권
    # 혼동도: A와 거의 같은 샘플 묶음은 A에 가깝다고 보고돼야 함
    near, dist = store.nearest_class(A[:5])
    assert near == "shakaA" and dist < 0.05
    # 영속화 + 삭제
    store2 = CustomGestures(d / "cg.npz")
    assert set(store2.class_names()) == {"shakaA", "shakaB"}
    store2.remove("shakaA")
    assert store2.class_names() == ["shakaB"]
    # 손상된 파일은 조용히 삼키지 않고 예외 (다음 add가 기존 등록을 덮어쓰는 사고 방지)
    (d / "bad.npz").write_bytes(b"not a zip")
    try:
        CustomGestures(d / "bad.npz")
        assert False, "손상 파일에서 예외가 나야 함"
    except Exception:
        pass


def test_build_prompt():
    from brain import WAKE_WORD, build_prompt

    p1 = build_prompt(False, None)                 # 대기 상태: 호출어 필수
    assert WAKE_WORD in p1 and "호출어 규칙" in p1 and "활성 세션" not in p1
    assert '"is_command"' in p1 and "환각 금지" in p1
    p2 = build_prompt(True, None)                  # 활성 세션: 호출어 불필요
    assert "활성 세션" in p2 and "호출어 규칙" not in p2
    p3 = build_prompt(True, "창을 닫을까요?")        # 확인 대기 중
    assert "confirm_yes" in p3 and "창을 닫을까요?" in p3


def test_one_euro():
    f = OneEuro(min_cutoff=1.0, beta=20.0)
    t = 0.0
    out = f((0.5, 0.5), t)
    assert tuple(out) == (0.5, 0.5)          # 첫 샘플은 그대로
    # 정지 상태의 미세 떨림 → 출력 변화가 입력 떨림보다 작아야 함 (스무딩)
    for i in range(30):
        t += 1 / 30
        out = f((0.5 + 0.002 * (-1) ** i, 0.5), t)
    assert abs(out[0] - 0.5) < 0.002
    # 빠른 이동 → 큰 지연 없이 따라와야 함 (반응성)
    for i in range(30):
        t += 1 / 30
        out = f((0.5 + (i + 1) * 0.01, 0.5), t)
    assert out[0] > 0.72                     # 목표 0.8까지 지연이 크지 않음
    f.reset()
    assert f((0.1, 0.1), t + 1)[0] == 0.1    # 리셋 후 새로 시작


def test_wake_first_frame():
    """호출어 끝 = 처음 임계를 넘은 프레임. 점수가 플래토를 이루면 최고점은 그 위 아무 데나 찍혀 뒤에 붙은 명령 끝까지 밀린다."""
    from types import SimpleNamespace
    from brain import WAKE_MODEL, WAKE_THRESHOLD, wake_score_of

    plateau = [0.0, 0.0, round(WAKE_THRESHOLD + 0.01, 3), 0.999, 0.999, 0.999, 0.2]  # 셋째 프레임이 임계를 처음 넘는다
    model = SimpleNamespace(predict_clip=lambda audio: [{WAKE_MODEL.stem: s} for s in plateau])
    top, i_first, lead = wake_score_of(model, np.zeros(16000, np.int16))
    assert top == 0.999 and i_first == 2 and lead == 0
    below = SimpleNamespace(predict_clip=lambda audio: [{WAKE_MODEL.stem: WAKE_THRESHOLD - 0.01}])
    assert wake_score_of(below, np.zeros(16000, np.int16))[1] is None


def test_speech_s():
    """유성 초 — voice_rejected 이벤트 가드. 2 s 소리 + 1 s 무음 → 2.0, 무음만 → 0, 빈 입력 → 0."""
    from brain import SPEAKER_JUDGE_SPEECH_S, speech_s
    rng = np.random.default_rng(0)
    loud = (rng.standard_normal(2 * 16000) * 2000).astype(np.int16)   # rms ≈ 2000 > 350
    quiet = np.zeros(16000, np.int16)
    assert abs(speech_s(np.concatenate([loud, quiet])) - 2.0) < 0.05
    assert speech_s(quiet) == 0.0
    assert speech_s(np.zeros(0, np.int16)) == 0.0
    assert speech_s(loud[:int(0.7 * 16000)]) < SPEAKER_JUDGE_SPEECH_S   # 단독 "시아야" 길이 → 이벤트 안 감


def test_speaker_input_lead():
    """3 s 크롭을 못 하는 발화는 말소리 앞 여유를 SPEAKER_LEAD_S 로 줄이고 뒤 꼬리는 둔다.
    앞 여유가 이미 짧거나 배경이 계속 커서 말 시작을 못 가리면 원본 그대로."""
    from brain import SPEAKER_LEAD_S, speaker_input
    rng = np.random.default_rng(0)
    loud = (rng.standard_normal(16000) * 2000).astype(np.int16)   # 말소리 1 s (rms ≈ 2000 > 350)
    audio = np.concatenate([np.zeros(int(1.9 * 16000), np.int16), loud, np.zeros(int(0.54 * 16000), np.int16)])
    out, t0, t1 = speaker_input(audio, None)
    assert abs(len(out) / 16000 - (SPEAKER_LEAD_S + 1.54)) < 0.05   # 앞 1.9 → 0.5 s, 말 1 s + 꼬리 0.54 s 는 그대로
    assert abs(t0 - (1.9 - SPEAKER_LEAD_S)) < 0.05 and t1 == round(len(audio) / 16000, 2)
    assert np.array_equal(out, audio[-len(out):])
    short = audio[int(1.6 * 16000):]                                # 앞 여유 0.3 s — 자를 것 없음
    assert speaker_input(short, None)[0] is short
    noisy = (rng.standard_normal(3 * 16000) * 2000).astype(np.int16)  # 배경이 처음부터 큼 — 말 시작을 못 가림
    out, t0, _ = speaker_input(noisy, None)
    assert out is noisy and t0 is None
    assert speaker_input(np.zeros(16000, np.int16), None)[1] is None  # 말소리 없음


def test_speaker_accum():
    """짧은 호출어 조각 이어붙이기(185) — 화자 모델 없이 합성 오디오로 버퍼 규칙만 확인.
    조각 길이를 서로 다르게 줘서, 이어붙인 결과 길이만 봐도 어떤 조각이 들어갔는지 알 수 있게 했다."""
    from brain import SPEAKER_ACCUM_MAX_AGE_S, SPEAKER_ACCUM_N, SpeakerAccum, speech_part
    rng = np.random.default_rng(0)

    def loud(sec):
        return (rng.standard_normal(int(sec * 16000)) * 2000).astype(np.int16)   # rms ≈ 2000 > 350
    quiet = np.zeros(16000, np.int16)

    # 무음은 떨어지고 말소리 블록만 남는다 (경계 블록 하나는 소리가 섞여 살아남음)
    assert abs(len(speech_part(np.concatenate([quiet, loud(1.0), quiet]))) / 16000 - 1.0) < 0.05
    assert len(speech_part(quiet)) == 0
    assert len(speech_part(np.zeros(0, np.int16))) == 0

    a = SpeakerAccum()
    p1, p2, p3 = speech_part(loud(0.5)), speech_part(loud(0.6)), speech_part(loud(0.7))
    assert a.offer(p1, 0.19, 0.0) is None                      # 유사도 미달 → 이어붙임도 없고 버퍼에도 안 쌓임
    assert a.offer(speech_part(loud(0.2)), 0.40, 0.0) is None  # 말소리 0.3 s 미만 → 같음
    assert len(a.offer(p1, 0.40, 0.0)) == len(p1)              # 앞의 둘이 안 쌓였으니 이번 조각만
    assert len(a.offer(p2, 0.40, 1.0)) == len(p1) + len(p2)
    c = a.offer(p3, 0.40, 2.0)
    assert len(c) == len(p1) + len(p2) + len(p3) and a.n_joined == 3
    assert np.array_equal(c[:len(p1)], p1)                     # 오래된 순으로 앞에 붙는다

    # 버퍼가 찬 뒤에는 가장 오래된 조각이 밀려난다
    p4, p5 = speech_part(loud(0.8)), speech_part(loud(0.9))
    assert len(a.offer(p4, 0.40, 3.0)) == len(p1) + len(p2) + len(p3) + len(p4)
    assert a.n_joined == SPEAKER_ACCUM_N + 1                   # 보관 3개 + 이번 조각
    assert len(a.offer(p5, 0.40, 4.0)) == len(p2) + len(p3) + len(p4) + len(p5)  # p1 은 빠짐

    a.clear()
    assert len(a.offer(p5, 0.40, 5.0)) == len(p5)              # 비운 뒤엔 이번 조각만

    b = SpeakerAccum()
    b.offer(p1, 0.40, 0.0)
    assert len(b.offer(p2, 0.40, SPEAKER_ACCUM_MAX_AGE_S + 1)) == len(p2)  # 20 s 지난 조각은 이어붙임에서 빠짐


def test_mouse_subpixel_accumulator():
    from main import Mouse
    m = Mouse(enabled=False)  # 로그만 — 실제 마우스 안 건드림
    m.move_rel(0.4, 0.0)
    m.move_rel(0.4, 0.0)
    assert abs(m._acc[0] - 0.8) < 1e-9      # 1px 미만은 누적
    m.move_rel(0.4, 0.0)                    # 1.2 → 1px 이동 + 잔여 0.2
    assert abs(m._acc[0] - 0.2) < 1e-9


def test_voice_bridge():
    """화자 등록 이벤트 흐름(65) — ready → 문장 5개 collect/progress → 샘플·npz 업로드 → captured.
    문장은 받는 자리에서 바로 임베딩하고, 짧거나 앞 문장과 안 닮으면 voice_sentence_rejected 뒤 같은 문장을 다시 기다린다.
    문장을 받을 때마다 해당 문장 녹음을 올리고 voice_captured 로 판독 결과를 보낸다. 5번째에도 녹음은 한 문장만 올린다.
    같은 문장을 다시 수집하라는 지시가 오면 그 문장부터 뒤 샘플을 버린다."""
    import io
    import wave

    from speaker import SpeakerVerifier
    from voice_bridge import SENTENCES, VoiceSession

    class FakeLink:
        rt = {"port": 0}
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append((o["type"], o["data"]))

    class FakeSpeaker(SpeakerVerifier):  # 임베딩만 가짜 — centroid·npz 직렬화는 진짜 코드
        def __init__(self, p):
            super().__init__(p)
            self.embeds = 0                                    # 몇 번 뽑았는지 — 문장마다 뽑는지 세려고
        def _model(self): return None
        def embed(self, a):
            self.embeds += 1
            return {7: np.array([1.0, 0.0]), 6: np.array([-1.0, 0.0])}.get(int(a[0]), np.array([0.0, 1.0]))  # 첫 샘플 값 = 화자 표식

    rng = np.random.default_rng(0)
    def loud(marker, s=2.0):
        # 앞 0.6 s 무음 + s 초 말소리(rms ≈ 2000) — 무음 블록이 20% 를 넘어야 noise_level 이 "낮음" 이 된다(VAD 프리롤 흉내)
        a = np.concatenate([np.zeros(int(0.6 * 16000), np.int16),
                            (rng.standard_normal(int(s * 16000)) * 2000).astype(np.int16)])
        a[0] = marker
        return a

    link = FakeLink()
    spk = FakeSpeaker("_no_such_profile.npz")
    vs = VoiceSession(link, spk, "_selftest_speaker.npz")
    uploads = []
    def put(url, body, ctype):
        uploads.append((url, body, ctype))
        link.sent.append(("PUT", ctype))
    vs._put = put

    def settle():
        """메인 루프 자리 — 업로드 워커가 끝나기를 기다렸다가 결과(판독·완료·실패 안내)를 내보낸다."""
        with vs._jobs_cv:
            assert vs._jobs_cv.wait_for(lambda: not vs._jobs and not vs._uploading, 3), "업로드 시간 초과"
        vs.apply_uploads()

    def utter(audio, t=None):
        vs.on_utter(audio, t)
        settle()

    def finalize(temp_id):
        vs.on_finalize(temp_id)
        settle()

    assert len(SENTENCES) >= 5                                 # BE 가 total(현재 5)을 정한다 — 상수는 그 이상이면 된다
    # 길이·소음 거절 — 임베딩 전에 거른다. 소음은 예산(2)이 다하면 받되 품질 낮음
    vs.on_start("t0", 5)
    vs.on_collect("t0", 1)
    utter(loud(7, 5.5))                                  # 발화 5.5 s — 문장 하나치곤 길다
    assert link.sent[-1][1]["code"] == "TOO_LONG"
    noisy = (rng.standard_normal(2 * 16000) * 2000).astype(np.int16)   # 조용한 구간이 없다 → 소음 높음
    noisy[0] = 7
    utter(noisy)
    utter(noisy)
    assert [d.get("code") for t, d in link.sent if t == "voice_sentence_rejected"][-2:] == ["NOISY", "NOISY"] and spk.embeds == 0
    utter(noisy)                                         # 소음 거절 예산 소진 — 받되 품질 낮음
    assert [t for t, _ in link.sent][-3:] == ["PUT", "voice_progress", "voice_captured"]   # 문장 하나 = 샘플 업로드 + 진행 + 판독
    assert link.sent[-1][1]["quality"] == "낮음" and link.sent[-1][1]["durationSec"] == 2.0 and spk.embeds == 1
    spk.embeds = 0
    link.sent.clear()
    vs.on_start("t1", 5)
    assert link.sent[-1] == ("voice_ready", {"tempId": "t1"})
    vs.on_collect("t1", 1)
    utter(loud(7, 0.2))                                  # 말소리 0.2 s — 헛기침 길이, 문장 1 그대로
    assert "voice_progress" not in [t for t, _ in link.sent]
    assert link.sent[-1][0] == "voice_sentence_rejected" and link.sent[-1][1]["tempId"] == "t1"
    assert link.sent[-1][1]["code"] == "TOO_SHORT" and spk.embeds == 0   # 짧으면 임베딩까지 가지도 않는다
    uploads.clear()
    samples = [loud(7, 1.0 + 0.2 * n) for n in range(1, 6)]
    for n, sample in enumerate(samples, 1):
        vs.on_collect("t1", n)
        utter(sample)
        assert spk.embeds == n                                 # 문장을 받을 때마다 하나씩 — 마지막에 5개를 몰아 뽑지 않는다
    types = [t for t, _ in link.sent]
    assert types.count("voice_progress") == 5 and types[-3:] == ["PUT", "PUT", "voice_captured"]
    # 1~5번 모두 해당 문장 녹음만 올리고, 마지막에만 전체 임베딩의 npz 를 함께 올린다.
    assert [c for t, c in link.sent if t == "PUT"] == ["audio/wav"] * 4 + ["audio/wav", "application/octet-stream"]
    caps = [d for t, d in link.sent if t == "voice_captured"]
    assert len(caps) == 5 and all(c["tempId"] == "t1" and c["quality"] == "양호" for c in caps)
    assert [c["durationSec"] for c in caps] == [round(len(a) / 16000, 1) for a in samples]
    wav_uploads = [(url, body) for url, body, ctype in uploads if ctype == "audio/wav"]
    assert len(wav_uploads) == 5
    for (url, body), sample in zip(wav_uploads, samples):
        assert url.endswith("/api/agent/voices/t1/sample")
        with wave.open(io.BytesIO(body), "rb") as recorded:
            assert recorded.getnchannels() == 1 and recorded.getsampwidth() == 2
            assert recorded.getframerate() == 16000
            assert np.array_equal(np.frombuffer(recorded.readframes(recorded.getnframes()), dtype="<i2"), sample)
    # 3번 문장만 다른 목소리 → 그 문장만 무른다. 거절 예산(2회)이 떨어지면 받아 주고, 5문장 일관성 0.24 < 0.5 로 최종 경고
    link.sent.clear()
    vs.on_start("t2", 5)
    for n in (1, 2):
        vs.on_collect("t2", n)
        utter(loud(7))
    vs.on_collect("t2", 3)
    utter(loud(9))                                       # 앞 문장과 안 닮음 → 거절 1
    assert link.sent[-1][0] == "voice_sentence_rejected" and link.sent[-1][1]["code"] == "INCONSISTENT"
    assert vs._n == 3 and sorted(vs._samples) == [1, 2]        # 순번은 그대로 — 같은 문장을 계속 기다린다
    utter(loud(7, 0.2))                                  # 짧은 발화(헛기침)는 늘 거절하되 예산은 안 쓴다
    assert link.sent[-1][1]["code"] == "TOO_SHORT" and vs._rejects == 1
    utter(loud(9))                                       # 거절 2 — 예산 소진
    assert [t for t, _ in link.sent].count("voice_sentence_rejected") == 3
    utter(loud(9))                                       # 예산이 없으니 받는다 — 1번 문장이 잘못 녹음돼도 갇히지 않게
    assert [t for t, _ in link.sent][-3:] == ["PUT", "voice_progress", "voice_captured"]
    assert link.sent[-1][1]["quality"] == "낮음"                # 받긴 하지만 판독 결과는 낮음 — FE 가 그 자리에서 "다시 녹음" 을 연다
    for n, marker in ((4, 9), (5, 6)):                         # 4번도 다른 목소리, 5번은 또 다른 방향 — 튀는 문장이 둘 이상
        vs.on_collect("t2", n)
        utter(loud(marker))
    # 하나만 뺄 수 없어 전체 판정이 낮음 — 올리기 전에 경고하고 사용자 선택을 기다린다
    assert link.sent[-1] == ("voice_quality_warn", {
        "tempId": "t2", "reason": "문장마다 목소리가 다르게 들렸어요. 다시 녹음하시겠어요?", "noise": "낮음"})
    assert "application/octet-stream" not in [c for t, c in link.sent if t == "PUT"]   # npz 는 아직 안 올린다
    vs.on_collect("t2", 5)                                     # "이 문장 다시" — 경고 대기가 풀리고 5번만 다시 기다린다
    assert vs._n == 5 and sorted(vs._samples) == [1, 2, 3, 4] and not vs._warn_pending
    sent_n, upload_n = len(link.sent), len(uploads)
    finalize("t2")                                       # 앞 경고에 대한 늦은 "그대로 진행" — 재수집 중이니 받지 않는다
    assert len(link.sent) == sent_n and len(uploads) == upload_n and vs._n == 5
    utter(loud(6))
    # 묻는 것은 등록 한 건에 한 번뿐 — 다시 읽고도 미달이면 올려서 녹음 확인 화면으로 넘긴다.
    # 온보딩 화면에는 "그대로 진행" 버튼이 없고 "다시 녹음" 은 마지막 문장만 다시 받아서, 매번 물으면 등록을 끝낼 수 없다
    assert [t for t, _ in link.sent][-3:] == ["PUT", "PUT", "voice_captured"]
    assert link.sent[-1][1]["quality"] == "낮음" and not vs._warn_pending
    sent_n, upload_n = len(link.sent), len(uploads)
    finalize("t2")                                        # 경고 대기가 아니므로 다시 올리지 않는다
    assert len(link.sent) == sent_n and len(uploads) == upload_n
    with np.load(io.BytesIO(uploads[-1][1]), allow_pickle=False) as profile:
        assert np.allclose(profile["centroid"], np.array([1.0, 2.0]) / np.sqrt(5))  # 마지막 문장만으로 프로필을 만들지 않는다.
    vs.on_cancel("t2")
    assert not vs.active
    # 일관성은 좋아도 소음이 높으면 같은 경고를 보낸다 — 사유는 noise 로 구분한다. "중단" 은 경고 대기도 같이 끝낸다
    link.sent.clear()
    uploads.clear()
    vs.on_start("t2n", 5)
    for n in range(1, 6):
        vs.on_collect("t2n", n)
        for _ in range(3):                                     # 소음 거절 예산(2) 이 남아 있는 동안은 무른다 — 통과할 때까지 다시 읽는다
            utter(noisy)
            if not vs._n:
                break
    assert link.sent[-1] == ("voice_quality_warn", {
        "tempId": "t2n", "reason": "주변이 시끄러워 목소리가 잘 담기지 않았어요. 조용한 곳에서 다시 녹음하시겠어요?",
        "noise": "높음"})
    vs.on_cancel("t2n")
    link.sent.clear()
    finalize("t2n")
    assert not link.sent and not vs.active                     # 중단 뒤 "그대로 진행" 이 늦게 와도 올리지 않는다
    # FE "다시 녹음" — 3번까지 읽은 뒤 1번부터 다시. 옛 2·3번이 남아 있으면 1번 하나로 등록이 끝나 버린다
    link.sent.clear()
    vs.on_start("t3", 5)
    for n in (1, 2, 3):
        vs.on_collect("t3", n)
        utter(loud(7))
    vs.on_collect("t3", 1)
    assert vs._samples == {}
    utter(loud(7))                                       # 1번만 다시 읽은 상태 — 아직 끝나면 안 된다
    assert "application/octet-stream" not in [c for t, c in link.sent if t == "PUT"]   # npz 는 다 모여야 올라간다
    for n in (2, 3, 4, 5):
        vs.on_collect("t3", n)
        utter(loud(7))
    assert [c for t, c in link.sent if t == "PUT"].count("application/octet-stream") == 1
    # FE "이 문장 다시" — 같은 n 이 다시 오면 그 문장만 버리고 앞 문장은 남는다
    vs.on_start("t4", 5)
    for n in (1, 2):
        vs.on_collect("t4", n)
        utter(loud(7))
    vs.on_collect("t4", 2)
    assert sorted(vs._samples) == [1] and sorted(vs._embs) == [1]   # 버린 문장은 임베딩도 같이 버린다
    utter(loud(9))                                       # 2번을 다른 목소리로 → 거절
    assert vs._rejects == 1
    vs.on_collect("t4", 1)                                     # "다시 녹음" — 비교 기준이 사라지면 예산도 되돌린다
    assert vs._embs == {} and vs._rejects == 0
    # "이 문장 다시" 를 누르기 직전에 시작한 낭독은 버린다 — 받으면 무르려던 그 발화로 문장이 그대로 넘어간다
    link.sent.clear()
    utter(loud(7), vs._collect_t - 0.1)                  # 지시보다 먼저 시작된 발화
    assert vs._n == 1 and link.sent == []                      # 진행도 거절도 없다 — 같은 문장을 계속 기다린다
    utter(loud(7), vs._collect_t + 0.1)                  # 지시 뒤에 시작한 낭독만 센다
    assert [t for t, _ in link.sent] == ["PUT", "voice_progress", "voice_captured"]
    vs.on_collect("t4", 1)                                     # 1번을 다시 — 아래 임베딩 실패 검사의 출발점
    # 임베딩 자체가 실패(모델 로드 불가 등)하면 사유만 보내고 code 키는 없다 — FE 가 멈춘 것처럼 보이지 않게
    spk.embed = lambda a: (_ for _ in ()).throw(RuntimeError("모델 없음"))
    utter(loud(7))
    assert link.sent[-1][0] == "voice_sentence_rejected" and "code" not in link.sent[-1][1] and vs._n == 1
    del spk.embed
    # 1번이 찌그러진 경우 — 2번을 두 번 읽었는데 둘은 닮고 1번과만 다르면 1번을 의심해 기준에서 빼고 2번을 받는다.
    # 마지막엔 1번이 나머지 넷과 안 닮아 프로필 평균에서 빠진다 → 경고 없이 양호
    link.sent.clear()
    vs.on_start("t5", 5)
    vs.on_collect("t5", 1)
    utter(loud(9))                                       # 찌그러진 1번 — 비교 대상이 없어 그냥 받는다
    vs.on_collect("t5", 2)
    utter(loud(7))                                       # 본인 — 1번과 안 닮음 → 거절 1
    assert link.sent[-1][0] == "voice_sentence_rejected" and vs._rejects == 1
    utter(loud(7))                                       # 다시 읽음 — 첫 시도와 닮음, 1번과만 다름 → 1번 의심, 2번 통과
    assert [t for t, _ in link.sent][-3:] == ["PUT", "voice_progress", "voice_captured"]
    assert vs._suspect == {1} and vs._rejects == 1
    for n in (3, 4, 5):
        vs.on_collect("t5", n)
        utter(loud(7))                                   # 기준이 2번뿐이라 전부 통과
    assert [t for t, _ in link.sent].count("voice_sentence_rejected") == 1
    assert link.sent[-1][0] == "voice_captured" and link.sent[-1][1]["quality"] == "양호"   # 1번 제외, 4문장 프로필
    # 진짜 2번 문제 — 두 시도가 서로도 안 닮으면 앞 문장을 의심하지 않고 그냥 거절 2/2
    link.sent.clear()
    vs.on_start("t6", 5)
    vs.on_collect("t6", 1)
    utter(loud(7))
    vs.on_collect("t6", 2)
    utter(loud(9))                                       # 1번과 다름 → 거절 1
    utter(loud(6))                                       # 1번과도, 첫 시도와도 다름 → 거절 2
    assert [t for t, _ in link.sent].count("voice_sentence_rejected") == 2 and vs._suspect == set() and vs._n == 2
    vs.on_cancel("t5")  # 이전 등록의 취소가 늦게 와도 현재 수집 상태를 유지한다.
    assert vs.active and vs.tempId == "t6" and vs._n == 2
    assert sorted(vs._samples) == [1] and sorted(vs._embs) == [1] and vs._rejects == 2

    # 업로드 실패 — 서버가 받지 못하면 판독 결과·완료를 보내지 않고, 사용자가 다시 시도할 수 있게 남겨 둔다
    fail = {"sample": False, "npz": False}
    def put_maybe_fail(url, body, ctype):
        if fail["npz" if url.endswith("/npz") else "sample"]:
            raise OSError("연결 거부")
        put(url, body, ctype)
    vs._put = put_maybe_fail
    link.sent.clear()
    uploads.clear()
    vs.on_start("t7", 5)
    vs.on_collect("t7", 1)
    utter(loud(7))
    assert [t for t, _ in link.sent][-3:] == ["PUT", "voice_progress", "voice_captured"]
    fail["sample"] = True
    vs.on_collect("t7", 2)
    utter(loud(7))
    assert link.sent[-1][0] == "voice_sentence_rejected" and "code" not in link.sent[-1][1]
    assert [t for t, _ in link.sent][-2] != "voice_progress"    # 저장 못 한 문장은 통과로 세지 않는다
    assert vs._n == 2 and sorted(vs._samples) == [1]            # 앞 문장은 남고 이 문장만 다시 기다린다
    fail["sample"] = False
    utter(loud(7))                                        # 다시 읽으면 그대로 이어진다
    assert [t for t, _ in link.sent][-3:] == ["PUT", "voice_progress", "voice_captured"] and vs._n == 0
    for n in (3, 4, 5):
        vs.on_collect("t7", n)
        fail["npz"] = n == 5
        utter(loud(7))
    # 마지막 문장 — npz 를 못 올렸으니 완료가 아니다. 음질 경고가 아니라 문장 재낭독으로 되돌린다
    assert link.sent[-1][0] == "voice_sentence_rejected" and "code" not in link.sent[-1][1]
    assert link.sent[-1][1]["n"] == 5 and "저장하지 못했" in link.sent[-1][1]["reason"]
    assert "voice_quality_warn" not in [t for t, _ in link.sent] and not vs._warn_pending
    assert vs._n == 5 and [t for t, _ in link.sent].count("voice_captured") == 4
    fail["npz"] = False
    utter(loud(7))                                        # 마지막 문장을 다시 읽으면 같은 업로드를 다시 시도한다
    assert [t for t, _ in link.sent][-3:] == ["PUT", "PUT", "voice_captured"]
    assert [c for t, c in link.sent if t == "PUT"][-1] == "application/octet-stream"
    assert link.sent[-1][1]["tempId"] == "t7" and vs._n == 0
    # 올리는 동안 도착한 "중단"·"다시 녹음" 은 업로드 결과보다 먼저 처리된다 — 지나간 수집의 판독 결과는 버린다.
    # 업로드는 워커가 하고 결과는 apply_uploads() 가 꺼내므로, 그 사이에 들어온 지시가 항상 앞선다
    for interrupt in ("cancel", "retry"):
        link.sent.clear()
        vs.on_start("t8", 5)
        vs.on_collect("t8", 1)
        vs.on_utter(loud(7))                                    # 업로드 워커 시작 — 결과는 아직 안 나간다
        if interrupt == "cancel":
            vs.on_cancel("t8")
        else:
            vs.on_collect("t8", 1)                              # 같은 tempId 로 다시 읽으라는 지시
        settle()
        # 업로드 자체는 이미 떠난 뒤라 PUT 은 남지만, 진행·판독·완료 이벤트는 보내지 않는다
        assert [t for t, _ in link.sent if t != "PUT"] == ["voice_ready"]

    # 올릴 대상은 시작할 때 고정하고, 겹친 업로드는 받은 순서대로 하나씩 올린다 —
    # 늦게 끝난 이전 PUT 이 새 등록의 녹음을 덮어쓰면 안 된다
    import threading
    started, hold = threading.Event(), threading.Event()
    def slow(url, body, ctype):
        started.set()
        assert hold.wait(3)
        put(url, body, ctype)
    vs._put = slow
    link.sent.clear()
    uploads.clear()
    vs.on_start("t9", 5)
    vs.on_collect("t9", 1)
    vs.on_utter(loud(7))                                        # 업로드 1 — PUT 중에 붙잡아 둔다
    assert started.wait(3)
    vs.on_start("t10", 5)                                       # 올리는 도중 새 등록이 시작된다
    vs.on_collect("t10", 1)
    vs.on_utter(loud(7))                                        # 업로드 2 — 앞의 것이 끝난 뒤에 올라가야 한다
    hold.set()
    settle()
    vs.apply_uploads()
    assert [url.split("/voices/")[1].split("/")[0] for url, _, _ in uploads] == ["t9", "t10"]
    assert [d["tempId"] for t, d in link.sent
            if t in ("voice_progress", "voice_captured")] == ["t10", "t10"]   # 지나간 등록의 결과는 안 보낸다
    vs._put = put

    # 부분 마무리: 1~4문장만 있어도 npz 를 만든다. 2문장이면 둘 다 쓰고, 3개 이상이면 기존 이상치 판정을 유지한다.
    for count in (1, 2, 3, 4):
        temp_id = f"partial-{count}"
        vs.on_start(temp_id, 5)
        for n in range(1, count + 1):
            vs.on_collect(temp_id, n)
            sample = loud(9 if n == 1 else 7, 1.0 + 0.2 * n)
            utter(sample)
            if vs._n:  # 2번을 한 번 더 읽으면 1번과만 다른 목소리로 판정하여 수집한다.
                utter(sample)
            assert vs._n == 0
        vs.on_collect(temp_id, count + 1)  # 다음 문장을 기다리던 중에도 현재 수집분으로 마무리한다.
        link.sent.clear()
        uploads.clear()
        finalize("old-temp")
        assert not link.sent and not uploads and vs._n == count + 1
        finalize(temp_id)                                # 경고 대기가 아니면 마무리하지 않는다
        assert not link.sent and not uploads
        vs._warn_pending = True                                # 음질 경고를 보내고 사용자가 "그대로 진행" 을 고른 상태
        finalize(temp_id)
        assert [t for t, _ in link.sent] == ["PUT", "PUT", "voice_captured"]
        assert [ctype for _, _, ctype in uploads] == ["audio/wav", "application/octet-stream"]
        assert uploads[0][0].endswith(f"/api/agent/voices/{temp_id}/sample")
        assert uploads[1][0].endswith(f"/api/agent/voices/{temp_id}/npz")
        with wave.open(io.BytesIO(uploads[0][1]), "rb") as recorded:
            assert np.array_equal(np.frombuffer(recorded.readframes(recorded.getnframes()), dtype="<i2"), sample)
        expected = ([0.0, 1.0] if count == 1 else
                    np.array([1.0, 1.0]) / np.sqrt(2) if count == 2 else [1.0, 0.0])
        with np.load(io.BytesIO(uploads[1][1]), allow_pickle=False) as profile:
            assert np.allclose(profile["centroid"], expected)
        assert link.sent[-1][1]["durationSec"] == round(len(sample) / 16000, 1)
        assert vs.active and vs._n == 0  # 등록 확정은 BE 의 voice_registered 를 기다린다.
        utter(loud(7))
        assert len(uploads) == 2
        # 같은 지시가 다시 와도 다시 올리거나 두 번 완료하지 않는다 — 경고 대기는 한 번 쓰면 끝난다.
        sent_n, upload_n = len(link.sent), len(uploads)
        vs.on_finalize(temp_id)
        assert len(link.sent) == sent_n and len(uploads) == upload_n
        vs.on_registered(1, False)
        link.sent.clear()
        uploads.clear()
        vs.on_finalize(temp_id)
        assert not link.sent and not uploads

    # 문장 0개: code 없는 사유를 보내고 등록을 유지한다. 이후 1번 낭독을 그대로 받을 수 있다.
    vs.on_start("empty", 5)
    link.sent.clear()
    vs._warn_pending = True                                    # 마무리 지시는 경고 대기에서만 받는다
    finalize("empty")
    assert link.sent == [("voice_sentence_rejected", {
        "tempId": "empty", "n": 1,
        "reason": "아직 문장을 하나도 받지 못했어요. 화면의 문장을 읽어주세요."})]
    assert not uploads and vs.active and vs._n == 1
    utter(loud(7), vs._collect_t + 0.1)
    assert sorted(vs._embs) == [1] and link.sent[-1][0] == "voice_captured"
    vs.on_cancel("empty")
    link.sent.clear()
    uploads.clear()
    finalize("empty")
    assert not link.sent and not uploads and not vs.active

    # 화면의 문장이 아니라 다른 말을 읽으면 MISMATCH 로 무른다 — 받아쓰기(1단 라우터)를 빌려 쓴다
    class FakeRouter:                                          # transcribe 만 흉내 내는 대역 — 진짜 받아쓰기는 돌리지 않는다
        def __init__(self): self.text, self.last_logprob = "", -0.3
        def warm(self): pass
        def transcribe(self, audio): return self.text, 0.1

    heard = FakeRouter()
    vs.stt = lambda: heard
    link.sent.clear()
    spk.embeds = 0
    vs.on_start("t11", 5)
    vs.on_collect("t11", 1)
    heard.text = "창문을 열자 찬 공기가 스며 나갔다"              # 읽다가 틀렸다 — 사유를 보내고 같은 문장을 다시 기다린다
    utter(loud(7))
    assert link.sent[-1][0] == "voice_sentence_rejected" and link.sent[-1][1]["code"] == "MISMATCH"
    assert spk.embeds == 0 and vs._n == 1 and vs._mismatch == 1  # 무른 문장은 임베딩도 안 뽑고 순번도 그대로다
    heard.text = SENTENCES[2].replace(" ", "")                 # 화면에 뜨는 문장은 FE 가 정한다 — 5개 중 하나면 띄어쓰기가 달라도 받는다
    utter(loud(7))
    assert link.sent[-1][0] == "voice_captured" and link.sent[-1][1]["quality"] == "양호" and spk.embeds == 1
    # 낭독으로 보기 어려운 것(주변 말소리·받아쓰기 실패)은 조용히 버린다 — 거절도 안 보내고 예산도 안 쓴다.
    # 받아쓰기 신뢰도가 낮다고 봐주지는 않는다 — 봐주면 whisper 가 못 알아들은 엉뚱한 발화까지 통과한다
    link.sent.clear()
    vs.on_collect("t11", 2)
    heard.text, heard.last_logprob = "골프.", -1.7
    utter(loud(7))
    utter(loud(7))
    assert link.sent == [] and vs._mismatch == 1 and spk.embeds == 1 and vs._n == 2   # 앞서 쓴 예산 1회 그대로
    # 읽다가 틀린 정도면 사유를 보내고 다시 기다린다. 예산(2회)이 떨어지면 받되 판독은 낮음 — 등록에 갇히지 않게
    heard.text, heard.last_logprob = "여름이 지나자 배짱이가 울었다", -0.3   # 마이크 실측에서 0.65 로 나온 갈래
    utter(loud(7))
    assert [d.get("code") for t, d in link.sent] == ["MISMATCH"] and vs._mismatch == 2
    utter(loud(7))
    assert link.sent[-1][0] == "voice_captured" and link.sent[-1][1]["quality"] == "낮음" and spk.embeds == 2
    vs.stt = lambda: (_ for _ in ()).throw(RuntimeError("faster-whisper 없음"))
    vs.on_collect("t11", 3)
    utter(loud(7))
    assert link.sent[-1][0] == "voice_captured" and spk.embeds == 3   # 받아쓰기를 못 써도 등록은 막지 않는다
    vs.stt = None

def test_wake_enroll():
    """온보딩 이름 불러보기(206) — 기준을 모두 넘긴 발화 WAKE_TOTAL(5)개 → wakeword_sample 5건 →
    개인화 템플릿 npz PUT → wakeword_done. 기준을 못 넘은 발화는 사유만 보내고 세지 않으며,
    다 모여 업로드까지 끝나야 저장소의 템플릿이 교체된다. 세부 규칙은 test_wake_template.py 가 본다."""
    from voice_bridge import WAKE_TOTAL, WakeEnroll

    class FakeLink:
        rt = {"port": 0}
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append((o["type"], o["data"]))

    class FakeStore:
        """등록이 쓰는 저장소 면만 흉내낸다 — 서버 쓰기도 저장소를 지난다(차례표로 순서를 지킨다)."""
        def __init__(self): self.committed, self.seq, self.broken, self.hold = [], 0, False, None
        def wake_word(self): return "시아야"
        def reserve_write(self):
            self.seq += 1
            return self.seq, 0
        def write_blob(self, body, seq):
            if self.hold:                    # 응답을 붙잡아 그 사이 재시작을 재현한다
                self.hold[0].set()
                assert self.hold[1].wait(3)
                self.hold = None
            puts.append(("http://x/api/agent/blobs/wakeword", len(body), "application/octet-stream"))
            return seq == self.seq
        def commit(self, template, why, generation=None):
            if self.broken:
                return None
            self.committed.append(template)
            return template.npz_bytes(), 0, self.seq

    class FakeSpeaker:
        profile_id = 3
        def _model(self): pass
        def embed(self, a):
            v = np.zeros(192, np.float32)
            v[0] = 1.0
            return v
        def centroid_of_embs(self, embs):
            c = np.asarray(embs).mean(axis=0)
            return c / (np.linalg.norm(c) + 1e-9), 1.0

    def clip(speech=0.8):
        """앞뒤가 조용하고 가운데만 말소리 — 호출어 한 마디."""
        return np.concatenate([np.zeros(6400, np.int16),
                               np.full(int(speech * 16000), 1000, np.int16),
                               np.zeros(9600, np.int16)])

    from brain import WAKE_FRAME_S, WAKE_MODEL, WAKE_PAD_S, speech_span

    scores = {"hit": 0.99}

    def predict_clip(audio):
        """실제 모델처럼 말소리가 끝나는 지점에 최고점을 찍는다 (호출어 끝)."""
        span = speech_span(audio)
        peak = max(0, int(round(((span[1] if span else 1.0) + WAKE_PAD_S) / WAKE_FRAME_S)))
        return [{WAKE_MODEL.stem: scores["hit"] if i == peak else 0.0} for i in range(peak + 1)]

    model = SimpleNamespace(predict_clip=predict_clip)
    link, puts, store = FakeLink(), [], FakeStore()
    we = WakeEnroll(link, FakeSpeaker(), store, model)
    we.on_utter(clip())                              # 시작 전 발화는 무시
    assert not we.active and link.sent == []
    we.on_start()
    we.on_utter(clip(0.1))                           # 헛기침 — 안 센다
    we.on_utter(clip(3.0))                           # 문장 — 안 센다
    scores["hit"] = 0.1
    we.on_utter(clip())                              # 고정 모델이 호출어로 안 들었다 — 안 센다
    scores["hit"] = 0.99
    assert [d["code"] for t, d in link.sent] == ["TOO_SHORT", "TOO_LONG", "MISMATCH"]
    assert all(d["n"] == 1 for _, d in link.sent)    # 순번은 그대로 1 이다
    for _ in range(WAKE_TOTAL):
        we.on_utter(clip())
    types = [t for t, _ in link.sent]
    assert types.count("wakeword_sample") == WAKE_TOTAL and types[-1] == "wakeword_done" and not we.active
    assert types.count("wakeword_rejected") == 3
    assert len(puts) == 1 and puts[0][0].endswith("/api/agent/blobs/wakeword") and puts[0][1] > 0
    assert puts[0][2] == "application/octet-stream"
    assert len(store.committed) == 1                 # 업로드까지 끝난 뒤에야 확정된다
    template = store.committed[0]
    assert template.wake_text == "시아야" and template.base_n == WAKE_TOTAL
    assert len(template.embs) == WAKE_TOTAL
    assert len(template.scores) == WAKE_TOTAL         # 시동어 점수 기록 (판정에는 쓰지 않는다)
    we.on_utter(clip())                              # 끝난 뒤 발화는 안 센다
    assert len(link.sent) == WAKE_TOTAL + 4
    link.sent.clear()
    we.on_start()                                    # 두 번째 회차 — 처음부터
    we.on_utter(clip())
    assert link.sent == [("wakeword_sample", {"n": 1, "total": WAKE_TOTAL})]
    # 로컬 저장만 실패한 경우 — 모은 5개를 그대로 두고, 다음 발화를 여섯 번째 샘플이 아니라 저장 재시도로 쓴다
    link.sent.clear()
    puts.clear()
    store.broken = True
    we.on_start()
    for _ in range(WAKE_TOTAL):
        we.on_utter(clip())
    rejected = [d for t, d in link.sent if t == "wakeword_rejected"]
    assert rejected[-1]["n"] == WAKE_TOTAL and rejected[-1]["total"] == WAKE_TOTAL  # total 을 넘는 순번은 안 보낸다
    assert not any(t == "wakeword_done" for t, _ in link.sent)
    assert len(we._samples) == WAKE_TOTAL and we.active and len(puts) == 1   # 서버에는 이미 저장됐다
    store.broken = False
    we.on_utter(clip())                              # 저장 재시도 — 샘플도 서버 쓰기도 되풀이하지 않는다
    assert len(we._samples) == WAKE_TOTAL and len(puts) == 1
    assert [t for t, _ in link.sent][-1] == "wakeword_done" and not we.active
    # 이전 회차의 PUT 응답을 기다리는 사이 등록을 다시 시작하면, 그 성공이 새 회차에 섞이지 않는다
    import threading
    link.sent.clear()
    puts.clear()
    store.committed.clear()
    we.on_start()
    for _ in range(WAKE_TOTAL - 1):
        we.on_utter(clip())
    store.hold = (threading.Event(), threading.Event())
    stale = threading.Thread(target=lambda: we.on_utter(clip()))   # 5번째 → 확정 → PUT 에 매달린다
    stale.start()
    assert store.hold[0].wait(3)
    we.on_start()                                    # 매달린 사이 재시작 (회차가 올라간다)
    store.hold[1].set()
    stale.join(5)
    assert not stale.is_alive() and not store.committed
    assert not any(t == "wakeword_done" for t, _ in link.sent)
    puts.clear()
    for _ in range(WAKE_TOTAL):                      # 새 회차의 5개
        we.on_utter(clip())
    assert len(puts) == 1                            # 새 본문이 실제로 서버에 저장된 뒤에 확정된다
    assert len(store.committed) == 1 and [t for t, _ in link.sent][-1] == "wakeword_done"


def test_wake_enroll_custom():
    """사용자 지정 호출어 등록 — "시아야" 와 같은 절차를 타고 발음 확인만 받아쓰기 모델의 단어 확률로 갈린다.
    5개가 모이면 판정 헤드를 학습해 등록본에 담고, 학습이 끝난 뒤에야 저장·확정한다. 학습 중 발화는 세지 않는다."""
    import threading
    from unittest.mock import patch

    import wake_head
    from speaker import WAKE_HEAD_DIM
    from voice_bridge import WAKE_ENROLL_WORD_FAILS, WAKE_TOTAL, WakeEnroll

    class FakeLink:
        rt = {"port": 0}
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append((o["type"], o["data"]))

    class FakeStore:
        def __init__(self): self.committed, self.word, self.seq = [], "철수야", 0
        def wake_word(self): return self.word
        def reserve_write(self):
            self.seq += 1
            return self.seq, 0
        def write_blob(self, body, seq):
            puts.append(len(body))
            return True
        def commit(self, template, why, generation=None):
            self.committed.append(template)
            return template.npz_bytes(), 0, self.seq

    class FakeSpeaker:
        def _model(self): pass
        def embed(self, a):
            v = np.zeros(192, np.float32)
            v[0] = 1.0
            return v
        def centroid_of_embs(self, embs):
            c = np.asarray(embs).mean(axis=0)
            return c / (np.linalg.norm(c) + 1e-9), 1.0

    def clip(speech=0.8):
        """앞뒤가 조용하고 가운데만 말소리 — 호출어 한 마디."""
        return np.concatenate([np.zeros(6400, np.int16),
                               np.full(int(speech * 16000), 1000, np.int16),
                               np.zeros(9600, np.int16)])

    from brain import WAKE_FRAME_S, WAKE_MODEL, WAKE_PAD_S, speech_span

    def predict_clip(audio):
        """"시아야" 회차용 고정 모델 대역 — 말소리가 끝나는 지점에 최고점을 찍는다."""
        span = speech_span(audio)
        peak = max(0, int(round(((span[1] if span else 1.0) + WAKE_PAD_S) / WAKE_FRAME_S)))
        return [{WAKE_MODEL.stem: 0.99 if i == peak else 0.0} for i in range(peak + 1)]

    head = (np.zeros(WAKE_HEAD_DIM, np.float32), np.float32(-1.5),
            np.zeros(WAKE_HEAD_DIM, np.float32), np.ones(WAKE_HEAD_DIM, np.float32))
    link, puts, store = FakeLink(), [], FakeStore()
    lp, words, trains, bank_ok, hold = {"v": -2.0}, [], [], {"v": True}, {"v": None}

    def scorer(audio, word):
        words.append(word)
        return lp["v"]

    def fake_bank(path=None):
        if not bank_ok["v"]:
            raise FileNotFoundError(path)
        return np.zeros((1000, 4), np.float16)      # train_head 대역이 보지 않는다

    def fake_train(clips, bank_X, feats=None):
        trains.append(len(clips))
        if hold["v"]:                               # 학습을 붙잡아 그 사이 재시작을 재현한다
            hold["v"][0].set()
            assert hold["v"][1].wait(5)
        return head

    with patch.object(wake_head, "load_bank", fake_bank), patch.object(wake_head, "train_head", fake_train):
        # ① 5개 통과 → 헤드를 학습해 담은 등록본으로 확정
        we = WakeEnroll(link, FakeSpeaker(), store, None, scorer)
        we.on_start()
        for _ in range(WAKE_TOTAL):
            we.on_utter(clip())
        we._trainer.join(20)
        assert [t for t, _ in link.sent].count("wakeword_sample") == WAKE_TOTAL
        assert trains == [WAKE_TOTAL] and words == ["철수야"] * WAKE_TOTAL     # 등록 대상 호출어로 채점한다
        assert ("notice", {"message": "이름을 익히는 중이에요. 잠시만 기다려 주세요."}) in link.sent, link.sent
        assert [t for t, _ in link.sent][-1] == "wakeword_done" and not we.active
        template = store.committed[0]
        assert template.has_head and template.wake_text == "철수야" and len(puts) == 1
        assert template.scores == (-2.0,) * WAKE_TOTAL                         # 기록은 단어 확률이다

        # ② 단어 확률이 하한 미만이면 MISMATCH — 순번은 그대로, 하한 위(-4.3)는 통과
        link.sent.clear()
        we.on_start()
        lp["v"] = -4.7
        we.on_utter(clip())
        assert link.sent == [("wakeword_rejected", {
            "n": 1, "total": WAKE_TOTAL, "code": "MISMATCH",
            "reason": '"철수야" 로 들리지 않았어요. 또박또박 다시 불러주세요.'})]
        link.sent.clear()
        lp["v"] = -4.3
        we.on_utter(clip())
        assert link.sent == [("wakeword_sample", {"n": 1, "total": WAKE_TOTAL})]

        # ③ 받아쓰기 모델이 없으면 code 없는 사유로 거절한다
        link.sent.clear()
        we.word_scorer = None
        we.on_utter(clip())
        assert link.sent == [("wakeword_rejected", {
            "n": 2, "total": WAKE_TOTAL, "reason": "받아쓰기 모델을 쓸 수 없어 등록할 수 없어요."})]
        we.word_scorer = scorer

        # ④ 부정 뱅크가 없으면 한 번도 부르게 하지 않고 접는다 — 5번 부른 뒤에 실패를 알리지 않는다
        link.sent.clear(); puts.clear(); trains.clear(); store.committed.clear()
        bank_ok["v"] = False
        we.on_start()
        we._preload.join(20)
        lp["v"] = -2.0
        assert not we.active and not we._samples, "뱅크가 없으면 수집을 이어 가지 않는다"
        assert link.sent == [("wakeword_rejected", {
            "n": 1, "total": WAKE_TOTAL,
            "reason": "이 PC 에 호출어 학습 자료가 없어 새 이름을 등록할 수 없어요."})], link.sent
        we.on_utter(clip())
        assert not we._samples and not trains, "접은 뒤 발화는 샘플이 아니다 — 명령으로 가야 한다"

        bank_ok["v"] = True
        we.on_start()
        for _ in range(WAKE_TOTAL):
            we.on_utter(clip())
        we._trainer.join(20)
        assert trains == [WAKE_TOTAL] and len(puts) == 1 and store.committed[0].has_head
        assert [t for t, _ in link.sent][-1] == "wakeword_done"

        # ④-2 수집 중에 설정 호출어가 바뀌면 모은 샘플을 버리고 새 이름으로 다시 받는다
        link.sent.clear(); puts.clear(); trains.clear(); store.committed.clear(); words.clear()
        we.on_start()
        for _ in range(3):
            we.on_utter(clip())
        assert len(we._samples) == 3
        store.word = "대길이"
        assert we.on_word_changed(store.word) and not we.on_word_changed(store.word)
        assert we.active and not we._samples and we.wake_text == "대길이"
        assert link.sent[-1] == ("wakeword_rejected", {
            "n": 1, "total": WAKE_TOTAL,
            "reason": '호출어가 "대길이" 로 바뀌었어요. 새 이름으로 다시 5번 불러주세요.'}), link.sent[-1]
        for _ in range(WAKE_TOTAL):
            we.on_utter(clip())
        we._trainer.join(20)
        assert words == ["철수야"] * 3 + ["대길이"] * WAKE_TOTAL       # 바뀐 뒤로는 새 이름으로 채점한다
        assert store.committed[0].wake_text == "대길이" and trains == [WAKE_TOTAL]
        store.word = "철수야"

        # ⑤ 학습 중에 재시작하면 그 결과는 새 회차에 반영하지 않는다 (학습 중 발화도 세지 않는다)
        link.sent.clear(); puts.clear(); trains.clear(); store.committed.clear()
        we.on_start()
        for _ in range(WAKE_TOTAL - 1):
            we.on_utter(clip())
        hold["v"] = (threading.Event(), threading.Event())
        we.on_utter(clip())                              # 5번째 → 학습 시작 → 매달린다
        stale, gate = we._trainer, hold["v"]
        assert gate[0].wait(5)
        we.on_utter(clip())
        assert len(we._samples) == WAKE_TOTAL            # 학습 중 발화는 샘플이 아니다
        we.on_start()                                    # 매달린 사이 재시작 (회차가 올라간다)
        hold["v"] = None
        gate[1].set()
        stale.join(5)
        assert not stale.is_alive() and not store.committed and not puts
        assert not any(t == "wakeword_done" for t, _ in link.sent)
        for _ in range(WAKE_TOTAL):                      # 새 회차는 스스로 학습해 확정한다
            we.on_utter(clip())
        we._trainer.join(20)
        assert len(store.committed) == 1 and len(puts) == 1
        assert [t for t, _ in link.sent][-1] == "wakeword_done"

        # ⑥ 단어 확률 미달이 이어지면 호출어를 바꾸라고 권한다 — 한 번 통과하면 셈이 풀린다
        link.sent.clear()
        we.on_start()
        lp["v"] = -5.0
        for _ in range(WAKE_ENROLL_WORD_FAILS):
            we.on_utter(clip())
        assert "다른 호출어를 골라 주세요" not in link.sent[0][1]["reason"]
        assert "이 호출어는 받아쓰기 모델이 잘 알아듣지 못해요. 다른 호출어를 골라 주세요." in link.sent[-1][1]["reason"]
        lp["v"] = -2.0
        we.on_utter(clip())
        lp["v"] = -5.0
        link.sent.clear()
        we.on_utter(clip())
        assert "다른 호출어를 골라 주세요" not in link.sent[-1][1]["reason"]

        # ⑦ "시아야" 는 고정 모델 그대로 — 헤드를 학습하지도, 단어 확률을 묻지도 않는다
        link.sent.clear(); puts.clear(); trains.clear(); store.committed.clear()
        n_words = len(words)
        store.word = "시아야"
        we.wake_model = SimpleNamespace(predict_clip=predict_clip)
        we.on_start()
        for _ in range(WAKE_TOTAL):
            we.on_utter(clip())
        assert not trains and len(words) == n_words       # 헤드 학습도, 단어 확률 질의도 없다
        assert [t for t, _ in link.sent][-1] == "wakeword_done" and not we.active
        assert len(store.committed) == 1 and store.committed[0].head is None


def test_notice_data():
    """안내 문구 notice(207) — kind 없으면 message 만, confirm 은 kind·timeoutSec, unknown_command 는 transcript 동봉,
    값 없는 필드는 빠진다. _say 는 오버레이(60자 넘으면 패널)와 BE notice 송신을 한 번에 한다."""
    from brain import Brain, notice_data

    assert notice_data("네, 듣고 있어요") == {"message": "네, 듣고 있어요"}
    assert notice_data("닫을까요?", "confirm", timeoutSec=12) == {"message": "닫을까요?", "kind": "confirm", "timeoutSec": 12}
    assert notice_data("명령을 이해하지 못했습니다.", "unknown_command", transcript="어쩌구") == {
        "message": "명령을 이해하지 못했습니다.", "kind": "unknown_command", "transcript": "어쩌구"}
    assert notice_data("x", None, transcript="", timeoutSec=None) == {"message": "x"}

    class Overlay:
        def __init__(self): self.calls = []
        def toast(self, m, s=None): self.calls.append(("toast", m, s))
        def panel(self, m): self.calls.append(("panel", m))

    class Link:
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append(o)

    b = Brain.__new__(Brain)                                   # __init__ 없이 — 오버레이·BE 만 가짜로 끼운다
    b.overlay, link = Overlay(), Link()
    b._be = lambda: link
    b._say("창을 닫을까요?", "confirm", 12.0, timeoutSec=12)
    assert b.overlay.calls[-1] == ("toast", "창을 닫을까요?", 12.0)
    assert link.sent[-1] == {"type": "notice", "data": {"message": "창을 닫을까요?", "kind": "confirm", "timeoutSec": 12}}
    b._say("가" * 61)
    assert b.overlay.calls[-1] == ("panel", "가" * 61) and link.sent[-1]["data"] == {"message": "가" * 61}
    b._be = lambda: None                                       # BE 미접속 — 오버레이만
    b._say("취소했습니다")
    assert b.overlay.calls[-1] == ("toast", "취소했습니다", None) and len(link.sent) == 2


def test_be_dom_text():
    """BE browser.dom_text 채택 — 성공 payload 만 dom 으로, 세션 전·미접속·빈 본문은 None(스크린샷 폴백)."""
    from brain import be_dom_text

    class FakeBE:
        def __init__(self, ok, payload): self.ok, self.payload = ok, payload
        def call(self, tool, args=None):
            assert tool == "browser.dom_text"
            return self.ok, self.payload

    page = {"via": "extension", "url": "https://x", "title": "T", "text": "본문", "truncated": False}
    assert be_dom_text(FakeBE(True, page)) == page
    assert be_dom_text(FakeBE(False, {"code": "SESSION_REQUIRED", "message": ""})) is None  # 세션 전 → 폴백
    assert be_dom_text(FakeBE(None, {"code": "NO_BE", "message": ""})) is None              # BE 미접속
    assert be_dom_text(FakeBE(True, {"via": "accessibility", "text": ""})) is None          # 빈 본문은 안 넣음
    assert be_dom_text(None) is None                                                       # 링크 없음


def test_mcp_delegation():
    """동작은 BE 몫 — 창·스크롤·캡처·탐색기가 MCP 도구로 나가는지, 못 나갈 때만 로컬로 떨어지는지.

    BE 는 hwnd 를 안 내주고 win:N 은 스냅샷 인덱스라(RefResolver) 제목으로 맞춘다. 같은 제목이
    여럿이면 엉뚱한 창을 건드리느니 None 을 돌려 로컬 폴백으로 보낸다.
    """
    from unittest.mock import Mock, patch

    from brain import Brain, virtual_screen_offset

    class FakeBE:
        def __init__(self, ctx):
            self.ctx, self.calls = ctx, []

        def call(self, tool, args=None):
            self.calls.append((tool, args))
            if tool == "context.get":
                return (True, self.ctx) if self.ctx is not None else (False, {"code": "FAILED", "message": ""})
            return True, {"message": "실행했습니다"}

    def brain_with(ctx):
        b = Brain.__new__(Brain)
        b.overlay = Mock()
        be = FakeBE(ctx)
        b._be = lambda: be
        return b, be

    two = {"foreground": {"ref": "win:1", "title": "메모장", "app": "notepad"},
           "windows": [{"ref": "win:1", "title": "메모장"}, {"ref": "win:2", "title": "크롬"}]}
    with patch("brain.window_title_of", return_value="크롬"):
        b, be = brain_with(two)
        assert b._win_ref(1234) == "win:2"                      # 제목 하나면 그 창
        assert be.calls[0][0] == "context.get"                  # 스냅샷을 새로 뜨고 나서 쓴다
    dup = {"foreground": {"ref": "win:2", "title": "크롬"},
           "windows": [{"ref": "win:1", "title": "크롬"}, {"ref": "win:2", "title": "크롬"}]}
    with patch("brain.window_title_of", return_value="크롬"), \
            patch("brain.foreground_hwnd", return_value=1234):
        assert brain_with(dup)[0]._win_ref(1234) == "win:2"     # 내가 포그라운드 → 확정
    with patch("brain.window_title_of", return_value="크롬"), \
            patch("brain.foreground_hwnd", return_value=9999):
        assert brain_with(dup)[0]._win_ref(1234) is None        # 제목만 같은 남의 창 → 조작하지 않는다
    dup_bg = {"foreground": {"ref": "win:3", "title": "메모장"},
              "windows": [{"ref": "win:1", "title": "크롬"}, {"ref": "win:2", "title": "크롬"}]}
    with patch("brain.window_title_of", return_value="크롬"):
        assert brain_with(dup_bg)[0]._win_ref(1234) is None     # 못 고르면 로컬 폴백
    with patch("brain.window_title_of", return_value="크롬"):
        assert brain_with(None)[0]._win_ref(1234) is None       # context.get 실패
        assert brain_with(two)[0]._win_ref(0) is None           # hwnd 없음

    b, be = brain_with(two)                                     # 탐색기 선택은 BE selected 로
    be.call = lambda tool, args=None: (True, {"items": [
        {"path": "C:\\a.txt", "selected": True}, {"path": "C:\\b.txt", "selected": False}]})
    assert b._explorer_selection() == ["C:\\a.txt"]
    b2, _ = brain_with(two)
    b2._be = lambda: None
    assert b2._explorer_selection() == []                        # BE 없으면 빈 목록

    import ctypes  # 캡처 좌표: 스크린샷이 가상 스크린 전체와 같을 때만 오프셋을 준다
    u = ctypes.windll.user32
    size = (u.GetSystemMetrics(78), u.GetSystemMetrics(79))
    assert virtual_screen_offset(size) == (u.GetSystemMetrics(76), u.GetSystemMetrics(77))
    assert virtual_screen_offset((size[0] - 1, size[1])) is None



def test_confirm_window_is_not_longer_than_what_the_user_sees():
    """확인 수용 시간이 FE 표시보다 길면 안 된다 (-324).

    FE 는 확인창 카운트다운을 자기 상수 10초로 고정하고 우리가 보내는 timeoutSec 을
    보지 않는다(notificationStore.js, Tauri overlay/index.html). 우리가 더 길게 받으면
    화면에서 질문이 사라진 뒤에 말한 "응" 이 먹혀 창이 닫히고 파일이 지워진다.
    되돌릴 수 없는 동작이라, 어긋날 바엔 짧은 쪽이 맞다(늦은 승인은 거절될 뿐이다).
    """
    from brain import CONFIRM_TIMEOUT_S

    FE_CONFIRM_SEC = 10   # Frontend/src/store/notificationStore.js · Integration/overlay/index.html
    assert CONFIRM_TIMEOUT_S <= FE_CONFIRM_SEC, (
        f"AI 가 {CONFIRM_TIMEOUT_S}초까지 받는데 화면은 {FE_CONFIRM_SEC}초만 보여 준다 — "
        "안 보이는 확인이 실행된다")
    # 정수로 내려가는 값이라 소수점이 잘려도 더 길어지지 않아야 한다
    assert int(CONFIRM_TIMEOUT_S) <= FE_CONFIRM_SEC


def test_app_ref_resolution():
    """앱 ref 는 BE 레지스트리에서 찾는다 — 슬러그가 기계마다 다르다.

    실측(9/17): AI 는 app:chrome 을 보냈지만 이 PC 의 BE 엔 app:google-chrome 만 있었고
    탐색기·그림판은 등록 자체가 없어 "크롬 열어줘"가 매번 APP_NOT_REGISTERED 로 떨어졌다.
    """
    from unittest.mock import Mock

    from brain import Brain

    b = Brain.__new__(Brain)
    b.overlay = Mock()
    apps = [{"ref": "app:calc", "name": "계산기"},
            {"ref": "app:google-chrome", "name": "Google Chrome"},
            {"ref": "app:notepad", "name": "메모장"}]
    b._be = lambda: Mock(call=Mock(return_value=(True, {"apps": apps})))
    b._apps = None
    assert b._app_ref("calc", "계산기") == "app:calc"              # ref 완전 일치
    assert b._app_ref("chrome", "크롬") == "app:google-chrome"      # 슬러그 조각 일치
    assert b._app_ref("paint", "그림판") is None                    # 등록 없음 → 안내하고 멈춘다
    b._apps = apps + [{"ref": "app:mspaint-x", "name": "그림판"}]
    assert b._app_ref("paint", "그림판") == "app:mspaint-x"         # 표시 이름 일치

    b2 = Brain.__new__(Brain)                                      # BE 미접속이면 빈 목록
    b2.overlay, b2._be, b2._apps = Mock(), (lambda: None), None
    assert b2._app_ref("calc", "계산기") is None


def test_save_crop_paths():
    """저장이 "원하는 부분"을 담는지 — 9/16 BE 이관 후 실사용 0회라 테스트가 유일한 방어선.

    9/3 실측(로그 17건 ↔ 파일 33개 1:1, 오버레이 14장)으로 bbox 선택 품질은 확인됐지만,
    그 뒤 이관하면서 (a) 짧은 줄글이 통째로 버려지고 (b) 작은 대상에 여백이 과하게 붙고
    (c) DOM 이 JSON 중간에서 끊기고 (d) 시선이 없는데 있다고 프롬프트가 선언하는 퇴화가 생겼다.
    """
    import json
    import threading
    import time
    from unittest.mock import Mock

    from brain import Brain, DOM_TEXT_MAX, bbox_to_box, build_prompt, dom_context_part

    # ── 여백: 화면 기준이 아니라 '상자의 15% 를 넘지 않게'. 큰 상자는 예전 그대로여야 한다.
    screen = (2880, 1800)
    big = bbox_to_box(screen, [200, 200, 800, 800])
    assert big == (518, 324, 2361, 1476), big      # 9/3 에 잘 나오던 크기 — 바뀌면 안 된다
    small = bbox_to_box(screen, [500, 500, 515, 515])
    assert small[2] - small[0] < 60, small         # 폭 43px 대상에 좌우 57px 씩 붙어 2.7배가 됐었다
    assert bbox_to_box(screen, [800, 800, 200, 200]) is None   # 뒤집힘
    assert bbox_to_box(screen, [10, 10, 990, 990]) is None     # 화면 90% 초과
    assert bbox_to_box(screen, None) is None

    # ── DOM: 직렬화 '전에' 잘라야 JSON 이 안 깨지고 truncated 가 모델에 도달한다.
    dom = {"url": "u", "title": "t", "via": "extension", "text": "가" * 20000, "truncated": False}
    part = dom_context_part(dom)
    body = json.loads(part.split(":\n", 1)[1].split("\n\n")[0])   # 깨졌으면 여기서 죽는다
    assert body["truncated"] is True and len(body["text"]) == DOM_TEXT_MAX
    assert "잘려 있다" in part                                   # 잘린 사실을 모델에 알린다
    assert "보고 있는 창이 아닐 수" in part                        # BE 는 백그라운드 브라우저도 읽어 준다
    assert "접근성" not in part
    assert "접근성" in dom_context_part({**dom, "via": "accessibility", "text": "짧음"})

    # ── 시선이 없으면 크롭 파트도 없다 — 있다고 선언하면 LLM 이 없는 근거를 전제한다.
    assert "(3) 발화 시작 순간" in build_prompt(True, None)
    assert "응시 영역 정보는 이번엔 없다" in build_prompt(True, None, has_crop=False)

    # ── 짧은 줄글: 예전엔 40자 미만이면 픽셀 경로로 갔고 bbox 가 null 이라 통째로 버려졌다.
    class Img:
        size = screen

    logs = []

    def run(result):
        b = Brain.__new__(Brain)
        b.overlay, b._pending, b._apps = Mock(), None, None
        b.act, b._be = True, (lambda: None)
        b._audio_lock, b._audio_generation = threading.Lock(), 0
        b.calls, b.said = [], []
        # BE 결과는 반환값으로 받는다(-320) — self 에 얹으면 병렬 실행 시 서로 덮어쓴다.
        saved_path = r"C:\\Users\\u\\Documents\\SIA\\저장_1 (1).txt"
        b._be_call = lambda tool, args=None: (
            b.calls.append((tool, args)) or (True, {"path": saved_path}, None))
        b._say = lambda msg, *a, **k: b.said.append(msg)
        b._session_until = lambda: 0.0
        import brain as _b
        saved = _b.log_utterance
        _b.log_utterance = lambda **f: logs.append(f)
        try:
            b._execute(result, None, t_utter=time.monotonic() - 6.0, full_img=Img(), tier=2)
        finally:
            _b.log_utterance = saved
        return b

    base = {"audio_is_speech": True, "is_command": True, "wake_heard": True,
            "action": "save_crop", "say": ""}
    b = run({**base, "save_text": "와이파이 비번 hunter2", "bbox": None})   # 20자, 박스 없음
    assert b.calls and b.calls[0][0] == "files.save", b.calls      # 버리지 않고 글로 저장한다
    assert "저장_1 (1).txt" in b.said[0], b.said                    # BE 가 실제로 쓴 경로를 말한다

    # LLM 이 say 를 채워도 경로가 가려지면 안 된다 — 저장물은 사용자가 짐작 못 하는 폴더로 간다.
    # (9/17 라이브: 바탕화면의 검증용 오버레이만 보고 "저장이 안 됐다"고 판단한 사고)
    b = run({**base, "say": "선택하신 영역을 저장했습니다.",
             "save_text": None, "bbox": [200, 200, 800, 800]})
    assert b.calls[0][0] == "screen.capture_region"
    assert b.said[0].startswith("선택하신 영역을 저장했습니다.") and "저장_1 (1).txt" in b.said[0], b.said

    b = run({**base, "save_text": "짧은 설명", "bbox": [200, 200, 800, 800]})
    assert b.calls[0][0] == "screen.capture_region", b.calls      # 박스가 있으면 이미지가 이긴다

    b = run({**base, "save_text": "가" * 50, "bbox": [200, 200, 800, 800]})
    assert b.calls[0][0] == "files.save", b.calls                 # 긴 줄글은 늘 텍스트 (기존 설계)

    b = run({**base, "save_text": None, "bbox": None})
    assert not b.calls and "찾지 못했" in b.said[0], (b.calls, b.said)   # 정말 모를 때만 포기한다

    # ── 계측: 저장 1건당 줄 하나. 이게 없으면 "원한 부분을 저장했나"를 사후에 못 잰다.
    kinds = [f["save_kind"] for f in logs if f.get("gate") == "save"]
    assert kinds == ["text", "region", "region", "text", "none"], kinds
    region = next(f for f in logs if f.get("save_kind") == "region")
    assert region["bbox"] == [200, 200, 800, 800] and region["box"] == list(big)
    assert region["screen"] == list(screen)
    assert 5.0 < region["utter_to_save_s"] < 8.0, region   # 시점 불일치 창 — 발화마다 잰다
    text = next(f for f in logs if f.get("save_kind") == "text")
    assert text["save_len"] == 15 and text["save_head"].startswith("와이파이")


def test_be_results_do_not_leak_between_threads():
    """BE 호출 결과를 self 에 얹지 않는다 — 병렬 실행의 선행 조건 (-320).

    예전엔 _be_ok 가 결과를 self._last_be_payload 에 얹고 호출측이 나중에 읽었다. 명령마다
    스레드가 도는 구조에서는 스레드 A 의 files.save 결과를 B 의 capture_region 이 덮어써서
    A 가 B 의 저장 경로를 말한다 — 9/17 에 하루 종일 잡은 경로 안내 버그와 같은 모양이다.
    """
    import threading
    import time
    from unittest.mock import Mock

    from brain import Brain

    # self 에 얹는 구조가 남아 있으면 다음 사람이 또 쓴다 — 아예 없어야 한다.
    assert not hasattr(Brain, "_last_be_payload"), "BE 결과를 self 에 얹는 통로가 다시 생겼다"
    assert not hasattr(Brain, "_be_ok"), "_be_ok(bool + self 통로)가 다시 생겼다"

    class FakeBE:            # 도구마다 다른 답을 느리게 돌려줘 호출이 겹치게 한다
        connected = True

        def call(self, tool, args):
            time.sleep(0.03)
            return True, {"path": f"/out/{tool}.bin"}

    b = Brain.__new__(Brain)
    b.link, b.overlay = FakeBE(), Mock()
    got, tools = {}, ("files.save", "screen.capture_region", "app.launch", "volume.set")

    def worker(tool):
        ok, payload, err = b._be_call(tool)
        got[tool] = (ok, payload["path"], err)

    ts = [threading.Thread(target=worker, args=(t,)) for t in tools]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    for tool in tools:        # 각 스레드가 '자기' 결과를 받아야 한다
        assert got[tool] == (True, f"/out/{tool}.bin", None), got


def test_tier1_does_not_queue_behind_llm():
    """1단 적중이 앞선 LLM 왕복 뒤에서 기다리지 않는다 (-320).

    9/18 라이브: 0.42초에 판정을 끝낸 1단 명령이 대기 23.57초를 먹었다. 워커가 하나라
    큐가 곧 지연이었다. 지금은 발화마다 스레드라 느린 발화가 뒤를 막지 않는다.
    """
    import threading
    import time
    from unittest.mock import patch

    from types import SimpleNamespace

    import numpy as np

    from brain import Brain, SpeakerAccum

    class Done(BaseException):
        pass

    brain = Brain.__new__(Brain)
    brain._audio_lock = threading.RLock()
    brain._audio_generation, brain._audio_since, brain.busy = 0, 0, 0
    brain.queue, brain._workers = [], []
    brain._client = object()
    brain._pending = brain.speaker = brain.wake = brain.link = brain.wake_template = None
    brain._accum = SpeakerAccum()
    brain.overlay = SimpleNamespace(toast=lambda *a, **k: None, panel=lambda *a, **k: None)
    brain._wake_ok = lambda *a: (True, "ok", 0.9, 0.0, 1.4)

    slow_in, hold = threading.Event(), threading.Event()
    order = []

    def router(audio, t_utter, lat=None):
        if audio[0] == 1:          # 느린 발화 — 2단 승격
            return "느린 발화"
        return {"action": "test", "fast": True}

    def ask(*a, **k):              # LLM 왕복을 재현한다. time.sleep 은 못 쓴다 —
        slow_in.set()             # run() 을 멈추려고 brain.time.sleep 을 패치하면 전역이 바뀐다
        hold.wait(3)
        return {"action": "test", "fast": False}

    def execute(result, *a):
        order.append("느림" if not result.get("fast") else "빠름")
        return None

    brain._try_router, brain._ask, brain._execute = router, ask, execute

    slow = np.ones(16000, dtype=np.int16)
    fast = np.zeros(16000, dtype=np.int16)
    with patch("brain.log_utterance"), patch("brain.EVAL_CAPTURE", False), \
            patch("brain.be_dom_text", lambda *_: None):
        brain.submit(slow, None, None)
        # run() 을 한 번 돌려 느린 발화를 스레드로 띄운다.
        with patch("brain.time.sleep", side_effect=Done):
            try:
                brain.run()
            except Done:
                pass
        assert slow_in.wait(2), "느린 발화가 시작되지 않았다"
        t0 = time.monotonic()
        brain.submit(fast, None, None)
        with patch("brain.time.sleep", side_effect=Done):
            try:
                brain.run()
            except Done:
                pass
        # 1단 발화는 LLM 왕복이 아직 안 끝났는데도 먼저 실행된다
        done = threading.Event()
        for _ in range(300):
            if order:
                break
            done.wait(0.01)
        waited = time.monotonic() - t0
        assert order and order[0] == "빠름", order
        assert waited < 1.0, f"1단 명령이 LLM 뒤에서 {waited:.2f}s 기다렸다"
        hold.set()                 # 이제 느린 발화를 풀어 준다
        assert brain._drain(5)
        assert order == ["빠름", "느림"], order
        assert brain.busy == 0


def test_answer_never_lands_on_an_unheard_question():
    """확인 대기 답변은 '그 질문보다 나중에 시작된 발화' 만 받는다 (-320 검수 blocker).

    발화마다 스레드가 도는 구조에서는 사용자가 "응, 삭제" 를 말한 **뒤에** 다른 스레드가
    LLM 왕복(12~29 s)을 끝내고 창 닫기 확인 대기를 열 수 있다. 만료 시각만 보면 그 승인이
    아직 듣지도 않은 창 질문에 붙어 창이 닫힌다 — 되돌릴 수 없는 동작이다.
    """
    import time

    from brain import Brain, Pending

    b = Brain.__new__(Brain)
    now = time.monotonic()

    # 사용자는 t=10 에 답했다. 질문이 t=8 에 떴으면 그 답이 맞다.
    b._pending = Pending("2개 파일을 삭제할까요?", "delete_file", now + 20, ["a"], (0.0, {}), now + 8, 0)
    assert b._pending_for(now + 10).kind == "delete_file"

    # 같은 답변인데 질문이 t=25 에 떴다면 — 사용자는 그 질문을 들은 적이 없다.
    b._pending = Pending("창을 닫을까요?", "window_close", now + 37, 1234, (0.0, {}), now + 25, 0)
    assert b._pending_for(now + 10) is None, "안 들은 질문에 답이 붙었다"
    assert b._pending_for(now + 30).kind == "window_close"   # 그 뒤 발화는 정상적으로 답할 수 있다

    # 만료된 것은 여전히 안 받는다
    b._pending = Pending("만료", "delete_file", now + 5, ["a"], (0.0, {}), now, 0)
    assert b._pending_for(now + 6) is None


def test_second_confirm_does_not_clobber_the_first():
    """답 안 한 확인 질문이 살아 있으면 새 확인 대기를 열지 않는다 (-320 검수 blocker).

    질문 둘이 동시에 떠 있으면 "응" 이 어느 쪽에 붙는지 사용자도 우리도 모른다.
    """
    import time
    from unittest.mock import Mock

    from brain import Brain, Pending

    b = Brain.__new__(Brain)
    b._audio_lock, b.overlay, b.link = threading.RLock(), Mock(), None
    said = []
    b._say = lambda msg, *a, **k: said.append(msg)

    b._pending = None
    b._open_confirm("파일을 삭제할까요?", " — 응/취소", "delete_file", ["a"], (0.0, {}), 0)
    first = b._pending
    assert first.kind == "delete_file" and said[-1].startswith("파일을 삭제할까요?")

    b._open_confirm("창을 닫을까요?", " — 응/취소", "window_close", 1234, (0.0, {}), 0)
    assert b._pending is first, "먼저 뜬 확인 질문이 덮였다"
    assert "먼저 물어본 것에 답해" in said[-1]

    # 먼저 것이 만료되면 새 질문은 정상적으로 열린다
    b._pending = first._replace(expire=time.monotonic() - 1)
    b._open_confirm("창을 닫을까요?", " — 응/취소", "window_close", 1234, (0.0, {}), 0)
    assert b._pending.kind == "window_close"


def test_stale_worker_only_clears_its_own_confirmation():
    """폐기된 스레드의 뒷정리가 옆 스레드가 방금 연 확인 대기를 지우지 않는다 (-320 검수).

    지우면 사용자가 제때 답해도 "확인 대기 중인 작업이 없습니다" 가 뜬다.
    """
    import time

    from brain import Brain, Pending

    b = Brain.__new__(Brain)
    b._audio_lock = threading.RLock()
    b._audio_generation, b.busy = 1, 1
    stale_gen, now = 0, time.monotonic()

    # 살아 있는 세대(1)의 워커가 연 확인 대기를, 폐기된 세대(0)의 워커가 거두면 안 된다.
    b._pending = Pending("삭제할까요?", "delete_file", now + 12, ["a"], (0.0, {}), now, 1)
    b._retire(stale_gen)
    assert b._pending is not None, "옆 스레드의 확인 대기가 지워졌다"

    # 자기가 만든 것(세대 0)은 거둔다 — 새 화자에게 넘기지 않는다.
    b.busy = 1
    b._pending = Pending("삭제할까요?", "delete_file", now + 12, ["a"], (0.0, {}), now, stale_gen)
    b._retire(stale_gen)
    assert b._pending is None and b.busy == 0


def test_wake_scoring_is_serialized_and_reset():
    """호출어 채점은 직렬이고 매번 버퍼를 비운다 (-320 검수 blocker).

    openwakeword Model 은 발화마다 독립이 아니다 — predict_clip 이 내부적으로 predict() 를
    청크마다 부르며 melspec/feature 버퍼를 이어 붙인다(reset 없음). 스레드 둘이 동시에
    돌리면 청크가 섞여 진짜 호출어 점수가 임계 아래로 내려가고, 사용자는 불러도 무반응을 본다.
    """
    import brain as B

    from unittest.mock import patch

    # 문자열 검사로 때우지 않는다 — 실제 _handle 을 여러 스레드로 돌려 채점이 겹치는지 본다.
    # (예전엔 inspect.getsource 로 "self._wake_lock" 유무만 봐서, 호출을 with 밖으로 내려도
    #  초록이었다. 검수 blocker 가 안 잠긴 채 통과했다.)
    overlap, inside, resets, lock = [], [], [], threading.Lock()

    class FakeModel:
        def reset(self):
            with lock:
                resets.append(1)

        def predict_clip(self, audio):
            with lock:
                inside.append(1)
                overlap.append(len(inside))
            done = threading.Event()
            done.wait(0.03)          # time.sleep 은 못 쓴다 — run() 정지에 패치돼 있다
            with lock:
                inside.pop()
            return [{B.WAKE_MODEL.stem: 0.0}]

    class Done(BaseException):
        pass

    b = B.Brain.__new__(B.Brain)
    b._audio_lock = threading.RLock()
    b._audio_generation, b._audio_since, b.busy = 0, 0, 0
    b.queue, b._workers = [], []
    b._client = object()
    b._pending = b.speaker = b.link = b.wake_template = None
    b._accum = B.SpeakerAccum()
    b.overlay = SimpleNamespace(toast=lambda *a, **k: None, panel=lambda *a, **k: None)
    b.wake = FakeModel()
    b._try_router = lambda *a, **k: {"action": "test"}
    b._execute = lambda *a, **k: None
    # 호출어 게이트는 통과시킨다 — 이 검사의 주제는 채점이 겹치느냐다.
    b._wake_ok = lambda *a: (True, "ok", 0.9, 0.0, 1.4)

    with patch("brain.log_utterance"), patch("brain.EVAL_CAPTURE", False):
        for _ in range(4):
            b.submit(np.zeros(16000, dtype=np.int16), None, None)
        with patch("brain.time.sleep", side_effect=Done):
            try:
                b.run()          # 큐 4건을 스레드 4개로 띄운다
            except Done:
                pass
        assert b._drain(10), "발화 처리 스레드가 끝나지 않았다"

    assert len(overlap) == 4, f"채점이 4번 돌지 않았다 ({len(overlap)})"
    assert max(overlap) == 1, f"호출어 채점이 겹쳤다 (동시 {max(overlap)}건)"
    assert len(resets) == 4, f"채점 전에 버퍼를 비우지 않았다 (reset {len(resets)}회)"


def test_mcp_roundtrip_is_not_serialized():
    """_rpc 의 락은 id 증가만 감싼다 — 왕복까지 감싸면 도구 호출이 전부 직렬이 된다.

    응답은 요청마다 새로 여는 커넥션으로 짝지어지므로 id 는 겹치지만 않으면 된다.
    왕복(urlopen timeout=15)을 락에 넣으면 -320 으로 없앤 큐 대기가 락으로 되살아난다.
    """
    import time

    from be_link import McpClient

    c = McpClient.__new__(McpClient)
    c._rpc_id, c._rpc_lock, c.session_id = 0, threading.Lock(), None
    inside, peak, lock = [], [], threading.Lock()
    ids = []

    def fake_post(body):
        with lock:
            inside.append(1)
            peak.append(len(inside))
            ids.append(body["id"])
        time.sleep(0.05)                      # 느린 BE 왕복
        with lock:
            inside.pop()
        return {"result": {}}, {}

    c._post = fake_post
    ts = [threading.Thread(target=lambda: c._rpc("tools/call", {})) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert max(peak) > 1, "MCP 왕복이 직렬로 묶였다 — 락이 _post 까지 감싸고 있다"
    assert sorted(ids) == [1, 2, 3, 4], f"JSON-RPC id 가 겹쳤다: {ids}"


def test_inflight_cap_waits_for_one_slot_not_everyone():
    """동시 실행 상한에 걸려도 **한 자리**만 기다린다 (-320 재점검).

    여기서 전원 대기(_drain)를 부르면, 가장 느린 LLM 왕복(실측 12~29 s)이 끝날 때까지
    run() 이 통째로 멈춰 -320 이 지운 큐 대기(23.57 s)가 그대로 되살아난다.
    """
    import time
    from unittest.mock import patch

    import brain as B

    slow, fast, started = threading.Event(), threading.Event(), []

    def handle(idx, *_):
        started.append(idx)
        (slow if idx == 0 else fast).wait(5)

    b = B.Brain.__new__(B.Brain)
    b._audio_lock, b._pending, b._workers = threading.RLock(), None, []
    b._handle = handle

    with patch("brain.MAX_INFLIGHT", 2):
        b._start(0, None, None, 1.0)      # 느린 발화 — 끝까지 잡아 둔다
        b._start(1, None, None, 2.0)      # 빠른 발화
        assert len(b._alive()) == 2

        # 3번째는 상한에 걸려 막힌다.
        third = threading.Thread(target=lambda: b._start(2, None, None, 3.0), daemon=True)
        third.start()
        blocked = threading.Event()
        blocked.wait(0.3)
        assert started == [0, 1], f"상한을 안 지켰다: {started}"

        fast.set()                        # 자리 하나만 비운다 (느린 쪽은 아직 돌고 있다)
        for _ in range(100):
            if len(started) == 3:
                break
            blocked.wait(0.02)
        assert started == [0, 1, 2], "슬롯이 비었는데 3번째가 안 떴다 — 전원 대기 중이다"
        assert b._workers[0].is_alive(), "느린 발화가 이미 끝났다 — 검사가 성립하지 않는다"

        slow.set()
        third.join(5)
        assert b._drain(5)


def test_session_is_be_owned():
    """세션 시간은 BE 소유다 — AI 는 자기 시계를 갖지 않는다 (-320).

    9/18 라이브에서 발화 19건 중 실행 0건이 나왔다. AI 가 SESSION_S=90 을 들고 있었는데
    BE 기본은 15초였고, 개시/연장 판정을 t_utter(사용자가 말한 시각)로 해서 LLM 왕복
    12~29초 뒤 호출 시점엔 이미 닫힌 세션에 extend 를 보냈다. BE 의 renew 는 만료된 세션을
    못 살리므로(active==null → SESSION_REQUIRED) 명령이 통째로 버려졌다.
    """
    import brain as b

    # 자기 시계가 남아 있으면 BE 설정과 어긋나 같은 사고가 반복된다.
    assert not hasattr(b, "SESSION_S"), "AI 에 세션 길이 상수가 다시 생겼다"
    assert "session_until" not in b.Brain.__init__.__code__.co_names, "로컬 세션 미러가 다시 생겼다"

    br = b.Brain.__new__(b.Brain)

    br.link = None                                   # BE 미연결 → 세션 없음
    assert br._session_until() == 0.0 and not br._session_live()

    now = __import__("time").monotonic()
    br.link = type("L", (), {"connected": True, "session_until_mono": now + 30})()
    assert br._session_until() == now + 30 and br._session_live()   # BE 값을 그대로 쓴다

    br.link.session_until_mono = now - 1             # BE 기준 이미 만료
    assert not br._session_live(), "만료 판정은 호출 시점 기준이어야 한다"


def test_media_seek():
    """영상 앞·뒤 이동은 media.seek 으로 나간다 — 인자 이름·대상 창이 회귀 지점이다.

    media.* 중 유일하게 배경 재생을 제어하지 못한다(방향키는 포커스 쥔 창이 받는다).
    그래서 발화 시점 창을 winRef 로 지목하고, 못 찾으면 인자를 빼 BE 기본 동작에 맡긴다.
    """
    from unittest.mock import Mock

    from brain import Brain

    def run(key, ref, ok=True):
        b = Brain.__new__(Brain)
        b.overlay, b.calls, b.said = Mock(), [], []
        b._win_ref = lambda hwnd: ref
        b._say = lambda msg, *a, **k: b.said.append(msg)

        def try_be(tool, args, say):
            b.calls.append((tool, args))
            return (True, None, None) if ok else (False, None, {"message": "거절"})
        b._try_be = try_be
        return b, b._media(key, "이동했습니다", hwnd=1234)

    b, done = run("forward", "win:3")
    assert done and b.calls == [("media.seek", {"dir": "forward", "winRef": "win:3"})], b.calls

    # back 을 그대로 보내면 BE 가 거절한다 — backward 로 바꿔야 한다.
    b, done = run("back", "win:3")
    assert done and b.calls[0][1]["dir"] == "backward", b.calls

    # 대상 창을 못 찾으면 인자를 뺀다(BE 기본: 지금 앞에 있는 창). 빈 winRef 를 보내지 않는다.
    b, done = run("forward", None)
    assert done and b.calls == [("media.seek", {"dir": "forward"})], b.calls

    # BE 가 못 하면 사실대로 말하고 로컬 단축키로 대신하지 않는다.
    b, done = run("forward", "win:3", ok=False)
    assert not done and b.said, (b.calls, b.said)
    assert not any(t != "media.seek" for t, _ in b.calls), b.calls

    # 표에 있는 키는 그대로 표대로 나간다 (seek 분기가 가로채지 않는다).
    b, done = run("playpause", "win:3")
    assert done and b.calls == [("media.play_pause", None)], b.calls


def test_mic_preview():
    """마이크 레벨 미리보기 — FE 파형의 유일한 공급원이다 (프로토콜 §5.5).

    이 경로가 비어 있으면 FE 는 에러도 없이 평평한 선만 그린다(9/17 실측: AI 에 mic_preview 0건,
    BE 중계·FE 소비는 이미 있었음). 그래서 배선이 끊기면 조용히 죽는 것부터 잡는다.
    """
    import json
    import threading
    from unittest.mock import Mock

    from be_link import AgentLink
    from voice_bridge import MIC_PREVIEW_HZ, MicPreview, mic_level

    # ① 레벨 정규화 — 선형으로 나누면 말소리가 0.03 이라 막대가 안 보인다. dBFS 로 편다.
    assert mic_level(0) == 0.0 and mic_level(-5) == 0.0     # 무음·음수 방어
    assert mic_level(32768) == 1.0 and mic_level(10 ** 6) == 1.0   # 포화는 자른다(버리지 않는다)
    assert 0.45 < mic_level(1000) < 0.55                    # 보통 말소리가 막대 절반쯤
    assert mic_level(350) < mic_level(1000) < mic_level(4000)

    # ② 수명 — 준비 단계가 없어 STARTING 없이 바로 READY, 끝은 STOPPED.
    link = Mock()
    mp = MicPreview(link)
    mp.tick(5000, 100.0)
    assert not link.send_event.called                       # 켜기 전엔 아무것도 안 보낸다

    mp.start()
    assert link.send_event.call_args_list[-1][0] == ("mic_preview_state", {"phase": "READY"})

    period = 1.0 / MIC_PREVIEW_HZ
    mp.tick(1000, 100.0)
    mp.tick(1000, 100.0 + period / 2)                       # 주기 안의 두 번째는 버린다
    mp.tick(1000, 100.0 + period * 1.5)
    levels = [c[0][1] for c in link.send_event.call_args_list if c[0][0] == "mic_preview_level"]
    assert [x["seq"] for x in levels] == [1, 2], levels     # 한 메시지에 진폭 하나, seq 는 1부터
    assert all(0.0 <= x["level"] <= 1.0 for x in levels)

    mp.stop()
    assert link.send_event.call_args_list[-1][0] == ("mic_preview_state", {"phase": "STOPPED"})
    n = link.send_event.call_count
    mp.stop()                                               # 두 번 꺼도 STOPPED 는 한 번만
    mp.tick(9000, 200.0)                                    # 꺼진 뒤 레벨은 안 보낸다
    assert link.send_event.call_count == n

    # ③ 이 두 이벤트가 메인 루프까지 오는가 — 중계 목록에서 빠지면 위 코드가 통째로 죽는다.
    ln = AgentLink.__new__(AgentLink)
    ln._events, ln._event_lock = [], threading.Lock()
    ln._session_condition, ln.be_session_id, ln.session_until_mono = threading.Condition(), None, 0.0
    ln.gesture_ready = False
    for attr in ("voice_sync", "calib", "wake", "wake_store"):
        setattr(ln, attr, None)
    ln._on_event(json.dumps({"type": "mic_preview_start", "data": {}}))
    ln._on_event(json.dumps({"type": "mic_preview_stop", "data": {}}))
    assert ln.take_events() == [("mic_preview_start", {}), ("mic_preview_stop", {})]


def test_llm_retry():
    """LLM 재시도 — 쿼터(429)는 다음 키로, 일시 장애(503·타임아웃)는 같은 키로 한 번만.
    503 을 그냥 올리면 사용자에겐 '오류' 토스트만 뜨고 명령이 조용히 사라진다."""
    from unittest.mock import patch

    import brain

    class FakeClient:
        def __init__(self, errors):
            self.errors, self.calls = list(errors), 0
            self.models = self

        def generate_content(self, **kw):
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            return "OK"

    made = []

    def fake_client(key):
        c = FakeClient(plan.pop(0) if plan else [])
        made.append(key)
        return c

    with patch("brain.llm_client", side_effect=fake_client):
        plan = [[]]                                            # 첫 호출에 성공
        c0 = brain.llm_client("k1")
        resp, c, ki, tries = brain.llm_generate(c0, ["p"], ["k1", "k2"], 0)
        assert resp == "OK" and ki == 0 and tries == 1

        plan = [[]]                                            # 429 → 키 전환 후 성공
        c0 = FakeClient([Exception("429 RESOURCE_EXHAUSTED")])
        resp, c, ki, tries = brain.llm_generate(c0, ["p"], ["k1", "k2"], 0)
        assert resp == "OK" and ki == 1 and tries == 2 and made[-1] == "k2"

        c0 = FakeClient([Exception("503 UNAVAILABLE"), None])   # 503 → 같은 키로 한 번 더
        c0.errors = [Exception("503 UNAVAILABLE")]
        resp, c, ki, tries = brain.llm_generate(c0, ["p"], ["k1"], 0)
        assert resp == "OK" and ki == 0 and tries == 2 and c0.calls == 2

        c0 = FakeClient([Exception("503 UNAVAILABLE"), Exception("503 UNAVAILABLE")])
        try:                                                   # 두 번째 503 은 올린다 (무한 재시도 금지)
            brain.llm_generate(c0, ["p"], ["k1"], 0)
            raise AssertionError("두 번째 일시 장애는 올라와야 한다")
        except Exception as e:
            assert "503" in str(e)

    assert brain.is_transient_error(Exception("503 UNAVAILABLE"))
    assert brain.is_transient_error(Exception("Read timed out"))
    assert not brain.is_transient_error(Exception("400 INVALID_ARGUMENT"))
    assert brain.is_quota_error(Exception("429")) and not brain.is_quota_error(Exception("503"))


def test_wake_model_load():
    """시동어 모델은 Gemini 키와 따로 올라온다 — 키가 없어도 brain.wake 가 채워져야
    온보딩 이름 불러보기가 실행과 같은 모델로 발음을 확인한다(assistant.py 의 wake_model 배선).
    모델 자체가 없거나 로드에 실패하면 그대로 None 이고, 그 사유는 키 없음과 따로 로그에 남는다."""
    from unittest.mock import Mock, patch

    import brain as brain_mod
    from brain import WAKE_MODEL_WORD, Brain
    from voice_bridge import WakeEnroll

    model, loads = object(), []

    def fake_loader():
        loads.append(model)
        return model

    with patch.object(brain_mod, "load_wake_model", fake_loader),             patch.object(brain_mod, "load_api_keys", return_value=[]):
        no_key = Brain(Mock())
    assert no_key.wake is model and not no_key.enabled and len(loads) == 1  # 키 없이도 모델은 올라온다

    enroll = WakeEnroll(Mock(), None, None)
    enroll.wake_model = no_key.wake                    # assistant.py 가 하는 것과 같은 전달
    assert enroll.wake_model is model and len(loads) == 1   # 등록도 같은 인스턴스 — 다시 로드하지 않는다

    with patch.object(brain_mod, "load_wake_model", fake_loader),             patch.object(brain_mod, "load_api_keys", return_value=["key"]),             patch("google.genai.Client", return_value=object()) as client:
        with_key = Brain(Mock())
    assert with_key.wake is model and with_key.enabled and client.call_count == 1  # 키가 있는 흐름은 그대로
    assert len(loads) == 2                                                          # Brain 하나당 한 번

    store = SimpleNamespace(snapshot=lambda: (WAKE_MODEL_WORD, None, 0))
    with patch.object(brain_mod, "load_wake_model", return_value=None),             patch.object(brain_mod, "load_api_keys", return_value=[]):
        broken = Brain(Mock(), wake_template=store)
    assert broken.wake is None                                                      # 로드 실패는 숨기지 않는다
    assert broken._wake_ok(None, 0, 0, True)[:2] == (False, "no_wake_model")         # 세션도 열리지 않는다


def test_wake_head():
    """사용자 지정 호출어 헤드 — 등록 녹음(합성 사인파 5개)으로 학습하면 그 녹음은 잡고 무음은 안 잡는다.
    실시간 스트림은 임계 이상에서만, 1.5 s 에 한 번만 잡고, reset 뒤에는 새로 잡는다."""
    from wake_head import (HEAD_DEBOUNCE_S, HEAD_DIM, HEAD_STREAM_THRESHOLD, HEAD_UTTER_THRESHOLD,
                           HeadStream, _features, _synthetic, score_utterance, train_head)

    # 두 임계는 따로다 — 상시 추론은 말하는 도중 최근 16프레임만 보아 같은 호출도 낮게 나온다(실측 0.114~0.933).
    # 하나로 합치면 상시 추론이 진짜 호출을 놓치거나, 발화 채점이 배경 말소리를 다 받아들인다.
    assert HEAD_STREAM_THRESHOLD < HEAD_UTTER_THRESHOLD
    assert HeadStream.__init__.__defaults__ == (HEAD_STREAM_THRESHOLD,)
    assert score_utterance.__defaults__ == (HEAD_UTTER_THRESHOLD,)

    af = _features()
    clips, bank = _synthetic(af)
    head = train_head(clips, bank, af)
    assert [v.shape for v in head] == [(HEAD_DIM,), (), (HEAD_DIM,), (HEAD_DIM,)], "헤드는 (W, b, mu, sd)"
    for clip in clips:
        top, end = score_utterance(af, head, clip)
        assert top > 0.5, f"학습한 녹음을 못 잡음: {top}"
        assert 0 < end <= len(clip) / 16000 + 1.0, f"끝 시각은 발화 기준 초여야 함: {end}"
    top, end = score_utterance(af, head, np.zeros(32000, np.int16))
    assert top < 0.1 and end is None, f"무음을 잡음: {top}"
    assert train_head(clips, bank, af)[0].tobytes() == head[0].tobytes(), "같은 녹음이면 같은 헤드여야 함"

    # 스트림 판정 규칙은 점수를 고정한 헤드로 본다 (W=0 이라 입력과 무관하게 sigmoid(b))
    zeros, ones = np.zeros(HEAD_DIM, np.float32), np.ones(HEAD_DIM, np.float32)
    block = np.zeros(480, np.int16)
    loud = HeadStream((zeros, np.float32(5.0), zeros, ones))
    hits = [loud.feed(block, i * 0.25) for i in range(14)]          # 0 ~ 3.25 s
    hits = [h for h in hits if h]
    assert [h[1] for h in hits] == [0.0, HEAD_DEBOUNCE_S, 2 * HEAD_DEBOUNCE_S], f"1.5 s 간격으로만 잡아야 함: {hits}"
    assert hits[0][0] == "wake_live" and hits[0][2] == 0.993 and loud.threshold_lo == loud.threshold
    loud.reset()
    assert loud.last_score == 0.0 and loud.feed(block, 3.5), "reset 뒤에는 직전 히트와 무관하게 새로 잡아야 함"
    quiet = HeadStream((zeros, np.float32(-5.0), zeros, ones))
    assert not any(quiet.feed(block, i * 0.25) for i in range(14)) and 0 < quiet.last_score < 0.1


def test_wake_template_head():
    """호출어 등록 파일의 헤드 칸 — 있으면 같은 값으로 돌아오고, 없으면 파일이 이전과 바이트까지 같다
    (본문 비교로 재업로드를 건너뛰는 동기화가 깨지지 않게). 헤드 칸이 깨졌거나 일부만 있으면 읽지 않는다."""
    import io

    import speaker
    import wake_head
    from speaker import EMBED_DIM, WAKE_SR, WAKE_TEMPLATE_VERSION, WakeTemplate

    # 두 파일이 같은 값을 따로 들고 있다 — 한쪽만 바뀌면 등록 때 만든 헤드를 읽을 때 거절한다
    assert wake_head.HEAD_EXTRACTOR == speaker.WAKE_HEAD_EXTRACTOR, "헤드 특징 이름이 wake_head 와 speaker 에서 달라짐"
    assert wake_head.HEAD_DIM == speaker.WAKE_HEAD_DIM, "헤드 차원이 wake_head 와 speaker 에서 달라짐"

    emb = np.zeros(EMBED_DIM, np.float32)
    emb[0] = 1.0
    embs = np.stack([emb] * 5)
    rng = np.random.default_rng(0)
    head = (rng.standard_normal(1536).astype(np.float32), np.float32(-1.5),
            rng.standard_normal(1536).astype(np.float32), rng.uniform(0.5, 2, 1536).astype(np.float32))
    with_head = WakeTemplate("철수야", (0.9,) * 5, embs, 5, head=head)
    back = WakeTemplate.read(io.BytesIO(with_head.npz_bytes()))
    assert back.has_head and back.wake_text == "철수야", "헤드 있는 파일을 헤드째 읽어야 함"
    assert all(np.array_equal(a, b) for a, b in zip(back.head, head)), "헤드 값이 저장 전과 같아야 함"

    plain = WakeTemplate("시아야", (0.99,) * 5, embs, 5)
    assert not plain.has_head and not WakeTemplate.read(io.BytesIO(plain.npz_bytes())).has_head
    with np.load(io.BytesIO(plain.npz_bytes()), allow_pickle=False) as data:
        assert data.files == ["version", "extractor", "sr", "wake_text", "scores", "embs", "base_n"], data.files
    before = io.BytesIO()
    np.savez(before, version=WAKE_TEMPLATE_VERSION, extractor=plain.extractor, sr=WAKE_SR,
             wake_text=plain.wake_text, scores=np.asarray(plain.scores, dtype=np.float32),
             embs=plain.embs, base_n=plain.base_n)   # 헤드 칸을 넣기 전의 저장 방식 그대로
    assert plain.npz_bytes() == before.getvalue(), "헤드 없는 파일은 이전과 바이트까지 같아야 함"

    with np.load(io.BytesIO(with_head.npz_bytes()), allow_pickle=False) as data:
        fields = dict(data)
    sd_zero = fields["head_sd"].copy()
    sd_zero[3] = 0.0
    nan_w = fields["head_W"].copy()
    nan_w[0] = np.nan
    cases = {"sd 에 0": fields | {"head_sd": sd_zero},
             "head_W 만 있음": {k: v for k, v in fields.items() if k == "head_W" or not k.startswith("head_")},
             "W 에 NaN": fields | {"head_W": nan_w},
             "b 가 스칼라 아님": fields | {"head_b": np.zeros(2, np.float32)},
             "mu 차원 다름": fields | {"head_mu": np.zeros(96, np.float32)},
             "다른 특징": fields | {"head_extractor": "other"}}
    for name, case in cases.items():
        buf = io.BytesIO()
        np.savez(buf, **case)
        try:
            WakeTemplate.read(io.BytesIO(buf.getvalue()))
        except ValueError:
            continue
        raise AssertionError(f"깨진 헤드를 받아들임: {name}")


def test_word_logprob():
    """받아쓰기 모델의 단어 확률 — 토큰 후보(앞 공백 있음·없음) 중 큰 값을 돌려주고, 끝의 종료 토큰은 평균에 넣지 않는다.
    빈 단어는 거절하고, 같은 단어의 토큰 후보는 한 번만 만든다. whisper 는 올리지 않고 대역을 쓴다."""
    from router import Router

    encoded = []
    tokens = {" 철수야": [1, 2], "철수야": [3], " 영희야": [4], "영희야": [5, 6]}
    probs = {(1, 2): [0.5, 0.5, 0.01], (3,): [0.1, 0.01],             # 마지막 값 = 종료 토큰
             (4,): [0.05, 0.01], (5, 6): [0.9, 0.9, 0.01]}

    class FakeTok:
        sot_sequence = (0,)
        def encode(self, text):
            encoded.append(text)
            return tokens[text]

    def align(enc, sot, batch, frames):
        assert enc.shape == (80, 3000) and frames == 100, "30 s 로 채운 특징과 실제 프레임 수를 넘겨야 함"
        return [SimpleNamespace(text_token_probs=probs[tuple(batch[0])])]

    r = Router("시아야")
    r._model = SimpleNamespace(feature_extractor=lambda audio: np.zeros((80, len(audio) // 160), np.float32),
                               encode=lambda f: f, model=SimpleNamespace(align=align))
    r._tok = FakeTok()
    audio = np.zeros(16000, np.int16)
    assert abs(r.word_logprob(audio, "철수야") - np.log(0.5)) < 1e-6, "공백 붙인 후보가 더 크면 그 값"
    assert abs(r.word_logprob(audio, "영희야") - np.log(0.9)) < 1e-6, "공백 없는 후보가 더 크면 그 값"
    assert r.word_logprob(audio, "철수야") == r.word_logprob(audio, "철수야")
    assert encoded == [" 철수야", "철수야", " 영희야", "영희야"], f"토큰 후보는 단어마다 한 번만 만들어야 함: {encoded}"
    assert r.last_logprob is None, "transcribe 의 통계를 건드리면 안 됨"
    for bad in ("", "   "):
        try:
            r.word_logprob(audio, bad)
        except ValueError:
            continue
        raise AssertionError(f"빈 단어를 받아들임: {bad!r}")


def test_head_stream_warmup():
    """상시 추론 헤드는 만들 때와 reset 뒤에 무음 2 s 를 먼저 흘린다 — openWakeWord 는 특징 버퍼를 무작위 잡음으로
    채워, 그대로 들으면 1.3 s 안에 헛히트가 난다. 창 16프레임이 모두 무음이면 무음을 더 흘려도 창이 그대로다."""
    from wake_head import HEAD_DIM, HeadStream

    zeros, ones = np.zeros(HEAD_DIM, np.float32), np.ones(HEAD_DIM, np.float32)
    hs = HeadStream((zeros, np.float32(-5.0), zeros, ones))
    silence = np.zeros(32000, np.int16)

    def settled():
        before = np.asarray(hs.af.get_features(16))
        hs.af(silence)
        return np.allclose(before, hs.af.get_features(16), atol=1e-3)

    assert settled(), "만든 직후 창이 무음이어야 함"
    noise = (np.random.default_rng(0).standard_normal(16000) * 3000).astype(np.int16)
    for i in range(0, 16000, 480):
        hs.feed(noise[i:i + 480], i / 16000)
    hs.reset()
    assert hs.last_score == 0.0 and settled(), "reset 뒤에도 창이 무음이어야 함"
    hs.af.reset()   # 무음을 흘리지 않은 openWakeWord 의 reset 만으로는 창이 무음이 아니다 — 위 검사가 헛돌지 않는다는 확인
    assert not settled(), "무작위 초기 버퍼가 그대로면 창이 달라져야 함"


def _custom_wake_run(word="철수야", head=True, lp=-2.0, speaker=True, audio=None, t_end=1.2, session=False):
    """사용자 지정 호출어 한 발화를 실제 run() 으로 돌린다. 헤드 채점·단어 확률·목소리 임베딩만 대역이다.
    → (마지막 로그 필드, wakeword_detected 수, score_utterance 대역, wake_score_of 대역, brain, 안내 문구들)"""
    import tempfile
    from pathlib import Path
    from unittest.mock import Mock, patch

    from brain import Brain
    from speaker import EMBED_DIM, WakeTemplate
    from test_usage_events import PROFILE, assistant, utter
    from voice_bridge import WakeTemplateStore

    emb = np.zeros(EMBED_DIM, np.float32)
    emb[0] = 1.0
    zeros = np.zeros(1536, np.float32)
    head = (zeros, np.float32(0.0), zeros, np.ones(1536, np.float32)) if head else None
    if audio is None:   # 단독 호출 — 말소리 0.39~1.2 s
        audio = np.concatenate([np.zeros(6400, np.int16), np.full(12800, 1000, np.int16), np.zeros(9600, np.int16)])
    with tempfile.TemporaryDirectory() as directory, assistant(profile=PROFILE if speaker else None) as (brain, link, _):
        store = WakeTemplateStore(Path(directory) / "wake.npz")
        try:
            store.commit(WakeTemplate(word, (0.9,) * 5, np.stack([emb] * 5), 5, head=head), "등록")
            store.on_settings({"wakeWord": word})
            brain.wake_template, brain.wake = store, Mock()   # 고정 모델 자리 — run() 이 reset() 을 부른다(-326)
            brain._wake_ok = Brain._wake_ok.__get__(brain)
            if speaker:
                brain.speaker.embed = lambda _: emb
            brain.word_logprob = Mock(return_value=lp)
            brain._head_features = Mock()
            link.session_until_mono = 100.0 if session else 0.0   # utter() 의 t_utter=10.0 기준
            with patch("brain.score_utterance", return_value=(0.97, t_end)) as score, \
                    patch("brain.wake_score_of", return_value=(0.99, 27, 0)) as oww, \
                    patch("brain.log_utterance") as log:
                utter(brain, audio=audio)
            wakes = [c for c in link._send.call_args_list if c.args[0]["type"] == "wakeword_detected"]
            toasts = [c.args[0] for c in brain.overlay.toast.call_args_list]
            return log.call_args.kwargs, len(wakes), score, oww, brain, toasts
        finally:
            store.close()


def test_custom_wake_gate():
    """"시아야" 가 아닌 호출어 — 헤드 → 목소리 → 받아쓰기 모델의 단어 확률을 모두 넘어야 세션을 연다.
    헤드 없는 등록본은 채점 없이 재등록을 안내하고, 받아쓰기 모델을 못 쓰면 열지 않는다. "시아야" 는 고정 모델 경로 그대로다."""
    from brain import WAKE_FRAME_S, WAKE_PAD_S, WAKE_WORD_AFTER_S

    log, wakes, score, oww, brain, toasts = _custom_wake_run()
    assert (log["gate"], log["wake_why"], wakes) == ("wake_only", "ok", 1), f"셋 다 통과하면 세션을 열어야 함: {log}"
    assert log["wake_score"] == 0.97 and log["wake_word_lp"] == -2.0 and not oww.called
    segment, word = brain.word_logprob.call_args.args
    end = round((1.2 + WAKE_PAD_S) / WAKE_FRAME_S) * WAKE_FRAME_S - WAKE_PAD_S
    assert word == "철수야" and len(segment) == int((end + WAKE_WORD_AFTER_S) * 16000), "호출어 끝 부근만 확인해야 함"

    for speaker in (True, False):   # --no-speaker 여도 단어 확률은 본다
        log, wakes, *_ = _custom_wake_run(lp=-5.0, speaker=speaker)
        assert (log["gate"], log["wake_why"], wakes) == ("wake_reject", "word_mismatch", 0), f"단어 확률 미달: {log}"
        assert log["wake_word_lp"] == -5.0

    # 세션 안에서는 호출어가 아니어도 버리지 않는다 — 짧은 명령("크롬 켜줘")이 단독 호출 후보로 잘못
    # 분류돼 단어 확률에서 떨어져도 명령 경로로 가야 한다 (화자 게이트는 그대로 지난다).
    log, wakes, *_ = _custom_wake_run(lp=-5.0, session=True)
    assert (log["gate"], log["wake_why"]) != ("wake_reject", "word_mismatch"), f"세션 안 명령을 버렸다: {log}"
    assert log["wake_why"] == "in_session" and wakes == 0, log

    log, wakes, score, _, brain, toasts = _custom_wake_run(head=False)
    assert (log["gate"], log["wake_why"], wakes) == ("wake_reject", "head_missing", 0), log
    assert not score.called and not brain.word_logprob.called, "헤드가 없으면 채점하지 않아야 함"
    assert "호출어를 다시 등록해 주세요" in toasts

    log, wakes, *_, toasts = _custom_wake_run(lp=None)
    assert (log["gate"], log["wake_why"], wakes) == ("wake_reject", "stt_unavailable", 0), log
    assert "받아쓰기 모델을 쓸 수 없어 호출어를 확인하지 못했습니다" in toasts

    log, wakes, score, oww, brain, _ = _custom_wake_run(word="시아야", head=False)
    assert (log["gate"], log["wake_why"], wakes) == ("wake_only", "ok", 1), f'"시아야" 는 고정 모델 경로: {log}'
    assert oww.called and not score.called and not brain.word_logprob.called


def test_custom_wake_prompt_and_clip():
    """현재 호출어가 LLM 프롬프트·1단 라우터에 들어가고, 헤드의 끝 시각을 프레임 번호로 바꿔 자른 호출어 구간이
    끝 시각 + WAKE_CLIP_TAIL_S 를 넘지 않는다 (뒤에 이어진 명령이 목소리 확인에 섞이지 않게)."""
    from brain import WAKE_CLIP_TAIL_S, WAKE_WORD, build_prompt

    for session, pending in ((False, None), (True, None), (True, "창을 닫을까요?")):
        default = build_prompt(session, pending)
        assert default == build_prompt(session, pending, wake_word=WAKE_WORD), "안 넘기면 지금 문구 그대로"
        custom = build_prompt(session, pending, wake_word="철수야")
        assert '"철수야"' not in default and custom == default.replace(f'"{WAKE_WORD}"', '"철수야"'), "호출어만 바뀌어야 함"

    command = np.concatenate([np.zeros(6400, np.int16), np.full(41600, 1000, np.int16), np.zeros(9600, np.int16)])  # 0.4~3.0 s 쉬지 않고 말함
    for k in (15, 18, 25, 30, 37):
        t_end = (76 * 160 + 1280 * k) / 16000 - 1.0          # score_utterance 가 내는 끝 시각
        for audio in (command, None):
            if audio is None and k != 18:
                continue                                      # 단독 호출은 말소리가 끝나는 1.2 s 에서만
            log, _, _, _, brain, _ = _custom_wake_run(audio=audio, t_end=t_end)
            assert log["seg_t1"] <= round(t_end + WAKE_CLIP_TAIL_S, 2), (k, t_end, log["seg_t1"])
    assert brain.router.word == "철수야", "1단 라우터도 현재 호출어로 맞춰야 함"


def test_brain_paused_drops_already_queued_utterance():
    """submit()은 paused 동안 새 발화를 안 쌓지만, 제스처 등록이 막 시작돼 paused가 켜지기
    *직전*에 이미 큐에 들어간 발화는 소비 스레드(run())가 따로 걸러야 한다 — 안 그러면
    등록 중에도 그 발화가 그대로 처리되어 세션이 열린다(S15P21D106-279가 노리던 것과 반대)."""
    import time as time_mod
    from unittest.mock import Mock, patch

    import brain as brain_mod
    from brain import Brain

    with patch.object(brain_mod, "load_wake_model", return_value=None),             patch.object(brain_mod, "load_api_keys", return_value=["key"]),             patch("google.genai.Client", return_value=object()):
        b = Brain(Mock())
    b.submit(b"\x00" * 100, None, None, t_utter=0.0)  # paused=False일 때 정상적으로 큐잉
    assert len(b.queue) == 1
    b.paused = True                                    # 등록이 막 시작된 상황을 흉내낸다
    b.start()
    for _ in range(40):                                # 최대 ~2초 대기 — 소비 스레드가 버릴 시간을 준다
        if not b.queue:
            break
        time_mod.sleep(0.05)
    assert not b.queue          # 큐에서 빠졌고(버려졌고)
    assert b.busy == 0          # 실제 처리 파이프라인(busy 증가)까지는 안 갔다


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 한글·em-dash 출력 크래시 방지
    except Exception:
        pass
    test_calibrator()
    test_gaze_buffer()
    test_gaze_buffer_stale()
    test_pinch_fsm()
    test_registration_execution_gate()
    test_registration_timing_contract()
    test_hold_toggle()
    test_gesture_stable()
    test_click_recal()
    test_vad_segmenter()
    test_swipe_detector()
    test_scale_by_hand_size()
    test_custom_gestures()
    test_build_prompt()
    test_one_euro()
    test_mouse_subpixel_accumulator()
    test_wake_first_frame()
    test_speech_s()
    test_speaker_input_lead()
    test_speaker_accum()
    test_voice_bridge()
    test_wake_enroll()
    test_wake_enroll_custom()
    test_wake_model_load()
    test_wake_head()
    test_wake_template_head()
    test_word_logprob()
    test_head_stream_warmup()
    test_custom_wake_gate()
    test_custom_wake_prompt_and_clip()
    test_brain_paused_drops_already_queued_utterance()
    test_notice_data()
    test_be_dom_text()
    test_mcp_delegation()
    test_llm_retry()
    test_session_is_be_owned()
    test_be_results_do_not_leak_between_threads()
    test_tier1_does_not_queue_behind_llm()
    test_inflight_cap_waits_for_one_slot_not_everyone()
    test_answer_never_lands_on_an_unheard_question()
    test_second_confirm_does_not_clobber_the_first()
    test_stale_worker_only_clears_its_own_confirmation()
    test_wake_scoring_is_serialized_and_reset()
    test_mcp_roundtrip_is_not_serialized()
    test_media_seek()
    test_mic_preview()
    test_save_crop_paths()
    test_app_ref_resolution()
    test_confirm_window_is_not_longer_than_what_the_user_sees()
    print("OK - 49/49 통과")
