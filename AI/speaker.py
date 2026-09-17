# -*- coding: utf-8 -*-
"""화자 인증 — 등록된 사용자 목소리에만 반응.

ECAPA-TDNN(SpeechBrain, voxceleb 사전학습)으로 발화를 192차원 임베딩으로 바꾸고,
등록 시 저장해 둔 사용자 임베딩과 코사인 유사도로 비교한다. 임계 미만이면
유튜브 소리·옆사람 목소리 → 무시. 얼굴인식과 같은 "등록→대조" 구조.

한계(정직하게): 배경 소음이 크면 임베딩이 오염돼 본인이 거부되거나 남이 통과할 수
있다. 그래서 임계는 실측 튜닝 노브이고, 입술 검증과 병행하면 더 강하다.
"""
import io
import threading

import numpy as np

MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
EMBED_DIM = 192
THRESHOLD = 0.45          # NOTE(튜닝): 화자 인증 코사인 유사도 하한. voxceleb ECAPA 실측 기준 본인 발화는 0.4~0.7.
                          # 값은 여기 한 곳만 본다 — npz 의 threshold 칸은 형식만 검사하고 값은 무시한다. 파일 값을 쓰면
                          # 재등록 때 그 순간의 메모리 값이 파일에 박혀 정한 값이 조용히 되돌아간다 (0.45 → 0.25 로 돌아간
                          # 사례 있음, gitignore 라 보이지도 않았다).


