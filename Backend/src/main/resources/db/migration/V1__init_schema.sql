-- ============================================================================
-- V1__init_schema.sql
--
-- SQLite 각색 규칙:
--   * BIGINT PK           → INTEGER PRIMARY KEY AUTOINCREMENT (id 는 서버가 발급)
--   * TINYINT 0|1         → INTEGER + CHECK (0,1)
--   * TSTZ / VARCHAR(23)  → TEXT. 값은 UTC 'yyyy-MM-dd HH:mm:ss.SSS' 23자 고정폭.
--                           생성은 common/Times 한 곳. datetime('now') 는 밀리초가 없어
--                           같은 폭이 아니므로 시각 비교 값은 전부 Java 가 바인딩한다.
--   * VARCHAR(n)          → TEXT (SQLite 는 길이를 강제하지 않는다. 절단은 서비스 계층)
--   * ALTER TABLE ADD CONSTRAINT 불가 → 전부 CREATE TABLE 인라인
-- ============================================================================

-- ---------------------------------------------------------------- app_settings
CREATE TABLE app_settings (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),  -- 항상 1. 싱글턴 강제
    settings_json        TEXT    NOT NULL,                    -- 설정 원본 JSON. 서버는 저장/반환만 하고 파싱하지 않는다 (예외: sessionSeconds 읽기)
    settings_version     INTEGER NOT NULL DEFAULT 1,          -- 쓸 때마다 +1. 에이전트 캐시 최신 여부 판단용
    settings_updated_at  TEXT,                                -- UTC yyyy-MM-dd HH:mm:ss.SSS
    agent_synced_version INTEGER,                             -- settings_version 보다 작으면 WebUI 편집이 아직 에이전트에 안 닿음
    agent_synced_at      TEXT,                                -- UTC yyyy-MM-dd HH:mm:ss.SSS
    agent_version        TEXT                                 -- 에이전트 빌드 버전. 버그 리포트 1순위 정보
);

-- ------------------------------------------------------------------------ blob
-- 이름이 고정된 전역 npz — wakeword(호출어 모델) 1종. 커스텀 제스처 템플릿은 gesture.npz(제스처별),
-- 보이스·보정 npz 는 voice_profile / calib_profile 에 있다.
CREATE TABLE blob (
    name       TEXT PRIMARY KEY CHECK (name IN ('wakeword')),
    payload    BLOB    NOT NULL,                              -- npz 바이너리 원본
    byte_size  INTEGER NOT NULL CHECK (byte_size BETWEEN 1 AND 5242880),
    sha256     TEXT    NOT NULL,                              -- 에이전트 캐시 무효화 기준이자 GET 의 ETag
    updated_at TEXT    NOT NULL                               -- UTC yyyy-MM-dd HH:mm:ss.SSS
);

-- --------------------------------------------------------------- voice_profile
-- 보이스(화자) 프로필 — 최대 4개(사용 1 + 스톡 3), 개수·활성 규칙은 서비스 계층.
-- 등록 진행 중 임시본은 DB 가 아니라 오케스트레이터 메모리에 있다 — 커밋된 확정본만 행이 된다
-- (재시작하면 진행 중이던 등록은 사라지는 게 맞고, 청소할 고아 행도 없다).
CREATE TABLE voice_profile (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,                       -- 기본 "내 목소리 N", 사용자 변경 가능
    active            INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),  -- 사용 중 = 1 (최대 1개)
    device_label      TEXT,                                   -- 등록 당시 마이크 이름 — 장비 교체 자동 맵핑 키
    npz               BLOB,                                   -- 화자 임베딩. PC 밖 반출 금지
    npz_sha256        TEXT,                                   -- 에이전트 캐시 무효화 기준이자 GET 의 ETag
    npz_bytes         INTEGER,
    sample            BLOB,                                   -- 재생용 샘플 오디오 — 화자 인식 시 마지막 발화로 갱신
    sample_mime       TEXT,                                   -- audio/webm | audio/wav
    sample_bytes      INTEGER,
    sample_updated_at TEXT,
    duration_sec      REAL,                                   -- 샘플 길이 (녹음 확인 화면 표시)
    quality           TEXT,                                   -- 녹음 품질 (양호 등) — AI 판정 문자열 그대로
    noise             TEXT,                                   -- 주변 소음 (낮음|높음)
    created_at        TEXT    NOT NULL,                       -- 등록일
    last_used_at      TEXT                                    -- 최근 사용일 — 활성 전환 시각
);

