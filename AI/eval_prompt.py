# -*- coding: utf-8 -*-
"""프롬프트 회귀 러너 — eval/cases/*를 재생해 현재 프롬프트의 통과율을 잰다.

프롬프트(brain.build_prompt)를 수정하면 머지 전에 이걸 돌려 기준선 대비
후퇴가 없는지 확인한다. 케이스 폴더 구조 (EVAL_CAPTURE=1로 비서를 돌리면
brain.capture_case가 자동 생성):

  eval/cases/<id>/audio.wav, full.jpg, crop.jpg, meta.json   ← 자동 수집
  eval/cases/<id>/expected.json                              ← 사람이 작성

expected.json에는 채점할 필드만 적는다. 키 뒤에 ~를 붙이면 부분 일치.
  {"is_command": false}                                   ← 오작동 차단 케이스
  {"is_command": true, "action": "save_crop"}
  {"action": "open_app", "app": "calc", "transcript~": "계산기"}

사용:
  python eval_prompt.py               전체 실행, 통과율 출력 + history.jsonl 기록
  python eval_prompt.py --only <id>   케이스 하나만 (라벨 디버깅용)
  python eval_prompt.py --tier1       같은 케이스로 1단 라우터만 오프라인 평가
                                      (LLM 미호출·비용 0 — STT 정확도·적중률·지연)
  python eval_prompt.py --draft       라벨 없는 케이스에 초안(expected.draft.json)
                                      자동 생성 — STT+라우터 추측, 사람은 검토만
  python eval_prompt.py --adopt       검토 끝난 초안을 expected.json으로 채택
  python eval_prompt.py --selftest    채점 로직 자가 점검 (API 안 씀)
"""
import json
import sys
import time

from paths import DATA_DIR

CASES = DATA_DIR / "eval" / "cases"
HISTORY = DATA_DIR / "eval" / "history.jsonl"


BOX_IOU_MIN = 0.5   # 영역 일치 하한. 물체 검출의 통상 기준이고, 9/3 기준선과 이만큼도
                    # 안 겹치면 "다른 데를 저장했다"로 본다.


