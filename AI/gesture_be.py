# -*- coding: utf-8 -*-
"""BE 제스처 동기화와 등록 촬영 보조.

카메라는 assistant.py만 소유한다. 이 모듈은 프레임을 받아 BE 프로토콜 이벤트와
제스처 템플릿(npz)을 처리하므로 별도 카메라를 열지 않는다.
"""
import base64
import io
import json
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from hands import CustomGestures, normalize_landmarks


class GestureRegistrationRejected(ValueError):
    """FE에 유사 제스처 정보를 함께 알려야 하는 등록 거부."""

    def __init__(self, reason, similar_to=None, similarity=None):
        super().__init__(reason)
        self.similar_to = similar_to
        self.similarity = similarity


def registration_blocks_gesture_execution(registration):
    """등록 모드에서는 샘플 수집 외의 제스처 명령을 실행하지 않는다.

    카메라와 랜드마크 추론은 계속 필요하지만, 같은 손모양이 정적·동적·양손
    명령으로 해석되어 로컬 또는 BE에서 실행되면 안 된다.
    """
    return bool(registration is not None and registration.active)


class GestureTemplateCache:
    """BE의 제스처별 npz를 받아 기존 kNN 저장소 형식으로 합친다."""

    def __init__(self, cache_dir, combined_path):
        self.cache_dir = Path(cache_dir)
        self.combined_path = Path(combined_path)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.cache_dir / "manifest.json"
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            self.manifest = {}

    @staticmethod
    def template_bytes(name, feats):
        out = io.BytesIO()
        feats = np.asarray(feats, dtype=np.float32)
        np.savez_compressed(out, X=feats, names=np.array([name] * len(feats)))
        return out.getvalue()

    @staticmethod
    def _read_template(payload, fallback_name):
        with np.load(io.BytesIO(payload), allow_pickle=False) as data:
            x = np.asarray(data["X"], dtype=np.float32)
            if x.ndim != 2 or x.shape[1] != 42 or len(x) == 0:
                raise ValueError("제스처 템플릿은 (N, 42) 랜드마크여야 합니다")
        return x, np.array([fallback_name] * len(x))

    def sync(self, link, refs):
        """refs=[{id,name,sha256}]를 로컬 캐시와 비교해 달라진 파일만 받는다."""
        refs = refs or []
        wanted = {str(item["id"]): item for item in refs if item.get("id") is not None}
        changed = False
        for gid, ref in wanted.items():
            old = self.manifest.get(gid, {})
            if old.get("sha256") == ref.get("sha256") and (self.cache_dir / f"g{gid}.npz").exists():
                if old.get("name") != ref.get("name", gid):
                    self.manifest[gid] = {"name": ref.get("name", gid), "sha256": ref.get("sha256")}
                    changed = True
                continue
            payload, digest = link.get_gesture_npz(gid, old.get("sha256"))
            if payload is not None:
                (self.cache_dir / f"g{gid}.npz").write_bytes(payload)
                self.manifest[gid] = {"name": ref.get("name", gid), "sha256": digest or ref.get("sha256")}
                changed = True
        for gid in list(self.manifest):
            if gid not in wanted:
                (self.cache_dir / f"g{gid}.npz").unlink(missing_ok=True)
                del self.manifest[gid]
                changed = True
        if changed or not self.combined_path.exists():
            self._rebuild(wanted)
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        return changed

    def _rebuild(self, refs):
        xs, names = [], []
        for gid, ref in refs.items():
            path = self.cache_dir / f"g{gid}.npz"
            if not path.exists():
                continue
            try:
                x, n = self._read_template(path.read_bytes(), str(ref.get("name", gid)))
                xs.append(x)
                names.append(n)
            except Exception as exc:
                print(f"[제스처] 템플릿 g{gid} 무시: {exc}")
        if xs:
            np.savez_compressed(self.combined_path, X=np.concatenate(xs), names=np.concatenate(names))
        else:
            self.combined_path.unlink(missing_ok=True)


