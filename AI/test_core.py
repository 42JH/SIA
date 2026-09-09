# -*- coding: utf-8 -*-
"""카메라 없이 도는 핵심 로직 스모크 테스트:  python test_core.py"""
import numpy as np

from gaze import FEATURE_DIM, Calibrator, ClickRecal, GazeBuffer
from hands import GestureStable, HoldToggle, OneEuro, PinchFSM


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
    from voice import BLOCK, VadSegmenter

    seg = VadSegmenter()
    quiet = np.full(BLOCK, 120, dtype=np.int16)
    loud = np.full(BLOCK, 4000, dtype=np.int16)
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


def test_dom_bridge():
    import json as j
    import time as t
    import urllib.error
    import urllib.request

    from dombridge import DomBridge

    b = DomBridge(port=18877)
    b.start()
    for _ in range(50):  # 서버 기동 대기
        try:
            urllib.request.urlopen("http://127.0.0.1:18877/health", timeout=1)
            break
        except Exception:
            t.sleep(0.05)
    assert b.context() is None
    body = j.dumps({"title": "x - YouTube", "video": {"present": True}}).encode()
    # 토큰 없는 POST는 거부(403)
    bad = urllib.request.Request("http://127.0.0.1:18877/context", data=body, method="POST")
    try:
        urllib.request.urlopen(bad, timeout=2)
        assert False, "토큰 없이 통과됨"
    except urllib.error.HTTPError as e:
        assert e.code == 403
    except ConnectionError:
        pass  # 윈도우에서 서버가 403 응답 전에 연결을 끊는 경우가 있음 — 거부는 거부
    assert b.context() is None  # 거부됐으니 저장 안 됨
    # 올바른 토큰 → 수신
    ok = urllib.request.Request("http://127.0.0.1:18877/context", data=body,
                                headers={"X-Bridge-Token": b.token}, method="POST")
    assert j.loads(urllib.request.urlopen(ok, timeout=2).read())["ok"]
    ctx = b.context()
    assert ctx and ctx["video"]["present"]
    assert b.context(max_age=0.0) is None  # 오래된 데이터는 자동 폐기


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