-- --------------------------------------------------------------- calib_profile
-- 시선 보정 프로필 — 규칙은 voice_profile 과 동일. 보정 정확도(평균/최대 오차·산점도)를 함께 저장한다.
CREATE TABLE calib_profile (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,                            -- 기본 "내 보정 N", 사용자 변경 가능
    active       INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
    device_label TEXT,                                        -- 등록 당시 카메라 이름 — 장비 교체 자동 맵핑 키
    npz          BLOB,                                        -- calib.npz. PC 밖 반출 금지
    npz_sha256   TEXT,
    npz_bytes    INTEGER,
    screen_w     INTEGER,                                     -- 학습된 화면 폭 — 해상도 불일치 시 재보정 유도
    screen_h     INTEGER,
    avg_error_px REAL,                                        -- 평균 오차. 기준 50px 이하 = 통과
    max_error_px REAL,                                        -- 최대 오차
    points_json  TEXT,                                        -- 시선 학습 결과 산점도 [{n,x,y,gx,gy}]
    created_at   TEXT    NOT NULL,                            -- 등록일
    last_used_at TEXT                                         -- 최근 사용일 — 활성 전환 시각
);

-- ------------------------------------------------------------------------ tool
CREATE TABLE tool (
    name              TEXT PRIMARY KEY,                       -- @McpTool(name). tool_call.tool_name 과 같은 값
    description       TEXT    NOT NULL,                       -- LLM 이 실제로 읽는 문장의 사본
    input_schema_json TEXT    NOT NULL,                       -- @McpToolParam 에서 생성된 JSON Schema
    session_required  INTEGER NOT NULL DEFAULT 0 CHECK (session_required IN (0, 1)),
    confirm_required  INTEGER NOT NULL DEFAULT 0 CHECK (confirm_required IN (0, 1)),  -- 집행 게이트가 아니라 선언 — "호출 전 사용자 동의 필요". MCP destructiveHint 로 나간다
    available         INTEGER NOT NULL DEFAULT 1 CHECK (available IN (0, 1)),  -- 이번 기동에 등록됐는가. 빠져도 행은 남긴다
    synced_at         TEXT    NOT NULL                        -- UTC yyyy-MM-dd HH:mm:ss.SSS
);

