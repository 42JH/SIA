# -*- coding: utf-8 -*-
"""BE 제스처 동기화와 등록 촬영 보조.

카메라는 assistant.py만 소유한다. 이 모듈은 프레임을 받아 BE 프로토콜 이벤트와
제스처 템플릿(npz)을 처리하므로 별도 카메라를 열지 않는다.
"""
import base64
import io
import json
import queue
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from hands import (CustomGestures, SCREEN_SWIPE_CONFIG, SwipeDetector,
                   normalize_landmarks, weighted_distance)
from custom_motion import (
    CustomGestureStore, FRAMES, PREFIX_MIN_MOTION, distance, encode_sequence,
    ordered_landmarks, read_templates, template_bytes as encode_template_bytes,
)


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


def encode_jpeg(frame, max_width=640, quality=75):
    """WS 전송용으로 프레임을 축소·JPEG 인코딩한다. 실패하면 None."""
    view = frame
    if frame.shape[1] > max_width:
        ratio = max_width / frame.shape[1]
        view = cv2.resize(frame, (max_width, int(frame.shape[0] * ratio)))
    ok, encoded = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(encoded).decode("ascii") if ok else None


class GesturePreview:
    """촬영 방식을 고르기 전, 카메라가 보고 있는 화면만 BE(cam_preview_*)로 흘려보낸다.

    카메라를 새로 열지 않고 상시 인식 루프가 이미 들고 있는 프레임을 그대로
    쓴다 — 그래서 인코딩·전송(느릴 수 있음)을 인식 루프와 같은 스레드에서
    동기로 하면 안 된다. tick()은 최신 프레임을 큐에 얹기만 하고(가득 차면
    오래된 걸 버림), 실제 JPEG 인코딩+전송은 별도 워커 스레드가 한다.
    tempId·회차 개념이 없고, reg_mode_start/calib_start 전후 조율은 BE가
    cam_preview_stop을 먼저 보내는 방식으로 책임진다 — AI는 켜고 끄기만 한다.
    """

    FRAME_INTERVAL_S = 1.0 / 12  # BE 계약 10~15fps 범위 내

    def __init__(self, link):
        self.link = link
        self.active = False
        self.last_queued_at = 0.0
        self._seq = 0
        self._queue = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def start(self):
        self.active = True
        self._seq = 0
        self.last_queued_at = 0.0
        self.link.send_event("cam_preview_state", {"phase": "READY"})

    def stop(self):
        if self.active:
            self.active = False
            self.link.send_event("cam_preview_state", {"phase": "STOPPED"})

    def tick(self, frame, now):
        """메인 루프에서 매 프레임 호출 — 인코딩 없이 큐에 얹기만 한다."""
        if not self.active or now - self.last_queued_at < self.FRAME_INTERVAL_S:
            return
        self.last_queued_at = now
        try:
            self._queue.get_nowait()  # 워커가 못 따라오면 오래된 프레임을 버린다
        except queue.Empty:
            pass
        self._queue.put_nowait(frame.copy())

    def _worker(self):
        while True:
            frame = self._queue.get()
            jpeg_b64 = encode_jpeg(frame)
            if jpeg_b64 is None:
                continue
            self._seq += 1
            self.link.send_event("cam_preview_frame", {
                "seq": self._seq, "jpegB64": jpeg_b64,
            })


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
        """레거시(X/names)와 NPZ v2(sequences 등)를 모두 이 이름으로 라벨링해 읽는다."""
        return read_templates(payload, name=fallback_name)

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
        parts = []
        for gid, ref in refs.items():
            path = self.cache_dir / f"g{gid}.npz"
            if not path.exists():
                continue
            try:
                parts.append(self._read_template(path.read_bytes(), str(ref.get("name", gid))))
            except Exception as exc:
                print(f"[제스처] 템플릿 g{gid} 무시: {exc}")
        if parts:
            combined = {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}
            self.combined_path.write_bytes(encode_template_bytes(combined))
        else:
            self.combined_path.unlink(missing_ok=True)


