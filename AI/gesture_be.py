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
from pathlib import Path

import cv2
import numpy as np
from gesture_diagnostics import save_registration_diagnostic

from hands import (REFERENCE_PALM_SIZE, SCREEN_SWIPE_CONFIG,
                   SwipeDetector, normalize_landmarks, pose_distances, scale_by_hand_size,
                   weighted_distance)
from custom_motion import (
    CustomGestureStore, FRAMES, MATCH_DISTANCE, PREFIX_MIN_MOTION, distance, encode_sequence,
    encode_pose_sequence, encode_world_sequence, normalize_arm_pose,
    ordered_landmarks, ordered_world_landmarks, read_templates,
    trim_motion_frames, template_bytes as encode_template_bytes,
    matching_distance, motion_matching_distance, motion_direction_8, TRACKING_GRACE_S,
)


class GestureRegistrationRejected(ValueError):
    """FE에 유사 제스처 정보를 함께 알려야 하는 등록 거부."""

    def __init__(self, reason, similar_to=None, similarity=None):
        super().__init__(reason)
        self.similar_to = similar_to
        self.similarity = similarity


# 내장 정적 제스처 충돌 시 보여줄 유사도의 기준 손모양들. 전부 실제로 촬영된
# 사진(testdata/builtin_finger_poses.json)의 21개 랜드마크(x,y) — 파일을
# 런타임에 읽지 않고 값을 그대로 박아 배포 환경 의존을 없앤다.
# 분류기는 펴짐/굽힘 사이에 여유 구간을 둬서(gesture_pose.py) 손가락을 살짝만
# 굽혀도 여전히 같은 라벨로 분류하므로, 그 프레임 비율만 보면 항상 100%로
# 뜬다 — 커스텀 중복 검사와 같은 방식(정규화된 손모양 사이 거리 → exp(-거리))
# 으로 바꿔야 실제로 얼마나 비슷한지가 드러난다. ILoveYou는 실제 촬영 데이터가
# 없어 기준이 없고, 그 경우는 기존 방식(분류 일치율)으로 자동 대체된다.
BUILTIN_POSE_REFERENCES = {
    "Victory": np.array([
        [0.4705, 0.7335], [0.4202, 0.6730], [0.4055, 0.5940], [0.4559, 0.5408],
        [0.5156, 0.5013], [0.4349, 0.4894], [0.4112, 0.3923], [0.3966, 0.3366],
        [0.3941, 0.2859], [0.4923, 0.4955], [0.4975, 0.3753], [0.4984, 0.3128],
        [0.5074, 0.2608], [0.5399, 0.5270], [0.5548, 0.4556], [0.5159, 0.5223],
        [0.4985, 0.5722], [0.5818, 0.5744], [0.5669, 0.5450], [0.5310, 0.5933],
        [0.5187, 0.6311],
    ], dtype=np.float32),
    "Closed_Fist": np.array([
        [0.5224, 0.6966], [0.4363, 0.6581], [0.3507, 0.5742], [0.3264, 0.4714],
        [0.3830, 0.4130], [0.3899, 0.4472], [0.3774, 0.3719], [0.3895, 0.4644],
        [0.3988, 0.4912], [0.4576, 0.4480], [0.4529, 0.3862], [0.4516, 0.5022],
        [0.4511, 0.4944], [0.5295, 0.4555], [0.5275, 0.4055], [0.5178, 0.5086],
        [0.5209, 0.5056], [0.6003, 0.4686], [0.5943, 0.4310], [0.5819, 0.4995],
        [0.5812, 0.5091],
    ], dtype=np.float32),
    "Open_Palm": np.array([
        [0.4739, 0.7525], [0.3975, 0.6914], [0.3452, 0.6025], [0.3093, 0.5313],
        [0.2569, 0.4957], [0.4346, 0.4753], [0.4181, 0.3762], [0.4166, 0.3152],
        [0.4216, 0.2630], [0.5063, 0.4730], [0.5183, 0.3604], [0.5296, 0.2949],
        [0.5388, 0.2420], [0.5673, 0.5015], [0.6037, 0.4024], [0.6274, 0.3460],
        [0.6468, 0.2965], [0.6174, 0.5508], [0.6697, 0.4831], [0.7021, 0.4412],
        [0.7291, 0.3999],
    ], dtype=np.float32),
    "Pointing_Up": np.array([
        [0.4819, 0.7085], [0.4344, 0.6512], [0.4130, 0.5725], [0.4602, 0.5170],
        [0.5220, 0.4885], [0.4574, 0.4750], [0.4547, 0.3706], [0.4558, 0.3104],
        [0.4651, 0.2584], [0.5125, 0.4976], [0.5280, 0.4332], [0.4949, 0.5053],
        [0.4898, 0.5378], [0.5625, 0.5308], [0.5664, 0.4983], [0.5198, 0.5684],
        [0.5161, 0.5911], [0.6072, 0.5704], [0.6041, 0.5380], [0.5640, 0.5846],
        [0.5600, 0.6030],
    ], dtype=np.float32),
    "Thumb_Up": np.array([
        [0.3840, 0.6687], [0.4084, 0.5315], [0.4623, 0.4373], [0.5263, 0.3639],
        [0.5480, 0.2991], [0.5840, 0.5032], [0.6182, 0.5044], [0.5746, 0.5236],
        [0.5394, 0.5366], [0.6080, 0.5792], [0.6105, 0.5719], [0.5683, 0.5760],
        [0.5403, 0.5885], [0.6027, 0.6492], [0.5992, 0.6247], [0.5623, 0.6280],
        [0.5300, 0.6383], [0.5895, 0.7108], [0.5888, 0.6841], [0.5539, 0.6773],
        [0.5236, 0.6805],
    ], dtype=np.float32),
    "Thumb_Down": np.array([
        [0.4195, 0.4106], [0.4488, 0.5077], [0.4940, 0.5977], [0.5474, 0.6678],
        [0.5457, 0.7230], [0.5996, 0.5505], [0.6554, 0.5667], [0.5792, 0.5402],
        [0.5434, 0.5274], [0.6156, 0.4920], [0.6722, 0.5039], [0.5779, 0.4854],
        [0.5542, 0.4851], [0.6173, 0.4344], [0.6714, 0.4468], [0.5895, 0.4367],
        [0.5648, 0.4360], [0.6129, 0.3765], [0.6554, 0.3820], [0.5982, 0.3868],
        [0.5766, 0.3872],
    ], dtype=np.float32),
}

# 프로토콜 식별자(similarTo)는 그대로 유지하고 사용자 문구에서만 읽기 쉬운
# 이름을 사용한다.
BUILTIN_GESTURE_DISPLAY_NAMES = {
    "Victory": "브이",
    "Open_Palm": "손바닥 펴기",
    "Closed_Fist": "주먹 쥐기",
    "Pointing_Up": "검지 올리기",
    "Thumb_Up": "엄지 올리기",
    "Thumb_Down": "엄지 내리기",
    "ILoveYou": "아이 러브 유",
}