-- --------------------------------------------------------------------- session
CREATE TABLE session (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,             -- 서버가 발급한다
    started_at TEXT NOT NULL,                                 -- UTC yyyy-MM-dd HH:mm:ss.SSS
    ended_at   TEXT,                                          -- NULL 이면 진행 중. started_at 보다 앞설 수 없다
    end_reason TEXT CHECK (end_reason IS NULL OR end_reason IN ('EXPIRED', 'STOPPED', 'WATCHDOG', 'SHUTDOWN')),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

-- ------------------------------------------------------------------ app_target
CREATE TABLE app_target (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key      TEXT    NOT NULL UNIQUE,                     -- app.launch 가 받는 키. 경로가 아니다
    display_name TEXT    NOT NULL,
    exec_path    TEXT    NOT NULL,                            -- 사용자가 등록한 것만. LLM 이 채우는 칸이 아니다
    args         TEXT    NOT NULL DEFAULT '',
    verified_at  TEXT,                                        -- UTC yyyy-MM-dd HH:mm:ss.SSS
    enabled      INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

-- --------------------------------------------------------------------- gesture
CREATE TABLE gesture (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    custom      INTEGER NOT NULL DEFAULT 0 CHECK (custom IN (0, 1)),  -- 1 = 사용자 등록(템플릿 npz 보유). 0 = canned(MediaPipe 기본, 헤더 참고)
    kind        TEXT NOT NULL CHECK (kind IN ('HAND', 'FACE')),  -- HAND (gestures) | FACE (facial)
    context     TEXT,                                         -- NULL = default. 'video' | 'youtube' 등
    name        TEXT NOT NULL,                                -- canned 는 MediaPipe 이름, 커스텀은 사용자 지정 이름
    label       TEXT,                                         -- UI 표시용 한국어 이름
    description TEXT,
    repeatable  INTEGER NOT NULL DEFAULT 0 CHECK (repeatable IN (0, 1)),  -- 반복되는 건 시퀀스 전체지 개별 단계가 아니다
    enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),  -- 목록 화면 켜기/끄기. 꺼지면 AI 감지 제외 + BE 실행 차단
    created_at  TEXT,                                         -- 등록일 (상세 화면 표시). canned 시드는 NULL
    video_path  TEXT,                                         -- 등록 때 촬영한 webm 파일명 (gestures/ 아래). canned 는 NULL
    npz         BLOB,                                         -- 템플릿 npz — 제스처별 1개 (흐름도 03). canned 는 NULL. PC 밖 반출 금지
    npz_sha256  TEXT,                                         -- 에이전트 캐시 무효화 기준이자 GET /api/agent/gestures/{id}/npz 의 ETag
    npz_bytes   INTEGER,
    UNIQUE (kind, context, name)
);

-- ---------------------------------------------------------------- gesture_step
CREATE TABLE gesture_step (
    gesture_id INTEGER NOT NULL REFERENCES gesture (id) ON DELETE CASCADE,
    tool_name  TEXT    NOT NULL REFERENCES tool (name),       -- @McpTool(name). tool_call.tool_name 과 같은 값
    step_no    INTEGER NOT NULL CHECK (step_no >= 1),         -- 1부터. 이 순서대로 호출한다
    args_json  TEXT    NOT NULL DEFAULT '{}',                 -- 이 단계에 고정된 인자. 예: {"dir":"up"}
    delay_ms   INTEGER,                                       -- 앞 단계 완료 후 대기. app.launch 다음 window.maximize 같은 경우
    UNIQUE (gesture_id, step_no)
);

-- ------------------------------------------------------------------- tool_call
CREATE TABLE tool_call (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER REFERENCES session (id)    ON DELETE SET NULL,  -- 세션 밖 호출(WebUI 버튼)이 있어 NULL 허용
    app_target_id INTEGER REFERENCES app_target (id) ON DELETE SET NULL,  -- app.launch 일 때만. args_json 파싱 없이 앱별 집계용
    tool_name     TEXT    NOT NULL REFERENCES tool (name),    -- 기록은 대상이 지워져도 남아야 하므로 tool 행은 DELETE 하지 않는다
    ts            TEXT    NOT NULL,                            -- Spring 자기 시계. UTC yyyy-MM-dd HH:mm:ss.SSS
    args_json     TEXT    NOT NULL DEFAULT '{}',               -- 기록 전 500자로 절단
    caller        TEXT    NOT NULL CHECK (caller IN ('LLM', 'GESTURE', 'UI')),
    outcome       TEXT    NOT NULL CHECK (outcome IN ('EXECUTED', 'BLOCKED', 'FAILED')),  -- 확인 게이트가 없어 CONFIRM_* 은 생기지 않는다 (ToolGate)
    reason        TEXT,
    latency_ms    INTEGER
);

-- ----------------------------------------------------------------- usage_event
CREATE TABLE usage_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uid   TEXT    NOT NULL UNIQUE,                      -- 이벤트마다 UUID. 재전송 중복 제거 기준 (INSERT OR IGNORE 근거)
    session_id  INTEGER REFERENCES session (id) ON DELETE SET NULL,  -- calibration 은 세션 밖이라 NULL 허용
    -- 프로필별 인식 정확도 집계 축. kind=voice → voice_profile.id / kind=gaze → calib_profile.id.
    -- kind 가 대상 테이블을 정하므로 FK 는 걸지 않는다 (재등록 rollback 판단 근거).
    profile_id  INTEGER,
    received_at TEXT    NOT NULL,                             -- UTC yyyy-MM-dd HH:mm:ss.SSS
    -- 제약 없음 — 모르는 kind 도 그대로 저장한다. 대시보드가 축으로 쓰는 값은
    -- voice | gaze | gesture | command | voice-rejected | calibration 여섯이다.
    kind        TEXT    NOT NULL,
    action      TEXT,
    context     TEXT,
    latency_ms  INTEGER,                                      -- 대시보드가 AVG 하는 값이라 컬럼으로 둔다. 아래 두 컬럼도 같은 규칙
    -- 0.000 ~ 1.000 인식 신뢰도. 인식 이벤트(voice|gaze|gesture)가 아니면 NULL.
    -- 범위를 벗어난 값은 서비스 계층이 NULL 로 낮춘다 (이벤트 자체는 버리지 않는다).
    accuracy    REAL    CHECK (accuracy IS NULL OR (accuracy >= 0.0 AND accuracy <= 1.0)),
    -- SIMPLE | COMPLEX. kind='command' 의 축이다.
    -- NULL 이면 평균 응답 시간 카드에서 제외한다 — SIMPLE 로 넘겨짚지 않는다.
    complexity  TEXT    CHECK (complexity IS NULL OR complexity IN ('SIMPLE', 'COMPLEX')),
    payload     TEXT    NOT NULL                              -- 나머지 지표. 모르는 키를 버리지 않는다
);

