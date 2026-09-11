# -*- coding: utf-8 -*-
"""시선 보정(캘리브레이션)의 AI 측 핸들러 — BE calib_* WS 이벤트로 구동.

FE가 3×3 각 칸 중앙(두더지 코)에 점을 그리고 실제 좌표를 보고하면, BE가
calib_collect_start{n,x,y}로 AI에 중계한다. AI는 그 순간 시선 특징을 모아
(특징,(x,y)) 페어로 쌓고, 9점이 끝나면 Calibrator를 학습해 npz를 REST로 올린 뒤
calib_result를 보낸다. calibrate.py의 수집·학습을 이벤트 구동으로 옮긴 것.

계약(dev/be 9f22328 API명세서·프로토콜 검토로 확정):
- 좌표는 AI가 만들지 않는다 — calib_point_ready{n,total}만 보내고, 좌표는
  calib_collect_start{n,x,y}로 받아 오차 기준점으로 쓴다.
- 계산은 AI: fit + 정합(예측·오차) + grade. BE는 받아 적고 중계만.
- points 원소는 {n, dx, dy} — dx=측정시선x-목표x, dy=측정시선y-목표y (목표점 원점 오차벡터).
- grade ∈ {excellent, good, poor} (DB CHECK 강제 — 'bad' 아님).
- npz를 PUT /api/agent/calibs/{tempId}/npz (X-Screen: WxH) 로 먼저 올린 뒤 calib_result.
- 비-첫 프로필은 자동 활성 안 됨 — calib_changed 받을 때만 활성 npz를 리로드한다.

미연결·미확정:
- gaze_cursor(실시간 커서)·samples[](원시 구름)는 계약에 없어 미발신(필요 시 BE에 추가 요청).
- 활성 npz 리로드(calib_changed)는 검증 후 파일 교체 + on_reload 콜백으로 GazeWorker 핫스왑(-245). assistant 가 콜백을 꽂는다. 시작·재접속 시엔 hello_ack 의 blobs.calib sha 비교로 같은 경로를 탄다(-161).
"""
import hashlib
import io
import os
import random
import time
import urllib.request

import numpy as np

from gaze import Calibrator

TOTAL = 9              # 3×3
SETTLE_S = 0.4         # 점이 뜬 뒤 눈이 그 점에 착지할 때까지 — 이 구간은 수집 안 한다(saccade 프레임 버림)
COLLECT_S = 0.9        # settle 뒤 실제 수집 창(초). 점당 총 체류 = SETTLE_S + COLLECT_S ≈ 1.3 s
MIN_TOTAL_SAMPLES = 30  # calibrate.py와 동일 하한
# grade 절대 px 컷 (해상도 고정 = 개발 노트북 기준, 통합 재실측[-176]으로 튜닝).
# 컷은 AI 소유 — spec 변경 없이 여기만 고치면 된다.
GRADE_EXCELLENT_PX = 160
GRADE_GOOD_PX = 250
# 위치 프리체크 임계 — 하드웨어(카메라 화각·노출)마다 달라 통합 재실측으로 튜닝(grade 컷과 동일 성격).
DIST_FAR_NORM = 0.07     # 홍채간 정규화 거리 이 미만 = 얼굴이 작음 = 너무 멂
DIST_NEAR_NORM = 0.13    # 이 초과 = 얼굴이 큼 = 너무 가까움
LIGHT_DARK = 60.0        # 프레임 밝기(회색조 평균 0~255) 이 미만 = 너무 어두움
LIGHT_BRIGHT = 200.0     # 이 초과 = 너무 밝음(과노출)


def grade_of(avg_error_px):
    if avg_error_px < GRADE_EXCELLENT_PX:
        return "excellent"
    if avg_error_px < GRADE_GOOD_PX:
        return "good"
    return "poor"