class SpeakerVerifier:
    """모델은 무겁게(12초) 로드되므로, 화자 인증을 켤 때만 생성한다."""

    def __init__(self, profile_path, threshold=THRESHOLD):
        self.profile_path = str(profile_path)
        self.default_threshold = threshold
        self._profile = (None, threshold, None, None)  # centroid, threshold, 활성 ID, sha256
        self._clf = None
        self._load_lock = threading.Lock()
        self.reload()

    @staticmethod
    def read_profile(source, default_threshold=THRESHOLD):
        """메모리에 적용하기 전에 npz 구조·차원·수치를 검증한다. 객체 역직렬화는 금지한다.
        threshold 칸은 형식만 확인하고 값은 default_threshold(코드 상수)를 쓴다 — 위 THRESHOLD 주석 참고."""
        with np.load(source, allow_pickle=False) as data:
            centroid = data["centroid"]
            threshold = data["threshold"] if "threshold" in data.files else np.asarray(default_threshold)
            if (centroid.shape != (EMBED_DIM,) or centroid.dtype.kind not in "fi"
                    or not np.isfinite(centroid).all() or not np.isclose(np.linalg.norm(centroid), 1, atol=1e-3)):
                raise ValueError("보이스 centroid는 정규화된 192차원 유한 벡터여야 합니다")
            if threshold.shape != () or threshold.dtype.kind not in "fi" or not -1 <= float(threshold) <= 1:
                raise ValueError("보이스 threshold는 -1~1 범위의 유한 스칼라여야 합니다")
        centroid.setflags(write=False)
        return centroid, float(default_threshold)

    def snapshot(self):
        """한 발화가 판정 도중 프로필을 바꿔 읽지 않도록 불변 묶음을 반환한다."""
        return self._profile

    def apply_profile(self, centroid, threshold, profile_id=None, sha256=None):
        self._profile = (centroid, threshold, profile_id, sha256)

    @property
    def centroid(self):
        return self._profile[0]

    @property
    def threshold(self):
        return self._profile[1]

    @property
    def profile_id(self):
        return self._profile[2]

    @property
    def profile_sha256(self):
        return self._profile[3]

    def reload(self):
        """부팅·단독 실행용 로컬 프로필 읽기 — 없거나 깨졌으면 미등록으로 시작한다."""
        try:
            self.apply_profile(*self.read_profile(self.profile_path, self.default_threshold))
        except Exception:
            self.apply_profile(None, self.default_threshold)

    @property
    def enrolled(self):
        return self.centroid is not None

    def _model(self):
        with self._load_lock:  # 워밍업 스레드와 판정 스레드가 첫 호출을 겹쳐 부르면 모델을 두 번 올린다
            if self._clf is None:
                import torch
                from speechbrain.inference.speaker import EncoderClassifier

                dev = "cuda:0" if torch.cuda.is_available() else "cpu"
                self._clf = EncoderClassifier.from_hparams(source=MODEL_SOURCE, run_opts={"device": dev})
                self._torch = torch
        return self._clf

    def embed(self, audio_i16):
        """int16 mono 16kHz → 192차원 L2정규화 임베딩."""
        clf = self._model()
        sig = np.asarray(audio_i16, dtype=np.float32) / 32768.0
        with self._torch.inference_mode():
            e = clf.encode_batch(self._torch.tensor(sig).unsqueeze(0)).squeeze().cpu().numpy()
        return e / (np.linalg.norm(e) + 1e-9)

    def centroid_of(self, audio_list):
        """여러 발화 → (평균 임베딩 L2 정규화, 샘플 간 최소 유사도). 최소 유사도는 일관성 지표 — 낮으면 녹음이 지저분한 것."""
        return self.centroid_of_embs([self.embed(a) for a in audio_list])

    def centroid_of_embs(self, embs):
        """이미 뽑아 둔 임베딩들 → (평균 임베딩 L2 정규화, 샘플 간 최소 유사도).
        문장마다 미리 임베딩해 두는 등록(voice_bridge)이 마지막에 같은 오디오를 다시 뽑지 않으려고 쓴다."""
        embs = np.asarray(embs)
        c = embs.mean(axis=0)
        c = c / (np.linalg.norm(c) + 1e-9)
        return c, float((embs @ c).min())

    def npz_bytes(self, centroid):
        """프로필 npz 직렬화 — 로컬 파일과 BE 업로드(65)가 같은 형식을 쓴다."""
        buf = io.BytesIO()
        np.savez(buf, centroid=centroid, threshold=self.threshold)
        return buf.getvalue()

    def enroll(self, audio_list):
        """여러 발화 → centroid 를 프로필 파일로 저장(CLI 등록). 샘플 간 최소 유사도 반환."""
        centroid, min_sim = self.centroid_of(audio_list)
        with open(self.profile_path, "wb") as f:
            f.write(self.npz_bytes(centroid))
        self.apply_profile(centroid, self.threshold)
        return min_sim

    def verify(self, audio_i16, profile=None):
        """(통과여부, 유사도). 미등록은 (True, None) 으로 통과시키고, 등록돼 있는데 대조에 실패하면
        (False, None) — 목소리를 확인하지 못한 발화를 통과시키면 화자 인증이 없는 것과 같아진다.
        실제 불일치는 유사도가 숫자로 남으므로 호출한 쪽에서 오류와 구분할 수 있다."""
        centroid, threshold, _, _ = self.snapshot() if profile is None else profile
        if centroid is None:
            return True, None
        try:
            sim = float(self.embed(audio_i16) @ centroid)
        except Exception as e:
            print(f"[화자 인증 오류, 차단] {type(e).__name__}: {e}")
            return False, None
        if not np.isfinite(sim):
            # 임베딩이 NaN·Inf 로 나오면(모델 이상·오디오 손상) 유사도도 숫자가 아니다.
            # 이대로 비교하면 항상 False 라 불일치처럼 보이므로, 오류로 구분해 돌려준다.
            print("[화자 인증 오류, 차단] 유사도가 유효한 숫자가 아닙니다")
            return False, None
        return sim >= threshold, sim


# --- 호출어 개인화 템플릿 (온보딩 5회 녹음으로 만든다) ---
WAKE_TEMPLATE_VERSION = 2
WAKE_SR = 16000
WAKE_LEGACY_EXTRA_MAX = 10   # 이전 실측 NPZ의 추가 행은 읽기만 허용한다. 판정은 등록 당시 기준 행만 쓴다.