def sync_gesture_store(link, cache, refs, start_recognition=True):
    """BE 참조 목록에 캐시를 맞추고 최신 CustomGestureStore를 반환한다.

    동기화·저장소 구성이 끝나기 전까지 link.gesture_ready를 내려 두어, 실행
    파이프라인이 절반만 갱신된 저장소로 인식을 시작하지 않게 막는다.
    """
    link.gesture_ready = False
    cache.sync(link, refs)
    store = CustomGestureStore(cache.combined_path)
    if start_recognition:
        link.gesture_ready = True
    return store


class GestureRegistration:
    """BE reg_mode_start에 대응하는 정적/동적 커스텀 제스처 촬영 상태기계."""

    DEFAULT_TAKES = 3
    DEFAULT_COUNTDOWN_S = 3.0
    DEFAULT_TAKE_S = 2.0
    STATIC_HOLD_S = 0.4
    MIN_STATIC_SAMPLES = 8
    MIN_STATIC_MOTION_FRAMES = 4  # 2손 정적: 회차당 평균낼 프레임이 너무 적으면 떨림이 안 지워진다
    FRAME_MARGIN = 0.02  # 정규화 좌표가 이만큼 넘게 [0,1]을 벗어나면 화면 밖으로 본다
    MAX_GAP_FRACTION = 0.3  # 회차 구간 대비 이 비율 넘게 손을 놓치면 거부
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"
    FRAME_INTERVAL_S = 0.10
    BUILTIN_OVERLAP = 0.20
    MIN_PALM_SIZE = 0.055
    MAX_SPREAD = 0.25
    COLLISION_DIST = 0.45

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
        self.sizes2 = []   # 양손일 때 두 번째 손(핸디드니스 정렬상 뒤쪽) 최소 크기 —
                           # 한쪽만 보면 다른 손이 너무 멀리 잡혀도 못 걸러낸다.
        self.builtin_hits = {}
        self.hand_counts = []
        self.take_frames = {}

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
        # STATIC은 BE 계약상 takeDurationSec을 안 보낸다 — FE/BE에는 "한 장 캡처"로
        # 보이지만, 흔들린 프레임 한 장이 그대로 정답으로 박제되지 않도록 AI
        # 내부적으로만 아주 짧게(STATIC_HOLD_S) 여러 프레임을 모아 학습 데이터로 쓴다.
        self.take_s = (
            self._positive_number(data, "takeDurationSec", self.DEFAULT_TAKE_S)
            if self.motion == self.DYNAMIC else self.STATIC_HOLD_S
        )
        self.take = 1
        self.phase = "COUNTDOWN"
        self.phase_at = time.monotonic() if now is None else now
        self.link.send_event("reg_started", {"tempId": self.temp_id})
        self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                           "phase": "COUNTDOWN"})
        hold_label = "촬영" if self.motion == self.DYNAMIC else "캡처 유지"
        print(f"[제스처 등록] 시작 tempId={self.temp_id} "
              f"({self.motion}, {self.takes}회, 카운트다운 {self.countdown_s:g}초, "
              f"{hold_label} {self.take_s:g}초)")

    def _emit_frame(self, frame, now, force=False):
        if not force and now - self.last_frame_at < self.FRAME_INTERVAL_S:
            return
        self.last_frame_at = now
        jpeg_b64 = encode_jpeg(frame)
        if jpeg_b64 is None:
            return
        self.seq += 1
        self.link.send_event("reg_frame", {
            "tempId": self.temp_id, "take": self.take, "seq": self.seq,
            "tsMs": int(now * 1000), "jpegB64": jpeg_b64,
        })

    @staticmethod
    def _hand_quality(landmarks):
        wrist, middle = landmarks[0], landmarks[9]
        dx, dy = middle[0] - wrist[0], middle[1] - wrist[1]
        return float(np.hypot(dx, dy)), float(np.arctan2(dy, dx))

    @classmethod
    def _hand_out_of_frame(cls, landmarks):
        lm = np.asarray(landmarks)
        return bool(np.any(lm < -cls.FRAME_MARGIN) or np.any(lm > 1 + cls.FRAME_MARGIN))

    @staticmethod
    def _as_hands(hands):
        if hands is None:
            return []
        return [hands] if isinstance(hands, dict) else list(hands)

    def _collect(self, hands, now):
        """현재 프레임의 손 관측을 기록한다. 크기 측정은 handedness로 정렬해 같은 손을 본다.

        hands는 MediaPipe가 그 프레임에 감지한 순서 그대로라 왼손/오른손이 프레임마다
        뒤바뀔 수 있다(ordered_landmarks도 이 이유로 감지 순서를 안 믿는다). 정렬 없이
        첫 번째 손만 보면 서로 다른 손을 오가며 측정해, 두 손 다 실제로는 안정적이어도
        크기가 인위적으로 흔들리는 것처럼 기록된다.
        """
        self.hand_counts.append(len(hands))
        self.take_frames.setdefault(self.take, []).append((now, hands))
        if not hands:
            return
        ordered = sorted(hands, key=lambda h: h.get("handedness") or "")
        primary = ordered[0]
        lm = primary["landmarks"]
        self.samples.append(normalize_landmarks(lm))
        size, _ = self._hand_quality(lm)
        self.sizes.append(size)
        if len(ordered) > 1:
            size2, _ = self._hand_quality(ordered[1]["landmarks"])
            self.sizes2.append(size2)
        label = primary.get("gesture")
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
            # 정적도 이제 take_s(STATIC_HOLD_S)만큼 짧게 여러 프레임을 모은다 —
            # 흔들린 프레임 한 장이 그대로 등록되는 걸 막기 위함. FE에는 여전히
            # 대표 프레임 하나면 충분하지만(BE가 마지막 프레임을 쓴다), 내부 학습
            # 데이터는 이 구간에서 모인 여러 장을 그대로 쓴다.
            self._emit_frame(frame, now)
            self._collect(hands, now)
            if now - self.phase_at >= self.take_s:
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

    def finish_for(self, temp_id):
        """temp_id가 현재 진행 중인 등록과 같을 때만 종료한다 (경합 방지)."""
        if temp_id and temp_id == self.temp_id:
            self.finish()

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
            hand_count = (2 if self.hand_counts and sum(n >= 2 for n in self.hand_counts)
                          >= len(self.hand_counts) * 0.7 else 1)
            self._validate_and_upload(hand_count)
            self.link.send_event("reg_captured", {"tempId": temp_id, "hands": hand_count})
            print("[제스처 등록] 품질 검사 통과. 기능 지정 대기")
        except (OSError, TimeoutError, RuntimeError) as exc:
            # put_gesture_npz(서버 업로드) 실패 — URLError·TimeoutError·(runtime.json
            # 없음 등) RuntimeError는 검증 실패가 아니라 인프라 문제라 str(exc)가
            # "<urlopen error offline>" 같은 개발자용 문구다. 사용자에게는 원인
            # 대신 조치를 안내한다.
            print(f"[제스처 등록] 업로드 실패: {exc}")
            self.link.send_event("reg_rejected", {
                "tempId": temp_id,
                "reason": "서버에 업로드하지 못했습니다. 네트워크 연결을 확인하고 다시 시도해주세요",
            })
        except ValueError as exc:
            payload = {"tempId": temp_id, "reason": str(exc)}
            if isinstance(exc, GestureRegistrationRejected) and exc.similar_to:
                payload["similarTo"] = exc.similar_to
                payload["similarity"] = exc.similarity
            self.link.send_event("reg_rejected", payload)
            print(f"[제스처 등록] 거부: {exc}")
        finally:
            self.reset()

    def _validate_and_upload(self, hand_count):
        if not self.samples:
            raise ValueError("손이 감지되지 않았습니다. 카메라에 손을 보여주세요")
        # 손 최소 크기(카메라와의 거리)는 두 번째 손도 같이 본다 — 한쪽만 보면 다른
        # 손이 너무 멀리/작게 잡혀도 못 걸러낸다. 크기 변화(MAX_SIZE_CV)는 뺐다 —
        # 저장 형식(normalize_landmarks·encode_sequence) 둘 다 스케일을 지우고
        # 저장하므로, 등록 중 카메라와의 거리가 바뀌어도 최종 결과엔 영향이 없다.
        if min(self.sizes) < self.MIN_PALM_SIZE:
            raise ValueError("손이 너무 작게 감지되었습니다. 손목까지 카메라에 보여주세요")
        if self.sizes2 and min(self.sizes2) < self.MIN_PALM_SIZE:
            raise ValueError("손이 너무 작게 감지되었습니다. 손목까지 카메라에 보여주세요")
        # 손이 화면 밖으로 나가면(카메라에 너무 가까이 대는 등) MediaPipe가 보이지
        # 않는 부분의 랜드마크를 정규화 좌표 [0,1] 밖으로 추정해 내보낸다 — 크기로는
        # 못 잡는다(화면 중앙에서 크게 잡히는 것 자체는 문제가 아니므로). 좌표
        # 범위를 직접 보고 잘렸는지 확인한다.
        for frames in self.take_frames.values():
            for _, hands in frames:
                for h in hands:
                    if self._hand_out_of_frame(h["landmarks"]):
                        raise ValueError("손이 화면 밖으로 벗어났습니다. 카메라에서 조금 떨어져 주세요")
        # "손모양이 실제로 안정적이었는지"는 1손 정적은 _upload_static의 MAX_SPREAD가,
        # 2손 정적은 _upload_motion의 회차별 spread 검사가 담당한다 — 둘 다 저장에
        # 실제로 쓰이는 정규화된 손모양 전체를 비교하므로, 여기 손목 각도 하나만 보던
        # 거친 사전 검사보다 정확하다(손가락 모양 변화까지 잡아내면서, 저장 시 지워지는
        # 손목 회전만으로는 안 걸리게 한다).
        # 정적 한 손만 기존 42차원 kNN 경로를 쓴다. 양손이거나 동적이면 NPZ v2
        # 시퀀스 경로로 간다 — 두 경로는 저장 형식과 충돌검사 대상이 다르다.
        if hand_count == 1 and self.motion == self.STATIC:
            self._upload_static()
        else:
            self._upload_motion(hand_count)

    def _upload_static(self):
        if len(self.samples) < self.MIN_STATIC_SAMPLES:
            raise ValueError("손 랜드마크가 충분히 수집되지 않았습니다")
        feats = np.asarray(self.samples, dtype=np.float32)
        spread = float(weighted_distance(feats - feats.mean(axis=0)).mean())
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
        if near and dist < self.COLLISION_DIST:
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

    # 동적 등록이 겹쳐선 안 되는 내장 동적 감지기 목록 — (표시 이름, 실행 때와 같은
    # 설정으로 새 인스턴스를 만드는 함수, 손 랜드마크에서 그 감지기가 원하는 입력을
    # 뽑는 함수). 서비스가 기본 제공하는 9종(정적 7 + 스와이프 좌/우)만 "내장"으로
    # 안내한다 — 스크롤·핀치볼륨은 아직 사용자에게 노출된 적 없는(enabled=False)
    # 기능이라 지금 "내장 스크롤과 비슷합니다"라고 하면 사용자가 이해할 수 없는
    # 사유가 된다. 그 기능들이 실제로 켜질 때, 이 목록에 다시 추가한다.
    BUILTIN_DYNAMIC_DETECTORS = (
        ("스와이프", lambda: SwipeDetector(**SCREEN_SWIPE_CONFIG), lambda lm: tuple(lm[9])),
    )

    def _builtin_dynamic_collision(self):
        """동적 등록이 내장 동적 감지기와 겹치는지, 실제 감지기로 그대로 재생해 확인한다.

        실행 때와 같은 감지기·같은 설정을 써서 "이 촬영이 실제로 라이브였다면
        내장 동작이 발동했을까"를 그대로 재현한다 — 근사치 규칙을 따로 만드는
        것보다 실제 판정 로직과 항상 일치하고, 목록에 등록만 해두면 다른 내장
        동적 감지기도 자동으로 같이 확인된다. 겹치면 이름을, 안 겹치면 None을
        돌려준다.

        1손·2손 모두 손마다(handedness 기준, 감지 순서는 프레임마다 바뀔 수
        있어 안 믿는다) 독립적으로 재생한다 — 2손 동작이라도 그중 한 손만의
        움직임이 내장 동작과 겹치면, 실행 중 그 손 하나만 raw 판정으로 새는
        순간(2손 커스텀 인식이 그 프레임만 실패하는 경우) 내장 동작이 조용히
        발동할 수 있기 때문이다.
        """
        for name, make_detector, extract in self.BUILTIN_DYNAMIC_DETECTORS:
            for take in range(1, self.takes + 1):
                detectors = {}
                for t, hands in self.take_frames.get(take, []):
                    seen = set()
                    for h in hands:
                        side = h.get("handedness") or "?"
                        seen.add(side)
                        detector = detectors.setdefault(side, make_detector())
                        if detector.update(extract(h["landmarks"]), t):
                            return name
                    for side, detector in detectors.items():
                        if side not in seen:
                            detector.update(None, t)
        return None

    def _upload_motion(self, hand_count):
        """양손 정적 또는 (한손/양손) 동적 — 회차별 궤적을 NPZ v2로 올린다.

        정적은 궤적이 아니라 자세 하나다. 0.4초간 모은 여러 프레임을 그대로
        궤적처럼 저장하면, 실시간 인식은 항상 "완벽히 정지한" 값(현재 프레임
        1장을 복제)과 비교하므로 등록 당시의 자연스러운 손떨림이 매 프레임
        오차로 그대로 남아 — 실사용 때 완벽히 일치하는 자세조차 페널티를
        받는다. 그래서 모은 프레임을 평균해 떨림을 지운 대표 자세 하나로
        만든 뒤, 인식 때와 똑같은 형태(그 자세를 2점으로 복제)로 저장한다.
        """
        sequences = []
        for take in range(1, self.takes + 1):
            frames = [(t, ordered_landmarks(hands)) for t, hands in self.take_frames.get(take, [])]
            frames = [(t, pts) for t, pts in frames if pts is not None]
            if len(frames) < 2:
                raise ValueError(f"{take}회차 촬영이 충분하지 않습니다. 손을 계속 화면에 보여주세요")
            # 2손 정적은 모은 프레임을 평균내 떨림을 지우는 방식이라(아래), 딱 2장으론
            # 평균의 의미가 없다 — encode_sequence가 요구하는 수학적 최소(2)와는 별개로,
            # 노이즈를 실제로 줄이려면 이만큼은 있어야 한다.
            if self.motion == self.STATIC and len(frames) < self.MIN_STATIC_MOTION_FRAMES:
                raise ValueError(f"{take}회차 촬영이 충분하지 않습니다. 손을 계속 화면에 보여주세요")
            # ordered_landmarks는 프레임별로 유효하면 통과시키므로(1손·2손 각각
            # 정상 모양), 회차 중간에 손 개수가 바뀌어도(가려짐 등) 여기까진
            # 안 걸러진다 — 그대로 두면 다음 encode_sequence가 raw numpy 오류로
            # 죽어 사용자에게 알아볼 수 없는 문구가 그대로 노출된다.
            if len({pts.shape[0] for _, pts in frames}) > 1:
                raise ValueError(f"{take}회차 촬영 중 손 개수가 바뀌었습니다. 손 개수를 유지해주세요")
            # 중간을 오래 놓치면 encode_sequence가 그 구간을 직선으로 채워
            # 실제로 없었던 움직임을 있었던 것처럼 만들어낸다 — 앞뒤 몇 프레임만
            # 살아남아도 조용히 통과하므로 최대 공백을 명시적으로 거부한다.
            gaps = [b - a for (a, _), (b, _) in zip(frames, frames[1:])]
            if gaps and max(gaps) > self.take_s * self.MAX_GAP_FRACTION:
                raise ValueError(f"{take}회차 촬영 중 손을 오래 놓쳤습니다. 손을 계속 화면에 보여주세요")
            if self.motion == self.STATIC:
                avg_pts = np.mean([pts for _, pts in frames], axis=0)
                seq = encode_sequence([0, 1], [avg_pts, avg_pts])
                # 손목 각도 하나가 아니라 정규화된 손모양 전체가 평균 자세에서 얼마나
                # 벗어났는지를 본다 — 1손 정적의 MAX_SPREAD와 같은 기준·같은 개념.
                # 손 전체가 살짝 돌아간 것(저장 시 지워짐)은 안 걸리고, 손가락이
                # 실제로 흔들린 경우만 잡힌다.
                spread = max(
                    distance(encode_sequence([0, 1], [pts, pts]), seq, hand_count)
                    for _, pts in frames
                )
                if spread > self.MAX_SPREAD:
                    raise ValueError(f"{take}회차 촬영 중 손모양이 흔들렸습니다. 자세를 고정해 다시 촬영하세요")
            else:
                seq = encode_sequence([t for t, _ in frames], [pts for _, pts in frames])
                movement = distance(seq, np.repeat(seq[:1], FRAMES, axis=0), hand_count)
                if movement < PREFIX_MIN_MOTION:
                    raise ValueError(f"{take}회차에서 움직임이 충분하지 않습니다. 동작을 끝까지 반복하세요")
            sequences.append(seq)
        # 내장 동적 감지기(스와이프 등)는 NPZ 템플릿이 아니라 별도 상태기계라
        # nearest_sequence 충돌검사 대상에 없다. 그대로 두면 내장 동작과 똑같이
        # 움직이는 동작을 커스텀으로 등록해도 경고 없이 통과하는데, 실행 시에는
        # 커스텀 동작 추적이 우선순위를 가져가(앞서 고친 우선순위 가드) 내장 동작이
        # 조용히 가려져 버린다 — 등록 시점에 미리 알려주는 게 낫다. 2손 동작도
        # 검사 대상이다 — 한 손만의 움직임이 내장과 겹쳐도, 실행 중 2손 인식이
        # 그 프레임만 실패하면 그 손 하나만으로 내장 동작이 새어나갈 수 있다.
        if self.motion == self.DYNAMIC:
            collided = self._builtin_dynamic_collision()
            if collided:
                # 1손 정적의 내장 겹침 문구와 형태를 맞춘다("내장 제스처 'X'와
                # 너무 유사합니다") — 정적은 프레임 비율(N/M)이 자연스럽게
                # 붙지만, 동적은 감지기 재생 결과(예/아니오)라 그 부분만 없다.
                raise GestureRegistrationRejected(
                    f"내장 제스처 '{collided}'와 너무 유사합니다", similar_to=collided
                )
        dist, near = min(
            (self.custom_store.nearest_sequence(seq, self.motion, hand_count) for seq in sequences),
            key=lambda item: item[0],
        )
        if near and dist < self.COLLISION_DIST:
            similarity = round(float(np.exp(-dist)), 4)
            raise GestureRegistrationRejected(
                f"기존 제스처 '{near}'와 너무 유사합니다",
                similar_to=near,
                similarity=similarity,
            )
        data = dict(
            X=np.empty((0, 42), np.float32), names=np.array([], dtype="U1"),
            sequences=np.stack(sequences), sequence_names=np.array(["__pending__"] * len(sequences)),
            motions=np.array([self.motion] * len(sequences)),
            hand_counts=np.array([hand_count] * len(sequences), dtype=np.int32),
            durations=np.array([self.take_s] * len(sequences), dtype=np.float32),
        )
        self.link.put_gesture_npz(self.temp_id, encode_template_bytes(data))