-- --------------------------------------------------------------------- 인덱스
-- SQLite 는 FK 컬럼에 인덱스를 자동으로 만들지 않는다.
CREATE INDEX idx_tool_call_ts       ON tool_call (ts DESC);
CREATE INDEX idx_tool_call_tool     ON tool_call (tool_name, ts DESC);
CREATE INDEX idx_tool_call_session  ON tool_call (session_id);
CREATE INDEX idx_event_recv         ON usage_event (received_at DESC);
CREATE INDEX idx_event_kind         ON usage_event (kind, received_at DESC);
CREATE INDEX idx_event_session      ON usage_event (session_id);
CREATE INDEX idx_event_profile      ON usage_event (profile_id, kind, received_at DESC);
CREATE INDEX idx_session_started    ON session (started_at DESC);
CREATE INDEX idx_gesture_step_tool  ON gesture_step (tool_name);
CREATE INDEX idx_gesture_custom     ON gesture (custom);

-- ============================================================================
-- 시드 — 설정 싱글턴 하나뿐이다.
-- tool 행은 기동 시 ToolCatalogSync 가 ToolCatalog(코드)를 UPSERT 해 만들고,
-- 기본(canned) 제스처 매핑 11건은 그 뒤 DefaultMappings 가 gesture 테이블이
-- 비어 있을 때 넣는다 — 도구 목록의 원천은 코드 하나이고 SQL 에 복제하지 않는다.
-- (gesture_step.tool_name FK 가 tool 행을 요구하므로 이 순서는 @Order 로 강제된다.)
-- ============================================================================

-- 설정 싱글턴 (seed/default-settings.json 과 동일 값이어야 한다).
-- 매핑은 여기 없다 — 매핑의 원천은 gesture / gesture_step 테이블이다.
-- 알려진 키의 정의·검증은 settings/SettingsSchema (저장 시 완전성·타입 강제).
-- micDevice·cameraDevice 는 OS 가 보고하는 장치 이름 원문이고 null 은 "시스템 기본 장치를 따른다"는 뜻이다
-- — 프로필의 device_label 로 그대로 복사돼 장비 교체 자동 맵핑의 키가 된다.
INSERT INTO app_settings (id, settings_json, settings_version, settings_updated_at)
VALUES (1,
        '{"wakeWord":"시아","sessionSeconds":15,"autoStart":true,"gazeCursor":false,"micDevice":null,"cameraDevice":null}',
        1,
        strftime('%Y-%m-%d %H:%M:%f', 'now'));
