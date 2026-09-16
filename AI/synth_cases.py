# -*- coding: utf-8 -*-
"""1단 라우터 평가용 합성 케이스 생성기 — 윈도우 TTS로 육성 없이 커버리지 확보.

아래 COMMANDS 표의 문장을 SAPI 한국어 음성으로 16kHz WAV 생성 →
eval/cases/synth_NN/에 정답 라벨과 함께 기록. 문장을 우리가 정하므로
정답을 아는 상태 — 라벨링이 필요 없다.

용도는 `eval_prompt.py --tier1` 전용. TTS 기계음은 화자 게이트에 걸리고
"기계음 기각" 판정과 얽히므로 LLM 회귀(run)에서는 synth_ 케이스를
건너뛴다. 실행할 때마다 synth_* 전체를 지우고 다시 만든다(멱등).

사용: python synth_cases.py
"""
import json
import shutil
from pathlib import Path

CASES = Path(__file__).parent / "eval" / "cases"

# (문장, 세션 활성 여부, 기대 라벨) — 기대 라벨은 --tier1과 LLM 회귀가 공용으로 읽는 형식
COMMANDS = [
    # 1단이 즉시 처리해야 하는 고정 명령
    ("시아야 계산기 열어줘", False, {"is_command": True, "action": "open_app", "app": "calc"}),
    ("시아야 메모장 켜줘", False, {"is_command": True, "action": "open_app", "app": "notepad"}),
    ("시아야 크롬 실행해줘", False, {"is_command": True, "action": "open_app", "app": "chrome"}),
    ("시아야 그림판 띄워줘", False, {"is_command": True, "action": "open_app", "app": "paint"}),
    ("음소거 해줘", True, {"is_command": True, "action": "media", "media_key": "mute"}),
    ("일시정지 해줘", True, {"is_command": True, "action": "media", "media_key": "playpause"}),
    ("다음 곡 틀어줘", True, {"is_command": True, "action": "media", "media_key": "next"}),
    ("볼륨 올려줘", True, {"is_command": True, "action": "media", "media_key": "volup"}),
    ("이제 그만", True, {"is_command": True, "action": "end_session"}),
    ("시아야 크롬 켜줘", False, {"is_command": True, "action": "open_app", "app": "chrome"}),
    ("시아야 계산기 켜", False, {"is_command": True, "action": "open_app", "app": "calc"}),
    ("시아야 탐색기 열어", False, {"is_command": True, "action": "open_app", "app": "explorer"}),
    ("시아야 그림판", False, {"is_command": True, "action": "open_app", "app": "paint"}),
    ("메모장 열어줄래", True, {"is_command": True, "action": "open_app", "app": "notepad"}),
    ("소리 좀 키워줘", True, {"is_command": True, "action": "media", "media_key": "volup"}),
    ("볼륨 낮춰", True, {"is_command": True, "action": "media", "media_key": "voldown"}),
    ("소리 80까지 높여줘", True, {"is_command": True, "action": "media", "media_key": "volset", "level": 80}),
    ("이전 곡", True, {"is_command": True, "action": "media", "media_key": "prev"}),
    ("멈춰", True, {"is_command": True, "action": "media", "media_key": "playpause"}),
    ("수고했어", True, {"is_command": True, "action": "end_session"}),
    # 1단이 손대면 안 되는 것 — 승격이 정답
    ("시아야 이거 저장해줘", False, {"is_command": True, "action": "save_crop"}),
    ("시아야 이 창 닫아줘", False, {"is_command": True, "action": "window", "window_op": "close"}),
    ("시아야 크롬 닫아줘", False, {"is_command": True, "action": "window", "window_op": "close"}),
    ("오늘 날씨 어때", False, {"is_command": False}),
    ("저 이제 밥 먹으러 갈게요", True, {"is_command": False}),
]


def korean_voice(spvoice):
    voices = spvoice.GetVoices("Language=412")  # 412 = ko-KR LCID
    if voices.Count == 0:
        raise SystemExit("한국어 TTS 음성이 없습니다 (설정 > 음성에서 한국어 추가)")
    return voices.Item(0)


def make_wav(spvoice, text, path):
    import win32com.client

    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Format.Type = 18  # SAFT16kHz16BitMono — 파이프라인과 동일 포맷 (22는 22kHz — 오독 주의)
    stream.Open(str(path), 3)  # 3 = SSFMCreateForWrite
    spvoice.AudioOutputStream = stream
    spvoice.Speak(text)
    stream.Close()


def main():
    import win32com.client

    for d in (CASES.glob("synth_*") if CASES.exists() else []):
        shutil.rmtree(d)
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.Voice = korean_voice(voice)
    for i, (text, session, expected) in enumerate(COMMANDS, 1):
        d = CASES / f"synth_{i:02d}"
        d.mkdir(parents=True, exist_ok=True)
        make_wav(voice, text, d / "audio.wav")
        (d / "meta.json").write_text(json.dumps(
            {"session": session, "pending_q": None, "dom": None, "synthetic": True},
            ensure_ascii=False), encoding="utf-8")
        (d / "expected.json").write_text(json.dumps(expected, ensure_ascii=False),
                                         encoding="utf-8")
        print(f"synth_{i:02d}: {text!r}")
    print(f"\n{len(COMMANDS)}건 생성 — 평가: python eval_prompt.py --tier1")


if __name__ == "__main__":
    main()