class GestureRegistration:
    """BE reg_mode_start에 대응하는 정적/동적 커스텀 제스처 촬영 상태기계."""

    DEFAULT_TAKES = 3
    DEFAULT_COUNTDOWN_S = 3.0
    DEFAULT_TAKE_S = 2.0
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"
    FRAME_INTERVAL_S = 0.10
    BUILTIN_OVERLAP = 0.20
    MIN_PALM_SIZE = 0.055
    MAX_SIZE_CV = 0.20
    MAX_ANGLE_STD_DEG = 20.0
    MAX_SPREAD = 0.25

    def __init__(self, link, template_cache, custom_store):
        self.link = link
        self.cache = template_cache
        self.custom_store = custom_store
        self.reset()

    def reset(self):
        self.temp_id = None
        self.phase = "IDLE"
        self.take = 0
        # BE reg_mode_start가 주는 촬영 설정을 따른다. 이벤트에 값이 없을 때만 기본값을 쓴다.
        self.takes = self.DEFAULT_TAKES
        self.countdown_s = self.DEFAULT_COUNTDOWN_S
        self.take_s = self.DEFAULT_TAKE_S
        self.motion = self.DYNAMIC
        self.phase_at = 0.0
        self.last_frame_at = 0.0
        self.seq = 0
        self.samples = []
        self.sizes = []
        self.angles = []
        self.builtin_hits = {}
        self.hand_counts = []

    @property
    def active(self):
        return self.temp_id is not None

    @staticmethod
    def _positive_number(data, key, default, integer=False):
        """BE 촬영 설정은 그대로 쓰고, 누락·형식 오류·0 이하일 때만 기본값을 쓴다."""
        try:
            value = int(data.get(key, default)) if integer else float(data.get(key, default))
        except (TypeError, ValueError):
            return default
        if value <= 0:
            return default
        return value

    def start(self, data, now=None):
        self.reset()
        self.temp_id = str(data.get("tempId", ""))
        if not self.temp_id:
            return
        motion = str(data.get("motion", self.DYNAMIC)).upper()
        self.motion = motion if motion in (self.STATIC, self.DYNAMIC) else self.DYNAMIC
        # FE 안내, BE 프리뷰 버퍼, AI 샘플 수집 구간을 같은 설정으로 맞춘다.
        self.takes = self._positive_number(
            data, "takes", self.DEFAULT_TAKES, integer=True
        )
        self.countdown_s = self._positive_number(
            data, "countdownSec", self.DEFAULT_COUNTDOWN_S
        )
        # STATIC은 BE 계약상 한 장 캡처이므로 takeDurationSec 자체가 없다.
        if self.motion == self.DYNAMIC:
            self.take_s = self._positive_number(
                data, "takeDurationSec", self.DEFAULT_TAKE_S
            )
        self.take = 1
        self.phase = "COUNTDOWN"
        self.phase_at = time.monotonic() if now is None else now
        self.link.send_event("reg_started", {"tempId": self.temp_id})
        self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                           "phase": "COUNTDOWN"})
        print(f"[제스처 등록] 시작 tempId={self.temp_id} "
              f"({self.motion}, {self.takes}회, 카운트다운 {self.countdown_s:g}초"
              + (f", 촬영 {self.take_s:g}초)" if self.motion == self.DYNAMIC else ", 회차당 캡처 1장)"))

    def _emit_frame(self, frame, now, force=False):
        if not force and now - self.last_frame_at < self.FRAME_INTERVAL_S:
            return
        self.last_frame_at = now
        view = frame
        if frame.shape[1] > 640:
            ratio = 640 / frame.shape[1]
            view = cv2.resize(frame, (640, int(frame.shape[0] * ratio)))
        ok, encoded = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            return
        self.seq += 1
        self.link.send_event("reg_frame", {
            "tempId": self.temp_id, "take": self.take, "seq": self.seq,
            "tsMs": int(now * 1000), "jpegB64": base64.b64encode(encoded).decode("ascii"),
        })

    @staticmethod
    def _hand_quality(landmarks):
        wrist, middle = landmarks[0], landmarks[9]
        dx, dy = middle[0] - wrist[0], middle[1] - wrist[1]
        return float(np.hypot(dx, dy)), float(np.arctan2(dy, dx))

    @staticmethod
    def _as_hands(hands):
        if hands is None:
            return []
        return [hands] if isinstance(hands, dict) else list(hands)

    def _collect(self, hands):
        """현재 프레임의 손 관측을 기록한다. 정적 템플릿은 첫 손을 사용한다."""
        self.hand_counts.append(len(hands))
        if not hands:
            return
        lm = hands[0]["landmarks"]
        self.samples.append(normalize_landmarks(lm))
        size, angle = self._hand_quality(lm)
        self.sizes.append(size)
        self.angles.append(angle)
        label = hands[0].get("gesture")
        if label and label != "None":
            self.builtin_hits[label] = self.builtin_hits.get(label, 0) + 1

    def tick(self, frame, hands, now=None):
        if not self.active:
            return None
        now = time.monotonic() if now is None else now
        hands = self._as_hands(hands)
        elapsed = now - self.phase_at
        if self.phase == "COUNTDOWN":
            if elapsed < self.countdown_s:
                return {"phase": self.phase, "take": self.take,
                        "remaining": max(0.0, self.countdown_s - elapsed)}
            self.phase = "RECORDING"
            self.phase_at = now
            self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                               "phase": "RECORDING"})
        if self.phase == "RECORDING":
            # 정적은 카운트다운 직후 한 장만 캡처한다. 동적만 시간 구간을 수집한다.
            self._emit_frame(frame, now, force=self.motion == self.STATIC)
            self._collect(hands)
            if self.motion == self.STATIC or now - self.phase_at >= self.take_s:
                if self.take < self.takes:
                    self.take += 1
                    self.phase = "COUNTDOWN"
                    self.phase_at = now
                    self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                                       "phase": "COUNTDOWN"})
                else:
                    self.phase = "WAIT_FINISH"
                    self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                                       "phase": "DONE"})
        return {"phase": self.phase, "take": self.take, "remaining": 0.0}

    def finish(self):
        if not self.active:
            return
        temp_id = self.temp_id
        if self.phase != "WAIT_FINISH":
            # BE/FE의 종료 이벤트가 촬영 계획보다 빨리 도착했을 때, 부분 샘플을
            # '손 랜드마크 부족' 품질 실패로 오인하지 않고 명시적 중단으로 처리한다.
            reason = (f"촬영이 완료되기 전에 등록이 종료되었습니다 "
                      f"({self.take}/{self.takes}회, {self.phase}). 다시 촬영하세요.")
            self.link.send_event("reg_rejected", {"tempId": temp_id, "reason": reason})
            print(f"[제스처 등록] 중단: {reason}")
            self.reset()
            return
        try:
            self._validate_and_upload()
            hands = 2 if self.hand_counts and sum(n >= 2 for n in self.hand_counts) >= len(self.hand_counts) * 0.7 else 1
            self.link.send_event("reg_captured", {"tempId": temp_id, "hands": hands})
            print("[제스처 등록] 품질 검사 통과. 기능 지정 대기")
        except ValueError as exc:
            payload = {"tempId": temp_id, "reason": str(exc)}
            if isinstance(exc, GestureRegistrationRejected) and exc.similar_to:
                payload["similarTo"] = exc.similar_to
                payload["similarity"] = exc.similarity
            self.link.send_event("reg_rejected", payload)
            print(f"[제스처 등록] 거부: {exc}")
        finally:
            self.reset()

    def _validate_and_upload(self):
        if len(self.samples) < 30:
            raise ValueError("손 랜드마크가 충분히 수집되지 않았습니다")
        sizes = np.asarray(self.sizes)
        angles = np.asarray(self.angles)
        if sizes.min() < self.MIN_PALM_SIZE:
            raise ValueError("손이 너무 작게 감지되었습니다. 손목까지 카메라에 보여주세요")
        if sizes.std() / max(sizes.mean(), 1e-6) > self.MAX_SIZE_CV:
            raise ValueError("등록 중 손 크기 변화가 큽니다")
        mean = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())
        delta = np.arctan2(np.sin(angles - mean), np.cos(angles - mean))
        if np.degrees(delta.std()) > self.MAX_ANGLE_STD_DEG:
            raise ValueError("등록 중 손 방향 변화가 큽니다")
        feats = np.asarray(self.samples, dtype=np.float32)
        spread = float(np.linalg.norm(feats - feats.mean(axis=0), axis=1).mean())
        if spread > self.MAX_SPREAD:
            raise ValueError("샘플이 너무 흩어졌습니다. 손모양을 고정해 다시 촬영하세요")
        for label, count in self.builtin_hits.items():
            if count >= len(feats) * self.BUILTIN_OVERLAP:
                raise GestureRegistrationRejected(
                    f"내장 제스처 '{label}'와 너무 유사합니다 ({count}/{len(feats)})",
                    similar_to=label,
                    similarity=round(count / len(feats), 4),
                )
        near, dist = self.custom_store.nearest_class(feats)
        if near and dist < 0.45:
            # 랜드마크 거리는 확률이 아니므로, 화면 표시용으로 단조 감소 점수로
            # 변환한다. 0은 동일, 거리가 멀수록 0에 가까워진다.
            similarity = round(float(np.exp(-dist)), 4)
            raise GestureRegistrationRejected(
                f"기존 제스처 '{near}'와 너무 유사합니다",
                similar_to=near,
                similarity=similarity,
            )
        payload = self.cache.template_bytes("__pending__", feats)
        self.link.put_gesture_npz(self.temp_id, payload)
