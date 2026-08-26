# -*- coding: utf-8 -*-
"""화자 등록 — 내 목소리를 비서에 학습시킨다.

실행:  python voice_enroll.py           (5개 문장 녹음 → 프로필 저장)
검증:  python voice_enroll.py --verify  (말하면 등록 목소리와 유사도 실시간 표시)
초기화: python voice_enroll.py --reset

마이크에 대고 아래 문구를 하나씩 자연스럽게 읽으면 된다. 조용한 곳에서 등록할수록
소음 환경에서도 잘 구분한다.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

from speaker import SpeakerVerifier
from voice import SR, VadSegmenter

HERE = Path(__file__).parent
PROFILE = HERE / "models" / "speaker.npz"
PHRASES = [
    "자비스 지금 화면 좀 정리해줘",
    "오늘 날씨가 참 맑고 좋다",
    "이 파일을 다른 폴더로 옮겨줄래",
    "다음 영상으로 넘어가고 음소거 해줘",
    "안녕하세요 저는 이 컴퓨터의 주인입니다",
]


def record_one(prompt_text, min_s=1.5):
    """한 문장을 발화 종료까지 녹음해 int16 반환 (VAD로 앞뒤 침묵 정리)."""
    import sounddevice as sd

    seg = VadSegmenter(end_silence_s=0.8, max_s=8.0)
    print(f"\n  \"{prompt_text}\"  ← 이 문장을 읽으세요...")
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=480) as stream:
        while True:
            data, _ = stream.read(480)
            ev = seg.feed(data[:, 0], time.monotonic())
            if ev and ev[0] == "utter":
                audio = ev[2]
                if len(audio) < SR * min_s:
                    print("  너무 짧습니다. 다시 읽어주세요.")
                    seg = VadSegmenter(end_silence_s=0.8, max_s=8.0)
                    continue
                print(f"  녹음됨 ({len(audio) / SR:.1f}초)")
                return audio


def enroll():
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    sv = SpeakerVerifier(PROFILE)
    print("화자 등록을 시작합니다. 조용한 곳에서 진행하세요.")
    print("(모델 로딩에 10초쯤 걸립니다)")
    sv._model()  # 미리 로드
    samples = [record_one(p) for p in PHRASES]
    consistency = sv.enroll(samples)
    print(f"\n등록 완료 → {PROFILE}")
    print(f"샘플 일관성(최소 유사도): {consistency:.2f} "
          + ("양호" if consistency > 0.5 else "낮음 — 조용한 곳에서 다시 등록 권장"))
    print("이제 assistant.py가 당신 목소리에만 반응합니다. 끄려면: --no-speaker")


def verify_live():
    sv = SpeakerVerifier(PROFILE)
    if not sv.enrolled:
        sys.exit("등록된 프로필이 없습니다. 먼저: python voice_enroll.py")
    sv._model()
    print("말해보세요. 등록 목소리와의 유사도를 표시합니다 (ESC 대신 Ctrl+C로 종료).")
    while True:
        audio = record_one("(아무 말이나)")
        ok, sim = sv.verify(audio)
        print(f"  유사도 {sim:.2f} → {'본인 (통과)' if ok else '타인/미디어 (차단)'} "
              f"[임계 {sv.threshold}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    if args.reset:
        PROFILE.unlink(missing_ok=True)
        print("화자 프로필 삭제됨.")
    elif args.verify:
        verify_live()
    else:
        enroll()
