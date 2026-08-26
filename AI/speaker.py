# -*- coding: utf-8 -*-
"""화자 인증 — 등록된 사용자 목소리에만 반응.

ECAPA-TDNN(SpeechBrain, voxceleb 사전학습)으로 발화를 192차원 임베딩으로 바꾸고,
등록 시 저장해 둔 사용자 임베딩과 코사인 유사도로 비교한다. 임계 미만이면
유튜브 소리·옆사람 목소리 → 무시. 얼굴인식과 같은 "등록→대조" 구조.

한계(정직하게): 배경 소음이 크면 임베딩이 오염돼 본인이 거부되거나 남이 통과할 수
있다. 그래서 임계는 실측 튜닝 노브이고, 입술 검증과 병행하면 더 강하다.
"""
import numpy as np

MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"


class SpeakerVerifier:
    """모델은 무겁게(12초) 로드되므로, 화자 인증을 켤 때만 생성한다."""

    def __init__(self, profile_path, threshold=0.25):
        # ponytail: threshold는 코사인 유사도 하한. voxceleb ECAPA 실측 기준
        # 본인 발화는 보통 0.4~0.7, 타인/미디어는 0.0~0.25. 조용한 환경에서 올리고,
        # 본인이 자주 거부되면 내린다. 실사용 로그(아래 verify 반환값) 보고 조정.
        self.profile_path = str(profile_path)
        self.threshold = threshold
        self._clf = None
        self.centroid = None
        try:
            d = np.load(self.profile_path)
            self.centroid = d["centroid"]
            self.threshold = float(d["threshold"]) if "threshold" in d.files else threshold
        except Exception:
            pass

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

    def enroll(self, audio_list):
        """여러 발화 → 평균 임베딩(centroid) 저장. 등록 샘플 간 최소 유사도 반환
        (일관성 지표 — 낮으면 녹음이 지저분한 것)."""
        embs = np.array([self.embed(a) for a in audio_list])
        c = embs.mean(axis=0)
        self.centroid = c / (np.linalg.norm(c) + 1e-9)
        np.savez(self.profile_path, centroid=self.centroid, threshold=self.threshold)
        sims = embs @ self.centroid
        return float(sims.min())

    def verify(self, audio_i16):
        """(통과여부, 유사도). 미등록이면 (True, 1.0) — 게이트 자체를 끔."""
        if not self.enrolled:
            return True, 1.0
        try:
            sim = float(self.embed(audio_i16) @ self.centroid)
        except Exception as e:
            print(f"[화자 인증 오류, 통과 처리] {e}")
            return True, 1.0
        return sim >= self.threshold, sim
