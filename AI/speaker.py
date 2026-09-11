# -*- coding: utf-8 -*-
"""화자 인증 — 등록된 사용자 목소리에만 반응.

ECAPA-TDNN(SpeechBrain, voxceleb 사전학습)으로 발화를 192차원 임베딩으로 바꾸고,
등록 시 저장해 둔 사용자 임베딩과 코사인 유사도로 비교한다. 임계 미만이면
유튜브 소리·옆사람 목소리 → 무시. 얼굴인식과 같은 "등록→대조" 구조.

한계(정직하게): 배경 소음이 크면 임베딩이 오염돼 본인이 거부되거나 남이 통과할 수
있다. 그래서 임계는 실측 튜닝 노브이고, 입술 검증과 병행하면 더 강하다.
"""
import io

import numpy as np

MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
EMBED_DIM = 192


class SpeakerVerifier:
    """모델은 무겁게(12초) 로드되므로, 화자 인증을 켤 때만 생성한다."""

    def __init__(self, profile_path, threshold=0.25):
        # NOTE(튜닝): threshold는 코사인 유사도 하한. voxceleb ECAPA 실측 기준
        # 본인 발화는 보통 0.4~0.7, 타인/미디어는 0.0~0.25. 조용한 환경에서 올리고,
        # 본인이 자주 거부되면 내린다. 실사용 로그(아래 verify 반환값) 보고 조정.
        self.profile_path = str(profile_path)
        self.default_threshold = threshold
        self._profile = (None, threshold, None, None)  # centroid, threshold, 활성 ID, sha256
        self._clf = None
        self.reload()

    @staticmethod
    def read_profile(source, default_threshold=0.25):
        """메모리에 적용하기 전에 npz 구조·차원·수치를 검증한다. 객체 역직렬화는 금지한다."""
        with np.load(source, allow_pickle=False) as data:
            centroid = data["centroid"]
            threshold = data["threshold"] if "threshold" in data.files else np.asarray(default_threshold)
            if (centroid.shape != (EMBED_DIM,) or centroid.dtype.kind not in "fi"
                    or not np.isfinite(centroid).all() or not np.isclose(np.linalg.norm(centroid), 1, atol=1e-3)):
                raise ValueError("보이스 centroid는 정규화된 192차원 유한 벡터여야 합니다")
            if threshold.shape != () or threshold.dtype.kind not in "fi" or not -1 <= float(threshold) <= 1:
                raise ValueError("보이스 threshold는 -1~1 범위의 유한 스칼라여야 합니다")
        centroid.setflags(write=False)
        return centroid, float(threshold)

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
        """(통과여부, 유사도). 미등록이면 (True, 1.0) — 게이트 자체를 끔."""
        centroid, threshold, _, _ = self.snapshot() if profile is None else profile
        if centroid is None:
            return True, 1.0
        try:
            sim = float(self.embed(audio_i16) @ centroid)
        except Exception as e:
            print(f"[화자 인증 오류, 통과 처리] {e}")
            return True, 1.0
        return sim >= threshold, sim