class CalibSession:
    def __init__(self, screen_wh, face_engine, link, calib_path, on_reload=None):
        self.sw, self.sh = int(screen_wh[0]), int(screen_wh[1])
        self.face = face_engine          # make_engine(...) — features(frame)→(12,) or None
        self.link = link                 # AgentLink (WS 발신·rt) 또는 스텁
        self.calib_path = str(calib_path)  # models/calib.npz
        self.active = False
        self.tempId = None
        self._n = 0                      # 현재 수집 중인 점(0=대기)
        self._until = 0.0                # 수집 창 마감 시각
        self._collect_after = 0.0        # 이 시각 이후부터 수집(점당 settle 뒤)
        self._pts = {}                   # n -> {"x","y","feats":[...]}
        self._order = []                 # 이번 세션의 점 방문 순서(1~9 랜덤 순열)
        self._done = 0                   # 지금까지 마친 점 수 — 순서와 무관하게 9면 마감
        self._precheck = None            # (face, distance, lighting) 마지막 전송 상태 — 변할 때만 재전송
        self.on_reload = on_reload       # 활성 보정 교체 시 호출: on_reload(Calibrator) — 런타임 핫스왑(-245)

    # ── BE 이벤트 진입점 (AgentLink._on_event 가 호출) ──
    def _begin(self, tempId):
        """점 방문 순서를 1~9 랜덤 순열로 새로 뽑고 첫 점을 요청한다.
        순차(1→9)면 눈이 다음 칸을 미리 알아 saccade 로 앞서가 fixation 이 흐려진다 —
        두더지 잡기처럼 예측 불가한 칸에서 튀어나오게 해 실제 응시를 강제한다.
        좌표는 여전히 FE 가 그 n 을 어디 그렸는지 calib_collect_start{n,x,y} 로 보고한다."""
        self.tempId = tempId
        self.active = True
        self._pts = {}
        self._n = 0
        self._order = random.sample(range(1, TOTAL + 1), TOTAL)
        self._done = 0
        # 새 보정마다 precheck 를 재전송해야 한다 — None 으로 리셋 안 하면 이전 보정의 마지막 상태와
        # 같아 "변화 없음"으로 calib_precheck 가 안 나가고, FE 위치확인이 "확인 중"에서 멈춘다.
        self._precheck = None
        self._request_point(self._order[0])

    def on_start(self, tempId):
        self._begin(tempId)

    def on_restart(self, tempId):
        self._begin(tempId or self.tempId)

    def on_collect_start(self, n, x, y):
        """FE가 점 n을 (x,y)에 그렸다 → 그 순간부터 수집 창 open."""
        if not self.active or n is None or x is None or y is None:
            return
        self._n = int(n)
        self._pts[self._n] = {"x": int(x), "y": int(y), "feats": []}
        now = time.monotonic()
        self._collect_after = now + SETTLE_S   # 눈이 새 점에 착지할 시간 — 그 전 프레임은 안 담는다
        self._until = self._collect_after + COLLECT_S

    def on_registered(self, prof_id, is_active):
        # 프로필 확정. 활성 여부는 BE가 결정 — 활성 리로드는 calib_changed에서만 한다.
        self.active = False
        print(f"[calib] 프로필 확정 id={prof_id} active={is_active}")

    def on_changed(self, data):
        """활성 보정이 바뀜 → 활성 npz를 내려받아 검증한 뒤 파일 교체 + 런타임 핫스왑(on_reload).

        검증(해상도·특징 차원)은 assistant 부팅 때와 같은 기준 — 통과 못 하면 파일도 안 덮고
        기존 보정을 그대로 쓴다(호환 안 되는 프로필이 멀쩡한 calib.npz 를 망치지 않게)."""
        try:
            raw = self._fetch_active()
            calib, why = self._load_validated(raw)
            if calib is None:
                print(f"[calib] 활성 보정 id={data.get('id')} 무시 — {why}")
                return
            with open(self.calib_path, "wb") as f:
                f.write(raw)
            if self.on_reload:
                self.on_reload(calib)  # GazeWorker.calib 교체 — 재시작 없이 다음 프레임부터 새 보정(-245)
            print(f"[calib] 활성 보정 리로드 id={data.get('id')} → {self.calib_path}"
                  + (" (런타임 핫스왑)" if self.on_reload else ""))
        except Exception as e:
            print(f"[calib] 활성 npz 리로드 실패: {e}")

    def _fetch_active(self):
        url = f"http://127.0.0.1:{self.link.rt['port']}/api/agent/calibs/active/npz"
        req = urllib.request.Request(url)
        req.add_header("X-Screen", f"{self.sw}x{self.sh}")  # BE 가 학습 해상도와 대조해 불일치면 409 — 내려받기 전 1차 차단
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()

    def on_blob_ref(self, ref):
        """hello_ack·recognition_start·settings_changed 의 blobs.calib {id, sha256, screenW, screenH}|None.

        시작·재접속 시 BE 활성 보정과 로컬 calib.npz 를 sha256 으로 맞춘다(-161). 다르면 on_changed 와
        같은 경로(내려받기→검증→파일 교체→핫스왑). BE 에 활성 보정이 없으면 로컬을 캐시로 유지한다
        (-161 DoD "실패 시 로컬 캐시 부팅") — 지우지 않는다. assistant 는 ClickRecal 을 안 써 로컬
        calib.npz 는 _finalize/on_changed 로만 바뀌므로 sha 비교가 안전하다."""
        if not isinstance(ref, dict) or not ref.get("sha256"):
            if os.path.exists(self.calib_path):
                print("[calib] BE 활성 보정 없음 — 로컬 calib.npz 유지(캐시)")
            return
        sw, sh = ref.get("screenW"), ref.get("screenH")
        if sw is not None and sh is not None and (int(sw), int(sh)) != (self.sw, self.sh):
            print(f"[calib] BE 활성 보정 id={ref.get('id')} 무시 — 해상도 불일치 {(int(sw), int(sh))} ≠ {(self.sw, self.sh)}")
            return
        want = str(ref["sha256"]).lower()
        have = None
        if os.path.exists(self.calib_path):
            with open(self.calib_path, "rb") as f:
                have = hashlib.sha256(f.read()).hexdigest()
        if have == want:
            return  # 이미 같은 보정 — 부팅 때 로드한 그대로
        self.on_changed({"id": ref.get("id")})

    def _load_validated(self, raw):
        """npz 바이트 → Calibrator. 화면 해상도·특징 차원이 지금 엔진과 다르면 (None, 사유)."""
        c = Calibrator.load(io.BytesIO(raw))
        if tuple(int(v) for v in c.screen) != (self.sw, self.sh):
            return None, f"해상도 불일치 {tuple(int(v) for v in c.screen)} ≠ {(self.sw, self.sh)}"
        d = self.face.dim
        if c.W.shape[0] != 1 + d + d * (d + 1) // 2:
            return None, "특징 차원 불일치(딥 모델 on/off 가 보정 때와 다름)"
        return c, ""

    def on_cancel(self, tempId):
        self.active = False
        self._n = 0
        print("[calib] 취소 — 이전 보정 유지")

    # ── 메인 루프가 프레임마다 호출 ──
    def feed_frame(self, frame_bgr):
        if not self.active:
            return
        f = self.face.features(frame_bgr)  # (12,) or None
        self._maybe_precheck(frame_bgr, f is not None)
        if self._n == 0:                   # 점 사이 대기(collect_start 기다림)
            return
        now = time.monotonic()
        if now > self._until:              # 창 끝 → 이 점 마감
            self._close_point()
            return
        if f is not None and now >= self._collect_after:  # settle 지난 뒤(착지 후)만 담는다
            self._pts[self._n]["feats"].append(f)

    # ── 내부 ──
    def _request_point(self, n):
        self._n = 0
        self.link._send({"type": "calib_point_ready", "data": {"n": n, "total": TOTAL}})

    def _close_point(self):
        n = self._n
        self._n = 0
        self.link._send({"type": "calib_point_done", "data": {"n": n}})
        self._done += 1
        if self._done < TOTAL:
            self._request_point(self._order[self._done])
        else:
            self._finalize()

    def _maybe_precheck(self, frame_bgr, face_ok):
        distance = self._distance_status() if face_ok else "-"  # 얼굴 없으면 거리 산출 불가
        lighting = self._lighting_status(frame_bgr)
        state = (face_ok, distance, lighting)
        if state == self._precheck:
            return
        self._precheck = state
        self.link._send({"type": "calib_precheck", "data": {
            "face": bool(face_ok), "distance": distance, "lighting": lighting}})

    def _distance_status(self):
        """홍채간 정규화 거리로 카메라 거리 판정. 얼굴 클수록(가까울수록) 값이 크다."""
        ipd = getattr(self.face, "last_ipd_norm", None)
        if not ipd:
            return "-"
        if ipd < DIST_FAR_NORM:
            return "너무 멀어요"
        if ipd > DIST_NEAR_NORM:
            return "너무 가까워요"
        return "ok"

    def _lighting_status(self, frame_bgr):
        """프레임 회색조 평균 밝기로 조명 판정."""
        if getattr(frame_bgr, "ndim", 0) < 3:  # 셀프테스트의 특징벡터 등 비-이미지 방어
            return "-"
        import cv2
        v = float(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).mean())
        if v < LIGHT_DARK:
            return "너무 어두워요"
        if v > LIGHT_BRIGHT:
            return "너무 밝아요"
        return "ok"

    def _finalize(self):
        self.active = False
        feats, targets = [], []
        for n in sorted(self._pts):
            p = self._pts[n]
            for fv in p["feats"]:
                feats.append(fv)
                targets.append((p["x"], p["y"]))
        if len(feats) < MIN_TOTAL_SAMPLES:
            self.link._send({"type": "calib_result", "data": {
                "tempId": self.tempId, "avgErrorPx": None, "maxErrorPx": None,
                "grade": "poor", "pass": False, "points": []}})
            return
        calib = Calibrator(self.sw, self.sh)
        calib.fit_base(np.array(feats), np.array(targets))
        points, errs = [], []
        for n in sorted(self._pts):
            p = self._pts[n]
            if not p["feats"]:
                continue
            med = np.median(np.array(p["feats"]), axis=0)
            gx, gy = calib.predict(med)          # 학습 모델로 그 점 예측 = 측정 시선
            dx, dy = int(round(gx - p["x"])), int(round(gy - p["y"]))
            points.append({"n": n, "dx": dx, "dy": dy})
            errs.append((dx * dx + dy * dy) ** 0.5)
        avg = float(np.mean(errs)); mx = float(np.max(errs))
        grade = grade_of(avg)
        calib.save(self.calib_path)
        self._upload(self.calib_path)
        self.link._send({"type": "calib_result", "data": {
            "tempId": self.tempId,
            "avgErrorPx": round(avg, 1), "maxErrorPx": round(mx, 1),
            "grade": grade, "pass": grade != "poor", "points": points}})

    def _upload(self, path):
        """npz를 BE에 업로드 — 해상도 종속이라 X-Screen 필수."""
        try:
            with open(path, "rb") as f:
                body = f.read()
            url = f"http://127.0.0.1:{self.link.rt['port']}/api/agent/calibs/{self.tempId}/npz"
            req = urllib.request.Request(url, data=body, method="PUT")
            req.add_header("Content-Type", "application/octet-stream")
            req.add_header("X-Screen", f"{self.sw}x{self.sh}")
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print(f"[calib] npz 업로드 실패: {e}")