def box_iou(a, b):
    """두 픽셀 사각형의 IoU. 안 겹치면 0.0."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if not inter:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua else 0.0


def match(expected, result):
    """expected의 각 항목이 result와 맞는지 — (통과 여부, 어긋난 필드 설명들)."""
    bad = []
    for k, want in expected.items():
        if k == "screen":
            continue          # box_px 를 픽셀로 풀기 위한 부속값 — 그 자체는 채점 대상이 아니다
        if k == "box_px":
            # 사용자 기준은 "저장할 대상을 특정했나" 다. 같은 기사 문단이라도 픽셀로 자르든
            # 글로 담든 둘 다 유효한 답이라(프롬프트가 그렇게 시킨다) 갈래 자체는 틀림이 아니다.
            # 실측(9/17): 9/3 에 이미지로 저장된 8건 중 2건을 지금 모델은 텍스트로 고르는데,
            # 담긴 내용은 응시한 그 문단이었다 — 박스만 보면 이걸 오답으로 센다.
            import brain

            got = brain.bbox_to_box(tuple(expected["screen"]), result.get("bbox"))
            if got is not None:
                iou = box_iou(got, want)
                if iou < BOX_IOU_MIN:
                    bad.append(f"box: IoU {iou:.2f} < {BOX_IOU_MIN} (기준 {want}, 이번 {list(got)})")
            elif (result.get("save_text") or "").strip():
                pass   # 줄글 갈래 — 대상은 특정했다
            else:
                bad.append("대상 미특정: bbox·save_text 둘 다 비었다 → 아무것도 저장되지 않는다")
            continue
        if k.endswith("~"):
            got = str(result.get(k[:-1]) or "")
            if str(want) not in got:
                bad.append(f"{k[:-1]}: {want!r} not in {got!r}")
        elif result.get(k) != want:
            bad.append(f"{k}: want {want!r}, got {result.get(k)!r}")
    return not bad, bad


def selftest():
    ok, _ = match({"is_command": True}, {"is_command": True, "action": "none"})
    assert ok
    ok, bad = match({"action": "open_app"}, {"action": "media", "is_command": True})
    assert not ok and bad[0].startswith("action")
    ok, _ = match({"transcript~": "계산기"}, {"transcript": "시아야 계산기 켜줘"})
    assert ok
    ok, _ = match({"transcript~": "계산기"}, {"transcript": "음악 틀어줘"})
    assert not ok
    ok, _ = match({"app": None}, {})  # 필드 부재는 null과 동일 취급
    assert ok
    assert box_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(box_iou((0, 0, 10, 10), (0, 0, 5, 10)) - 0.5) < 1e-9
    exp = {"box_px": [0, 0, 1000, 1000], "screen": [2000, 2000]}
    ok, bad = match(exp, {"bbox": [0, 0, 500, 500]})      # 정규화 0~1000 → 화면 절반
    assert ok, bad
    ok, bad = match(exp, {"bbox": [500, 500, 999, 999]})  # 반대쪽 사분면
    assert not ok and "IoU" in bad[0], bad
    ok, bad = match(exp, {"bbox": None})                  # 둘 다 없으면 아무것도 저장 안 된다
    assert not ok and "대상 미특정" in bad[0], bad
    ok, _ = match(exp, {"bbox": None, "save_text": "응시한 문단 전문"})   # 줄글 갈래도 정답
    assert ok
    print("selftest ok")


def run(only=None, action=None):
    from PIL import Image
    from google.genai import types

    import brain

    keys = brain.load_api_keys()
    if not keys:
        sys.exit("GEMINI_API_KEY 없음 — 환경변수 또는 gemini_api_key.txt")
    ki = 0
    client = brain.llm_client(keys[ki])  # 설정·재시도는 brain 과 같은 것을 쓴다

    # synth_(TTS) 케이스는 1단 평가 전용 — TTS 기계음은 화자 게이트·기계음
    # 기각 판정과 얽혀서 LLM 회귀에서는 제외한다 (--tier1에서만 채점).
    dirs = [d for d in sorted(CASES.iterdir())
            if d.is_dir() and not d.name.startswith("synth_")] if CASES.exists() else []
    if only:
        dirs = [d for d in dirs if d.name == only]
    if action:
        dirs = [d for d in dirs
                if (d / "expected.json").exists()
                and json.loads((d / "expected.json").read_text(encoding="utf-8")).get("action") == action]
    unlabeled = [d.name for d in dirs if not (d / "expected.json").exists()]
    dirs = [d for d in dirs if (d / "expected.json").exists()]
    if not dirs:
        sys.exit(f"채점 가능한 케이스 없음 (라벨 없는 케이스 {len(unlabeled)}개) — "
                 "EVAL_CAPTURE=1로 비서를 돌려 수집 후 expected.json을 채우세요")

    fails = []
    for d in dirs:
        expected = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        # 실서비스 _ask와 동일한 파트 구성·다이어트·설정으로 재생
        parts = [types.Part.from_bytes(data=(d / "audio.wav").read_bytes(), mime_type="audio/wav")]
        for name, mw, q in (("full.jpg", 1024, 65), ("crop.jpg", 640, 70)):
            f = d / name
            if f.exists():
                parts.append(types.Part.from_bytes(
                    data=brain.jpeg_bytes(Image.open(f), max_w=mw, quality=q),
                    mime_type="image/jpeg"))
        if meta.get("dom"):
            parts.append(brain.dom_context_part(meta["dom"]))
        parts.append(brain.build_prompt(meta.get("session", False), meta.get("pending_q"),
                                        (d / "crop.jpg").exists()))
        t0 = time.monotonic()
        result, err = {}, None
        try:
            resp, client, ki, _ = brain.llm_generate(client, parts, keys, ki)
            result = brain.llm_json(resp)
        except Exception as e:
            err = e
        ok, bad = (False, [f"호출 실패: {err}"]) if err else match(expected, result)
        if not ok:
            fails.append(d.name)
        print(f"[{'PASS' if ok else 'FAIL'}] {d.name} ({time.monotonic() - t0:.1f}s)"
              + ("" if ok else " — " + "; ".join(bad)))

    total, passed = len(dirs), len(dirs) - len(fails)
    print(f"\n통과 {passed}/{total} ({100 * passed / total:.0f}%)"
          + (f", 라벨 없음 {len(unlabeled)}개" if unlabeled else ""))
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": brain.MODEL,
                            "total": total, "passed": passed, "fails": fails},
                           ensure_ascii=False) + "\n")
    sys.exit(1 if fails else 0)


TIER1_ACTIONS = {"open_app", "media", "end_session"}  # 1단 v1 처리 범위


def run_tier1():
    """케이스의 오디오만으로 1단 라우터를 오프라인 평가 — LLM·비용 없음.

    출력: 케이스별 STT 결과와 라우팅 판정, 그리고 세 바구니 집계 —
    즉시 처리(정답/오답), 승격(정상 — 1단 범위 밖), 미스(1단 범위인데 승격).
    """
    import brain
    from router import Router

    r = Router(brain.WAKE_WORD)
    dirs = [d for d in sorted(CASES.iterdir()) if d.is_dir() and (d / "expected.json").exists()] \
        if CASES.exists() else []
    if not dirs:
        sys.exit("라벨된 케이스 없음 — EVAL_CAPTURE=1로 수집 후 expected.json을 채우세요")
    hit_ok = hit_bad = escal = miss = 0
    lat = []
    for d in dirs:
        expected = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        text, sec, logprob = r.transcribe(_load_audio(d))
        lat.append(sec)
        hit = r.route(text, True, logprob)  # brain 은 게이트(호출어·세션)를 통과한 발화만 라우터에 넘기므로(-211 이후) 라우팅 정확도도 그 기준으로 잰다
        in_scope = expected.get("is_command", True) and expected.get("action") in TIER1_ACTIONS
        if hit:
            ok, bad = match(expected, hit)
            hit_ok += ok; hit_bad += not ok
            mark = "정답" if ok else "오답 — " + "; ".join(bad)
            print(f"[즉시:{mark}] {d.name} ({sec:.2f}s lp={logprob:.2f}) {text!r}")
        else:
            miss += in_scope; escal += not in_scope
            print(f"[{'미스(1단 범위인데 승격)' if in_scope else '승격(정상)'}] {d.name} ({sec:.2f}s lp={logprob:.2f}) {text!r}")
    total = len(dirs)
    print(f"\n총 {total}건 — 즉시 처리 {hit_ok + hit_bad} (정답 {hit_ok} / 오답 {hit_bad}), "
          f"정상 승격 {escal}, 미스 {miss}")
    print(f"STT 지연: 중앙값 {sorted(lat)[len(lat) // 2]:.2f}s, 최대 {max(lat):.2f}s")
    if hit_bad:
        sys.exit(1)  # 즉시 처리가 틀리는 건 위험 — 오답 0이 합격선


def _load_audio(d):
    """케이스 wav → 16kHz int16. 파이프라인 표준(16k)이 아니면 리샘플 —
    샘플레이트 불일치는 STT가 조용히 궤멸하는 종류라 로더가 방어한다."""
    import wave as wavmod

    import numpy as np

    with wavmod.open(str(d / "audio.wav")) as w:
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if sr != 16000:
        n = int(len(a) * 16000 / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)),
                      a.astype(np.float32)).astype(np.int16)
    return a


def run_draft():
    """라벨 초안 자동 생성 — 사람의 라벨링을 '작성'에서 '검토'로 바꾼다.

    STT로 받아쓰고 1단 라우터로 액션을 추측해 expected.draft.json을 만든다.
    _stt 필드에 받아쓴 텍스트가 있어 오디오를 안 듣고도 검토 가능. 초안은
    채점에 쓰이지 않는다 — 검토·수정 후 --adopt 해야 expected.json이 된다
    (검토 안 된 라벨이 기준선을 오염시키지 않게 하는 2단계 장치).
    """
    import brain
    from router import DEICTIC, Router

    r = Router(brain.WAKE_WORD)
    made = 0
    for d in (sorted(CASES.iterdir()) if CASES.exists() else []):
        if not d.is_dir() or (d / "expected.json").exists() or (d / "expected.draft.json").exists():
            continue
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        text, _, logprob = r.transcribe(_load_audio(d))
        hit = r.route(text, meta.get("session", False), logprob)
        if hit:  # 라우터가 확신한 고정 명령 — 라벨 통째로 초안
            draft = {k: v for k, v in hit.items()
                     if k in ("is_command", "action", "app", "media_key")}
        elif any(w in text for w in DEICTIC):  # 지시어 — 명령일 확률 높음, 액션은 사람이
            draft = {"is_command": True}
        else:  # 사전 밖 — 잡음·대화일 확률 높음 (검토에서 뒤집으면 됨)
            draft = {"is_command": False}
        draft["_stt"] = text
        (d / "expected.draft.json").write_text(
            json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
        made += 1
        print(f"[초안] {d.name}: {text!r} → {draft}")
    print(f"\n초안 {made}건 — 검토·수정 후 `--adopt`로 채택하세요 (_stt는 채택 시 제거됨)")


def run_adopt():
    """검토 끝난 초안을 채점용 라벨로 채택 — _로 시작하는 보조 필드는 버린다."""
    n = 0
    for d in (sorted(CASES.iterdir()) if CASES.exists() else []):
        f = d / "expected.draft.json"
        if not d.is_dir() or not f.exists():
            continue
        clean = {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items()
                 if not k.startswith("_")}
        (d / "expected.json").write_text(
            json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        f.unlink()
        n += 1
    print(f"채택 {n}건 — 이제 채점 대상입니다")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--tier1" in sys.argv:
        run_tier1()
    elif "--draft" in sys.argv:
        run_draft()
    elif "--adopt" in sys.argv:
        run_adopt()
    else:
        only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
        action = sys.argv[sys.argv.index("--action") + 1] if "--action" in sys.argv else None
        run(only, action)