class WakeTemplate:
    """온보딩 호출어의 화자 기준 — 호출어 문자열과 등록 임베딩을 보관한다.

    발음은 시동어 모델에서, 목소리는 등록 임베딩과의 유사도로 따로 확인한다.
    보이스 프로필 번호와는 묶지 않는다 — 화자 재등록으로 번호가 바뀌어도 등록본은 그대로 쓴다 (303).
    NOTE(한계): 짧은 호출어는 화자 정보가 적다. 등록자·타인 녹음으로 임계값을 확인해야 한다.
    """

    def __init__(self, wake_text, scores, embs, base_n, extractor=MODEL_SOURCE):
        self.wake_text = wake_text
        self.scores = tuple(float(s) for s in scores)   # 등록 때 시동어 점수 — 실측 기록용, 판정에는 안 쓴다
        self.embs = np.asarray(embs, dtype=np.float32)
        self.base_n = int(base_n)
        self.extractor = extractor

    @property
    def base_embs(self):
        return self.embs[:self.base_n]

    # --- 판정 ---
    def similarity(self, emb):
        """등록 당시 기준 5개와의 최고 유사도. 이전 실측에서 추가한 행은 판정에 쓰지 않는다."""
        scores = self.base_embs @ np.asarray(emb, dtype=np.float32)
        if not np.isfinite(scores).all():
            return None
        return float(scores.max())

    def matches_setting(self, wake_text):
        """등록 당시 호출어와 현재 설정이 같은지 확인한다."""
        return self.wake_text.strip() == (wake_text or "").strip()

    # --- 저장 ---
    def npz_bytes(self):
        buf = io.BytesIO()
        np.savez(buf, version=WAKE_TEMPLATE_VERSION, extractor=self.extractor, sr=WAKE_SR,
                 wake_text=self.wake_text, scores=np.asarray(self.scores, dtype=np.float32),
                 embs=self.embs, base_n=self.base_n)
        return buf.getvalue()

    @staticmethod
    def read(source):
        """NPZ의 형식·모델·차원·수치를 확인한 뒤 읽는다. 다른 모델의 임베딩은 비교하지 않는다."""
        with np.load(source, allow_pickle=False) as data:
            version = int(data["version"])
            if version != WAKE_TEMPLATE_VERSION:
                raise ValueError(f"호출어 템플릿 형식 버전이 다릅니다 ({version} != {WAKE_TEMPLATE_VERSION})")
            extractor = str(data["extractor"])
            if extractor != MODEL_SOURCE:
                raise ValueError(f"다른 임베딩 모델로 만든 템플릿입니다 ({extractor})")
            if int(data["sr"]) != WAKE_SR:
                raise ValueError("호출어 템플릿 표본율이 다릅니다")
            embs = data["embs"]
            base_n = int(data["base_n"])
            if (embs.ndim != 2 or embs.shape[1] != EMBED_DIM or len(embs) < 1
                    or embs.dtype.kind not in "fi" or not np.isfinite(embs).all()
                    or not np.allclose(np.linalg.norm(embs, axis=1), 1, atol=1e-3)):
                raise ValueError(f"호출어 임베딩은 정규화된 {EMBED_DIM}차원 유한 벡터여야 합니다")
            if not 1 <= base_n <= len(embs) or len(embs) - base_n > WAKE_LEGACY_EXTRA_MAX:
                raise ValueError("기준 샘플 수가 범위를 벗어났습니다")
            wake_text = str(data["wake_text"])
            if not wake_text.strip():
                raise ValueError("호출어 문자열이 비어 있습니다")
            scores = data["scores"]
            if scores.ndim != 1 or scores.dtype.kind not in "fi" or not np.isfinite(scores).all():
                raise ValueError("등록 점수 기록이 유한한 1차원 배열이 아닙니다")
            # 이전 형식의 profile_id 필드는 있어도 읽지 않는다
        embs = np.array(embs, dtype=np.float32)
        embs.setflags(write=False)
        return WakeTemplate(wake_text, scores, embs, base_n, extractor)
