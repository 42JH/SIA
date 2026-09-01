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
  python eval_prompt.py --selftest    채점 로직 자가 점검 (API 안 씀)
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
CASES = HERE / "eval" / "cases"
HISTORY = HERE / "eval" / "history.jsonl"


def match(expected, result):
    """expected의 각 항목이 result와 맞는지 — (통과 여부, 어긋난 필드 설명들)."""
    bad = []
    for k, want in expected.items():
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
    ok, _ = match({"transcript~": "계산기"}, {"transcript": "자비스 계산기 켜줘"})
    assert ok
    ok, _ = match({"transcript~": "계산기"}, {"transcript": "음악 틀어줘"})
    assert not ok
    ok, _ = match({"app": None}, {})  # 필드 부재는 null과 동일 취급
    assert ok
    print("selftest ok")


def run(only=None):
    from PIL import Image
    from google import genai
    from google.genai import types

    import brain

    key = brain.load_api_key()
    if not key:
        sys.exit("GEMINI_API_KEY 없음 — 환경변수 또는 gemini_api_key.txt")
    client = genai.Client(api_key=key)

    dirs = [d for d in sorted(CASES.iterdir()) if d.is_dir()] if CASES.exists() else []
    if only:
        dirs = [d for d in dirs if d.name == only]
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
        parts.append(brain.build_prompt(meta.get("session", False), meta.get("pending_q")))
        cfg = dict(response_mime_type="application/json", temperature=0.1)
        if "lite" not in brain.MODEL:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        t0 = time.monotonic()
        try:
            resp = client.models.generate_content(
                model=brain.MODEL, contents=parts, config=types.GenerateContentConfig(**cfg))
            text = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            result = json.loads(text)
            ok, bad = match(expected, result)
        except Exception as e:
            ok, bad, result = False, [f"호출 실패: {e}"], {}
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


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
        run(only)