def _selftest():
    """계약 로직 자가검증 — grade 컷 + dx/dy + 9점 흐름(가짜 link·face)."""
    assert grade_of(120) == "excellent" and grade_of(200) == "good" and grade_of(300) == "poor"

    class FakeLink:
        rt = {"port": 0}
        def __init__(self): self.sent = []
        def _send(self, o): self.sent.append((o["type"], o.get("data", {})))

    class FakeFace:  # 목표점을 그대로 특징으로 — predict가 목표 근처를 내도록
        dim = 2
        def features(self, frame): return frame  # frame = (fx, fy) 특징 벡터

    sw, sh = 1920, 1080
    link = FakeLink()
    cs = CalibSession((sw, sh), FakeFace(), link, "_selftest_calib.npz")
    cs._upload = lambda p: None  # 업로드 스킵

    # 9점 = 3×3 중앙. 점 n 의 목표 좌표 = cell[n-1]. 특징 = 목표 좌표(정규화)라 회귀가 거의 항등.
    cell = [(int((c + 0.5) * sw / 3), int((r + 0.5) * sh / 3)) for r in range(3) for c in range(3)]
    cs.on_start("t1")
    # AI 가 요청한 순서를 그대로 따라간다 — 이제 1→9 순차가 아니라 랜덤 순열이다.
    requested = []
    for _ in range(TOTAL):
        assert link.sent[-1][0] == "calib_point_ready"
        n = link.sent[-1][1]["n"]
        requested.append(n)
        x, y = cell[n - 1]
        cs.on_collect_start(n, x, y)
        cs._collect_after = 0  # 셀프테스트는 즉시 feed 라 settle 우회(라이브는 SETTLE_S 만큼 대기)
        for _ in range(10):
            cs.feed_frame(np.array([x / sw, y / sh], dtype=float))  # 특징=정규화 목표
        cs._until = 0  # 창 강제 마감
        cs.feed_frame(np.array([x / sw, y / sh], dtype=float))
    assert sorted(requested) == list(range(1, TOTAL + 1)), f"1~9 중복없이 전부여야: {requested}"  # 랜덤 순열
    res = [s for s in link.sent if s[0] == "calib_result"]
    assert res, "calib_result 미발신"
    d = res[-1][1]
    assert d["grade"] in ("excellent", "good", "poor")
    assert len(d["points"]) == 9 and all(set(p) == {"n", "dx", "dy"} for p in d["points"])
    assert d["tempId"] == "t1" and isinstance(d["pass"], bool)
    # 활성 보정 핫스왑(-245): 내려받은 npz 를 검증해 통과하면 on_reload 로 런타임 교체, 아니면 파일도 안 덮는다.
    good = open("_selftest_calib.npz", "rb").read()  # 위 _finalize 가 저장한 것 — (sw,sh), dim 2
    swapped = []
    cs.on_reload = swapped.append
    cs._fetch_active = lambda: good
    cs.on_changed({"id": 1})
    assert len(swapped) == 1 and tuple(swapped[0].screen) == (sw, sh), "호환 npz 는 핫스왑돼야"
    o = Calibrator.load("_selftest_calib.npz"); o.screen = (1280, 720); o.save("_selftest_other.npz")
    cs._fetch_active = lambda: open("_selftest_other.npz", "rb").read()
    cs.on_changed({"id": 2})
    assert len(swapped) == 1, "해상도 다른 npz 는 스왑되면 안 됨"
    assert open("_selftest_calib.npz", "rb").read() == good, "거부된 npz 가 기존 calib.npz 를 덮으면 안 됨"
    # 시작/재접속 동기화(-161): blobs.calib sha 가 로컬과 같으면 안 받고, 다르면 받아 핫스왑, 해상도 다르면 무시, None 이면 로컬 유지.
    fetches = []
    cs._fetch_active = lambda: (fetches.append(1), good)[1]
    sha_good = hashlib.sha256(good).hexdigest()
    cs.on_blob_ref({"id": 1, "sha256": sha_good, "screenW": sw, "screenH": sh})
    assert not fetches and len(swapped) == 1, "로컬과 같은 sha 면 내려받지 않아야"
    cs.on_blob_ref({"id": 2, "sha256": "0" * 64, "screenW": sw, "screenH": sh})
    assert len(fetches) == 1 and len(swapped) == 2, "sha 다르면 내려받아 핫스왑해야"
    cs.on_blob_ref({"id": 3, "sha256": "1" * 64, "screenW": 1280, "screenH": 720})
    cs.on_blob_ref(None)
    assert len(fetches) == 1 and len(swapped) == 2, "해상도 불일치·활성 없음은 내려받기·스왑 없이 로컬 유지"
    import os
    for f in ("_selftest_calib.npz", "_selftest_other.npz"):
        if os.path.exists(f): os.remove(f)
    # 랜덤성: on_start 를 여러 번 하면 순서가 매번 같지 않다(순차 회귀 방지 확인)
    orders = set()
    for _ in range(20):
        cs.on_start("t")
        assert sorted(cs._order) == list(range(1, TOTAL + 1))  # 매번 1~9 완전 순열
        orders.add(tuple(cs._order))
    assert len(orders) > 1, "점 순서가 랜덤이 아님(항상 동일)"
    print(f"selftest ok — grade={d['grade']} avg={d['avgErrorPx']}px 방문순서={requested} 랜덤확인={len(orders)}종")


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 출력 크래시 방지
    except Exception:
        pass
    if "--selftest" in sys.argv:
        _selftest()
