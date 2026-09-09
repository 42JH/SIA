# -*- coding: utf-8 -*-
"""ETH-XGaze 사전학습 ResNet-18 시선 추정.

얼굴 크롭(224x224) → (pitch, yaw) 라디안. 출력이 절대적으로 정확할 필요는
없다 — 개인 캘리브레이션 회귀가 화면 좌표 매핑을 학습하므로, 시선 방향에
매끄럽게 단조 반응하는 신호면 충분하다. 홍채 기하 특징과 결합해 쓴다.
"""
import cv2
import numpy as np

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class DeepGaze:
    def __init__(self, weights_path):
        import torch
        import torchvision

        self.torch = torch
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        model = torchvision.models.resnet18(num_classes=2)
        sd = torch.load(weights_path, map_location="cpu", weights_only=True)
        if isinstance(sd, dict) and "model" in sd:  # ptgaze 체크포인트 래핑
            sd = sd["model"]
        sd = {k.removeprefix("module."): v for k, v in sd.items()}
        model.load_state_dict(sd)
        self.model = model.eval().to(self.dev)
        self._mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1).to(self.dev)
        self._std = torch.tensor(IMAGENET_STD).view(3, 1, 1).to(self.dev)

    def gaze(self, crop_bgr_224):
        """224x224 BGR 얼굴 크롭 → (pitch, yaw) 라디안."""
        rgb = cv2.cvtColor(crop_bgr_224, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        t = self.torch.from_numpy(rgb).permute(2, 0, 1).to(self.dev)
        t = ((t - self._mean) / self._std).unsqueeze(0)
        with self.torch.inference_mode():
            out = self.model(t)[0].float().cpu().numpy()
        return float(out[0]), float(out[1])


def face_crop(frame_bgr, lm, out=224):
    """랜드마크 기준 롤 보정 정사각 얼굴 크롭 (코끝 중심, 눈 사이 거리 비례).

    ETH-XGaze의 정식 정규화(카메라 행렬 워프)의 근사 — 잔여 왜곡은
    캘리브레이션 회귀가 흡수한다.
    """
    h, w = frame_bgr.shape[:2]

    def p(i):
        return np.array([lm[i].x * w, lm[i].y * h])

    er, el = p(33), p(263)  # 좌우 눈 바깥 꼬리
    center = p(1)           # 코끝
    d = el - er
    roll = float(np.degrees(np.arctan2(d[1], d[0])))
    size = 2.4 * float(np.linalg.norm(d)) + 1e-6
    M = cv2.getRotationMatrix2D((float(center[0]), float(center[1])), roll, out / size)
    M[0, 2] += out / 2 - center[0]
    M[1, 2] += out / 2 - center[1]
    return cv2.warpAffine(frame_bgr, M, (out, out))