def test_wake_gate():
    """시동어 게이트 판정 — 실측 로그 재현: 세션 밖 저점수(0.001, 호출어 없는 "계산기 켜줘")는 차단,
    세션 안 저점수(후속 명령 "볼륨 올려")는 통과, 섀도는 무조건 통과."""
    from brain import WAKE_THRESHOLD, wake_rejects
    assert wake_rejects(0.001, in_session=False)                   # 세션 밖 비호출 → 차단 (API 절감)
    assert not wake_rejects(0.001, in_session=True)                # 세션 안은 호출어 불필요 → 후속 명령 통과
    assert not wake_rejects(0.95, in_session=False)                # 호출 → 통과
    assert not wake_rejects(WAKE_THRESHOLD, in_session=False)      # 경계값은 통과
    assert not wake_rejects(0.001, in_session=False, shadow=True)  # 섀도: 로그만, 차단 없음


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
    짧은 발화는 같은 문장을 다시 기다리고, 샘플이 서로 안 닮으면 voice_quality_warn 뒤 voice_finalize 가 와야 올린다.
    같은 문장을 다시 수집하라는 지시가 오면 그 문장부터 뒤 샘플을 버린다."""
    from speaker import SpeakerVerifier
    from voice_bridge import SENTENCES, VoiceSession

    class FakeLink:
        rt = {"port": 0}
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append((o["type"], o["data"]))

    class FakeSpeaker(SpeakerVerifier):  # 임베딩만 가짜 — centroid·npz 직렬화는 진짜 코드
        def _model(self): return None
        def embed(self, a): return np.array([1.0, 0.0]) if a[0] == 7 else np.array([0.0, 1.0])  # 첫 샘플 값 = 화자 표식

    rng = np.random.default_rng(0)
    def loud(marker, s=2.0):
        a = (rng.standard_normal(int(s * 16000)) * 2000).astype(np.int16)
        a[0] = marker
        return a

    link = FakeLink()
    vs = VoiceSession(link, FakeSpeaker("_no_such_profile.npz"), "_selftest_speaker.npz")
    vs._put = lambda url, body, ctype: link.sent.append(("PUT", ctype))
    assert len(SENTENCES) >= 5                                 # BE 가 total(현재 5)을 정한다 — 상수는 그 이상이면 된다
    vs.on_start("t1", 5)
    assert link.sent[-1] == ("voice_ready", {"tempId": "t1"})
    vs.on_collect("t1", 1)
    vs.on_utter(loud(7, 0.5))                                  # 말소리 0.5 s — 낭독 아님, 문장 1 그대로
    assert "voice_progress" not in [t for t, _ in link.sent]
    for n in (1, 2, 3, 4, 5):
        vs.on_collect("t1", n)
        vs.on_utter(loud(7))
    types = [t for t, _ in link.sent]
    assert types.count("voice_progress") == 5 and types[-3:] == ["PUT", "PUT", "voice_captured"]
    assert [c for t, c in link.sent if t == "PUT"] == ["audio/wav", "application/octet-stream"]
    d = link.sent[-1][1]
    assert d["tempId"] == "t1" and d["quality"] == "양호" and d["noise"] in ("낮음", "높음") and d["durationSec"] > 5
    # 3번 문장만 다른 목소리 → 샘플 일관성 0.24 < 0.5 → 경고 후 멈춤, finalize 가 와야 업로드
    link.sent.clear()
    vs.on_start("t2", 5)
    for n, marker in ((1, 7), (2, 7), (3, 9), (4, 7), (5, 7)):
        vs.on_collect("t2", n)
        vs.on_utter(loud(marker))
    assert link.sent[-1][0] == "voice_quality_warn" and link.sent[-1][1]["tempId"] == "t2"
    vs.on_finalize("t2")
    assert link.sent[-1][0] == "voice_captured" and link.sent[-1][1]["quality"] == "낮음"
    vs.on_cancel("t2")
    assert not vs.active
    # FE "다시 녹음" — 3번까지 읽은 뒤 1번부터 다시. 옛 2·3번이 남아 있으면 1번 하나로 등록이 끝나 버린다
    link.sent.clear()
    vs.on_start("t3", 5)
    for n in (1, 2, 3):
        vs.on_collect("t3", n)
        vs.on_utter(loud(7))
    vs.on_collect("t3", 1)
    assert vs._samples == {}
    vs.on_utter(loud(7))                                       # 1번만 다시 읽은 상태 — 아직 끝나면 안 된다
    assert "voice_captured" not in [t for t, _ in link.sent]
    for n in (2, 3, 4, 5):
        vs.on_collect("t3", n)
        vs.on_utter(loud(7))
    assert [t for t, _ in link.sent].count("voice_captured") == 1
    # FE "이 문장 다시" — 같은 n 이 다시 오면 그 문장만 버리고 앞 문장은 남는다
    vs.on_start("t4", 5)
    for n in (1, 2):
        vs.on_collect("t4", n)
        vs.on_utter(loud(7))
    vs.on_collect("t4", 2)
    assert sorted(vs._samples) == [1]


def test_wake_enroll():
    """온보딩 이름 불러보기(206) — wakeword_enroll_start 뒤 "시아야" 길이 발화 10개 → wakeword_sample 10건 → npz PUT → wakeword_done.
    너무 짧거나(헛기침) 긴(문장) 발화는 세지 않고, 끝난 뒤 다시 시작하면 처음부터 다시 센다."""
    from voice_bridge import WAKE_TOTAL, WakeEnroll

    class FakeLink:
        rt = {"port": 0}
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append((o["type"], o["data"]))

    rng = np.random.default_rng(1)
    def loud(s):
        return (rng.standard_normal(int(s * 16000)) * 2000).astype(np.int16)

    link, puts = FakeLink(), []
    we = WakeEnroll(link)
    we._put = lambda url, body, ctype: puts.append((url, len(body), ctype))
    we.on_utter(loud(0.7))                                     # 시작 전 발화는 무시
    assert not we.active and link.sent == []
    we.on_start()
    we.on_utter(loud(0.1))                                     # 0.1 s — 헛기침, 안 센다
    we.on_utter(loud(3.0))                                     # 3 s — 문장, 안 센다
    assert link.sent == []
    for _ in range(WAKE_TOTAL):
        we.on_utter(loud(0.7))
    types = [t for t, _ in link.sent]
    assert types.count("wakeword_sample") == WAKE_TOTAL and types[-1] == "wakeword_done" and not we.active
    assert link.sent[0][1] == {"n": 1, "total": WAKE_TOTAL} and link.sent[-2][1] == {"n": WAKE_TOTAL, "total": WAKE_TOTAL}
    assert len(puts) == 1 and puts[0][0].endswith("/api/agent/blobs/wakeword") and puts[0][1] > 0
    assert puts[0][2] == "application/octet-stream"
    we.on_utter(loud(0.7))                                     # 끝난 뒤 발화는 안 센다
    assert len(link.sent) == WAKE_TOTAL + 1
    link.sent.clear()
    we.on_start()                                              # 두 번째 회차 — 처음부터
    we.on_utter(loud(0.7))
    assert link.sent == [("wakeword_sample", {"n": 1, "total": WAKE_TOTAL})]


def test_command_enroll():
    """온보딩 명령 문장 말하기(206) — command_enroll_start → command_ready, command_collect{n} 뒤 낭독 길이 발화마다
    command_progress{n}, 5번째 뒤 command_done. 짧은 발화는 같은 문장을 다시 기다리고, 지시 없이 온 발화는 세지 않는다."""
    from voice_bridge import SENTENCES, CommandEnroll

    class FakeLink:
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append((o["type"], o["data"]))

    rng = np.random.default_rng(2)
    def loud(s):
        return (rng.standard_normal(int(s * 16000)) * 2000).astype(np.int16)

    link = FakeLink()
    ce = CommandEnroll(link)
    ce.on_utter(loud(2.0))                                     # 시작 전 — 무시
    assert link.sent == []
    ce.on_start()
    assert link.sent == [("command_ready", {})]
    ce.on_utter(loud(2.0))                                     # collect 전 — 무시
    ce.on_collect(1)
    ce.on_utter(loud(0.5))                                     # 0.5 s — 낭독 아님, 문장 1 그대로
    assert len(link.sent) == 1
    for n in range(1, len(SENTENCES) + 1):
        ce.on_collect(n)
        ce.on_utter(loud(2.0))
    types = [t for t, _ in link.sent]
    assert types.count("command_progress") == len(SENTENCES) and types[-1] == "command_done" and not ce.active
    assert link.sent[1][1] == {"n": 1} and link.sent[-2][1] == {"n": len(SENTENCES)}
    ce.on_utter(loud(2.0))                                     # 끝난 뒤 — 무시
    assert len(link.sent) == len(SENTENCES) + 2


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
    test_hold_toggle()
    test_gesture_stable()
    test_click_recal()
    test_vad_segmenter()
    test_swipe_detector()
    test_custom_gestures()
    test_dom_bridge()
    test_build_prompt()
    test_one_euro()
    test_mouse_subpixel_accumulator()
    test_wake_gate()
    test_speech_s()
    test_speaker_accum()
    test_voice_bridge()
    test_wake_enroll()
    test_command_enroll()
    test_notice_data()
    test_be_dom_text()
    print("OK - 22/22 통과")
