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
- 활성 npz 리로드 시 런타임 GazeWorker 핫스왑은 상위(assistant)에서 (여기선 파일만 교체).
"""
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


def grade_of(avg_error_px):
    if avg_error_px < GRADE_EXCELLENT_PX:
        return "excellent"
    if avg_error_px < GRADE_GOOD_PX:
        return "good"
    return "poor"


class CalibSession:
    def __init__(self, screen_wh, face_engine, link, calib_path):
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
        self._face_ok = None             # precheck 상태 변화 감지용

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
        # 새 보정마다 precheck 를 재전송해야 한다 — None 으로 리셋 안 하면 이전 보정에서 얼굴이
        # 이미 True 라 "상태 변화"가 없어 calib_precheck 가 안 나가고, FE 위치확인이 "확인 중"에서 멈춘다.
        self._face_ok = None
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
        """활성 보정이 바뀜 → 활성 npz를 내려받아 파일 교체(런타임 핫스왑은 상위 담당)."""
        try:
            url = f"http://127.0.0.1:{self.link.rt['port']}/api/agent/calibs/active/npz"
            with urllib.request.urlopen(url, timeout=15) as r:
                data_bytes = r.read()
            with open(self.calib_path, "wb") as f:
                f.write(data_bytes)
            print(f"[calib] 활성 보정 리로드 id={data.get('id')} → {self.calib_path}")
        except Exception as e:
            print(f"[calib] 활성 npz 리로드 실패: {e}")

    def on_cancel(self, tempId):
        self.active = False
        self._n = 0
        print("[calib] 취소 — 이전 보정 유지")

    # ── 메인 루프가 프레임마다 호출 ──
    def feed_frame(self, frame_bgr):
        if not self.active:
            return
        f = self.face.features(frame_bgr)  # (12,) or None
        self._maybe_precheck(f is not None)
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

    def _maybe_precheck(self, face_ok):
        if face_ok == self._face_ok:
            return
        self._face_ok = face_ok
        # distance·lighting 은 스텁 — 얼굴 유무만 실계산(추후 눈 거리/휘도로 확장)
        self.link._send({"type": "calib_precheck", "data": {
            "face": bool(face_ok), "distance": "ok", "lighting": "ok"}})

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
    import os
    for f in ("_selftest_calib.npz",):
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
