# -*- coding: utf-8 -*-
"""화자 등록 — 내 목소리를 비서에 학습시킨다.

실행:  python voice_enroll.py           (5개 문장 녹음 → 프로필 저장)
검증:  python voice_enroll.py --verify  (말하면 등록 목소리와 유사도 실시간 표시)
초기화: python voice_enroll.py --reset

호출어 개인화 템플릿(models/wake.npz)은 앱 온보딩에서 등록하고 여기서는 상태만 확인한다:
  python voice_enroll.py --wake-info    (등록된 호출어·기준 샘플 수·연결된 프로필)

마이크에 대고 아래 문구를 하나씩 자연스럽게 읽으면 된다. 조용한 곳에서 등록할수록
소음 환경에서도 잘 구분한다.
"""
import argparse
import sys
import time
from pathlib import Path


from speaker import SpeakerVerifier
from voice import SR, VadSegmenter

HERE = Path(__file__).parent
PROFILE = HERE / "models" / "speaker.npz"
PHRASES = [
    "시아야 지금 화면 좀 정리해줘",
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
        score = f"{sim:.2f}" if sim is not None else "측정 불가"
        print(f"  유사도 {score} → "
              f"{'본인 (통과)' if ok else ('타인/미디어 (차단)' if sim is not None else '인증 오류 (차단)')} "
              f"[임계 {sv.threshold}]")


def wake_info():
    from voice_bridge import WakeTemplateStore

    store = WakeTemplateStore(HERE / "models" / "wake.npz")
    t = store.current
    if t is None:
        sys.exit("등록된 호출어 템플릿이 없습니다" + (f" (읽기 실패: {store.load_error})" if store.load_error else ""))
    print(f"호출어 \"{t.wake_text}\" — 기준 {t.base_n}개, "
          f"보이스 프로필 {t.profile_id if t.bound else '미연결'}")
    print(f"등록 때 시동어 점수(기록용, 판정에는 쓰지 않음): {[round(s, 2) for s in t.scores]}")
    return store


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 한글·em-dash 출력 크래시 방지
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--wake-info", action="store_true", help="호출어 템플릿 상태 보기")
    args = ap.parse_args()
    if args.wake_info:
        wake_info()
    elif args.reset:
        PROFILE.unlink(missing_ok=True)
        print("화자 프로필 삭제됨.")
    elif args.verify:
        verify_live()
    else:
        enroll()