def _builtin_pose_similarity(label, feats):
    """분류 일치율이 아니라 실제 손모양 거리 기반 유사도. 기준 손모양이 없는
    라벨은 None을 돌려줘 호출측이 기존 방식(분류 일치율)으로 대신하게 한다.

    pose_distances처럼 반대 손(좌우 반전)으로 찍었을 가능성도 같이 본다 —
    안 그러면 같은 브이를 반대 손으로 찍었을 때 부당하게 낮은 유사도가 나온다.
    """
    reference = BUILTIN_POSE_REFERENCES.get(label)
    if reference is None:
        return None
    ref_feature = normalize_landmarks(reference)
    mean_feature = np.asarray(feats, dtype=np.float32).mean(axis=0)
    dist = float(pose_distances(ref_feature[None, :], mean_feature)[0])
    return round(float(np.exp(-dist)), 4)


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
        self._generation = 0
        self._preview_error = False
        self._queue = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def start(self):
        self._generation += 1
        self._preview_error = False
        self.active = True
        self._seq = 0
        self.last_queued_at = 0.0
        self.link.send_event("cam_preview_state", {"phase": "READY"})

    def stop(self):
        if self.active:
            self.active = False
            self._generation += 1
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
        # reg_frame과 동일한 단조 시계 기준(ms). 인코딩 대기 전 시각을 보존한다.
        self._queue.put_nowait((self._generation, int(now * 1000), frame.copy()))

    def _worker(self):
        while True:
            generation, ts_ms, frame = self._queue.get()
            if not self.active or generation != self._generation:
                continue
            try:
                jpeg_b64 = encode_jpeg(frame)
                if jpeg_b64 is None:
                    raise ValueError('미리보기 JPEG 변환 실패')
                if not self.active or generation != self._generation:
                    continue
                if self._preview_error:
                    self.link.send_event('cam_preview_state', {'phase': 'READY'})
                self._seq += 1
                sent = self.link.send_event("cam_preview_frame", {
                    "seq": self._seq, "jpegB64": jpeg_b64, "tsMs": ts_ms,
                })
                if sent is False:
                    raise RuntimeError('미리보기 전송 실패')
                self._preview_error = False
            except Exception as exc:
                if not self.active or generation != self._generation:
                    continue
                if not self._preview_error:
                    print(f'[카메라 미리보기 오류] {exc}')
                    try:
                        self.link.send_event('cam_preview_state', {
                            'phase': 'ERROR',
                            'message': '카메라 미리보기 전송에 실패했습니다. 연결을 확인하며 다시 시도합니다.',
                        })
                    except Exception:
                        pass
                self._preview_error = True


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
    OUT_OF_FRAME_HOLD_S = 0.20
    OUT_OF_FRAME_RATIO = 0.20
    OUT_OF_FRAME_MAX_GAP_S = 0.25  # 긴 관측 공백을 연속 이탈로 추정하지 않는다
    MAX_GAP_FRACTION = 0.3  # 회차 구간 대비 이 비율 넘게 손을 놓치면 거부
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"
    FRAME_INTERVAL_S = 0.10
    BUILTIN_OVERLAP = 0.20
    MIN_PALM_SIZE = 0.055
    MAX_SPREAD = 0.25
    STATIC_SPREAD_PERCENTILE = 90
    STATIC_SPREAD_MAX_RATIO = 0.20
    # 1손 촬영에서 MediaPipe가 화면 가장자리나 얼굴 일부를 잠깐 두 번째 손으로
    # 잡는 경우가 있다. 한 회차의 절반 미만인 추가 검출은 주로 보이던 손만
    # 추적하고, 절반 이상 계속될 때만 실제 손 개수 변경으로 본다.
    ONE_HAND_EXTRA_MAX_RATIO = 0.50
    COLLISION_DIST = 0.45
    # 동적 템플릿 실측: 같은 '한 손 비틀기' 3회 내 거리는 최대 0.319,
    # 서로 다른 저장 제스처의 최근접 거리는 0.482였다. 정적과 같은 0.45를
    # 쓰면 손 펴기/모으기(0.38~0.44)까지 비틀기로 오판하므로 분리한다.
    DYNAMIC_COLLISION_DIST = 0.35
    # 회차 간 허용 오차. 정적은 자세 하나의 손끝 가중 거리라 기존 안전 여유를
    # 유지한다. 동적은 실측 반복 촬영에서 속도·시작 시점 차이만으로도 0.15~0.35가
    # 나왔으므로 실행 매칭값의 60%(0.132)를 그대로 쓰면 정상 촬영까지 대부분
    # 거부한다. 세 회차 템플릿을 모두 저장하는 점을 감안해 0.35까지 허용하되,
    # 모든 회차 쌍을 비교해 한 회차가 실제로 다른 동작인 경우는 계속 거부한다.
    TAKE_STATIC_DISTANCE = 0.35 * 0.6  # 42차원 kNN의 손끝 가중 L2 단위
    TAKE_SEQUENCE_DISTANCE = 0.35

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
        self.builtin_uncertain = 0
        self.hand_counts = []
        self.take_frames = {}
        self.take_pose_frames = {}
        self.comparison_diagnostics = []

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

    def _validate_frame_bounds(self):
        """회차별 감지 프레임을 검사한다. 한 프레임 튐은 거절하지 않는다."""
        for take, frames in self.take_frames.items():
            observed = outside = 0
            run_start = previous = None
            longest = 0.0
            for t, hands in frames:
                if not hands:
                    run_start = previous = None
                    continue
                observed += 1
                clipped = any(self._hand_out_of_frame(h["landmarks"]) for h in hands)
                if clipped:
                    outside += 1
                    if run_start is None or previous is None or not 0 < t - previous <= self.OUT_OF_FRAME_MAX_GAP_S:
                        run_start = t
                    longest = max(longest, t - run_start)
                else:
                    run_start = None
                previous = t
            ratio = outside / observed if observed else 0.0
            if outside >= 2 and (longest + 1e-9 >= self.OUT_OF_FRAME_HOLD_S
                                 or ratio >= self.OUT_OF_FRAME_RATIO):
                print(f"[제스처 화면 이탈] tempId={self.temp_id} take={take} frames={outside}/{observed} ratio={ratio:.3f} longest={longest:.3f}s")
                raise ValueError(f"{take}회차 촬영 중 손이 화면 밖으로 벗어났습니다. 손목과 손끝이 화면 안에 들어오도록 해주세요")

    @staticmethod
    def _as_hands(hands):
        if hands is None:
            return []
        return [hands] if isinstance(hands, dict) else list(hands)

    def _collect(self, hands, now, pose_landmarks=None):
        """현재 프레임의 손 관측을 기록한다. 크기 측정은 handedness로 정렬해 같은 손을 본다.

        hands는 MediaPipe가 그 프레임에 감지한 순서 그대로라 왼손/오른손이 프레임마다
        뒤바뀔 수 있다(ordered_landmarks도 이 이유로 감지 순서를 안 믿는다). 정렬 없이
        첫 번째 손만 보면 서로 다른 손을 오가며 측정해, 두 손 다 실제로는 안정적이어도
        크기가 인위적으로 흔들리는 것처럼 기록된다.
        """
        self.hand_counts.append(len(hands))
        self.take_frames.setdefault(self.take, []).append((now, hands))
        self.take_pose_frames.setdefault(self.take, []).append(
            (now, normalize_arm_pose(pose_landmarks)))
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
        if primary.get('pose_verification') == 'unverified_finger_pose':
            self.builtin_uncertain += 1
        if label and label != "None":
            self.builtin_hits[label] = self.builtin_hits.get(label, 0) + 1

    def tick(self, frame, hands, now=None, pose_landmarks=None):
        if not self.active:
            return None
        now = time.monotonic() if now is None else now
        hands = self._as_hands(hands)
        # The registration screen remains a live camera preview during the
        # 3-2-1 countdown.  Only RECORDING frames become training samples, but
        # both phases must stream reg_frame events so the UI never freezes on
        # the last preview image between takes.
        if self.phase in ("COUNTDOWN", "RECORDING"):
            self._emit_frame(frame, now)
        elapsed = now - self.phase_at
        if self.phase == "COUNTDOWN":
            if elapsed < self.countdown_s:
                return {"phase": self.phase, "take": self.take,
                        "remaining": max(0.0, self.countdown_s - elapsed)}
            self.phase = "RECORDING"
            self.phase_at = now
            if self.motion == self.DYNAMIC:
                self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                                   "phase": "RECORDING"})
        if self.phase == "RECORDING":
            # 정적도 이제 take_s(STATIC_HOLD_S)만큼 짧게 여러 프레임을 모은다 —
            # 흔들린 프레임 한 장이 그대로 등록되는 걸 막기 위함. FE에는 여전히
            # 대표 프레임 하나면 충분하지만(BE가 마지막 프레임을 쓴다), 내부 학습
            # 데이터는 이 구간에서 모인 여러 장을 그대로 쓴다.
            self._collect(hands, now, pose_landmarks)
            if now - self.phase_at >= self.take_s:
                self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                                   "phase": "DONE"})
                if self.take < self.takes:
                    self.take += 1
                    self.phase = "COUNTDOWN"
                    self.phase_at = now
                    self.link.send_event("reg_take", {"tempId": self.temp_id, "take": self.take,
                                                       "phase": "COUNTDOWN"})
                else:
                    self.phase = "WAIT_FINISH"
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
        outcome, diagnostic_reason = 'error', ''
        try:
            hand_count = (2 if self.motion == self.STATIC and not self.samples
                          else self._infer_hand_count())
            self._validate_and_upload(hand_count)
            self.link.send_event("reg_captured", {"tempId": temp_id, "hands": hand_count})
            print("[제스처 등록] 품질 검사 통과. 기능 지정 대기")
            outcome = 'captured'
        except (OSError, TimeoutError, RuntimeError) as exc:
            outcome, diagnostic_reason = 'upload_failed', str(exc)
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
            outcome, diagnostic_reason = 'rejected', str(exc)
            payload = {"tempId": temp_id, "reason": str(exc)}
            if isinstance(exc, GestureRegistrationRejected) and exc.similar_to:
                payload["similarTo"] = exc.similar_to
                payload["similarity"] = exc.similarity
            self.link.send_event("reg_rejected", payload)
            print(f"[제스처 등록] 거부: {exc}")
        finally:
            try:
                path = save_registration_diagnostic(self, outcome, diagnostic_reason)
                if path:
                    print(f"[제스처 진단 저장] {path}")
            except Exception as exc:
                print(f"[제스처 진단 저장 실패] {exc}")
            self.reset()

    def _validate_and_upload(self, hand_count):
        if not self.samples:
            if self.motion == self.STATIC and self._upload_pose_only_static():
                return
            raise ValueError("손이 감지되지 않았습니다. 카메라에 손을 보여주세요")
        # 순간 좌표 튐 대신 회차별 지속 시간/빈도로 화면 이탈을 판정한다.
        self._validate_frame_bounds()
        # 기도처럼 두 손을 계속 맞댄 정적 자세는 MediaPipe가 어떤 회차는 한 손,
        # 어떤 회차는 두 손으로 셀 수 있다. 명확한 두 손 회차가 기존 템플릿과
        # 아주 가깝다면 그 증거로 중복을 확정하고, 아니면 정확한 재촬영 사유를 준다.
        if self.motion == self.STATIC:
            partial = self._partial_two_hand_static_collision()
            if partial is not None:
                name, score, one_hand_takes, two_hand_takes = partial
                if name is not None:
                    raise GestureRegistrationRejected(
                        f"'{name}'와 너무 유사합니다",
                        similar_to=name,
                        similarity=round(float(np.exp(-score)), 4),
                    )
                one_text = "·".join(map(str, one_hand_takes))
                two_text = "·".join(map(str, two_hand_takes))
                raise ValueError(
                    f"{one_text}회차는 한 손, {two_text}회차는 두 손으로 감지되어 "
                    "두 손을 맞댄 자세의 손 개수를 안정적으로 확인하지 못했습니다. "
                    "손바닥 사이를 조금 벌려 두 손의 윤곽이 모두 보이게 다시 촬영해주세요"
                )
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

    def _upload_pose_only_static(self):
        """Register a static arm pose when overlapping hands cannot be detected."""
        sequences = []
        for take in range(1, self.takes + 1):
            poses = [pose for _, pose in self.take_pose_frames.get(take, [])
                     if pose is not None]
            sequence = encode_pose_sequence(poses) if len(poses) >= 2 else None
            if sequence is None:
                return False
            sequences.append(sequence)
        self._validate_take_consistency(
            sequences,
            lambda a, b: float(np.sqrt(np.mean(np.square(a - b)))),
            0.28,
        )
        matches = []
        for sequence in sequences:
            best = (float("inf"), None)
            for index, name in enumerate(self.custom_store.data["sequence_names"]):
                if not bool(self.custom_store.data["pose_valid"][index]):
                    continue
                score = float(np.sqrt(np.mean(np.square(
                    sequence - self.custom_store.data["pose_sequences"][index]))))
                if score < best[0]:
                    best = score, str(name)
            matches.append(best if best[0] < 0.28 else (float("inf"), None))
        self._validate_custom_collision_votes(matches)
        count = len(sequences)
        data = dict(
            X=np.empty((0, 42), np.float32), names=np.array([], dtype="U1"),
            sequences=np.zeros((count, FRAMES, 2, 21, 2), np.float32),
            sequence_names=np.array(["__pending__"] * count),
            motions=np.array([self.STATIC] * count),
            hand_counts=np.array([2] * count, dtype=np.int32),
            durations=np.array([self.take_s] * count, dtype=np.float32),
            world_sequences=np.zeros((count, FRAMES, 2, 21, 3), np.float32),
            world_valid=np.zeros(count, dtype=bool),
            pose_sequences=np.stack(sequences),
            pose_valid=np.ones(count, dtype=bool),
        )
        self.link.put_gesture_npz(self.temp_id, encode_template_bytes(data))
        return True

    def _validate_hand_size(self, hand_count):
        """모든 등록 거부 검사를 통과한 뒤 마지막으로 손 크기를 검사한다."""
        # 저장에 사용하는 동일한 추적 손만 측정한다. 한 손 동작에서 배경의 작은
        # 오검출 손이 잠깐 잡혀도 크기 판정을 오염시키지 않는다.
        if hand_count == 1:
            measured_sizes = [self._hand_quality(observed["landmarks"])[0]
                              for take in range(1, self.takes + 1)
                              for _, observed in self._one_hand_take_observations(take)]
        else:
            measured_sizes = [self._hand_quality(hand["landmarks"])[0]
                              for frames in self.take_frames.values()
                              for _, hands in frames if len(hands) == 2
                              for hand in hands]
        # 원본 회차가 없는 단위 테스트와 이전 호출 경로의 호환성을 유지한다.
        if not measured_sizes:
            measured_sizes = list(self.sizes)
            if hand_count == 2:
                measured_sizes.extend(self.sizes2)
        if not measured_sizes or np.percentile(measured_sizes, 10) < self.MIN_PALM_SIZE:
            raise ValueError("손이 너무 작게 감지되었습니다. 카메라에 조금 더 가까이 손목까지 보여주세요")

    def _partial_two_hand_static_collision(self):
        """회차별 손 수가 1손/2손으로 완전히 갈린 접촉 자세를 처리한다."""
        one_hand_takes = []
        two_hand_takes = []
        for take in range(1, self.takes + 1):
            raw = self.take_frames.get(take, [])
            valid = [(t, ordered_landmarks(hands)) for t, hands in raw]
            valid = [(t, points) for t, points in valid if points is not None]
            if valid and all(len(points) == 1 for _, points in valid):
                one_hand_takes.append(take)
            elif valid and all(len(points) == 2 for _, points in valid):
                two_hand_takes.append((take, valid))
        if not one_hand_takes or not two_hand_takes:
            return None

        best = (float("inf"), None)
        for take, frames in two_hand_takes:
            average = np.mean([points for _, points in frames], axis=0)
            sequence = encode_sequence([0, 1], [average, average])
            candidates = self.custom_store.sequence_comparisons(
                sequence, self.STATIC, 2,
                world_sequence=self._two_hand_world_sequence(take, static=True))
            if candidates and candidates[0]["score"] < best[0]:
                best = (float(candidates[0]["score"]), candidates[0]["name"])
        # 한 회차 증거만 쓰는 예외 경로이므로 일반 중복 기준(0.45)보다 엄격한
        # 실제 실행 인식 기준(0.22) 안에서만 기존 제스처라고 확정한다.
        if best[1] is not None and best[0] < MATCH_DISTANCE:
            return best[1], best[0], one_hand_takes, [take for take, _ in two_hand_takes]
        return None, float("inf"), one_hand_takes, [take for take, _ in two_hand_takes]

    def _upload_static(self):
        if len(self.samples) < self.MIN_STATIC_SAMPLES:
            raise ValueError("손을 충분한 시간 동안 확인하지 못했습니다. 촬영이 끝날 때까지 손을 화면에 유지해주세요")
        poses = []
        aligned_features = []
        reference = np.asarray(self.samples[0])
        for take in range(1, self.takes + 1):
            features = []
            extra_hand_seen = False
            for _, hands in self.take_frames.get(take, []):
                # 손이 안 보인 프레임처럼, 잠깐 다른 손(배경·본인 반대손)이 같이
                # 잡힌 프레임도 그 프레임만 건너뛴다 — 회차 전체를 즉시 거절하면
                # 나머지가 깨끗한 1손 촬영이었어도 못 쓴다. 다만 회차 전체가
                # 계속 2손 이상이었다면(아래) "충분하지 않습니다"보다 정확한
                # 원인을 알려준다.
                if len(hands) == 1:
                    feature = normalize_landmarks(hands[0]["landmarks"])
                    mirrored = feature.copy()
                    mirrored[0::2] *= -1
                    # 실행/중복 검사는 양손 호환인데 등록 평균만 반전을 무시하면
                    # 회차마다 손을 바꾼 같은 자세가 불일치·큰 분산으로 거절된다.
                    if weighted_distance(mirrored - reference) < weighted_distance(feature - reference):
                        feature = mirrored
                    features.append(feature)
                elif len(hands) > 1:
                    extra_hand_seen = True
            if not features:
                if extra_hand_seen:
                    raise ValueError(f"{take}회차에서 손 개수가 한 손이 아니라 두 손으로 계속 감지되었습니다. 한 손 동작은 다른 손을 화면 밖에 두고 촬영해주세요")
                raise ValueError(f"{take}회차에서 손을 확인한 시간이 너무 짧습니다. 촬영이 끝날 때까지 손을 보여주세요")
            pose = np.mean(features, axis=0)
            self._validate_static_stability(
                take, [float(weighted_distance(feature - pose)) for feature in features]
            )
            poses.append(pose)
            aligned_features.extend(features)
        feats = np.asarray(aligned_features, dtype=np.float32)
        # 촬영 자체가 일관되지 않으면 한 회차의 우연한 근접값을 중복으로
        # 확정하지 않는다. 품질 검사를 통과한 뒤 기존 제스처와 비교한다.
        # 기존/내장 제스처와 겹치지 않는다는 걸 먼저 확인한 뒤에야 회차 간
        # 일관성을 본다 — 애초에 충돌·중복이라 거부될 동작이면 일관성부터
        # 맞추라고 헛수고를 시키지 않는다(동적 등록과 같은 원칙).
        ranked_hits = sorted(self.builtin_hits.items(), key=lambda item: (-item[1], item[0]))
        # When unverified finger poses dominate, naming the smaller classified
        # subset as a built-in collision is misleading and may show a tiny
        # geometric similarity. A clear label still wins when it has at least
        # as much evidence as the uncertain frames.
        top_builtin_count = ranked_hits[0][1] if ranked_hits else 0
        if (self.builtin_uncertain >= len(feats) * self.BUILTIN_OVERLAP
                and self.builtin_uncertain > top_builtin_count):
            raise ValueError("손가락 모양을 정확히 확인하기 어렵습니다. 손가락이 겹치지 않도록 보여주세요")
        if ranked_hits and ranked_hits[0][1] >= len(feats) * self.BUILTIN_OVERLAP:
            label, count = ranked_hits[0]
            # dict 삽입 순서는 촬영 초반의 오인식을 우선시한다. 최빈 후보를 쓰고
            # 동률이면 특정 동작과 같다고 단정하지 않는다.
            if len(ranked_hits) > 1 and ranked_hits[1][1] == count:
                raise ValueError("촬영 중 여러 기본 제스처가 비슷한 빈도로 인식되었습니다. 손 모양을 고정해 다시 촬영해주세요")
            # 전체 프레임을 합친 비율만 보면, 회차 하나의 소수 프레임이 나머지
            # 회차와 무관하게 전체 판정을 뒤집을 수 있다(그 회차가 유난히 프레임이
            # 많았다면). 커스텀 중복 다수결(_validate_custom_collision_votes)과
            # 같은 원리로, 이 라벨이 회차 과반수에서도 독자적으로 우세했는지
            # 추가로 확인한다.
            if self._builtin_static_takes_agree(label):
                # 분류 일치율(몇 %가 같은 라벨로 분류됐는지)만 보면, 분류기가 펴짐·
                # 굽힘 사이에 두는 여유 구간 안에서는 손가락을 살짝 굽혀도 여전히
                # 같은 라벨로 분류돼 항상 100%로 뜬다. 기준 손모양이 있는 라벨은
                # 실제 손모양 거리 기반 유사도로 대신한다 — 없으면 분류 일치율로
                # 되돌아간다.
                geo_similarity = _builtin_pose_similarity(label, feats)
                display_name = BUILTIN_GESTURE_DISPLAY_NAMES.get(label, label)
                raise GestureRegistrationRejected(
                    f"기본 제스처 '{display_name}'와 너무 비슷합니다. 다른 손 모양으로 등록해주세요",
                    similar_to=label,
                    similarity=geo_similarity if geo_similarity is not None else round(count / len(feats), 4),
                )
        if self.builtin_uncertain >= len(feats) * self.BUILTIN_OVERLAP:
            raise ValueError("손가락 모양을 정확히 확인하기 어렵습니다. 손가락이 겹치지 않도록 보여주세요")
        matches = []
        for take, pose in enumerate(poses, 1):
            near, dist = self.custom_store.nearest_class(np.asarray([pose], dtype=np.float32))
            matches.append((dist, near))
            print(f"[제스처 중복 검사] tempId={self.temp_id} take={take} motion=STATIC "
                  f"nearest={near!r} distance={dist:.4f} threshold={self.COLLISION_DIST}")
        # 위 nearest_class는 1손 정적(legacy) 저장소만 본다 — 같은 손모양을 동적으로
        # 등록해뒀으면 못 잡는다(정적/동적은 완전히 분리된 저장소·특징 표현이라).
        # 회전 정규화 없는(legacy와 다른) 대표 자세를 새로 만들어 self.data의
        # 1손 동적 템플릿과도 비교한다.
        raw_per_take = []
        for take in range(1, self.takes + 1):
            raw = [p for p in (ordered_landmarks(hands) for _, hands in self.take_frames.get(take, []))
                   if p is not None and len(p) == 1]
            if raw:
                raw_per_take.append(np.mean(raw, axis=0))
        for index, raw_pose in enumerate(raw_per_take):
            cross_pose = encode_sequence([0, 1], [raw_pose] * 2)
            cross_candidates = self.custom_store.cross_boundary_matches(cross_pose, self.STATIC, 1)
            if cross_candidates and cross_candidates[0][0] < matches[index][0]:
                matches[index] = cross_candidates[0]
        self._validate_custom_collision_votes(matches)
        # 충돌·중복이 아니라는 게 확인된 뒤에야 회차 간 일관성을 본다.
        self._validate_take_consistency(
            poses, lambda a, b: float(weighted_distance(a - b)), self.TAKE_STATIC_DISTANCE
        )
        payload = self.cache.template_bytes("__pending__", feats)
        self._validate_hand_size(1)
        self.link.put_gesture_npz(self.temp_id, payload)

    def _builtin_static_takes_agree(self, label):
        """label이 회차 과반수에서도 독자적으로 우세했는지 확인한다.

        전체 프레임을 합친 비율만 보면, 한 회차의 소수 프레임이 나머지
        회차와 무관하게 전체 판정을 뒤집을 수 있다 — 다른 두 회차가 전혀
        다른 손모양이었어도, 그 회차가 프레임을 더 많이 만들었다면 그
        회차만으로 "내장 제스처와 충돌"이라고 오판할 수 있다. 커스텀 중복
        다수결과 같은 원리를 내장 정적 충돌 판정에도 적용한다.
        """
        votes = 0
        for take in range(1, self.takes + 1):
            hits = {}
            total = 0
            for _, hands in self.take_frames.get(take, []):
                if len(hands) != 1:
                    continue
                total += 1
                frame_label = hands[0].get("gesture")
                if frame_label and frame_label != "None":
                    hits[frame_label] = hits.get(frame_label, 0) + 1
            if not total:
                continue
            ranked = sorted(hits.items(), key=lambda item: (-item[1], item[0]))
            if ranked and ranked[0][0] == label and ranked[0][1] >= total * self.BUILTIN_OVERLAP:
                votes += 1
        return votes >= max(1, self.takes // 2 + 1)

    # 동적 등록이 겹쳐선 안 되는 내장 동적 감지기 목록 — (표시 이름, 실행 때와 같은
    # 설정으로 새 인스턴스를 만드는 함수, 손 하나(dict)에서 그 감지기가 원하는
    # 입력을 뽑는 함수). 서비스가 기본 제공하는 9종(정적 7 + 스와이프 좌/우)만
    # "내장"으로 안내한다 — 스크롤·핀치볼륨은 아직 사용자에게 노출된 적 없는
    # (enabled=False) 기능이라 지금 "내장 스크롤과 비슷합니다"라고 하면 사용자가
    # 이해할 수 없는 사유가 된다. 그 기능들이 실제로 켜질 때, 이 목록에 다시
    # 추가한다. extract는 원본 좌표를 반환하고 감지기가 시작 손 크기로
    # 배율을 고정한다. 실행 때(assistant.py)도 같은 경로를 사용한다.
    BUILTIN_DYNAMIC_DETECTORS = (
        ("스와이프", lambda: SwipeDetector(**SCREEN_SWIPE_CONFIG),
         lambda h: h["landmarks"][9]),
    )
    # 거부 문구에 방향까지 보여준다 — similar_to(BE 이벤트 이름)는 이미
    # 방향별로 구분돼 나가고 있었는데, 사용자에게 보이는 문구만 "스와이프"
    # 통칭이라 어느 방향과 겹쳤는지 알 수 없었다.
    SWIPE_DIRECTION_LABELS = {
        "Swipe_Left": "왼쪽 스와이프",
        "Swipe_Right": "오른쪽 스와이프",
        "Swipe_Up": "위쪽 스와이프",
        "Swipe_Down": "아래쪽 스와이프",
    }

    def _builtin_dynamic_collision(self, hand_count=None, take_directions=None):
        """동적 등록이 내장 동적 감지기와 겹치는지, 실제 감지기로 그대로 재생해 확인한다.

        실행 때와 같은 감지기·같은 설정을 써서 "이 촬영이 실제로 라이브였다면
        내장 동작이 발동했을까"를 그대로 재현한다 — 근사치 규칙을 따로 만드는
        것보다 실제 판정 로직과 항상 일치하고, 목록에 등록만 해두면 다른 내장
        동적 감지기도 자동으로 같이 확인된다.

        1손·2손 모두 손마다(handedness 기준, 감지 순서는 프레임마다 바뀔 수
        있어 안 믿는다) 독립적으로 재생한다 — 2손 동작이라도 그중 한 손만의
        움직임이 내장 동작과 겹치면, 실행 중 그 손 하나만 raw 판정으로 새는
        순간(2손 커스텀 인식이 그 프레임만 실패하는 경우) 내장 동작이 조용히
        발동할 수 있기 때문이다.

        다만 2손이 서로를 향해 모이는 동작(박수 등)은 손 하나만 보면 항상
        스와이프처럼 보인다 — 그런 동작까지 전부 막으면 등록 자체가 너무
        제한적이다. 그래서 2손 프레임에서는 두 손 사이 거리도 같이 추적해,
        발동 시점에 그 거리가 뚜렷이 줄어들고 있었으면(서로 다가가는 중)
        충돌로 세지 않고 계속 스캔한다 — 두 손이 독립적으로 같은 방향을
        모두 따라 움직이는(진짜 우연히 같이 스와이프하는) 경우는 거리가
        안 줄어드니 여전히 걸린다.

        겹치면 (표시용 이름, 구체적인 이벤트값, 유사도) 튜플을, 안 겹치면
        (None, None, None)을 돌려준다. 감지기 반환값이 문자열이면(SwipeDetector의
        "Swipe_Left" 등, BE 기본 제스처 이름과 그대로 일치) 그걸 similar_to로 쓸
        수 있게 넘기고, 아니면(PalmScrollDetector의 정수 스텝처럼 이름이 아닌 값)
        표시용 이름으로 대체한다.

        유사도는 감지기가 실제로 보는 거리(궤적 이동량)가 아니라, 발동 시점
        직전 SCREEN_SWIPE_CONFIG['max_t'] 구간에서 그 손이 움직인 거리를 발동
        기준 거리로 나눈 근사값이다(손 크기 보정 포함, 1.0 초과는 자름) — 커스텀
        중복 유사도(exp(-거리), 항상 0~1)와 척도·의미가 다른 근사치임을 참고할 것.
        """
        hand_count = self._infer_hand_count() if hand_count is None else hand_count
        for name, make_detector, extract in self.BUILTIN_DYNAMIC_DETECTORS:
            for take in range(1, self.takes + 1):
                detectors = {}
                histories = {}  # side -> [(t, x, y)] 손 크기 보정된 좌표, 유사도 근사용
                separations = []  # (t, 두 손 사이 거리) — 2손 프레임에서만 채워진다
                if hand_count == 1:
                    # 배경 사람의 손이 순간적으로 함께 잡혀도 내장 스와이프로
                    # 재생하지 않는다. 등록 템플릿에 실제로 쓰는 주 손 궤적과
                    # 같은 것을 사용해야 품질 검사와 충돌 검사의 대상이 일치한다.
                    source = [(t, [observed]) for t, observed
                              in self._one_hand_take_observations(take)]
                else:
                    source = self.take_frames.get(take, [])
                for t, hands in source:
                    if len(hands) == 2:
                        p0, p1 = hands[0]["landmarks"][9], hands[1]["landmarks"][9]
                        separations.append((t, float(np.hypot(p0[0] - p1[0], p0[1] - p1[1]))))
                    seen = set()
                    for h in hands:
                        side = h.get("handedness") or "?"
                        seen.add(side)
                        detector = detectors.setdefault(side, make_detector())
                        anchor = extract(h)
                        size = h.get("size", REFERENCE_PALM_SIZE)
                        scaled = scale_by_hand_size(anchor, size)
                        history = histories.setdefault(side, [])
                        history.append((t, scaled[0], scaled[1]))
                        event = detector.update(anchor, t, size=size)
                        if event and self._hands_were_converging(separations, t):
                            print(f"[제스처 스와이프 제외] tempId={self.temp_id} take={take} hand={side} "
                                  f"direction={event} (두 손이 서로 다가가는 중이라 충돌로 안 셈)")
                            event = None
                        take_direction = (take_directions[take - 1]
                                          if take_directions and take <= len(take_directions)
                                          else None)
                        if (event in ("Swipe_Left", "Swipe_Right")
                                and take_direction in {
                                    "UP", "UP_RIGHT", "DOWN_RIGHT", "DOWN",
                                    "DOWN_LEFT", "UP_LEFT",
                                }):
                            print(f"[gesture diagonal bypass] tempId={self.temp_id} take={take} "
                                  f"builtin={event} direction={take_direction}")
                            event = None
                        if event:
                            start = self.take_frames[take][0][0]
                            print(f"[제스처 스와이프 충돌] tempId={self.temp_id} take={take} elapsed={t-start:.3f}s hand={side} direction={event}")
                            window_s = SCREEN_SWIPE_CONFIG.get('max_t', 0.5)
                            window = [(x, y) for ht, x, y in history if t - ht <= window_s + 0.04]
                            displacement = (max(np.hypot(x - window[0][0], y - window[0][1]) for x, y in window)
                                           if len(window) > 1 else 0.0)
                            similarity = round(min(1.0, displacement / SCREEN_SWIPE_CONFIG.get('dist', 0.12)), 4)
                            return name, (event if isinstance(event, str) else name), similarity
                    for side, detector in detectors.items():
                        if side not in seen:
                            detector.update(None, t)
        return None, None, None

    @staticmethod
    def _hands_were_converging(separations, t, lookback=None, min_change=0.5):
        """t 시점 직전 lookback초 동안 두 손 사이 거리가 뚜렷이 변했는지(모이거나 벌어지거나).

        min_change는 SwipeDetector 발동 기준(dist, 손 크기 기준 비율)의 절반 —
        스와이프를 낼 만큼 한 손이 움직이는 동안 두 손 간격도 그만큼(의 절반
        이상) 좁혀지거나 넓혀졌다면, 그 손은 "따로" 움직인 게 아니라 상대 손을
        향해(또는 상대 손에서 멀어지며) 움직인 것으로 본다 — 박수(모임)와
        양손 펼치기(벌어짐) 둘 다 손 하나만 보면 스와이프처럼 보이는 동작이라
        방향에 상관없이 같은 예외를 적용한다. 2손 프레임이 없었던 촬영(1손
        동적)에서는 항상 False — 기존 동작 그대로 유지된다.
        """
        if len(separations) < 2:
            return False
        lookback = SCREEN_SWIPE_CONFIG.get("max_t", 0.5) if lookback is None else lookback
        window = [sep for ts, sep in separations if t - lookback - 0.04 <= ts <= t]
        if len(window) < 2:
            return False
        return abs(window[0] - window[-1]) > SCREEN_SWIPE_CONFIG.get("dist", 0.12) * min_change

    def _validate_take_consistency(self, takes, compare, threshold):
        # 기존 등록본과의 중복이 아니라 이번 촬영끼리의 불일치다.
        # similarTo를 보내지 않아 FE가 기존 제스처 충돌로 표시하지 않게 한다.
        distances = np.zeros((len(takes), len(takes)), dtype=float)
        for i, first in enumerate(takes):
            for j in range(i + 1, len(takes)):
                score = float(compare(first, takes[j]))
                print(f"[제스처 회차 일관성] tempId={self.temp_id} takes={i+1},{j+1} "
                      f"distance={score:.4f} threshold={threshold}")
                distances[i, j] = distances[j, i] = score if np.isfinite(score) else float('inf')
        if not takes:
            raise ValueError("촬영된 동작이 없습니다. 다시 촬영하세요")
        # 실행은 저장된 예시 하나와 일치하면 인식한다. 모든 회차를 실행 기준
        # 안에서 설명하는 실제 대표 회차가 있으면 같은 동작으로 인정한다.
        # 서로 다른 두 그룹이나 하나의 고립된 오촬영은 대표를 찾지 못한다.
        if np.isfinite(distances).all() and np.any(np.max(distances, axis=1) <= threshold):
            return
        i, j = np.unravel_index(np.argmax(distances), distances.shape)
        if self.motion == self.STATIC:
            raise ValueError(
                f"{i+1}회차와 {j+1}회차의 손가락 모양이 서로 다릅니다. "
                "모든 회차에서 같은 손 모양을 유지해주세요"
            )
        raise ValueError(
            f"{i+1}회차와 {j+1}회차의 움직임 차이가 큽니다. "
            "같은 손 모양으로 같은 방향의 동작을 반복해주세요"
        )

    def _validate_motion_directions(self, sequences):
        """세 촬영의 끝점 이동이 같은 45도 방향 구간인지 확인한다."""
        labels = {
            "RIGHT": "오른쪽", "DOWN_RIGHT": "오른쪽 아래", "DOWN": "아래쪽",
            "DOWN_LEFT": "왼쪽 아래", "LEFT": "왼쪽", "UP_LEFT": "왼쪽 위",
            "UP": "위쪽", "UP_RIGHT": "오른쪽 위",
        }
        hand_count = self._infer_hand_count()
        directions = [motion_direction_8(sequence, hand_count) for sequence in sequences]
        for i in range(len(sequences)):
            for j in range(i + 1, len(sequences)):
                if directions[i] is not None and directions[j] is not None:
                    print(f"[제스처 회차 방향] tempId={self.temp_id} takes={i+1},{j+1} "
                          f"directions={directions[i]},{directions[j]}")
                    if directions[i] != directions[j]:
                        raise ValueError(
                            f"{i+1}회차는 {labels[directions[i]]}, {j+1}회차는 "
                            f"{labels[directions[j]]} 방향으로 움직였습니다. "
                            "세 번 모두 같은 방향으로 움직여주세요"
                        )
                    continue
                first = (sequences[i][-1] - sequences[i][0]).ravel()
                second = (sequences[j][-1] - sequences[j][0]).ravel()
                first_norm, second_norm = np.linalg.norm(first), np.linalg.norm(second)
                # 원형 동작처럼 시작과 끝이 가까우면 끝점 방향 자체가 의미 없으므로
                # 기존 전체 궤적 거리만 사용한다.
                if first_norm < 0.1 or second_norm < 0.1:
                    continue
                cosine = float(np.dot(first, second) / (first_norm * second_norm))
                print(f"[제스처 회차 방향] tempId={self.temp_id} takes={i+1},{j+1} "
                      f"cosine={cosine:.4f}")
                if cosine < 0:
                    raise ValueError(
                        f"{i+1}회차와 {j+1}회차의 동작 방향이 반대입니다. "
                        "모든 회차에서 같은 방향으로 움직여주세요"
                    )

    @staticmethod
    def _dynamic_take_distance(a, b, hand_count):
        """Scale-normalized distance used only for repeat-take consistency.

        A large swipe spans several palm lengths, so a small timing difference
        creates a large absolute landmark error even when direction and path
        are the same.  Duplicate/runtime matching keeps its strict absolute
        distance; only the three attempts' consistency score is normalized by
        their own movement magnitude.
        """
        raw = motion_matching_distance(a, b, hand_count)
        still_a = np.repeat(a[:1], len(a), axis=0)
        still_b = np.repeat(b[:1], len(b), axis=0)
        magnitude = (distance(a, still_a, hand_count)
                     + distance(b, still_b, hand_count)) / 2
        return raw / max(1.0, magnitude)

    def _validate_static_stability(self, take, spreads):
        """자연스러운 떨림은 허용하고 지속적인 손가락 모양 변화만 거부한다."""
        values = np.asarray(spreads, dtype=float)
        if not len(values) or not np.isfinite(values).all():
            raise ValueError(f"{take}회차에서 손 모양을 안정적으로 확인하지 못했습니다. 다시 촬영해주세요")
        percentile = float(np.percentile(values, self.STATIC_SPREAD_PERCENTILE))
        exceed_ratio = float(np.mean(values > self.MAX_SPREAD))
        print(f"[제스처 정적 안정성] tempId={self.temp_id} take={take} "
              f"p{self.STATIC_SPREAD_PERCENTILE}={percentile:.4f} "
              f"overRatio={exceed_ratio:.3f} threshold={self.MAX_SPREAD}")
        # 한두 프레임의 좌표 튐이나 전체 프레임의 20% 미만인 순간 흔들림은
        # 허용한다. 대표 자세에서 크게 벗어난 상태가 지속될 때만 거부한다.
        if (percentile > self.MAX_SPREAD
                and exceed_ratio + 1e-9 >= self.STATIC_SPREAD_MAX_RATIO):
            raise ValueError(
                f"{take}회차 촬영 중 손 모양이 많이 바뀌었습니다. "
                "손 전체가 조금 움직이는 것은 괜찮지만 손가락 모양은 유지해주세요"
            )

    def _validate_custom_collision_votes(self, matches, threshold=None):
        """같은 기존 제스처와 과반수 회차가 겹칠 때만 중복으로 확정한다."""
        threshold = self.COLLISION_DIST if threshold is None else threshold
        required = max(1, len(matches) // 2 + 1)
        hits = {}
        for score, name in matches:
            if name and np.isfinite(score) and score < threshold:
                hits.setdefault(name, []).append(float(score))
        repeated = [(len(scores), float(np.mean(scores)), name)
                    for name, scores in hits.items() if len(scores) >= required]
        if repeated:
            count, mean_dist, name = min(repeated, key=lambda item: (-item[0], item[1], item[2]))
            print(f"[제스처 중복 확정] tempId={self.temp_id} name={name!r} "
                  f"votes={count}/{len(matches)} meanDistance={mean_dist:.4f} "
                  f"threshold={threshold}")
            raise GestureRegistrationRejected(
                f"'{name}'와 너무 유사합니다",
                similar_to=name,
                similarity=round(float(np.exp(-mean_dist)), 4),
            )
        if hits:
            detail = ", ".join(f"{name}:{len(scores)}/{len(matches)}" for name, scores in sorted(hits.items()))
            print(f"[제스처 중복 불확실] tempId={self.temp_id} hits={detail} "
                  f"threshold={threshold}")
            raise ValueError(
                "3회 중 일부 촬영만 기존 제스처와 비슷해 정확히 판단하기 어렵습니다. "
                "세 번 모두 같은 손 모양과 동작으로 다시 촬영해주세요"
            )

    def _two_hand_take_frames(self, take):
        """이 회차를 두 손 프레임 기준으로 정리한다.

        박수처럼 두 손이 맞닿는 동작은 그 순간 감지기가 한 손으로 잘못 세는
        경우가 흔하다. 정상 두 손 프레임으로 둘러싸인 TRACKING_GRACE_S 이내의
        짧은 구간은 가려짐으로 보고 허용한다.

        손을 맞댄 채로 시작하거나(벌어지는 동작) 맞댄 채로 끝나는(모이는
        동작) 경우도 있다 — 두 손이 하나로 보이는 자연스러운 시작·끝 자세라
        그 구간이 아무리 길어도 허용한다. 대신 "두 손이 처음 확인된 지점"부터
        "마지막으로 확인된 지점"까지(실제 두 손 동작이 있었던 구간) 안에서는
        여전히 대부분(80%) 두 손이어야 한다 — 그 안에서 손을 놓치는 건
        자연스러운 시작·끝이 아니라 추적 실패다.

        반환: (이 회차가 '두 손 촬영'으로 인정되는지, 그 경우 쓸 유효 2손
        프레임 목록 — 두 손을 한 번도 확인 못 했으면 빈 리스트).
        """
        frames = [(t, ordered_landmarks(hands)) for t, hands in self.take_frames.get(take, [])]
        if not frames:
            return False, []
        two_idxs = [i for i, (_, pts) in enumerate(frames) if pts is not None and len(pts) == 2]
        if not two_idxs:
            return False, []
        valid = [frames[i] for i in two_idxs]
        inner = frames[two_idxs[0]:two_idxs[-1] + 1]
        gaps = [b - a for (a, _), (b, _) in zip(valid, valid[1:])]
        enough_two_hand_evidence = len(valid) >= max(2, int(np.ceil(len(frames) * 0.2)))
        ok = enough_two_hand_evidence and not (len(valid) < len(inner) * 0.8
                  or (len(valid) < len(inner) and max(gaps, default=0) >= TRACKING_GRACE_S))
        return ok, valid

    def _two_hand_world_sequence(self, take, static=False):
        """Build optional 3D data for a two-hand take.

        Missing world landmarks never affect one-hand or dynamic registration.
        For a new two-hand static template, however, most accepted frames must
        carry valid world landmarks or the pose would silently fall back to the
        ambiguous 2D representation that confuses prayer with a roof.
        """
        raw = self.take_frames.get(take, [])
        frames = [(t, ordered_world_landmarks(hands)) for t, hands in raw]
        valid = [(t, points) for t, points in frames if points is not None]
        if not valid or len(valid) < max(2, int(np.ceil(len(raw) * 0.7))):
            return None
        if static:
            average = np.mean([points for _, points in valid], axis=0)
            return encode_world_sequence([0, 1], [average, average])
        return encode_world_sequence([t for t, _ in valid], [p for _, p in valid])

    def _one_hand_take_observations(self, take):
        """1손 촬영에서 순간적인 두 번째 손 오검출을 제거해 주 손만 반환한다.

        한 손만 잡힌 프레임들에서 가장 자주 나온 handedness를 주 손으로 정한다.
        두 손이 잡힌 프레임에서는 같은 handedness를 우선 선택하고, 라벨까지
        흔들렸으면 직전 주 손의 손목 위치와 가장 가까운 후보로 추적을 잇는다.
        """
        raw = self.take_frames.get(take, [])
        singleton_sides = []
        for _, hands in raw:
            if len(hands) == 1 and ordered_landmarks(hands) is not None:
                singleton_sides.append(hands[0].get("handedness") or "Unknown")
        preferred = (max(set(singleton_sides), key=singleton_sides.count)
                     if singleton_sides else None)
        extra = sum(len(hands) > 1 for _, hands in raw)
        if raw and extra / len(raw) >= self.ONE_HAND_EXTRA_MAX_RATIO:
            raise ValueError(
                f"{take}회차에서 손 개수가 한 손이 아니라 두 손으로 계속 감지되었습니다. "
                "한 손 동작은 다른 손을 화면 밖에 두고 다시 촬영해주세요"
            )

        observations = []
        previous = None
        for timestamp, hands in raw:
            candidates = []
            for observed in hands:
                points = ordered_landmarks([observed])
                if points is not None:
                    candidates.append((observed, points[0]))
            if not candidates:
                continue
            same_side = [item for item in candidates
                         if (item[0].get("handedness") or "Unknown") == preferred]
            pool = same_side or candidates
            if previous is None:
                # 첫 프레임부터 오검출이 섞였으면 더 크게 잡힌 손을 실제 손으로 본다.
                chosen_observed, chosen_points = max(
                    pool, key=lambda item: self._hand_quality(item[1])[0])
            else:
                chosen_observed, chosen_points = min(
                    pool, key=lambda item: float(np.linalg.norm(item[1][0] - previous[0])))
            previous = chosen_points
            observations.append((timestamp, chosen_observed))
        return observations

    def _one_hand_take_frames(self, take):
        return [(timestamp, np.asarray(observed["landmarks"], dtype=np.float32)[None, ...])
                for timestamp, observed in self._one_hand_take_observations(take)]

    def _infer_hand_count(self):
        """이번 등록이 한 손/두 손 촬영인지 판정한다.

        원래는 프레임 전체에서 '2손 감지' 비율이 70% 이상이어야 두 손으로
        판정했다. 하지만 박수처럼 두 손이 맞닿는 동작은 접촉 순간 감지기가
        찰나(수십~백여 ms)만 한 손으로 잘못 세는 경우가 흔해, 그런 순간들이
        누적되면 비율이 70% 밑으로 떨어져 한 손으로 오판된다 — 그러면
        _upload_motion의 가려짐 허용 로직(hand_count==2에서만 동작) 자체가
        스킵돼 회차 중간 손 개수 불일치로 등록이 통째로 거부된다.

        그래서 정상 2손 프레임으로 앞뒤가 둘러싸인 TRACKING_GRACE_S 이내의
        짧은 구간은 "2손이 잠깐 가려졌을 뿐"으로 보고 2손으로 채워 넣은 뒤
        비율을 계산한다 — 이후 실제 검증(_two_hand_take_frames)이 받아줄
        정도의 가려짐이라면, 판정 단계에서도 같은 기준으로 봐야 한다.

        손을 맞댄 채로 시작·종료하는 회차(_two_hand_take_frames가 인정하는
        경우)는 그 회차 전체를 2손으로 센다 — 안 그러면 맞댄 구간이 길 때
        똑같이 비율을 깎아 전체 판정을 한 손으로 뒤집어 버린다.
        """
        total = two_hand = 0
        for take in range(1, self.takes + 1):
            raw = self.take_frames.get(take, [])
            total += len(raw)
            ok, valid = self._two_hand_take_frames(take)
            if ok:
                two_hand += len(raw)
                continue
            frames = [(t, ordered_landmarks(hands)) for t, hands in raw]
            two_idxs = [i for i, (_, pts) in enumerate(frames) if pts is not None and len(pts) == 2]
            two_hand += len(two_idxs)
            for a, b in zip(two_idxs, two_idxs[1:]):
                if b > a + 1 and frames[b][0] - frames[a][0] < TRACKING_GRACE_S:
                    two_hand += b - a - 1  # 둘러싸인 짧은 가려짐 구간을 2손으로 채움
        return 2 if total and two_hand >= total * 0.7 else 1

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
        world_sequences = []
        world_valid = []
        pose_sequences = []
        pose_valid = []
        durations = []
        for take in range(1, self.takes + 1):
            raw = self.take_frames.get(take, [])
            frames = [(t, ordered_landmarks(hands)) for t, hands in raw]
            if hand_count == 2 and frames:
                ok, valid = self._two_hand_take_frames(take)
                if not valid:
                    raise ValueError(f"{take}회차에서 두 손을 확인하지 못했습니다. 손 개수를 유지하고 두 손을 보여주세요")
                if not ok:
                    raise ValueError(
                        f"{take}회차에서 두 손 중 한 손을 일정 시간 확인하지 못했습니다. "
                        "손을 맞댄 채로 시작하거나 끝내는 것은 괜찮지만, 동작 중에는 두 손이 모두 보이게 해주세요"
                    )
                frames = valid
            elif hand_count == 1:
                frames = self._one_hand_take_frames(take)
            frames = [(t, pts) for t, pts in frames if pts is not None]
            if len(frames) < 2:
                raise ValueError(f"{take}회차에서 손을 확인한 시간이 너무 짧습니다. 촬영이 끝날 때까지 손을 보여주세요")
            # 손을 놓친 구간이 촬영 맨 앞이나 끝에 걸리면, 놓친 프레임이 그냥
            # 통째로 사라져 위 길이·아래 중간 공백 검사 어디에도 안 걸린다 —
            # 동작의 앞부분(또는 뒷부분)이 잘려나간 채로 조용히 넘어가, 다른
            # 회차와는 궤적이 통째로 달라 보여 "회차가 다르다"는 엉뚱한 사유로
            # 거부된다. 실제 원인(손을 놓친 시점)을 바로 알려준다. 2손은 손을
            # 맞댄 채 시작·종료하는 게 정상이라(_two_hand_take_frames가 이미
            # 확인) 여기서는 보지 않는다 — 1손에서만 의미가 있다.
            if hand_count == 1 and raw and (frames[0][0] - raw[0][0] >= TRACKING_GRACE_S
                       or raw[-1][0] - frames[-1][0] >= TRACKING_GRACE_S):
                raise ValueError(
                    f"{take}회차 촬영 시작 또는 끝에서 손을 놓쳤습니다. "
                    "촬영이 시작되기 전에 손을 화면에 먼저 보여주세요"
                )
            # 2손 정적은 모은 프레임을 평균내 떨림을 지우는 방식이라(아래), 딱 2장으론
            # 평균의 의미가 없다 — encode_sequence가 요구하는 수학적 최소(2)와는 별개로,
            # 노이즈를 실제로 줄이려면 이만큼은 있어야 한다.
            if self.motion == self.STATIC and len(frames) < self.MIN_STATIC_MOTION_FRAMES:
                raise ValueError(f"{take}회차에서 손을 확인한 시간이 너무 짧습니다. 촬영이 끝날 때까지 손을 보여주세요")
            # ordered_landmarks는 프레임별로 유효하면 통과시키므로(1손·2손 각각
            # 정상 모양), 회차 중간에 손 개수가 바뀌어도(가려짐 등) 여기까진
            # 안 걸러진다 — 그대로 두면 다음 encode_sequence가 raw numpy 오류로
            # 죽어 사용자에게 알아볼 수 없는 문구가 그대로 노출된다.
            if len({pts.shape[0] for _, pts in frames}) > 1:
                raise ValueError(f"{take}회차 촬영 중 손 개수가 바뀌었습니다. 손 개수를 유지해주세요")
            if frames[0][1].shape[0] != hand_count:
                raise ValueError(f"{take}회차 촬영의 손 개수가 다른 회차와 다릅니다. 모든 회차에서 손 개수를 유지해주세요")
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
                self._validate_static_stability(take, [
                    distance(encode_sequence([0, 1], [pts, pts]), seq, hand_count)
                    for _, pts in frames
                ])
            else:
                original_start, original_end = frames[0][0], frames[-1][0]
                frames = trim_motion_frames(frames)
                print(f"[제스처 동작 구간] tempId={self.temp_id} take={take} start={frames[0][0]-original_start:.3f}s end={frames[-1][0]-original_start:.3f}s captured={original_end-original_start:.3f}s")
                seq = encode_sequence([t for t, _ in frames], [pts for _, pts in frames])
                movement = distance(seq, np.repeat(seq[:1], FRAMES, axis=0), hand_count)
                if movement < PREFIX_MIN_MOTION:
                    raise ValueError(f"{take}회차의 움직임이 너무 작아 동적 제스처로 구분하기 어렵습니다. 동작을 조금 더 크게 해주세요")
            sequences.append(seq)
            if self.motion == self.STATIC and hand_count == 2:
                world_seq = self._two_hand_world_sequence(take, static=True)
                world_valid.append(world_seq is not None)
                world_sequences.append(
                    world_seq if world_seq is not None
                    else np.zeros((FRAMES, 2, 21, 3), np.float32))
            else:
                world_valid.append(False)
                world_sequences.append(np.zeros((FRAMES, 2, 21, 3), np.float32))
            pose_frames = [pose for _, pose in self.take_pose_frames.get(take, [])
                           if pose is not None]
            pose_seq = (encode_pose_sequence(pose_frames)
                        if self.motion == self.STATIC and len(pose_frames) >= 2 else None)
            pose_valid.append(pose_seq is not None)
            pose_sequences.append(
                pose_seq if pose_seq is not None
                else np.zeros((FRAMES, 6, 2), np.float32))
            durations.append(frames[-1][0] - frames[0][0] if self.motion == self.DYNAMIC else self.take_s)
        take_directions = ([motion_direction_8(sequence, hand_count) for sequence in sequences]
                           if self.motion == self.DYNAMIC else None)
        compare = (lambda a, b, count: self._dynamic_take_distance(a, b, count)
                   if self.motion == self.DYNAMIC else matching_distance(a, b, count))
        matches = []
        for take, seq in enumerate(sequences, 1):
            world_seq = (world_sequences[take - 1]
                         if world_valid[take - 1] else None)
            candidates = self.custom_store.sequence_comparisons(
                seq, self.motion, hand_count, world_sequence=world_seq)
            score, name = ((candidates[0]['score'], candidates[0]['name']) if candidates
                           else (float('inf'), None))
            self.comparison_diagnostics.append(dict(take=take, candidates=candidates))
            if candidates:
                print(f"[제스처 특징 비교] tempId={self.temp_id} take={take} " + json.dumps(candidates[0], ensure_ascii=False))
            # sequence_comparisons는 동작 종류(motion)가 같아야만 비교한다 — 같은
            # 손모양을 정적/동적으로 다르게 등록했을 때의 중복은 놓친다. 반대
            # 종류 저장소(cross_boundary_matches)와, 1손이면 1손 정적(legacy)
            # 저장소(cross_legacy_matches)도 같이 봐서 그 경계를 넘는 중복을 잡는다.
            cross = self.custom_store.cross_boundary_matches(seq, self.motion, hand_count)
            if cross and cross[0][0] < score:
                score, name = cross[0]
            if hand_count == 1:
                legacy_name, legacy_dist = self.custom_store.cross_legacy_matches(seq, 1)
                if legacy_name and legacy_dist < score:
                    score, name = legacy_dist, legacy_name
            matches.append((score, name))
            collision_threshold = (self.DYNAMIC_COLLISION_DIST
                                   if self.motion == self.DYNAMIC else self.COLLISION_DIST)
            print(f"[제스처 중복 검사] tempId={self.temp_id} take={take} motion={self.motion} hands={hand_count} nearest={name!r} distance={score:.4f} threshold={collision_threshold}")
        # 내장 동적 감지기(스와이프 등)는 NPZ 템플릿이 아니라 별도 상태기계라
        # nearest_sequence 충돌검사 대상에 없다. 그대로 두면 내장 동작과 똑같이
        # 움직이는 동작을 커스텀으로 등록해도 경고 없이 통과하는데, 실행 시에는
        # 커스텀 동작 추적이 우선순위를 가져가(앞서 고친 우선순위 가드) 내장 동작이
        # 조용히 가려져 버린다 — 등록 시점에 미리 알려주는 게 낫다. 2손 동작도
        # 검사 대상이다 — 한 손만의 움직임이 내장과 겹쳐도, 실행 중 2손 인식이
        # 그 프레임만 실패하면 그 손 하나만으로 내장 동작이 새어나갈 수 있다.
        if self.motion == self.DYNAMIC:
            collided, collided_event, collided_similarity = self._builtin_dynamic_collision(
                hand_count, take_directions)
            if collided:
                # similar_to는 표시용 통칭("스와이프")이 아니라 구체적인 이벤트
                # 이름("Swipe_Left" 등, BE 기본 제스처 이름과 일치)을 보낸다 —
                # FE가 그 이름으로 실제 제스처를 찾아 보여줄 수 있게 한다.
                # 문구(reason)도 통칭 대신 방향까지 보여준다 — 매핑에 없는
                # 이벤트(향후 다른 내장 동적 감지기)는 통칭으로 되돌아간다.
                # similarity는 실제 감지기가 보는 발동 여부/거리와는 다른, 발동
                # 직전 이동거리 ÷ 발동 기준 거리의 근사값이다(_builtin_dynamic_collision
                # 참고) — 커스텀 중복 유사도와 척도가 다를 수 있다.
                display_name = self.SWIPE_DIRECTION_LABELS.get(collided_event, collided)
                raise GestureRegistrationRejected(
                    f"'{display_name}'와 너무 유사합니다", similar_to=collided_event,
                    similarity=collided_similarity,
                )
        self._validate_custom_collision_votes(
            matches,
            self.DYNAMIC_COLLISION_DIST if self.motion == self.DYNAMIC else self.COLLISION_DIST,
        )
        if self.motion == self.DYNAMIC:
            self._validate_motion_directions(sequences)
        # 충돌·중복이 아니라는 게 확인된 뒤에야 회차 간 일관성(모양·방향)을
        # 본다 — 애초에 거부될 동작이면 일관성부터 맞추라고 헛수고를 시키지
        # 않는다. 위 두 검사(내장 충돌은 모든 회차를 순회, 중복검사는 회차별로
        # 비교) 모두 회차 전체를 이미 다 보므로 순서를 바꿔도 정확도는 그대로다.
        self._validate_take_consistency(
            sequences, lambda a, b: compare(a, b, hand_count), self.TAKE_SEQUENCE_DISTANCE
        )
        data = dict(
            X=np.empty((0, 42), np.float32), names=np.array([], dtype="U1"),
            sequences=np.stack(sequences), sequence_names=np.array(["__pending__"] * len(sequences)),
            motions=np.array([self.motion] * len(sequences)),
            hand_counts=np.array([hand_count] * len(sequences), dtype=np.int32),
            durations=np.array(durations, dtype=np.float32),
            world_sequences=np.stack(world_sequences),
            world_valid=np.array(world_valid, dtype=bool),
            pose_sequences=np.stack(pose_sequences),
            pose_valid=np.array(pose_valid, dtype=bool),
        )
        self._validate_hand_size(hand_count)
        self.link.put_gesture_npz(self.temp_id, encode_template_bytes(data))
