# SIA API 명세서

SIA 백엔드(BE)가 제공하는 REST 엔드포인트 · MCP 도구 · WebSocket 메시지의 요청 · 응답 규격이다.
WS 메시지의 필드 단위 양식은 §4 에 있다. 이벤트가 오가는 순서 · 세션 계약 · MCP 전송 규칙은 [프로토콜.md](프로토콜.md), 데이터 모델은 [ERD.md](ERD.md)에 있다.

## 목차

| 절 | 내용 |
|---|---|
| [0](#0-공통-규약) | 공통 규약 — 주소 · 인증 · 시각 · 오류 응답 · 목록 형식 |
| [1](#1-rest--fe-용) | REST (FE) — 상태 · 설정 · 도구 · 앱 · 제스처 · 기록 · 대시보드 · 미리보기 · 백업 · 프로필 · 장치 목록 · 장비 맵핑 |
| [2](#2-rest--ai-용) | REST (AI) — npz · 오디오 업/다운로드, 통계 배치 |
| [3](#3-mcp-도구-30개) | MCP 도구 30개 — 인자 · 응답 · 실패 코드 |
| [4](#4-websocket-메시지-양식) | WebSocket 메시지 양식 — 봉투 · 채널별 이벤트의 필드 타입 · 예시 |
| [5](#5-부록--엔드포인트--이벤트-색인) | 부록 — 엔드포인트 · 이벤트 색인 |

---

## 0. 공통 규약

### 0.1 주소 · 인증

| 표면 | 주소 | 인증 |
|---|---|---|
| REST | `http://127.0.0.1:8080` | 없음 |
| MCP | `http://127.0.0.1:8080/mcp` | `Authorization: Bearer <token>` (또는 `X-MC-Token`) + `X-Caller: LLM\|GESTURE` |

- BE 는 `127.0.0.1` 에만 바인딩한다.
- CORS 는 `/api/**` 에만 적용된다. 허용 Origin 은 `http://localhost:*`, `http://127.0.0.1:*`, 허용 메서드는 `GET POST PUT PATCH DELETE OPTIONS` 다.
- MCP 토큰의 기본값은 `sia-mcp-server` 이고 환경변수 `SIA_AGENT_TOKEN` 으로 대체된다. AI 는 `%APPDATA%/SIA/runtime.json` 의 `token` 을 읽는다.
- 토큰이 없거나 틀리면 **401** `{"code":"UNAUTHORIZED","message":"MCP 토큰이 필요합니다"}`.
- `X-Caller` 가 없거나 알 수 없는 값이면 `LLM` 으로 처리한다.

### 0.2 본문 형식

| 자리 | Content-Type |
|---|---|
| REST 요청 · 응답 기본 | `application/json;charset=UTF-8` |
| npz 업/다운로드 | `application/octet-stream` |
| 샘플 오디오 | `audio/webm` 또는 `audio/wav` (업로드한 그대로 서빙) |
| 영상 | `video/webm` |

### 0.3 시각 · 기간 필터

| 자리 | 형식 | 예 |
|---|---|---|
| 응답의 모든 시각 | UTC `yyyy-MM-dd HH:mm:ss.SSS` (23자) | `2026-08-31 04:12:07.913` |
| 조회 필터 `from` / `to` | 위 23자 또는 `yyyy-MM-dd` 10자 | `2026-08-24` |

`from` 이 10자면 `00:00:00.000`, `to` 가 10자면 `23:59:59.999` 를 붙여 비교한다.

### 0.4 오류 응답

모든 REST 오류는 같은 형태다. `message` 는 사용자에게 그대로 표시할 수 있는 한국어 문장이다. `detail` 은 내부 원인 문자열이 있을 때만 붙으며 사용자에게 표시하지 않는다.

```json
{ "code": "SETTINGS_STALE", "message": "다른 곳에서 먼저 저장된 설정이 있습니다. 최신 설정을 불러온 뒤 다시 저장해 주세요" }
```
```json
{ "code": "INTERNAL_ERROR", "message": "파일 저장에 실패했습니다. 잠시 후 다시 시도해주세요", "detail": "Access is denied" }
```

| code | HTTP | 조건 |
|---|:-:|---|
| `INVALID_REQUEST` | 400 · 405 · 415 | 본문 · 파라미터 형식 오류. 405 · 415 는 HTTP 상태만 다르고 `code` 는 같다 |
| `APP_NOT_REGISTERED` | 400 | 등록되지 않은 앱 실행 |
| `APP_PATH_INVALID` | 400 | 등록된 실행 파일이 존재하지 않음 |
| `REF_NOT_FOUND` | 400 | `win:N` / `app:key` 를 찾을 수 없음 |
| `UNAUTHORIZED` | 401 | MCP 토큰 없음 · 불일치 |
| `ELEVATED_WINDOW` | 403 | 관리자 권한 창 제어 |
| `NOT_FOUND` | 404 | 없는 경로 · 없는 appKey |
| `BLOB_NOT_FOUND` | 404 | 저장된 npz 없음 |
| `PROFILE_NOT_FOUND` | 404 | 없는 프로필. 진행 중 등록의 `tempId` 불일치 포함 |
| `FILE_NOT_FOUND` | 404 | 파일 없음 |
| `GESTURE_NOT_FOUND` | 404 | 없는 제스처 id |
| `SETTINGS_STALE` | 409 | 설정 낙관적 잠금 실패 |
| `CALIB_RESOLUTION_MISMATCH` | 409 | 보정 해상도 불일치 |
| `SESSION_REQUIRED` | 409 | 활성 세션 없음 |
| `PROFILE_LIMIT` | 409 | 프로필 4개 초과 |
| `PROFILE_IN_USE` | 409 | 사용 중이거나 마지막 1개인 프로필 삭제 |
| `INTERNAL_ERROR` | 500 | 그 외 |
| `MODEL_DOWNLOAD_FAILED` | 502 | 모델 다운로드 실패 |
| `EXTENSION_UNAVAILABLE` | 503 | 브라우저 확장 미연결 |

형식 오류(`INVALID_REQUEST`)의 공통 규칙:

| 조건 | HTTP | `message` |
|---|:-:|---|
| 쿼리 · 경로 파라미터 타입 불일치, 필수 파라미터 누락, 본문 역직렬화 실패 | 400 | `요청 형식이 올바르지 않습니다`. 타입 불일치 · 누락은 `detail` 에 파라미터 이름이 붙는다 |
| 허용되지 않는 메서드 | 405 | `요청 형식이 올바르지 않습니다` |
| 지원하지 않는 `Content-Type` | 415 | `요청 형식이 올바르지 않습니다` |
| JSON 본문이 비어 있음 | 400 | `본문이 비어 있습니다` |
| JSON 본문이 객체가 아님 | 400 | `본문은 JSON 객체여야 합니다` |

뒤의 두 줄은 본문 필드를 바로 읽는 엔드포인트(`PATCH /api/voices/{id}` · `PATCH /api/calibs/{id}` · `POST /api/devices/remap` · `PATCH /api/gestures/{id}` · `PUT /api/gestures/{id}`)의 규칙이다. 그 밖의 엔드포인트는 각 절의 메시지를 쓴다.

MCP 도구 호출은 이 HTTP 상태를 쓰지 않는다. 도구 실행 오류는 HTTP 200 + `isError: true` 로 돌아오고 `structuredContent.code` 에는 §3.1 의 코드가 쓰인다.

### 0.5 목록 응답 형식

| 엔드포인트 | 형식 | 페이지 |
|---|---|---|
| `GET /api/tool-calls` · `GET /api/sessions` | `{page, pageSize, total, items}` | `page` 는 1부터, 50건 고정 |
| `GET /api/gestures` | `{page, pageSize, total, items}` | `page` 는 0부터, `size` 기본 20 (1~100) |
| `GET /api/voices` · `GET /api/calibs` | `{items}` | 없음 |
| 그 외 목록 | JSON 배열 | 없음 |

---

## 1. REST — FE 용

### 1.1 `GET /api/status` — 상태 요약

FE 가 주기적으로 폴링하는 엔드포인트다.

**200**

```json
{
  "agentConnected": true,
  "feConnected": true,
  "extConnected": false,
  "settingsVersion": 4,
  "agentSyncedVersion": 4,
  "agentVersion": "0.4.2",
  "settingsPending": false,
  "activeSession": { "id": 128, "remainingSec": 14 },
  "activeVoiceId": 1,
  "activeCalibId": 2,
  "mcpToolCount": 27
}
```

| 필드 | 의미 |
|---|---|
| `agentConnected` | `/ws/agent` 구독자 1 이상 |
| `feConnected` | `/ws/fe` 구독자 1 이상 |
| `extConnected` | `/ws/ext` 구독자 1 이상 |
| `settingsVersion` | 현재 설정 버전 |
| `agentSyncedVersion` | AI 가 마지막으로 받은 설정 버전. 한 번도 받지 않았으면 `null` |
| `agentVersion` | AI 가 `hello` 로 보낸 버전. 한 번도 접속하지 않았으면 `null` |
| `settingsPending` | `agentSyncedVersion` 이 `null` 이거나 `settingsVersion` 보다 작으면 `true` |
| `activeSession` | 활성 세션 `{id, remainingSec}`. 없으면 `null`. `remainingSec` 은 올림값, 남아 있으면 최소 1 |
| `activeVoiceId` / `activeCalibId` | 사용 중인 보이스 · 시선 보정 프로필 id. 없으면 `null` |
| `mcpToolCount` | 이번 기동에 등록된 도구 수 (`tool.available = 1`) |

### 1.2 `GET /api/settings` — 설정 조회

**200**

```json
{
  "version": 4,
  "updatedAt": "2026-08-31 04:12:07.913",
  "agentSyncedVersion": 4,
  "agentSyncedAt": "2026-08-31 04:12:08.140",
  "agentVersion": "0.4.2",
  "settingsPending": false,
  "settings": {
    "wakeWord": "시아",
    "sessionSeconds": 15,
    "autoStart": true,
    "gazeCursor": false,
    "micDevice": null,
    "cameraDevice": null,
    "micDeviceId": null,
    "cameraDeviceId": null
  }
}
```

`settings` 는 자유 JSON 객체다. FE 가 추가한 키는 그대로 보관 · 반환된다. 아래 알려진 키 8개는 BE 가 타입과 존재를 보장한다.

| 키 | 타입 | 기본값 | 읽는 쪽 · 의미 |
|---|---|---|---|
| `wakeWord` | 비어 있지 않은 문자열 | `"시아"` | AI (호출어 감지). 온보딩 문장은 FE · AI 의 고정 상수라 이 값과 무관하다 |
| `sessionSeconds` | 1 이상 정수 | `15` | BE 세션 유지 시간. 변경은 다음 세션 개시 · 갱신부터 적용 |
| `autoStart` | boolean | `true` | FE 가 집행한다. BE 는 저장 · 중계만 한다 |
| `gazeCursor` | boolean | `false` | AI 가 `true` 일 때만 `gaze_cursor` 를 보낸다 |
| `micDevice` | 문자열 \| `null` | `null` | 마이크 장치 이름 (OS 원문). `null` = 시스템 기본 마이크 |
| `cameraDevice` | 문자열 \| `null` | `null` | 카메라 장치 이름 (OS 원문). `null` = 지정하지 않음 |
| `micDeviceId` | 문자열 \| `null` | `null` | AI (마이크 열기). `GET /api/devices` 가 준 `mics[].id`. `null` = 시스템 기본 마이크 |
| `cameraDeviceId` | 문자열 \| `null` | `null` | AI (카메라 열기). `GET /api/devices` 가 준 `cameras[].id`. `null` = 지정하지 않음 |

- 장치 이름은 OS 가 보고하는 이름 원문이다 (예: `"마이크(Realtek(R) Audio)"`, `"HD Webcam"`).
- 장치 목록 열거는 BE 가 한다 — `GET /api/devices`(§1.35). FE 는 거기서 받은 `name` 과 `id` 를 짝으로 저장한다.
- 이름과 id 는 역할이 다르다. **이름**은 화면 표시와 프로필 장비 라벨용이고, **id** 는 AI 가 실제로 장치를 여는 키다. 이름은 같은 모델이 두 대면 겹칠 수 있어 여는 키로 쓸 수 없다.
- 이름은 프로필의 `deviceLabel` 로 복사되어 장비 교체 자동 맵핑(§1.32)의 키가 된다. 프로필 확정 시 FE 가 `deviceLabel` 을 함께 보내면 그 값이 설정값보다 우선한다.
- 이 네 키는 모두 AI 에게 `settings_changed` 로 그대로 전달된다 — 선택 결과를 AI 에 알리는 별도 엔드포인트는 없다.
- **`null` 의 뜻은 마이크와 카메라가 다르다.** Windows 에는 기본 입력 장치(마이크)가 있지만 **기본 카메라는 없다**. 그래서 마이크의 `null` 은 "시스템 기본 장치를 따른다" 는 지시이고, 카메라의 `null` 은 "고르지 않았다" — AI 가 열거 순서 첫 장치를 연다.
- `wakeWord` 를 바꿔도 호출어 모델(`blob:wakeword`)은 재학습되지 않는다.

### 1.3 `PUT /api/settings` — 설정 교체

부분 갱신이 아니라 통째 교체다. FE 는 GET 으로 받은 `settings` 를 수정해 전부 돌려보낸다.

```json
{
  "settings": {
    "wakeWord": "시아",
    "sessionSeconds": 60,
    "autoStart": true,
    "gazeCursor": true,
    "micDevice": "마이크(Realtek(R) Audio)",
    "micDeviceId": "{0.0.1.00000000}.{a53af75a-d537-4666-9a94-9121beb12019}",
    "cameraDevice": "HD Webcam",
    "cameraDeviceId": "\\\\?\\usb#vid_046d&pid_082d&mi_00#7&1a2b3c4d&0&0000#{e5323777-f976-4f5b-9b55-b94699c46e44}",
    "previewMirror": true
  },
  "updatedAt": "2026-08-31 04:12:07.913"
}
```

| 필드 | 필수 | 규칙 |
|---|:-:|---|
| `settings` | O | JSON 객체. 키가 없으면 본문 전체를 설정으로 본다 |
| `updatedAt` | | 직전 GET 이 준 값. 낙관적 잠금 기준 — 저장분보다 과거면 409. 생략하면 충돌 검사를 하지 않는다 |

**200** — 저장 직후 상태. `GET /api/settings` 와 같은 형태. `version` 이 1 오르고 `updatedAt` 은 서버가 다시 찍는다. 저장 성공 시 AI 에 `settings_changed` 가 즉시 나간다.

알려진 키 처리 규칙:

| 규칙 | 동작 |
|---|---|
| 완전성 | 본문에 **없는** 알려진 키는 기존 값(없으면 기본값)으로 채워 저장한다 |
| 명시적 `null` | `micDevice: null` 처럼 키가 있고 값이 `null` 이면 그대로 저장한다. 채우지 않는다 |
| 타입 안전 | 알려진 키의 타입이 틀리면 저장하지 않고 **400** |
| 미지의 키 | 검사 · 보정하지 않고 그대로 저장한다 |

**400 INVALID_REQUEST**

```json
{ "code": "INVALID_REQUEST", "message": "설정 본문은 JSON 객체여야 합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "세션 유지 시간(sessionSeconds) 설정은 1 이상의 정수여야 합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "마이크(micDevice) 설정은 OS 가 보고하는 장치 이름 문자열이거나 null(시스템 기본)이어야 합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "마이크 장치 ID(micDeviceId) 설정은 GET /api/devices 가 준 장치 식별자 문자열이거나 null(시스템 기본)이어야 합니다" }
```

**409 SETTINGS_STALE** — `updatedAt` 이 현재 저장분보다 **과거**일 때만 난다 (23자 고정폭 UTC 문자열의 문자열 비교). 저장분과 같거나 더 나중인 값은 통과한다. 회복: `GET /api/settings` → 변경분 재적용 → 새 `updatedAt` 으로 재시도.

```json
{ "code": "SETTINGS_STALE", "message": "다른 곳에서 먼저 저장된 설정이 있습니다. 최신 설정을 불러온 뒤 다시 저장해 주세요" }
```

### 1.4 `GET /api/tools` — 도구 사전

```
GET /api/tools
GET /api/tools?all=true
```

| 파라미터 | 기본 | 설명 |
|---|---|---|
| `all` | `false` | `true` 면 이번 기동에 등록되지 않은 도구(`available: false`)도 포함 |

**200** — `name` 오름차순 배열.

```json
[
  {
    "name": "app.launch",
    "description": "등록된 앱을 실행합니다. appRef 는 app.list 또는 context.get 이 준 ref(app:키)만 사용할 수 있으며, 파일 경로를 직접 넘길 수 없습니다.",
    "sessionRequired": true,
    "confirmRequired": false,
    "available": true,
    "syncedAt": "2026-08-31 03:59:11.002"
  }
]
```

| 필드 | 의미 |
|---|---|
| `description` | LLM 에 노출되는 도구 설명 원문 |
| `sessionRequired` | S 플래그 — 활성 세션 필요 |
| `confirmRequired` | C 플래그 — AI 가 호출 전 사용자 동의를 받는다 |
| `available` | 이번 기동에 MCP 서버에 등록됨 |
| `syncedAt` | 마지막 동기화 시각 |

### 1.5 `GET /api/apps/scan` · `POST /api/apps/scan` — 설치 앱 스캔 · 일괄 등록

두 엔드포인트는 같은 스캔 규칙을 쓴다. 시작 메뉴(`%ProgramData%` · `%APPDATA%` 아래 `Microsoft\Windows\Start Menu\Programs`)의 `.lnk` 를 해석해 실행 파일을 찾는다.

| 규칙 | 값 |
|---|---|
| 대상 | `.exe` 를 가리키고 실재하는 바로가기 |
| 중복 | 같은 실행 파일은 1개로 합친다 |
| 제외 | 이름에 `uninstall` · `uninst` · `remove` · `제거` · `updater` · `repair` · `readme` · `help` · `manual` 이 들어가는 바로가기 |
| 상한 | `.lnk` 600개, 결과 200개 |
| 정렬 | 이름 오름차순 |
| 소요 | 수 초. 내부 타임아웃 20초 |

#### `GET /api/apps/scan` — 후보 조회

등록 후보 목록을 돌려준다. DB 를 바꾸지 않는다. 항목을 골라 등록하는 화면이 쓴다.

**200** — 배열.

```json
[
  {
    "name": "Visual Studio Code",
    "execPath": "C:\\Users\\me\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
    "args": "",
    "suggestedKey": "visual-studio-code",
    "registered": false,
    "appKey": null
  },
  {
    "name": "카카오톡",
    "execPath": "C:\\Program Files (x86)\\Kakao\\KakaoTalk\\KakaoTalk.exe",
    "args": "",
    "suggestedKey": "kakaotalk",
    "registered": true,
    "appKey": "kakaotalk"
  }
]
```

| 필드 | 설명 |
|---|---|
| `suggestedKey` | 이름을 `[a-z0-9-]` 로 정규화한 제안값. 전부 떨어지면 exe 파일명, 그것도 안 되면 `app`. 목록 안에서 중복되면 `-2`, `-3` 을 붙인다 |
| `registered` | 같은 `execPath` 가 이미 등록되어 있으면 `true` |
| `appKey` | 등록되어 있으면 그 키, 아니면 `null` |

#### `POST /api/apps/scan` — 스캔 결과 일괄 등록

최초 실행 온보딩에서 FE 가 1회 호출한다. 스캔 결과 중 아직 등록되지 않은 실행 파일을 전부 `app_target` 에 등록한다. 요청 본문은 없다.

| 규칙 | 값 |
|---|---|
| 등록 대상 | `execPath` 가 등록된 앱 어디에도 없는 항목. 경로 비교는 대소문자 무시 완전 일치 |
| `appKey` | 스캔의 `suggestedKey`. 기존 키와 겹치면 `-2`, `-3` … 접미사 |
| `displayName` | 바로가기 이름 (`name`) |
| `args` | 바로가기의 인자 |
| `enabled` | `true` |
| `verifiedAt` | 등록 시각 (스캔이 실재를 확인한 파일만 대상이다) |
| 기존 등록 | 수정하지 않는다. 이미 등록된 실행 파일은 `skipped` 로 센다 |
| 재호출 | 새로 설치된 앱만 추가된다 |

**200**

```json
{
  "scanned": 103,
  "registered": 97,
  "skipped": 6,
  "items": [
    {
      "id": 12,
      "appKey": "visual-studio-code",
      "displayName": "Visual Studio Code",
      "execPath": "C:\\Users\\me\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
      "args": "",
      "verifiedAt": "2026-09-02 03:10:44.120",
      "enabled": true
    }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `scanned` | 스캔 결과 수 |
| `registered` | 이번 호출로 등록된 수 |
| `skipped` | 이미 등록되어 건너뛴 수 |
| `items` | 이번 호출로 등록된 행. §1.6 의 행 형식. 이름 오름차순 |

등록된 앱은 즉시 `app.launch` 대상이 되고 `context.get` · `app.list` 의 `apps` 에 나타난다. 개별 앱을 빼려면 `POST /api/apps` 로 `enabled: false` 를 저장하거나 `DELETE /api/apps/{appKey}` 로 지운다.

### 1.6 `GET /api/apps` — 등록 앱 목록

`app.launch` 가 실행할 수 있는 앱 전체다.

Windows 기본 앱 두 개는 BE 가 기동 때 넣어 두므로 등록 없이 처음부터 목록에 있다 — `notepad`(메모장) · `calc`(계산기). 시작 메뉴 스캔(§1.5)은 이 둘을 찾지 못한다(Store 앱이라 `.lnk` 가 없다). 다른 행과 똑같이 §1.7 로 경로 · 이름 · `enabled` 를 고칠 수 있고, 그 수정은 그대로 남는다. **목록에서 빼려면 §1.9 삭제가 아니라 §1.7 `enabled: false` 다** — 지우면 다음 기동에 다시 생긴다.

**200** — `appKey` 오름차순.

```json
[
  {
    "id": 3,
    "appKey": "chrome",
    "displayName": "Chrome",
    "execPath": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "args": "",
    "verifiedAt": "2026-08-31 03:59:12.410",
    "enabled": true
  }
]
```

`verifiedAt` 이 `null` 이면 마지막 검사 시점에 실행 파일이 없었다.

### 1.7 `POST /api/apps` — 앱 등록 · 수정

같은 `appKey` 가 있으면 갱신한다.

```json
{
  "appKey": "vscode",
  "displayName": "Visual Studio Code",
  "execPath": "C:\\Users\\me\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
  "args": "",
  "enabled": true
}
```

| 필드 | 필수 | 규칙 |
|---|:-:|---|
| `appKey` | O | `^[a-z0-9_-]{1,40}$` |
| `displayName` | O | 공백 불가 |
| `execPath` | O | 공백 불가. 존재 여부는 저장을 막지 않고 `verifiedAt` 으로만 표시한다 |
| `args` | | 생략 시 빈 문자열 |
| `enabled` | | 생략 시 `true` |

**200** — 저장된 행. 경로가 실재하지 않으면 `verifiedAt` 이 `null` 이다.

**400 INVALID_REQUEST**

```json
{ "code": "INVALID_REQUEST", "message": "appKey 는 영문 소문자·숫자·하이픈·언더스코어 1~40자여야 합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "표시 이름(displayName)이 필요합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "실행 파일 경로(execPath)가 필요합니다" }
```

### 1.8 `POST /api/apps/verify` — 경로 검증

두 모드가 있다.

**모드 1 — 등록 앱 재검사.** `verifiedAt` 을 갱신한다.

```json
{ "appKey": "vscode" }
```
```json
{ "appKey": "vscode", "exists": true, "verifiedAt": "2026-08-31 05:22:40.907" }
```

**모드 2 — 등록 전 경로 확인.** DB 를 바꾸지 않는다.

```json
{ "execPath": "C:\\Program Files\\Notepad++\\notepad++.exe" }
```
```json
{ "execPath": "C:\\Program Files\\Notepad++\\notepad++.exe", "exists": true }
```

**404 NOT_FOUND** `{ "code": "NOT_FOUND", "message": "등록되지 않은 앱입니다: vscode" }`
**400 INVALID_REQUEST** `{ "code": "INVALID_REQUEST", "message": "appKey 또는 execPath 가 필요합니다" }`

### 1.9 `DELETE /api/apps/{appKey}` — 앱 등록 해제

**204** 본문 없음. **404 NOT_FOUND** `{ "code": "NOT_FOUND", "message": "등록되지 않은 앱입니다: vscode" }`

### 1.10 `GET /api/gestures` — 제스처 목록

```
GET /api/gestures?page=0&size=20
GET /api/gestures?custom=false
GET /api/gestures?custom=true&page=0&size=20
GET /api/gestures?kind=HAND
GET /api/gestures?dangling=true
```

| 파라미터 | 기본 | 설명 |
|---|---|---|
| `page` | 0 | 0부터 |
| `size` | 20 | 1~100 으로 클램프 |
| `kind` | — | `HAND` / `FACE` |
| `custom` | — | `true` = 커스텀만, `false` = 기본 제공만, 생략 = 전부 |
| `dangling` | `false` | `true` 면 `runnable` 이 `false` 인 것만 |

**200** — `items` 는 `id` 오름차순.

```json
{
  "page": 0,
  "pageSize": 20,
  "total": 12,
  "items": [
    {
      "id": 1,
      "kind": "HAND",
      "context": null,
      "name": "Open_Palm",
      "label": "세션 연장",
      "description": null,
      "repeatable": false,
      "enabled": true,
      "custom": false,
      "createdAt": null,
      "videoUrl": null,
      "runnable": true,
      "steps": [
        { "tool": "session.extend", "args": {}, "delayMs": null, "available": true }
      ]
    },
    {
      "id": 14,
      "kind": "HAND",
      "context": null,
      "name": "손가락 하트",
      "label": "음악 재생",
      "description": "음악 앱 실행 후 재생목록을 연다",
      "repeatable": false,
      "enabled": true,
      "custom": true,
      "createdAt": "2026-03-12 09:30:00.000",
      "videoUrl": "/api/gestures/14/video",
      "runnable": true,
      "steps": [
        { "tool": "app.launch", "args": { "appRef": "app:music" }, "delayMs": null, "available": true },
        { "tool": "files.open", "args": { "path": "C:\\Users\\me\\Music\\집중.m3u" }, "delayMs": 300, "available": true }
      ]
    }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `kind` | `HAND` / `FACE` |
| `context` | 매핑이 걸리는 컨텍스트 (`youtube` / `video`). `null` 이면 컨텍스트 제약 없는 기본 매핑 |
| `enabled` | 켜기/끄기 상태. 꺼지면 AI 감지 제외 + BE 실행 차단 |
| `custom` | `true` = 사용자 등록 제스처, `false` = 기본 제공 |
| `createdAt` | 등록일. 기본 제공은 `null` |
| `videoUrl` | 등록 영상 URL. 없으면 `null` |
| `runnable` | 모든 스텝의 도구가 이번 기동에 등록되어 있으면 `true`. 스텝이 없으면 `false` |
| `steps[].available` | 그 스텝 도구의 가용 여부 |

커스텀 제스처 신규 등록은 REST 가 아니라 WS `macro_assign` 경로다.

### 1.11 `GET /api/gestures/{id}` — 제스처 단건

**200** — §1.10 `items` 원소와 같은 형태. **404 GESTURE_NOT_FOUND**.

### 1.12 `GET /api/gestures/{id}/video` · `GET /api/gestures/{id}/npz` — 등록 영상 · 템플릿 백업

`/video` — **200** `video/webm`. 없는 id 는 **404 GESTURE_NOT_FOUND**. 제스처는 있지만 등록 영상이 없으면 **404** (본문 없음). 사용자 카메라 영상이므로 PC 밖으로 내보내지 않는다.

`/npz` — 커스텀 제스처 템플릿 npz 의 백업 다운로드. 프로필 백업(`GET /api/voices/{id}/npz`)과 같은 역할이다.

**200** `application/octet-stream`, `Content-Disposition: attachment; filename="gesture-{id}.npz"`.
**404 GESTURE_NOT_FOUND** 제스처 없음. **404 BLOB_NOT_FOUND** 기본 제공 제스처 (템플릿 없음).

### 1.13 `PATCH /api/gestures/{id}` — 켜기/끄기

기본 제공 제스처를 포함한 모든 제스처에 허용된다.

```json
{ "enabled": false }
```

**204**. AI 에 `gesture_toggled {name, context, enabled}` 가 나간다.

**400 INVALID_REQUEST** `{ "code": "INVALID_REQUEST", "message": "enabled(true|false) 가 필요합니다" }`. 빈 본문 · 객체가 아닌 본문은 §0.4 의 공통 메시지다.
**404 GESTURE_NOT_FOUND** `{ "code": "GESTURE_NOT_FOUND", "message": "해당 제스처가 없습니다: 999" }`

### 1.14 `PUT /api/gestures/{id}` — 커스텀 제스처 수정

이름 · 라벨 · 설명 · 반복 · 기능(스텝)을 바꾼다. 보낸 필드만 바뀐다. 동작(영상) 재촬영은 WS `reg_start {replaceGestureId}` 경로다.

```json
{
  "name": "손가락 하트",
  "label": "음악 재생",
  "steps": [
    { "tool": "app.launch", "args": { "appRef": "app:music" } },
    { "tool": "volume.step", "args": { "dir": "down" } }
  ]
}
```

| 필드 | 규칙 |
|---|---|
| `name` | 같은 (kind, context) 안에서 중복 불가. 바뀌면 AI 에 `gesture_renamed {id, oldName, newName}`. 템플릿 npz 는 그대로다 |
| `label` · `description` · `repeatable` | 선택 |
| `steps` | 1~5개. 각 단계에 `tool` 필수, `GET /api/tools` 에 있는 이름만. C 도구(`window.close` · `files.delete`) 금지. `[]` 는 400 |

**200** — 수정 직후 단건 (§1.11 형태).

**400 INVALID_REQUEST**

```json
{ "code": "INVALID_REQUEST", "message": "기본 제공 제스처는 켜기/끄기와 기능 변경만 가능합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "이미 같은 이름의 제스처가 있어요" }
```
```json
{ "code": "INVALID_REQUEST", "message": "매크로 단계는 최대 5개까지 쌓을 수 있습니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "사용자 동의가 필요한 도구는 제스처로 실행할 수 없습니다: window.close" }
```
```json
{ "code": "INVALID_REQUEST", "message": "매크로에는 최소 한 단계가 필요합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "각 단계에는 tool 이 필요합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "등록되지 않은 도구입니다: app.lunch" }
```

빈 본문 · 객체가 아닌 본문은 §0.4 의 공통 메시지다.

**404 GESTURE_NOT_FOUND** `{ "code": "GESTURE_NOT_FOUND", "message": "해당 제스처가 없습니다: 999" }`

### 1.15 `DELETE /api/gestures/{id}` — 커스텀 제스처 삭제

**204**. 템플릿 npz 와 등록 영상 파일도 함께 지우고 AI 에 `gesture_removed {id, name}` 이 나간다.

**404 GESTURE_NOT_FOUND** `{ "code": "GESTURE_NOT_FOUND", "message": "해당 제스처가 없습니다: 999" }`
**400 INVALID_REQUEST** `{ "code": "INVALID_REQUEST", "message": "기본 제공 매핑은 삭제할 수 없습니다" }`

### 1.16 `GET /api/tool-calls` — 도구 실행 기록

```
GET /api/tool-calls?from=2026-08-24&to=2026-08-31&outcome=BLOCKED&caller=GESTURE&page=2
```

| 파라미터 | 기본 | 값 |
|---|---|---|
| `from` / `to` | 없음 | `yyyy-MM-dd` 또는 23자 시각 |
| `outcome` | 없음 | `EXECUTED` / `BLOCKED` / `FAILED` |
| `caller` | 없음 | `LLM` / `GESTURE` |
| `page` | 1 | 1 미만은 1 |

**200** — 최신순(`ts DESC, id DESC`), 페이지당 50건.

```json
{
  "page": 1,
  "pageSize": 50,
  "total": 317,
  "items": [
    {
      "id": 316,
      "sessionId": 128,
      "appTargetId": 3,
      "tool": "app.launch",
      "ts": "2026-08-31 05:30:44.120",
      "argsJson": "{\"appRef\":\"app:chrome\"}",
      "caller": "LLM",
      "outcome": "EXECUTED",
      "reason": null,
      "latencyMs": 148
    },
    {
      "id": 315,
      "sessionId": null,
      "appTargetId": null,
      "tool": "scroll.step",
      "ts": "2026-08-31 05:29:58.002",
      "argsJson": "{\"dir\":\"down\",\"amount\":3}",
      "caller": "GESTURE",
      "outcome": "BLOCKED",
      "reason": "세션이 활성화되지 않았습니다",
      "latencyMs": 1
    }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `sessionId` | 세션 없이 실행된 호출은 `null` |
| `appTargetId` | `app.launch` 만 채워진다 |
| `argsJson` | JSON 문자열. 500자를 넘으면 `{"_truncated":<원본 길이>,"_preview":"<앞부분>"}` 로 대체된다 — 항상 파싱 가능하다 |
| `reason` | 차단 · 실패 사유. 255자에서 잘린다. 성공은 `null` |
| `latencyMs` | 게이트 진입부터 반환까지 |

`session.extend` · `session.cancel` 은 기록되지 않는다.

### 1.17 `GET /api/sessions` — 세션 기록

```
GET /api/sessions?from=2026-08-30&page=1
```

| 파라미터 | 기본 | 값 |
|---|---|---|
| `from` / `to` | 없음 | `startedAt` 기준 |
| `page` | 1 | |

**200** — 최신순, 페이지당 50건.

```json
{
  "page": 1,
  "pageSize": 50,
  "total": 42,
  "items": [
    { "id": 128, "startedAt": "2026-08-31 05:30:11.001", "endedAt": "2026-08-31 05:31:41.220", "endReason": "EXPIRED", "toolCallCount": 4 },
    { "id": 127, "startedAt": "2026-08-31 05:12:03.774", "endedAt": null, "endReason": null, "toolCallCount": 0 }
  ]
}
```

`endedAt` · `endReason` 이 `null` 이면 진행 중인 세션이다.

| `endReason` | 뜻 |
|---|---|
| `EXPIRED` | 타이머 만료 |
| `STOPPED` | AI `session_end` 또는 `session.cancel` |
| `WATCHDOG` | 활성 세션이 있는 상태에서 `session_open` 이 와서 강제 종료 |
| `SHUTDOWN` | BE 기동 시 미종료 세션 일괄 정리 |

### 1.18 대시보드 공통 규약

§1.19 ~ §1.23 은 같은 `period` 규약을 쓴다.

| `period` | 버킷 단위 (`bucketUnit`) | 버킷 수 | 구간 |
|---|---|:-:|---|
| `day` (기본) | `HOUR_3` — 00시 · 03시 … 21시 | 8 | 오늘 로컬 00:00 부터 |
| `week` | `DAY` — 요일 라벨 | 7 | 오늘 포함 7일 |
| `month` | `WEEK` — 1주차 ~ 5주차 | 5 | 오늘 포함 최근 7일이 5주차, 7일씩 거슬러 4칸 |
| `year` | `MONTH` — 월 라벨 | 12 | 이번 달 포함 12개월 |

| 규칙 | 내용 |
|---|---|
| 집계 원본 | `usage_event` · `tool_call`. 집계 테이블은 없다 |
| 시각 축 | 로컬 타임존. 서버가 로컬 경계를 UTC 로 환산해 조회한다 |
| 빈 버킷 | 반드시 채운다. 개수는 `0`, 평균값(정확도 · 응답 시간)은 `null` |
| `summary` | 버킷 값의 평균이 아니라 기간 전체 재집계다 |
| `month` 의 주 | 달력 주가 아니라 굴러가는 7일이다 |
| `year` 라벨 | 첫 버킷과 1월 버킷은 `YY년 M월`, 그 밖은 `M월`. `key` 에는 항상 연도가 들어 있다 (`"2025-09"`) |
| 모르는 `period` | **400** `{ "code": "INVALID_REQUEST", "message": "period 는 day \| week \| month \| year 중 하나여야 합니다" }` |

### 1.19 `GET /api/dashboard/overview` — 대시보드 첫 화면

카드 4개를 한 번에 준다. 기간 인자는 없다. 정확도 · 응답 시간 · 사용량은 `week`, 프로그램은 `day` 로 고정이다.

**200**

```json
{
  "generatedAt": "2026-08-31 06:12:44.301",
  "accuracy": { "period": "week", "voice": 0.96, "gaze": 0.91, "motion": 0.89, "sampleCount": 412 },
  "latency": { "period": "week", "simpleMs": 800, "complexMs": 2400, "simpleCount": 64, "complexCount": 56 },
  "usage": {
    "period": "week",
    "bucketUnit": "DAY",
    "buckets": [
      { "key": "2026-08-25", "label": "화", "count": 38 },
      { "key": "2026-08-26", "label": "수", "count": 52 },
      { "key": "2026-08-27", "label": "목", "count": 21 },
      { "key": "2026-08-28", "label": "금", "count": 60 },
      { "key": "2026-08-29", "label": "토", "count": 44 },
      { "key": "2026-08-30", "label": "일", "count": 71 },
      { "key": "2026-08-31", "label": "월", "count": 51 }
    ],
    "total": 337
  },
  "topApps": [
    { "appKey": "chrome", "displayName": "크롬", "count": 17 },
    { "appKey": "slack", "displayName": "슬랙", "count": 16 }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `accuracy.*` | 0.0 ~ 1.0. 표본이 없으면 `null` |
| `latency.*Ms` | 정수 밀리초 |
| `usage.buckets[].count` | 제스처 + 보이스 합산 횟수 |
| `topApps` | 최대 5개. 실행 0회인 앱은 없다. `appKey` · `displayName` 규칙은 §1.23 |

### 1.20 `GET /api/dashboard/accuracy` — 인식 정확도

```
GET /api/dashboard/accuracy?period=day
```

**200**

```json
{
  "period": "day",
  "bucketUnit": "HOUR_3",
  "buckets": [
    { "key": "2026-08-31T00", "label": "00시", "voice": 0.97, "gaze": 0.93, "motion": 0.90, "sampleCount": 12 },
    { "key": "2026-08-31T03", "label": "03시", "voice": null, "gaze": null, "motion": null, "sampleCount": 0 }
  ],
  "summary": { "voice": 0.95, "gaze": 0.92, "motion": 0.90, "sampleCount": 137 }
}
```

| 필드 | 설명 |
|---|---|
| `voice` / `gaze` / `motion` | `usage_event.kind` 가 `voice` / `gaze` / `gesture` 인 이벤트의 `AVG(accuracy)`. 소수점 셋째 자리 반올림. 표본 0 이면 `null` |
| `sampleCount` | 세 계열 합계 표본 수 |

`accuracy IS NULL` 인 행은 분모에서 빠진다. `voice-rejected` 는 `voice` 에 포함되지 않는다.

### 1.21 `GET /api/dashboard/latency` — 평균 응답 시간

```
GET /api/dashboard/latency?period=day
```

`usage_event.kind = 'command'` 이벤트의 `latencyMs` 를 읽는다. 호출어부터 결과까지 사용자가 체감하는 시간이다.

**200**

```json
{
  "period": "day",
  "bucketUnit": "HOUR_3",
  "buckets": [
    { "key": "2026-08-31T00", "label": "00시", "simpleMs": 780, "complexMs": 2410, "simpleCount": 4, "complexCount": 2 },
    { "key": "2026-08-31T03", "label": "03시", "simpleMs": null, "complexMs": null, "simpleCount": 0, "complexCount": 0 }
  ],
  "summary": { "simpleMs": 800, "complexMs": 2300, "overallMs": 1500, "simpleCount": 64, "complexCount": 56 }
}
```

| 필드 | 설명 |
|---|---|
| `simpleMs` / `complexMs` | `complexity` 가 `SIMPLE` / `COMPLEX` 인 이벤트의 `AVG(latency_ms)`, 정수 반올림 |
| `overallMs` | 표본 가중 평균 |
| `complexity` 없는 이벤트 | 이 카드에서 제외된다 |

### 1.22 `GET /api/dashboard/usage` — 제스처 / 보이스 사용량

```
GET /api/dashboard/usage?period=day
```

**200**

```json
{
  "period": "day",
  "bucketUnit": "HOUR_3",
  "buckets": [
    { "key": "2026-08-31T00", "label": "00시", "count": 3, "gesture": 2, "voice": 1 },
    { "key": "2026-08-31T12", "label": "12시", "count": 14, "gesture": 9, "voice": 5 }
  ],
  "summary": {
    "total": 51,
    "average": 2.1,
    "averageUnit": "HOUR",
    "peak": { "key": "2026-08-31T12", "label": "12시", "count": 14 }
  }
}
```

| 필드 | 설명 |
|---|---|
| `count` | `gesture + voice` |
| `average` | `total` 을 아래 분모로 나눈 값 |
| `averageUnit` | 분모의 단위 |
| `peak` | 최다 버킷. 동률이면 먼저 오는 버킷. 전 구간 0 이면 `null` |

| `period` | `averageUnit` | 분모 |
|---|---|:-:|
| `day` | `HOUR` | 24 |
| `week` | `DAY` | 7 |
| `month` | `WEEK` | 5 |
| `year` | `MONTH` | 12 |

`voice-rejected` 는 세지 않는다.

### 1.23 `GET /api/dashboard/apps` — 자주 사용하는 프로그램

```
GET /api/dashboard/apps?period=day&limit=10
```

| 파라미터 | 기본 | 값 |
|---|---|---|
| `period` | `day` | §1.18 |
| `limit` | 10 | 1~20 클램프 |

**200**

```json
{
  "period": "day",
  "items": [
    { "appKey": "chrome", "displayName": "크롬", "count": 17, "share": 0.315 },
    { "appKey": "slack", "displayName": "슬랙", "count": 16, "share": 0.296 }
  ],
  "summary": { "totalLaunches": 54, "topAppKey": "chrome", "topDisplayName": "크롬", "topCount": 17 }
}
```

| 필드 | 설명 |
|---|---|
| `count` | `tool_call` 중 `tool_name = 'app.launch'` 이고 `outcome = 'EXECUTED'` 인 건수 |
| `share` | `count / totalLaunches`, 소수점 3자리 |
| `appKey` | 등록 앱의 `app_key`. 등록 해제된 앱(§1.9)의 실행 기록도 카드에 남는다 — 기록된 호출 인자 `appRef` 가 `app:키` 형태면 그 키로 복원하고, 아니면 `null` |
| `displayName` | 조회 시점의 `app_target.display_name`. 등록 해제된 앱은 `appKey` 와 같은 값이고, 키를 복원할 수 없으면 `등록 해제된 앱` |
| `totalLaunches` | `limit` 으로 잘리기 전 전체 합 |

### 1.24 `GET /api/dashboard/summary` — 기간 집계 (운영 진단용)

```
GET /api/dashboard/summary?days=30
```

| 파라미터 | 기본 | 값 |
|---|---|---|
| `days` | 7 | 1~90 클램프 |

날짜 축은 UTC 다. FE 대시보드 화면은 이 엔드포인트를 쓰지 않는다.

**200**

```json
{
  "days": 7,
  "byOutcome": [
    { "outcome": "EXECUTED", "count": 240 },
    { "outcome": "BLOCKED", "count": 51 },
    { "outcome": "FAILED", "count": 4 }
  ],
  "byCaller": [
    { "caller": "LLM", "count": 201 },
    { "caller": "GESTURE", "count": 116 }
  ],
  "byApp": [
    { "appKey": "chrome", "displayName": "Chrome", "count": 18 }
  ],
  "byTool": [
    { "tool": "scroll.step", "calls": 96, "executed": 88, "successRate": 0.917 },
    { "tool": "files.save", "calls": 0, "executed": 0, "successRate": null }
  ],
  "avgLatencyByKind": [
    { "kind": "voice", "avgLatencyMs": 412.6, "count": 88 }
  ],
  "accuracyByKind": [
    { "kind": "voice", "avgAccuracy": 0.951, "count": 88 },
    { "kind": "gaze", "avgAccuracy": 0.923, "count": 26 },
    { "kind": "gesture", "avgAccuracy": 0.902, "count": 23 }
  ],
  "voiceRejected": 11,
  "emptySessions": 6,
  "totalSessions": 42
}
```

| 필드 | 설명 |
|---|---|
| `byTool` | 카탈로그 전체가 축이다. 호출 0회인 도구도 `calls: 0` 으로 나온다. 이때 `successRate` 는 `null` |
| `successRate` | `executed / calls`, 소수점 3자리 |
| `avgLatencyByKind` | `usage_event` 에서 `latencyMs` 가 있는 이벤트만. 소수점 1자리 |
| `accuracyByKind` | `usage_event` 에서 `accuracy` 가 있는 이벤트만. 소수점 3자리 |
| `voiceRejected` | `kind = 'voice-rejected'` 건수 |
| `emptySessions` | 도구를 한 번도 부르지 않은 세션 수 |

### 1.25 `GET /api/dashboard/timeseries` — 일자별 추이 (운영 진단용)

```
GET /api/dashboard/timeseries?days=7
```

**200** — 오늘 포함 `days` 일. 데이터가 없는 날도 0 으로 채운다. `date` 는 로컬 날짜이며, 하루의 경계는 로컬 자정이다 (§1.19~§1.23 카드와 같은 축).

```json
{
  "days": 7,
  "items": [
    { "date": "2026-08-25", "toolCalls": 0, "sessions": 0, "events": 0 },
    { "date": "2026-08-26", "toolCalls": 12, "sessions": 3, "events": 40 }
  ]
}
```

### 1.26 `GET /api/previews/{tempId}-{take}.webm` — 등록 미리보기 영상

```
GET /api/previews/9f3a2c17-2.webm
```

**200** `video/webm`. URL 은 WS `reg_recorded` 의 `takes[].webmUrl` 을 그대로 쓴다. **404** 파일 없음 (본문 없음).

파일명은 `[a-zA-Z0-9-]+\.webm` 패턴만 허용한다. 사용자 카메라 영상이므로 PC 밖으로 내보내지 않는다.

### 1.27 `GET /api/export/blobs/{name}` — 호출어 모델 npz 백업

`name` 은 `wakeword` 하나다. 프로필 백업은 `GET /api/voices/{id}/npz` · `GET /api/calibs/{id}/npz`, 커스텀 제스처 템플릿 백업은 `GET /api/gestures/{id}/npz` (§1.12) 다.

**200**

```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="wakeword.npz"
```

**404 BLOB_NOT_FOUND** `{ "code": "BLOB_NOT_FOUND", "message": "저장된 데이터가 없습니다: wakeword" }`
**400 INVALID_REQUEST** `{ "code": "INVALID_REQUEST", "message": "알 수 없는 데이터 이름입니다. wakeword 만 사용할 수 있습니다 (커스텀 제스처 템플릿은 /api/agent/gestures/{id}/npz, 시선 보정·보이스는 프로필 API 를 사용하세요)" }`

### 1.28 `DELETE /api/data` — 전체 삭제

**204** 본문 없음. 되돌릴 수 없다.

삭제 범위:

| 대상 | 처리 |
|---|---|
| `tool_call` · `session` · `usage_event` | 전부 삭제 |
| `blob` (wakeword) | 전부 삭제 |
| `voice_profile` · `calib_profile` | 전부 삭제 |
| 커스텀 제스처 · 스텝 · 템플릿 npz · 등록 영상 파일 | 전부 삭제 후 기본 제스처 매핑 11건 복원 |
| 등록 앱 | 전부 삭제 후 Windows 기본 앱 2건(`notepad` · `calc`) 복원 |
| 설정 | 시드값으로 되돌린다. `version` 은 계속 증가한다 |
| 활성 세션 | 종료. 활성 세션이 있었으면 FE · AI 에 `session_state {state: "PASSIVE", reason: "STOPPED"}` 가 나간다 |

완료 후 AI 에 `wipe`, FE 에 `settings_sync` 가 나간다.

### 1.29 보이스 프로필 — `/api/voices/**`

등록 플로우는 WS 다. REST 는 조회 · 이름 변경 · 활성화 · 삭제 · 백업이다. 공통 규칙은 §1.31.

#### `GET /api/voices` — 목록

**200** — 사용 중 먼저, 그다음 등록일 순.

```json
{
  "items": [
    {
      "id": 1,
      "name": "내 목소리 1",
      "active": true,
      "deviceLabel": "마이크(Realtek(R) Audio)",
      "durationSec": 4.2,
      "quality": "양호",
      "noise": "낮음",
      "sampleUrl": "/api/voices/1/sample",
      "createdAt": "2026-03-12 09:30:00.000",
      "lastUsedAt": "2026-08-30 11:02:07.913",
      "accuracy": { "d7": 0.94, "d30": 0.93, "all": 0.92 }
    }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `deviceLabel` | 등록 당시 마이크 이름. 없으면 `null` |
| `sampleUrl` | 재생용 샘플 오디오. 샘플이 없으면 `null` |
| `accuracy` | `usage_event(kind=voice, profile_id)` 의 7일 · 30일 · 전체 평균. 데이터가 없는 창은 `null` |

#### `GET /api/voices/{id}/sample` — 샘플 오디오

**200** `audio/webm` 또는 `audio/wav`. 없으면 **404 PROFILE_NOT_FOUND**.

#### `GET /api/voices/{id}/npz` — 백업 다운로드

**200** `application/octet-stream`, `Content-Disposition: attachment; filename="voice-{id}.npz"`. 없으면 **404 PROFILE_NOT_FOUND**.

#### `PATCH /api/voices/{id}` — 이름 변경

```json
{ "name": "스튜디오 보이스" }
```

**204**. **400 INVALID_REQUEST** `"보이스 이름이 필요합니다"`. **404 PROFILE_NOT_FOUND**.

#### `POST /api/voices/{id}/activate` — 사용으로 설정

**200** `{ "id": 2, "name": "스튜디오 보이스" }`. 이전 활성과 새 활성의 `lastUsedAt` 이 갱신되고, AI 에 `voice_changed {id, sha256}` 가 나간다.

#### `DELETE /api/voices/{id}` — 삭제

**204**. **409 PROFILE_IN_USE**:

```json
{ "code": "PROFILE_IN_USE", "message": "사용 중인 보이스는 삭제할 수 없습니다. 먼저 다른 보이스를 사용으로 설정해 주세요" }
```
```json
{ "code": "PROFILE_IN_USE", "message": "보이스는 최소 1개 이상 남아 있어야 합니다" }
```

#### `GET /api/voice-reg/{tempId}/sample` — 등록 진행 중 샘플

커밋 전 임시 녹음의 재생용이다. WS `voice_review` 의 `sampleUrl` 이 이 경로다. 등록이 끝나거나 취소되면 **404 PROFILE_NOT_FOUND**.

### 1.30 시선 보정 프로필 — `/api/calibs/**`

보정 플로우는 WS 다. 공통 규칙은 §1.31.

#### `GET /api/calibs` — 목록

**200** — 사용 중 먼저, 그다음 등록일 순.

```json
{
  "items": [
    {
      "id": 1,
      "name": "내 보정 1",
      "active": true,
      "deviceLabel": "HD Webcam",
      "screenW": 1920,
      "screenH": 1080,
      "avgErrorPx": 38.0,
      "maxErrorPx": 62.0,
      "grade": "good",
      "createdAt": "2026-03-12 09:30:00.000",
      "lastUsedAt": "2026-08-30 11:02:07.913"
    }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `screenW` / `screenH` | 학습 해상도 |
| `avgErrorPx` / `maxErrorPx` | 평균 · 최대 오차 |
| `grade` | 오차 등급 `excellent \| good \| poor`. 판정 기준은 AI 서버가 관리하고 BE 는 받아 적는다. 등급이 없던 시절에 만든 보정은 `null` |

#### `GET /api/calibs/{id}` — 상세

목록 필드에 `pointsJson` 이 붙는다. 산점도 원본 JSON 문자열이고, `dx, dy` 는 목표점을 원점으로 둔 오차 벡터다.

```json
{ "id": 1, "name": "내 보정 1", "active": true, "deviceLabel": "HD Webcam", "screenW": 1920, "screenH": 1080, "avgErrorPx": 38.0, "maxErrorPx": 62.0, "grade": "good", "createdAt": "2026-03-12 09:30:00.000", "lastUsedAt": "2026-08-30 11:02:07.913", "pointsJson": "[{\"n\":1,\"dx\":11,\"dy\":12}]" }
```

#### `GET /api/calibs/{id}/npz` — 백업 다운로드

**200** `application/octet-stream`, `Content-Disposition: attachment; filename="calib-{id}.npz"`.

#### `PATCH /api/calibs/{id}` — 이름 변경

```json
{ "name": "거실 웹캠" }
```

**204**. **400 INVALID_REQUEST** `"보정 이름이 필요합니다"`.

#### `POST /api/calibs/{id}/activate` — 사용으로 설정

**200** `{ "id": 2, "name": "거실 웹캠" }`. AI 에 `calib_changed {id, sha256, screenW, screenH}` 가 나간다.

#### `DELETE /api/calibs/{id}` — 삭제

**204**. **409 PROFILE_IN_USE**:

```json
{ "code": "PROFILE_IN_USE", "message": "사용 중인 보정은 삭제할 수 없습니다. 먼저 다른 보정을 사용으로 설정해 주세요" }
```
```json
{ "code": "PROFILE_IN_USE", "message": "보정은 최소 1개 이상 남아 있어야 합니다" }
```

### 1.31 프로필 공통 규칙

| 규칙 | 값 |
|---|---|
| 개수 상한 | 종류별 4개 (사용 중 1 + 보관 3) |
| 초과 등록 | WS 가 `voice_reg_denied` / `calib_denied` 로 거절 |
| 첫 프로필 | 자동으로 사용 중 |
| 추가 프로필 | 보관으로 저장. 활성화는 `activate` |
| 기본 이름 | `내 목소리 N` / `내 보정 N`. 비어 있는 가장 작은 N |
| 삭제 | 사용 중 금지 · 마지막 1개 금지 |
| 장비 라벨 | OS 장치 이름 원문. 커밋의 `deviceLabel` → 설정 `micDevice` / `cameraDevice` 순. 둘 다 없으면 `null` 로 저장되고 자동 맵핑 후보에서 빠진다 |
| 최근 사용일 | 활성 전환 시 이전 · 새 활성 모두 갱신 |
| 없는 id | **404 PROFILE_NOT_FOUND** |

### 1.32 `POST /api/devices/remap` — 장비 교체 후 프로필 자동 맵핑

설정에서 마이크 / 카메라를 바꾼 뒤 FE 가 호출한다. `deviceLabel` 은 프로필의 `deviceLabel` 과 완전 일치로 비교한다.

```json
{ "kind": "mic", "deviceLabel": "USB Mic" }
```

| 필드 | 필수 | 규칙 |
|---|:-:|---|
| `kind` | O | `mic` / `camera` |
| `deviceLabel` | O | OS 장치 이름 원문. 빈 문자열 · `null` 은 400 |

**200** — 일치 프로필 수에 따라 세 갈래다.

정확히 1개 → 자동 활성화:

```json
{ "kind": "mic", "deviceLabel": "USB Mic", "activated": { "id": 2, "name": "스튜디오 보이스" }, "matches": [ { "id": 2, "name": "스튜디오 보이스", "active": false, "createdAt": "2026-05-02 14:00:00.000", "lastUsedAt": "2026-08-30 09:00:00.000" } ] }
```

`matches[].active` · `lastUsedAt` 은 자동 활성화 **전** 의 값이다. 전환 결과는 `activated` 만 반영한다.

2개 이상 → 자동 전환하지 않는다. 최근 사용일 내림차순 목록을 준다. 사용자가 고른 뒤 FE 가 `activate` 를 호출한다:

```json
{ "kind": "mic", "deviceLabel": "USB Mic", "activated": null, "matches": [ { "id": 4, "name": "…", "active": false, "createdAt": "…", "lastUsedAt": "…" }, { "id": 2, "name": "…", "active": false, "createdAt": "…", "lastUsedAt": "…" } ] }
```

0개 → `"activated": null, "matches": []`. FE 는 재등록 플로우로 안내한다.

`kind: camera` 의 `matches` 항목에는 `avgErrorPx` 가 추가된다.

**400 INVALID_REQUEST** `"deviceLabel 이 필요합니다"` / `"kind 는 mic 또는 camera 여야 합니다"`. 빈 본문 · 객체가 아닌 본문은 §0.4 의 공통 메시지다.

### 1.33 모델 — `GET /api/models` · `POST /api/models/{name}/redownload`

인식 모델 파일은 BE 가 기동 직후 백그라운드에서 내려받고 sha256 으로 검증한다. 진행 · 완료 · 실패는 WS `model_progress` · `model_downloaded` · `model_error` 로 FE 에 간다.

#### `GET /api/models` — 모델 상태

**200** — `models.json` 의 모델마다 한 줄.

```json
[
  { "name": "whisper-small", "filename": "whisper-small.bin", "fileReady": true, "loaded": true, "downloading": false }
]
```

| 필드 | 의미 |
|---|---|
| `fileReady` | 파일이 있고 sha256 검증을 통과했다 |
| `loaded` | AI 가 `model_loaded` 로 적재를 확인했다 |
| `downloading` | 다운로더가 확보 중이다 |

#### `POST /api/models/{name}/redownload` — 재다운로드

FE 가 `model_error` 를 받은 뒤 사용자 동의를 얻어 호출한다. BE 는 기존 파일을 버리고 다시 받는다. 요청 본문은 없다.

**202**

```json
{ "name": "whisper-small", "status": "DOWNLOADING" }
```

| 규칙 | 값 |
|---|---|
| 비동기 | 응답은 접수만 뜻한다. 진행은 `model_progress`, 완료는 `model_downloaded`, 실패는 `model_error` 로 온다 |
| 재적재 | 다운로드가 끝나고 AI 가 접속 중이면 `model_load` 를 다시 보낸다 |
| 중복 호출 | 이미 받는 중이면 다시 큐에 넣지 않고 202 를 돌려준다 |

**404 NOT_FOUND** `{ "code": "NOT_FOUND", "message": "알 수 없는 모델입니다: whisper-small" }`

### 1.34 `GET /api/captures/{file}` — 캡처 결과물

MCP `screen.capture` · `screen.capture_region` 이 저장한 PNG 를 서빙한다. URL 은 WS `capture_saved` 의 `url` 을 그대로 쓴다.

```
GET /api/captures/capture_20260902_041230.png
```

**200** `image/png`. **404** 파일 없음 (본문 없음).

파일명은 `[A-Za-z0-9_-]+\.png` 패턴만 허용한다. 저장 위치는 `~/Pictures/SIA/` 다. 사용자 화면 이미지이므로 PC 밖으로 내보내지 않는다.

### 1.35 `GET /api/devices` — 고를 수 있는 입력 장치

초기설정과 설정 화면의 마이크 · 카메라 드롭다운을 채운다. 장치 열거는 BE 가 한다.

**200**

```json
{
  "mics": [
    { "name": "마이크(Realtek(R) Audio)", "id": "{0.0.1.00000000}.{a53af75a-d537-4666-9a94-9121beb12019}", "isDefault": true }
  ],
  "cameras": [
    { "name": "HD Webcam", "id": "\\\\?\\usb#vid_046d&pid_082d&mi_00#7&1a2b3c4d&0&0000#{e5323777-f976-4f5b-9b55-b94699c46e44}" }
  ]
}
```

| 필드 | 의미 |
|---|---|
| `mics[].name` · `cameras[].name` | OS 가 보고하는 장치 이름 원문. 설정 `micDevice` / `cameraDevice` 에 그대로 넣는다. 같은 모델을 두 개 꽂으면 이름이 겹칠 수 있다 |
| `mics[].id` | Core Audio 엔드포인트 ID. 설정 `micDeviceId` 에 그대로 넣는다 |
| `cameras[].id` | 장치 인터페이스 경로. 설정 `cameraDeviceId` 에 그대로 넣는다 |
| `mics[].isDefault` | Windows 소리 설정의 기본 입력 장치인지. 목록 안에 최대 하나다 |

카메라 항목에는 `isDefault` 가 없다.

- 마이크는 **연결 · 활성** 상태만 낸다. 뽑힌 장치는 목록에 없다.
- **카메라에 `isDefault` 가 없는 것은 OS 에 기본 카메라가 없기 때문이다.** 마이크의 `isDefault` 는 BE 가 정한 값이 아니라 Core Audio 에 물어본 답(`GET /api/devices` 시점의 기본 입력 장치)인데, 카메라에는 물어볼 API 가 없다. FE 는 카메라 드롭다운에 "기본" 항목을 두는 대신 **목록 첫 항목을 미리 선택**한다.
- 설정에서 카메라의 `null` 은 "시스템 기본" 이 아니라 **"고르지 않았다"** 다 (§1.2). 이 경우 AI 가 열거 순서 첫 장치를 연다.
- 장치를 하나도 못 읽어도 오류가 아니다. 빈 목록(`{"mics": [], "cameras": []}`)이 와도 마이크는 "시스템 기본"으로 진행할 수 있고, 카메라는 고를 수 있는 장치가 없다는 뜻이다.
- `id` 는 이름과 달리 장치마다 유일하고 프로세스 밖에서도 뜻이 유지된다. AI 는 이 값으로 장치를 연다 — 이름은 화면 표시와 프로필 장비 라벨(§1.31)용이다.
- 선택 결과는 `PUT /api/settings`(§1.3) 로 저장한다. 저장 성공 시 BE 가 AI 에 `settings_changed` 로 실어 보내므로 별도 통지 호출은 없다. 이어서 `POST /api/devices/remap`(§1.32) 으로 프로필 자동 맵핑을 돌린다.

---

## 2. REST — AI 용

바이너리(npz · 오디오)와 통계 배치는 WS 가 아니라 REST 로 오간다. 인증은 없다.

### 2.1 `PUT /api/agent/blobs/{name}` — 호출어 모델 npz 업로드

`name` 은 `wakeword` 하나다. 커스텀 제스처 템플릿은 §2.10 · §2.11, 보이스 · 보정은 §2.4 · §2.8 이다.

```
PUT /api/agent/blobs/wakeword
Content-Type: application/octet-stream

<npz 바이너리>
```

| 규칙 | 값 |
|---|---|
| Content-Type | `application/octet-stream`. 다른 값은 **415 INVALID_REQUEST** |
| 크기 | 1바이트 이상 5MB 이하 |
| 멱등성 | 저장분과 sha256 이 같으면 저장 · 통지를 생략한다 |
| 통지 | 실제로 저장된 경우에만 AI 에 `settings_changed` 가 나간다 |

**204** — 저장 성공 또는 동일 내용으로 생략. 둘 다 204 다.

**400 INVALID_REQUEST**

```json
{ "code": "INVALID_REQUEST", "message": "업로드 크기는 1바이트 이상 5MB 이하여야 합니다" }
```
```json
{ "code": "INVALID_REQUEST", "message": "알 수 없는 데이터 이름입니다. wakeword 만 사용할 수 있습니다 (커스텀 제스처 템플릿은 /api/agent/gestures/{id}/npz, 시선 보정·보이스는 프로필 API 를 사용하세요)" }
```

### 2.2 `GET /api/agent/blobs/{name}` — 호출어 모델 npz 다운로드

```
GET /api/agent/blobs/wakeword
If-None-Match: "6f1b1c…d0"
```

**200** — `ETag: "<sha256>"`, `Content-Type: application/octet-stream`, 본문은 npz.
**304 Not Modified** — `If-None-Match` 가 저장분 sha256 과 같을 때. 본문 없음.
**404 BLOB_NOT_FOUND** `{ "code": "BLOB_NOT_FOUND", "message": "저장된 데이터가 없습니다: wakeword" }`
**400 INVALID_REQUEST** — `name` 이 `wakeword` 가 아닐 때. 메시지는 §2.1 과 같다.

`If-None-Match` 는 `"abc"` · `W/"abc"` · `abc` 어느 형태로 보내도 받는다. ETag 값은 sha256 그대로이며 `hello_ack` · `recognition_start` 의 `blobs` 값과 같다.

### 2.3 `POST /api/agent/events` — 통계 이벤트 배치

발화 원문(transcript)은 싣지 않는다.

배열을 그대로 보내거나 `{ "events": [...] }` 로 감싼다.

```json
[
  { "eventUid": "d3b1a0f2-6c1e-4f0a-9d2e-77a1b0c3e401", "kind": "voice", "sessionId": 128, "profileId": 1, "action": "transcribe", "context": "youtube", "latencyMs": 412, "accuracy": 0.93, "payload": { "wordCount": 7 } },
  { "eventUid": "0f9c77aa-2b41-4a10-8f57-1e2d3c4b5a60", "kind": "gesture", "sessionId": 128, "action": "Thumb_Up", "latencyMs": 38, "accuracy": 0.88 },
  { "eventUid": "6a2f01bd-95c4-4d33-8a7e-5b0e9f11c2d7", "kind": "command", "sessionId": 128, "action": "summarize", "latencyMs": 2410, "complexity": "COMPLEX" }
]
```

| 필드 | 필수 | 규칙 |
|---|:-:|---|
| `eventUid` | O | UUID. UNIQUE. 중복은 저장하지 않고 `duplicates` 로 센다 |
| `kind` | O | 자유 문자열. 모르는 값도 그대로 저장한다 |
| `sessionId` | | 존재하지 않는 id 면 `null` 로 낮춰 저장한다 |
| `profileId` | | `kind: voice` 면 활성 보이스 id, `kind: gaze` 면 활성 보정 id. `recognition_start` / `voice_changed` / `calib_changed` 가 준 id |
| `action` / `context` | | 자유 문자열 |
| `latencyMs` | | 정수 밀리초. `kind: command` 는 호출어부터 결과까지의 사용자 체감 시간 |
| `accuracy` | | 0.0 ~ 1.0 실수. 범위 밖이면 그 값만 `null` 로 낮춘다 |
| `complexity` | | `SIMPLE` / `COMPLEX`. 그 외 값은 `null` |
| `payload` | | 객체 또는 문자열. 직렬화 후 1000자를 넘으면 `{"_truncated":<원본 길이>,"_preview":"<앞부분>"}` 로 대체된다 |

`received_at` 은 서버 시각이다.

**200** — 일부가 실패해도 200 이다. 판정은 세 카운터로 한다.

```json
{ "accepted": 2, "duplicates": 0, "rejected": 1 }
```

`rejected` 는 `eventUid` 또는 `kind` 가 없거나 빈 항목, 객체로 변환할 수 없는 항목(배열 원소가 객체가 아님), 저장 중 예외가 난 항목의 수다.

**400 INVALID_REQUEST** `{ "code": "INVALID_REQUEST", "message": "이벤트 배열이 필요합니다 (본문 자체가 배열이거나 events 필드)" }`

#### 대시보드가 읽는 `kind`

| `kind` | 보내는 시점 | 필요한 필드 | 쓰이는 곳 |
|---|---|---|---|
| `voice` | 음성 명령을 1회 인식했을 때 | `accuracy`, `profileId` | 인식 정확도(음성) · 사용량(보이스) · 프로필별 정확도 |
| `gaze` | 시선 추적이 대상을 1회 판정했을 때 | `accuracy`, `profileId` | 인식 정확도(시선) |
| `gesture` | 제스처를 1회 인식했을 때 | `accuracy` | 인식 정확도(모션) · 사용량(제스처) |
| `command` | 사용자 명령 한 건이 끝났을 때 | `latencyMs`, `complexity` | 평균 응답 시간 |
| `voice-rejected` | 화자 게이트가 발화를 폐기했을 때 | — | 진단용 (§1.24 `voiceRejected`) |
| `calibration` | BE 가 `calib_result` 수신 시 스스로 기록 | — | 진단용 |

- 인식 1회 = 이벤트 1건이다. 같은 발화를 부분 결과마다 보내지 않는다.
- 정확도와 사용량은 같은 이벤트에서 집계된다. 정확도만 따로 보내는 이벤트를 만들지 않는다.
- `voice-rejected` 는 사용자 화면의 카드 어디에도 들어가지 않는다.
- `stt` 는 `voice` 의 별칭으로 읽는다. 새로 보내는 쪽은 `voice` 를 쓴다.

#### `complexity` 판정

| 값 | 기준 |
|---|---|
| `SIMPLE` | 도구 한 번으로 끝난 명령 |
| `COMPLEX` | LLM 추론이나 다단계 도구 호출이 포함된 명령 |

AI 가 정한다. BE 는 추측하지 않으며, `complexity` 가 없는 `command` 이벤트는 평균 응답 시간 카드에서 제외된다.

### 2.4 `PUT /api/agent/voices/{tempId}/npz` — 등록 중 임베딩 업로드

WS `voice_captured` 를 보내기 전에 올린다. `Content-Type: application/octet-stream`, 1바이트 ~ 10MB.

**204**. `tempId` 가 진행 중 등록과 다르면 **404 PROFILE_NOT_FOUND**. 크기 위반은 **400**. `Content-Type` 이 `application/octet-stream` 이 아니면 **415 INVALID_REQUEST**.

### 2.5 `PUT /api/agent/voices/{tempId}/sample` — 등록 중 샘플 오디오 업로드

`Content-Type` 이 그대로 재생 MIME 이 된다 (`audio/webm` 또는 `audio/wav`). 없으면 `audio/webm` 으로 저장한다. WS `voice_captured` 전에 올린다. 1바이트 ~ 10MB.

**204**. **404 PROFILE_NOT_FOUND**.

### 2.6 `PUT /api/agent/voices/active/sample` — 활성 보이스 샘플 갱신

`PUT /api/agent/voices/{tempId}/sample` (§2.5) 의 `tempId` 자리에 `active` 를 쓴 것이다. 화자 인식이 성공할 때마다 마지막 발화 오디오로 활성 프로필의 재생 샘플을 교체한다.

```
PUT /api/agent/voices/active/sample
Content-Type: audio/webm

<오디오 바이너리>
```

| 규칙 | 값 |
|---|---|
| 크기 | 검사하지 않는다 |
| MIME | `Content-Type` 값이 그대로 `sample_mime` 이 된다. 생략하면 `null` 로 저장하며 기본값을 채우지 않는다 |

**204**. 활성 프로필이 없으면 **404 PROFILE_NOT_FOUND** `"사용 중인 보이스가 없습니다"`.

### 2.7 `GET /api/agent/voices/active/npz` — 활성 보이스 다운로드

WS `voice_changed` 를 받으면 여기서 갈아끼운다. `ETag` = sha256, `If-None-Match` → **304**.

**200** `application/octet-stream`. 활성 프로필이 없으면 **404 PROFILE_NOT_FOUND**.

### 2.8 `PUT /api/agent/calibs/{tempId}/npz` — 보정 npz 업로드

WS `calib_result` 를 보내기 전에 올린다. `X-Screen: WxH` 는 필수다. 학습 해상도가 프로필에 저장된다. 1바이트 ~ 5MB.

```
PUT /api/agent/calibs/9f3a2c17/npz
Content-Type: application/octet-stream
X-Screen: 1920x1080
```

**204**. `X-Screen` 없음 · 형식 오류 → **400**. `tempId` 불일치 → **404 PROFILE_NOT_FOUND**. `Content-Type` 이 `application/octet-stream` 이 아니면 **415 INVALID_REQUEST**. 재측정 후 다시 올리면 이전 업로드를 대체한다.

### 2.9 `GET /api/agent/calibs/active/npz` — 활성 보정 다운로드

WS `calib_changed` 를 받으면 여기서 갈아끼운다. `ETag` / **304** 규칙은 §2.7 과 같다.

`X-Screen: WxH` 를 보내면 학습 해상도와 대조한다. 불일치면 **409**:

```json
{ "code": "CALIB_RESOLUTION_MISMATCH", "message": "사용 중인 보정은 1920x1080 해상도에서 만들어졌습니다. 시선 보정을 다시 진행해 주세요" }
```

`X-Screen` 형식이 틀리면 **400 INVALID_REQUEST** `"X-Screen 형식은 '1920x1080' 이어야 합니다"`. 해상도 대조는 `If-None-Match` 판정보다 먼저다 — 불일치면 ETag 가 같아도 304 가 아니라 409 다.

활성 프로필이 없으면 **404 PROFILE_NOT_FOUND**. 판정 순서는 404 → 400 → 409 → 304 → 200 이다.

### 2.10 `PUT /api/agent/gestures/{tempId}/npz` — 등록 중 제스처 템플릿 업로드

WS `reg_captured` 를 보내기 전에 올린다. `Content-Type: application/octet-stream`, 1바이트 ~ 5MB. 확정 전이라 BE 메모리에만 있고, FE 의 `macro_assign` 이 `gesture` 행으로 확정한다. 다시 올리면 이전 업로드를 대체한다.

```
PUT /api/agent/gestures/9f3a2c17/npz
Content-Type: application/octet-stream

<npz 바이너리>
```

**204**. `tempId` 가 진행 중 등록과 다르면 **404 GESTURE_NOT_FOUND**. 크기 위반은 **400 INVALID_REQUEST**. `Content-Type` 이 `application/octet-stream` 이 아니면 **415 INVALID_REQUEST**.

```json
{ "code": "GESTURE_NOT_FOUND", "message": "진행 중인 제스처 등록이 없습니다: 9f3a2c17" }
```

### 2.11 `GET /api/agent/gestures/{id}/npz` — 제스처 템플릿 다운로드

WS `gesture_registered {id, sha256}` 를 받은 뒤, 그리고 `blobs.gestures` 와 로컬 캐시의 sha256 이 다를 때 내려받는다. `ETag` = sha256, `If-None-Match` → **304**.

```
GET /api/agent/gestures/14/npz
If-None-Match: "8c22b1de44a0…"
```

**200** `application/octet-stream`. 제스처가 없으면 **404 GESTURE_NOT_FOUND**, 기본 제공 제스처(템플릿 없음)면 **404 BLOB_NOT_FOUND**. `id` 는 숫자여야 한다 — 숫자가 아닌 값은 같은 경로 패턴의 `PUT /api/agent/gestures/{tempId}/npz` 에 걸려 메서드 불일치로 처리되므로 **405 INVALID_REQUEST** `"요청 형식이 올바르지 않습니다"` 다.

```json
{ "code": "BLOB_NOT_FOUND", "message": "저장된 제스처 템플릿이 없습니다: 3" }
```

---

## 3. MCP 도구 30개

### 3.1 호출 · 반환 형식 요약

전송 · 인증 · 게이트 규칙의 정의는 [프로토콜.md §7](프로토콜.md#7-mcp-mcp--도구-호출) 이다. 아래는 도구 명세를 읽기 위한 요약이다.

- 호출: `tools/call` `{ "name": "<도구>", "arguments": { ... } }`. 응답의 `result` 가 `CallToolResult` 다. 이 절의 응답 예시는 `result` 안쪽만 보인다.
- 성공: `isError: false`. 데이터가 있으면 `structuredContent` 가 정본이고 `content[0].text` 는 그 JSON 직렬화다. 데이터가 없으면 `content[0].text` 가 `"실행했습니다"` 이고 `structuredContent` 는 없다.
- 실패 · 차단: `isError: true`. `content[0].text` 는 LLM 에 들어가는 한국어 완결 문장, `structuredContent` 는 `{code, message}`. 사용자에게 보여 줄 문장은 AI 가 WS `notice {message}` 로 보내고 FE 가 표시한다.
- **S** = 활성 세션 필요. 없으면 `SESSION_REQUIRED`. **C** = AI 가 호출 전 사용자 동의를 받는다.
- 세션 없음 실패 응답은 모든 S 도구에 공통이다.

```json
{ "content": [{ "type": "text", "text": "세션이 활성화되지 않았습니다" }], "isError": true, "structuredContent": { "code": "SESSION_REQUIRED", "message": "세션이 활성화되지 않았습니다" } }
```

| `code` | 뜻 |
|---|---|
| `SESSION_REQUIRED` | 활성 세션 없음 |
| `REF_NOT_FOUND` | `win:N` / `app:key` 를 찾을 수 없음 |
| `APP_NOT_REGISTERED` | 등록되지 않은 앱 |
| `APP_PATH_INVALID` | 등록된 실행 파일 없음 |
| `ELEVATED_WINDOW` | 관리자 권한 창 |
| `FILE_NOT_FOUND` | 파일 없음 |
| `INVALID_REQUEST` | 인자 형식 오류 — 같은 인자로 재시도하면 또 실패한다. 인자를 고쳐 다시 호출해야 한다 |
| `FAILED` | 그 외 실패 (실행 자체가 실패) |

`code` 는 위 8개뿐이다. 앞의 6개는 정책 게이트가 막은 것으로 `tool_call.outcome = BLOCKED` 이고, `INVALID_REQUEST` 와 `FAILED` 는 둘 다 `outcome = FAILED` 로 기록된다 — 기록의 어휘는 세 값(`EXECUTED` · `BLOCKED` · `FAILED`)뿐이고, `INVALID_REQUEST` 는 LLM 이 읽는 결과 코드에만 나타난다.

`INVALID_REQUEST` 가 나는 자리는 다음과 같다.

| 도구 | 조건 | `message` |
|---|---|---|
| `window.resize` | 모르는 프리셋 | `지원하지 않는 창 크기 프리셋입니다: <preset> (LEFT_HALF\|RIGHT_HALF\|CENTER)` |
| `explorer.items` | 탐색기 창이 아님 | `지정한 창은 파일 탐색기 창이 아닙니다. context.get으로 탐색기 창의 ref를 확인하세요` |
| `explorer.items` | 포그라운드 창 없음 | `포그라운드 창이 없습니다` |
| `scroll.step` | 모르는 방향 | `지원하지 않는 스크롤 방향입니다: <dir> (up\|down\|left\|right)` |
| `volume.step` | 모르는 방향 | `지원하지 않는 볼륨 방향입니다: <dir> (up\|down)` |
| `volume.set` | `level` 누락 | `볼륨 값(level)이 필요합니다 (0~100)` |
| `files.open` | 빈 경로 | `열 파일의 절대 경로가 필요합니다` |
| `files.open` | 상대 경로 | `파일 경로는 절대 경로여야 합니다: <path>` |
| `files.save` | 이름 부적합 | `저장할 파일 이름이 올바르지 않습니다` |
| `screen.capture_region` | 좌표 누락 · 빈 영역 · 화면 밖 영역 | §3.21 |

### 3.2 `context.get` — 화면 상황 스냅샷

창 · 앱을 조작하기 전에 먼저 호출한다. 호출 시점에 창 스냅샷이 갱신되므로 여기서 받은 `ref` 는 곧바로 유효하다.

요청 `{}`

```json
{
  "content": [{ "type": "text", "text": "{\"contextChain\":[\"youtube\",\"video\",\"base\"], …}" }],
  "isError": false,
  "structuredContent": {
    "contextChain": ["youtube", "video", "base"],
    "foreground": { "ref": "win:1", "title": "고양이 브이로그 - YouTube - Chrome", "app": "chrome" },
    "windows": [
      { "ref": "win:1", "title": "고양이 브이로그 - YouTube - Chrome", "app": "chrome", "state": "MAXIMIZED" },
      { "ref": "win:2", "title": "보고서.docx - Word", "app": "winword", "state": "NORMAL" },
      { "ref": "win:3", "title": "다운로드 - 파일 탐색기", "app": "explorer", "state": "NORMAL" }
    ],
    "apps": [
      { "ref": "app:chrome", "name": "Chrome" },
      { "ref": "app:vscode", "name": "Visual Studio Code" }
    ],
    "volume": { "level": 33, "muted": false },
    "capabilities": ["window", "scroll", "app", "media", "files"]
  }
}
```

| 필드 | 설명 |
|---|---|
| `contextChain` | 포그라운드 창 제목에 `youtube`(대소문자 무시)가 있으면 `["youtube","video","base"]`, 아니면 `["base"]` |
| `foreground` | 포그라운드 창. 없거나 스냅샷에 없으면 `null` |
| `windows[].ref` | 1부터 시작하는 순번. 호출마다 다시 매겨진다 |
| `windows[].app` | 프로세스 실행 파일 이름 (확장자 없음) |
| `windows[].state` | `NORMAL` / `MINIMIZED` / `MAXIMIZED` |
| `apps` | `enabled = 1` 인 등록 앱. `displayName` 오름차순 |
| `volume` | 현재 시스템 볼륨 `{level 0~100, muted}`. 출력 장치가 없거나 조회에 실패하면 `null`. 상대적인 요청("조금 줄여줘")을 `volume.set` 의 절대값으로 옮길 때 쓴다 |
| `capabilities` | 고정 5개 |

`ref` 는 호출마다 재발급된다. 조작 직전에 `context.get` 또는 `window.list` 로 다시 받는다. 만료된 ref 는 `REF_NOT_FOUND` 로 실패한다.

### 3.3 `app.list` — 실행 가능한 앱

요청 `{}`

```json
{ "content": [{ "type": "text", "text": "{\"apps\":[{\"ref\":\"app:chrome\",\"name\":\"Chrome\"}]}" }], "isError": false, "structuredContent": { "apps": [{ "ref": "app:chrome", "name": "Chrome" }] } }
```

등록된 앱이 없으면 `{"apps":[]}` 다.

### 3.4 `app.launch` — 앱 실행 · S

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `appRef` | O | `app:<key>`. `app:` 접두사 없이 `<key>` 만 넘겨도 받는다. 파일 경로는 넘길 수 없다 |

```json
{ "appRef": "app:chrome" }
```
```json
{ "content": [{ "type": "text", "text": "{\"ok\":true,\"pid\":18240}" }], "isError": false, "structuredContent": { "ok": true, "pid": 18240 } }
```

`pid` 는 실행된 프로세스 id 다. 참고값이며 후속 창 조작은 `context.get` 의 ref 로 한다.

| 실패 | `code` | `message` |
|---|---|---|
| 미등록 · 비활성 | `APP_NOT_REGISTERED` | 등록되지 않은 앱입니다. app.list로 실행 가능한 앱을 확인하세요 |
| 실행 파일 없음 | `APP_PATH_INVALID` | 앱 실행 파일을 찾을 수 없습니다. 설정에서 경로를 다시 등록해주세요 |
| `appRef` 가 없거나 비었거나 `app:` 만 있음 | `REF_NOT_FOUND` | 대상을 찾을 수 없습니다. context.get으로 목록을 다시 확인하세요 |
| 실행 실패 | `FAILED` | 앱 실행에 실패했습니다. 잠시 후 다시 시도해주세요 |

`win:1` 처럼 종류가 다른 ref 는 접두사 없는 키로 취급되어 `APP_NOT_REGISTERED` 로 실패한다.

### 3.5 `window.list` — 창 재조회

요청 `{}`

```json
{ "content": [{ "type": "text", "text": "{\"windows\":[…]}" }], "isError": false, "structuredContent": { "windows": [ { "ref": "win:1", "title": "고양이 브이로그 - YouTube - Chrome", "app": "chrome", "state": "MAXIMIZED" } ] } }
```

보이는 창 중 제목이 있는 창만 포함한다. 도구 창(`WS_EX_TOOLWINDOW`)은 제외한다. Z 순서(앞쪽 먼저)를 유지한다.

### 3.6 `window.focus` / `window.minimize` / `window.maximize` / `window.restore` · S

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `winRef` | O | `win:N` |

```json
{ "winRef": "win:2" }
```
```json
{ "content": [{ "type": "text", "text": "실행했습니다" }], "isError": false }
```

| 실패 | `code` | `message` |
|---|---|---|
| 없는 ref | `REF_NOT_FOUND` | 대상을 찾을 수 없습니다. context.get으로 목록을 다시 확인하세요 |
| 관리자 권한 창 (`window.focus` 만) | `ELEVATED_WINDOW` | 관리자 권한으로 실행된 창은 제어할 수 없습니다 |

`window.minimize` · `window.maximize` · `window.restore` 는 `ELEVATED_WINDOW` 로 실패하지 않는다.

### 3.7 `window.resize` — 크기 · 위치 프리셋 · S

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `winRef` | O | `win:N` |
| `preset` | O | `LEFT_HALF` / `RIGHT_HALF` / `CENTER`. 대소문자를 가리지 않는다 |

```json
{ "winRef": "win:2", "preset": "LEFT_HALF" }
```
```json
{ "content": [{ "type": "text", "text": "실행했습니다" }], "isError": false }
```

| 실패 | `code` | `message` |
|---|---|---|
| 없는 ref | `REF_NOT_FOUND` | 대상을 찾을 수 없습니다. context.get으로 목록을 다시 확인하세요 |
| 관리자 권한 창 | `ELEVATED_WINDOW` | 관리자 권한으로 실행된 창은 제어할 수 없습니다 |
| 모르는 프리셋 | `INVALID_REQUEST` | 지원하지 않는 창 크기 프리셋입니다: TOP (LEFT_HALF\|RIGHT_HALF\|CENTER) |

### 3.8 `window.close` — 창 닫기 · S · C

AI 는 호출 전에 사용자 동의를 받는다. BE 는 동의가 끝난 요청으로 보고 바로 닫는다.

```json
{ "winRef": "win:2" }
```
```json
{ "content": [{ "type": "text", "text": "{\"closed\":true}" }], "isError": false, "structuredContent": { "closed": true } }
```

실패는 `REF_NOT_FOUND` · `ELEVATED_WINDOW` 다 (문장은 §3.6 과 같다).

### 3.9 `window.next` / `window.prev` — 창 순환 · S

요청 `{}`. 스냅샷을 갱신한 뒤 포그라운드 기준으로 다음 / 이전 창을 포커스한다. 끝에서 순환한다. 포그라운드가 목록에 없으면 첫 창으로 간다.

```json
{ "content": [{ "type": "text", "text": "{\"focused\":{…}}" }], "isError": false, "structuredContent": { "focused": { "ref": "win:3", "title": "다운로드 - 파일 탐색기", "app": "explorer", "state": "NORMAL" } } }
```

창이 하나도 없으면 `REF_NOT_FOUND` + `"전환할 창이 없습니다"`. 전환 대상이 관리자 권한 창이면 포커스 단계에서 `ELEVATED_WINDOW` 다 (문장은 §3.6 과 같다).

### 3.10 `explorer.items` — 탐색기 항목

"이 파일" 류 지시어를 절대 경로로 바꾸는 통로다. 읽기 전용이며 세션이 필요 없다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `winRef` | | `win:N`. 생략하면 포그라운드 창 |

```json
{ "winRef": "win:3" }
```
```json
{
  "content": [{ "type": "text", "text": "{\"folder\":\"C:\\\\Users\\\\me\\\\Downloads\", …}" }],
  "isError": false,
  "structuredContent": {
    "folder": "C:\\Users\\me\\Downloads",
    "items": [
      { "name": "보고서.docx", "path": "C:\\Users\\me\\Downloads\\보고서.docx", "selected": true, "bounds": { "x": 412, "y": 260, "w": 180, "h": 24 } },
      { "name": "사진.png", "path": "C:\\Users\\me\\Downloads\\사진.png", "selected": false, "bounds": { "x": 412, "y": 288, "w": 180, "h": 24 } },
      { "name": "설치파일.exe", "path": "C:\\Users\\me\\Downloads\\설치파일.exe", "selected": false, "bounds": null }
    ],
    "count": 3,
    "truncated": false
  }
}
```

| 필드 | 설명 |
|---|---|
| `folder` | 창이 보고 있는 폴더의 절대 경로. 특수 폴더면 `null` 일 수 있다 |
| `items[].selected` | 탐색기에서 현재 선택된 항목 |
| `items[].bounds` | 화면 픽셀 사각형 (가상 스크린 물리 픽셀). 얻지 못하면 `null` |
| `count` | 폴더의 전체 항목 수 |
| `truncated` | 300개 상한을 넘겨 잘렸으면 `true` |

| 실패 | `code` | `message` |
|---|---|---|
| 탐색기 창이 아님 | `INVALID_REQUEST` | 지정한 창은 파일 탐색기 창이 아닙니다. context.get으로 탐색기 창의 ref를 확인하세요 |
| 포그라운드 창 없음 | `INVALID_REQUEST` | 포그라운드 창이 없습니다 |

시선 좌표와 `bounds` 의 교차 판정은 AI 가 한다 ([프로토콜.md §7.5](프로토콜.md#75-시선--bounds-교차-규칙)).

### 3.11 `scroll.step` — 스크롤 · S

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `dir` | O | `up` / `down` / `left` / `right` |
| `amount` | | 1~10. 생략 시 3. 범위 밖 값은 거절하지 않고 1~10 으로 클램프한다 |

```json
{ "dir": "down", "amount": 7 }
```
```json
{ "content": [{ "type": "text", "text": "실행했습니다" }], "isError": false }
```

알 수 없는 방향은 `INVALID_REQUEST` `"지원하지 않는 스크롤 방향입니다: <dir> (up|down|left|right)"`. 포커스된 창이 대상이다.

### 3.12 `media.play_pause` / `media.mute_toggle` / `media.next` / `media.prev` · S

요청 `{}`. 실행 경로가 `via` 로 돌아온다.

```json
{ "content": [{ "type": "text", "text": "{\"via\":\"youtube\"}" }], "isError": false, "structuredContent": { "via": "youtube" } }
```
```json
{ "content": [{ "type": "text", "text": "{\"via\":\"media_key\"}" }], "isError": false, "structuredContent": { "via": "media_key" } }
```

| 도구 | 포그라운드가 유튜브일 때 (창 포커스 후 단축키) | 그 외 (시스템 미디어 키) |
|---|---|---|
| `media.play_pause` | `k` | PLAY_PAUSE |
| `media.mute_toggle` | `m` | MUTE |
| `media.next` | `Shift+n` | NEXT |
| `media.prev` | `Shift+p` | PREV |

### 3.13 `volume.step` — 시스템 볼륨 한 단계 · S

한 단계씩만 움직인다. 값을 정해 맞출 때는 §3.22 `volume.set` 을 쓴다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `dir` | O | `up` / `down` |

```json
{ "dir": "up" }
```
```json
{ "content": [{ "type": "text", "text": "실행했습니다" }], "isError": false }
```
```json
{ "content": [{ "type": "text", "text": "지원하지 않는 볼륨 방향입니다: louder (up|down)" }], "isError": true, "structuredContent": { "code": "INVALID_REQUEST", "message": "지원하지 않는 볼륨 방향입니다: louder (up|down)" } }
```

### 3.14 `files.open` — 기본 프로그램으로 파일 열기 · S

Windows 기본 연결 프로그램으로 연다. 내용을 바꾸지 않는다. 제스처 매크로의 "파일 실행" 단계가 이 도구를 쓴다. 경로는 등록 화면의 파일 선택기가 확정해 `gesture_step.args_json` 에 저장된다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `path` | O | 절대 경로 |

```json
{ "path": "C:\\Users\\me\\Documents\\회의록.txt" }
```
```json
{ "content": [{ "type": "text", "text": "{\"opened\":true,\"path\":\"C:\\\\Users\\\\me\\\\Documents\\\\회의록.txt\"}" }], "isError": false, "structuredContent": { "opened": true, "path": "C:\\Users\\me\\Documents\\회의록.txt" } }
```

| 실패 | `code` | `message` |
|---|---|---|
| 빈 경로 | `INVALID_REQUEST` | 열 파일의 절대 경로가 필요합니다 |
| 상대 경로 | `INVALID_REQUEST` | 파일 경로는 절대 경로여야 합니다: <path> |
| 파일 없음 | `FILE_NOT_FOUND` | 파일을 찾을 수 없습니다. 제스처 설정에서 파일을 다시 지정해 주세요 |
| 열기 실패 | `FAILED` | 파일을 열지 못했습니다. 잠시 후 다시 시도해주세요 |

### 3.15 `files.delete` — 휴지통 이동 · S · C

완전 삭제가 아니라 휴지통 이동이다. AI 는 호출 전에 사용자 동의를 받는다. BE 는 재확인하지 않는다. `paths` 는 절대 경로 배열이며 디렉터리를 주면 그 아래가 통째로 이동한다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `paths` | O | 절대 경로 문자열 배열 |

```json
{ "paths": ["C:\\Users\\me\\Downloads\\보고서.docx", "C:\\Users\\me\\Downloads\\사진.png"] }
```

전부 성공:

```json
{ "content": [{ "type": "text", "text": "{\"trashed\":2,\"failed\":[]}" }], "isError": false, "structuredContent": { "trashed": 2, "failed": [] } }
```

일부 실패 — 개별 실패는 `failed` 목록이다. `isError` 는 `false` 다.

```json
{ "content": [{ "type": "text", "text": "{\"trashed\":1,\"failed\":[\"C:\\\\Users\\\\me\\\\Downloads\\\\사진.png — 파일을 찾을 수 없습니다\"]}" }], "isError": false, "structuredContent": { "trashed": 1, "failed": ["C:\\Users\\me\\Downloads\\사진.png — 파일을 찾을 수 없습니다"] } }
```

`failed` 항목은 `<경로> — <사유>` 문자열이다.

| 사유 | 조건 |
|---|---|
| 파일을 찾을 수 없습니다 | 경로가 없다 |
| 경로가 비어 있습니다 | 빈 문자열 (항목은 `(빈 경로) — …`) |
| 이 환경에서는 휴지통 이동을 지원하지 않습니다 | 휴지통을 쓸 수 없는 환경 |
| 휴지통 이동에 실패했습니다 | OS 가 이동을 거부했다, 또는 이동 중 예외에 메시지가 없다 |
| <예외 메시지> | 이동 중 예외 (권한 · 잠금 등). 예외의 메시지가 그대로 사유가 된다 |

`paths` 가 비어 있으면 `{"trashed":0,"failed":[]}` 로 끝난다.

### 3.16 `files.save` — 텍스트 파일 저장 · S

저장 위치는 `~/Documents/SIA/` 하나다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `name` | O | 파일 이름. 경로 구분자 · `..` · Windows 금지 문자(`< > : " \| ? *`) · 제어 문자는 제거되고 끝의 점 · 공백은 잘린다 |
| `content` | | 저장할 내용. 없으면 빈 파일 |

```json
{ "name": "회의록.txt", "content": "1. 프로토콜 확정\n2. 세션 15초 유지" }
```
```json
{ "content": [{ "type": "text", "text": "{\"path\":\"C:\\\\Users\\\\me\\\\Documents\\\\SIA\\\\회의록.txt\"}" }], "isError": false, "structuredContent": { "path": "C:\\Users\\me\\Documents\\SIA\\회의록.txt" } }
```

같은 이름이 있으면 `회의록 (1).txt` 처럼 번호를 붙인다.

| 실패 | `code` | `message` |
|---|---|---|
| 이름 부적합 | `INVALID_REQUEST` | 저장할 파일 이름이 올바르지 않습니다 |
| 저장 실패 | `FAILED` | 파일 저장에 실패했습니다. 잠시 후 다시 시도해주세요 |

### 3.17 `system.lock` — 화면 잠금 · S

Windows 세션을 잠근다 (`LockWorkStation`). 로그아웃 · 종료가 아니므로 작업 내용은 남는다. 제스처 매크로에 넣을 수 있으며, 잠금 직후 입력이 잠금 화면으로 가므로 마지막 스텝에 둔다.

요청 `{}`

```json
{ "content": [{ "type": "text", "text": "{\"locked\":true}" }], "isError": false, "structuredContent": { "locked": true } }
```

### 3.18 `session.extend` — 세션 연장

유효 명령을 처리한 직후에만 호출한다. WS `session_renew` 와 같은 동작이다. `tool_call` 기록과 `tool_result` 를 남기지 않는다.

요청 `{}`

```json
{ "content": [{ "type": "text", "text": "{\"remainingSec\":15,\"deadlineMs\":1788148417913}" }], "isError": false, "structuredContent": { "remainingSec": 15, "deadlineMs": 1788148417913 } }
```

활성 세션이 없으면 `SESSION_REQUIRED`.

### 3.19 `session.cancel` — 세션 종료

요청 `{}`. FE · AI 양쪽에 `session_state(PASSIVE)` 가 push 된다. `tool_call` 기록과 `tool_result` 를 남기지 않는다.

```json
{ "content": [{ "type": "text", "text": "{\"state\":\"PASSIVE\",\"reason\":\"STOPPED\"}" }], "isError": false, "structuredContent": { "state": "PASSIVE", "reason": "STOPPED" } }
```

활성 세션이 없으면 `SESSION_REQUIRED`.

### 3.20 `screen.capture` — 화면 캡처 저장 · S

화면 또는 창을 PNG 로 저장하고 FE 에 `capture_saved` 를 보낸다. 인식용 스냅샷이 아니라 사용자가 보관할 결과물이다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `winRef` | | `win:N`. 주면 그 창의 화면 사각형, 생략하면 전체 가상 스크린 |

```json
{ "winRef": "win:2" }
```
```json
{ "content": [{ "type": "text", "text": "{\"path\":\"C:\\\\Users\\\\me\\\\Pictures\\\\SIA\\\\capture_20260902_041230.png\",\"url\":\"/api/captures/capture_20260902_041230.png\",\"width\":1920,\"height\":1080}" }], "isError": false, "structuredContent": { "path": "C:\\Users\\me\\Pictures\\SIA\\capture_20260902_041230.png", "url": "/api/captures/capture_20260902_041230.png", "width": 1920, "height": 1080 } }
```

| 필드 | 설명 |
|---|---|
| `path` | 저장된 PNG 의 절대 경로. 위치는 `~/Pictures/SIA/` |
| `url` | FE 가 표시에 쓰는 경로 (§1.34) |
| `width` / `height` | 캡처 픽셀 크기 (물리 픽셀) |

같은 초에 두 번 저장하면 `capture_20260902_041230_2.png` 처럼 번호를 붙인다. FE 에는 같은 내용의 `capture_saved` 가 push 된다.

| 실패 | `code` | `message` |
|---|---|---|
| 죽었거나 없는 ref | `REF_NOT_FOUND` | 대상을 찾을 수 없습니다. context.get으로 목록을 다시 확인하세요 |
| 화면 읽기 실패 | `FAILED` | 화면 캡처에 실패했습니다. 잠시 후 다시 시도해주세요 |
| 저장 실패 | `FAILED` | 캡처 저장에 실패했습니다. 잠시 후 다시 시도해주세요 |

### 3.21 `screen.capture_region` — 두 점 영역 캡처 저장 · S

좌상단 · 우하단 두 점이 감싸는 화면 영역만 PNG 로 저장하고 FE 에 `capture_saved` 를 보낸다. 저장 위치 · 파일명 · 응답 형식은 `screen.capture` 와 같다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `x1` | O | 좌상단 모서리의 x 좌표 (int) |
| `y1` | O | 좌상단 모서리의 y 좌표 (int) |
| `x2` | O | 우하단 모서리의 x 좌표 (int) |
| `y2` | O | 우하단 모서리의 y 좌표 (int) |

- 좌표계는 가상 스크린 물리 픽셀이다. `explorer.items` 의 `bounds`, `gaze_cursor` 의 `x, y` 와 같다 ([프로토콜.md §7.5](프로토콜.md#75-시선--bounds-교차-규칙)).
- 두 점의 순서는 가리지 않는다. 우상단 · 좌하단 등 어느 두 대각 모서리로 와도 두 점을 감싸는 같은 사각형으로 정규화한다. 너비는 `|x1 − x2|`, 높이는 `|y1 − y2|` 다.
- 가상 스크린 밖으로 나간 부분은 잘라낸다. 응답의 `width` · `height` 는 잘라낸 뒤의 실제 크기다.

```json
{ "x1": 400, "y1": 200, "x2": 1600, "y2": 900 }
```
```json
{ "content": [{ "type": "text", "text": "{\"path\":\"C:\\\\Users\\\\me\\\\Pictures\\\\SIA\\\\capture_20260902_041512.png\",\"url\":\"/api/captures/capture_20260902_041512.png\",\"width\":1200,\"height\":700}" }], "isError": false, "structuredContent": { "path": "C:\\Users\\me\\Pictures\\SIA\\capture_20260902_041512.png", "url": "/api/captures/capture_20260902_041512.png", "width": 1200, "height": 700 } }
```

| 필드 | 설명 |
|---|---|
| `path` | 저장된 PNG 의 절대 경로. 위치는 `~/Pictures/SIA/` |
| `url` | FE 가 표시에 쓰는 경로 (§1.34) |
| `width` / `height` | 잘라낸 뒤 실제로 캡처된 픽셀 크기 (물리 픽셀) |

FE 에는 같은 내용의 `capture_saved` 가 push 된다. 제스처 매크로에 넣을 수 있으며, 그때 좌표는 등록 시 고정된다.

| 실패 | `code` | `message` |
|---|---|---|
| 좌표 누락 | `INVALID_REQUEST` | 캡처 영역의 좌표 네 개(x1, y1, x2, y2)가 모두 필요합니다 |
| 너비 또는 높이가 0 | `INVALID_REQUEST` | 캡처 영역이 비어 있습니다. 두 점의 x 좌표끼리, y 좌표끼리 서로 달라야 합니다 |
| 화면과 겹치지 않음 | `INVALID_REQUEST` | 캡처 영역이 화면 밖입니다. 좌표는 가상 스크린 물리 픽셀이어야 합니다 |
| 화면 읽기 실패 | `FAILED` | 화면 캡처에 실패했습니다. 잠시 후 다시 시도해주세요 |
| 저장 실패 | `FAILED` | 캡처 저장에 실패했습니다. 잠시 후 다시 시도해주세요 |

### 3.22 `volume.set` — 시스템 볼륨 절대값 · S

기본 재생 장치의 마스터 볼륨을 지정한 값으로 맞춘다. `level` 은 작업표시줄 볼륨 슬라이더와 같은 척도라 `30` 이면 슬라이더도 30% 에 선다. 현재 볼륨은 §3.2 `context.get` 의 `volume` 에 있다 — "조금만 줄여줘" 같은 상대적인 요청은 그 값에서 계산해 부른다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `level` | O | `0` ~ `100`. 범위 밖은 `0` 또는 `100` 으로 잘라서 맞춘다 (실패가 아니다) |

```json
{ "level": 30 }
```
```json
{ "content": [{ "type": "text", "text": "{\"level\":30,\"muted\":false}" }], "isError": false, "structuredContent": { "level": 30, "muted": false } }
```

| 필드 | 설명 |
|---|---|
| `level` | **실제로 반영된** 값. 잘렸거나 장치가 다른 값으로 맞췄으면 요청 값과 다르다 — 사용자에게는 이 값을 읽어 준다 |
| `muted` | 반영 후 음소거 상태 |

`level > 0` 이면 음소거도 함께 푼다. 볼륨을 먼저 맞춘 뒤 풀기 때문에 이전의 큰 볼륨으로 한 번 터지지 않는다. `level: 0` 은 음소거를 건드리지 않고 볼륨만 0 으로 내린다.

| 실패 | `code` | `message` |
|---|---|---|
| `level` 누락 | `INVALID_REQUEST` | 볼륨 값(level)이 필요합니다 (0~100) |
| 출력 장치 없음 · 오디오 접근 실패 | `FAILED` | 시스템 볼륨을 조절하지 못했습니다 |

### 3.23 `browser.search` — 브라우저 검색 · 주소 열기 · S

기본 브라우저로 검색어를 찾거나 주소를 연다. **여는 경로가 둘이고, 갈림은 브라우저 확장(§4.6) 연결 여부 하나다.** 어느 쪽으로 열리든 `ok: true` 이고, 차이는 `via` 와 `domAvailable` 두 필드로만 드러난다.

| 인자 | 필수 | 규칙 |
|---|:-:|---|
| `query` | O | 검색어, 또는 `http://` · `https://` 로 시작하는 주소. 500자 이하 |

`query` 를 실제로 열 주소로 바꾸는 규칙은 셋뿐이다.

| `query` | 여는 주소 |
|---|---|
| `http(s)://` 로 시작 | 그 주소 그대로 |
| 다른 스킴(`file:` · `javascript:` · `data:` · `chrome:` …) 이거나 `://` 를 포함 | 열지 않는다 — `INVALID_REQUEST` |
| 그 외 전부 | `https://www.google.com/search?q=<URL 인코딩>`. `www.naver.com` 처럼 스킴 없는 도메인도 검색어로 넘긴다 |

```json
{ "query": "반도체 수출 전망" }
```

확장이 연결돼 있을 때 — 확장이 활성 크롬 창에 **새 탭**으로 연다.

```json
{ "content": [{ "type": "text", "text": "{\"ok\":true,\"via\":\"extension\",\"url\":\"https://www.google.com/search?q=%EB%B0%98%EB%8F%84%EC%B2%B4+%EC%88%98%EC%B6%9C+%EC%A0%84%EB%A7%9D\",\"title\":\"반도체 수출 전망 - Google 검색\",\"tabId\":42,\"domAvailable\":true}" }], "isError": false, "structuredContent": { "ok": true, "via": "extension", "url": "https://www.google.com/search?q=%EB%B0%98%EB%8F%84%EC%B2%B4+%EC%88%98%EC%B6%9C+%EC%A0%84%EB%A7%9D", "title": "반도체 수출 전망 - Google 검색", "tabId": 42, "domAvailable": true } }
```

확장이 없을 때 — OS 기본 브라우저로 연다.

```json
{ "content": [{ "type": "text", "text": "{\"ok\":true,\"via\":\"os\",\"url\":\"https://www.google.com/search?q=%EB%B0%98%EB%8F%84%EC%B2%B4+%EC%88%98%EC%B6%9C+%EC%A0%84%EB%A7%9D\",\"domAvailable\":false}" }], "isError": false, "structuredContent": { "ok": true, "via": "os", "url": "https://www.google.com/search?q=%EB%B0%98%EB%8F%84%EC%B2%B4+%EC%88%98%EC%B6%9C+%EC%A0%84%EB%A7%9D", "domAvailable": false } }
```

| 필드 | 설명 |
|---|---|
| `via` | `extension` 또는 `os`. 실제로 연 주체 |
| `url` | 실제로 연 주소 |
| `title` | 확장 경로에서만 온다. 2.5초 안에 로딩이 끝나지 않으면 `null` |
| `tabId` | 확장 경로에서만 온다. 크롬 탭 id — 참고값이고 BE 가 이 값으로 뭘 하지는 않는다 |
| `domAvailable` | `true` 면 이어서 `browser.dom_text`(§3.24)로 그 페이지 본문을 읽을 수 있다. `false` 면 열어 준 것까지만 확실하다 — **AI 는 이때 본문을 읽었다고 말하지 않는다** |

확장이 연결돼 있어도 4초 안에 회신하지 않거나 실패를 보고하면 OS 경로로 폴백해 `via: "os"` 로 답한다. "검색해줘"가 조용히 실패하지 않게 하기 위한 것이고, 그 창은 이미 확장이 응답하지 못하는 상태라 탭이 둘 열리지는 않는다.

| 실패 | `code` | `message` |
|---|---|---|
| `query` 누락 · 공백뿐 | `INVALID_REQUEST` | 검색어나 주소(query)가 필요합니다 |
| 500자 초과 | `INVALID_REQUEST` | 검색어가 너무 깁니다 (500자 이하) |
| `http(s)` 가 아닌 스킴 | `INVALID_REQUEST` | http(s) 가 아닌 주소는 열 수 없습니다. 검색어를 넘기세요 |
| host 가 없는 `http(s)` 주소 | `INVALID_REQUEST` | 열 수 없는 주소입니다. 올바른 http(s) 주소이거나 검색어여야 합니다 |
| 두 경로 다 브라우저를 못 띄움 | `FAILED` | 브라우저를 열지 못했습니다. 잠시 후 다시 시도해주세요 |

### 3.24 `browser.dom_text` — 보고 있는 페이지 본문 · S

사용자가 지금 보고 있는 웹페이지의 본문을 읽어 돌려준다. 인자가 없다 — **어느 페이지를 읽을지는 AI 가 고르지 않고 BE 가 정한다.** `browser.search`(§3.23)와 마찬가지로 갈림은 브라우저 확장(§4.6) 연결 여부 하나이고, 차이는 `via` 로만 드러난다.

| 확장 | 대상 | 본문의 질 |
|---|---|---|
| 연결됨 | 크롬의 마지막 활성 창의 활성 탭 | `article` → `main` → `[role=main]` → `body` 순으로 **본문만** 추출 |
| 미연결 | 포그라운드 브라우저 창, 없으면 Z 순서상 가장 앞의 브라우저 창 | 접근성 트리 텍스트 전체 — 메뉴 · 사이드바가 섞인다 |

```json
{}
```

```json
{ "content": [{ "type": "text", "text": "{\"via\":\"extension\",\"url\":\"https://news.example.com/article/12345\", …}" }], "isError": false, "structuredContent": { "via": "extension", "url": "https://news.example.com/article/12345", "title": "반도체 수출 3개월 연속 증가", "text": "지난달 반도체 수출액이 …", "truncated": false } }
```

| 필드 | 설명 |
|---|---|
| `via` | `extension` 또는 `accessibility`. 본문을 어디서 얻었는지 — `accessibility` 면 본문 아닌 텍스트가 섞여 있다 |
| `url` | 페이지 주소. 접근성 경로에서는 브라우저 엔진에 따라 `null` 일 수 있다 |
| `title` | 페이지 제목. 없으면 `null` |
| `text` | 본문. 20,000자 이하 |
| `truncated` | 20,000자에서 잘렸으면 `true` |

읽지 못한 경우는 빈 결과가 아니라 실패다 — `available: false` 같은 별도 어휘를 두지 않는다.

| 실패 | `code` | `message` |
|---|---|---|
| 확장이 4초 안에 무응답 | `FAILED` | 브라우저 확장이 응답하지 않습니다 |
| 확장이 실패 보고 | `FAILED` | 활성 탭이 웹 페이지가 아닙니다 · 페이지에서 읽을 본문이 없습니다 · 이 페이지에서는 본문을 읽을 수 없습니다 중 하나. 확장이 생략하면 `본문을 추출하지 못했습니다` |
| 브라우저 창이 없음 (접근성) | `FAILED` | 열려 있는 브라우저 창을 찾지 못했습니다 |
| UIA 실패 · 제한 시간 초과 (접근성) | `FAILED` | 브라우저에서 본문을 읽지 못했습니다 |
| 읽었지만 비어 있음 (접근성) | `FAILED` | 페이지에서 읽을 본문이 없습니다 |

접근성 경로일 때는 BE 가 FE 에 `notice` 를 직접 보내 확장 부재를 알린다 (60초 1회, 프로토콜.md §6.6). 도구 호출 하나가 최대 4초(확장) · 4.5초(접근성) 걸린다.

---

## 4. WebSocket 메시지 양식

세 WS 채널의 메시지 양식이다. 이벤트가 오가는 순서와 의미는 [프로토콜.md](프로토콜.md) §4 ~ §8 에 있고, 여기서는 메시지 하나의 형식(필드 · 타입 · 필수 여부)을 정한다.

### 4.1 공통

| 채널 | 주소 | 방향 | 허용 Origin |
|---|---|---|---|
| `/ws/fe` | `ws://127.0.0.1:8080/ws/fe` | FE ↔ BE | `http://localhost:*`, `http://127.0.0.1:*` |
| `/ws/agent` | `ws://127.0.0.1:8080/ws/agent` | AI ↔ BE | 같음. Origin 헤더가 없는 네이티브 클라이언트 허용 |
| `/ws/ext` | `ws://127.0.0.1:8080/ws/ext` | 브라우저 확장 ↔ BE | 위 두 패턴 + `chrome-extension://*` |

인증은 없다. 모든 메시지는 텍스트 프레임 하나에 JSON 객체 하나다.

```json
{ "type": "session_state", "data": { "state": "ACTIVE", "sessionId": 128, "deadlineMs": 1788148327913, "remainingSec": 15 } }
```

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:-:|---|
| `type` | string | O | 이벤트 이름. 이 절의 표에 있는 값 |
| `data` | object | O | 이벤트 본문. 보낼 내용이 없으면 `{}`. `null` 로 보내지 않는다 |

| 규칙 | 내용 |
|---|---|
| 모르는 `type` | 무시한다. 오류 응답 없음 |
| `type` 없음 · JSON 아님 | 보낸 소켓에만 `error {message}` |
| 처리 중 검증 실패 | 보낸 소켓에만 `error {message, of}`. `of` 는 실패한 원본 `type` |
| BE 발신 | 해당 채널 구독자 전원에게 브로드캐스트 |
| 프레임 상한 | 4MB. idle 타임아웃 없음 |
| 절대 시각 | epoch millis 정수 (`deadlineMs`, `tsMs`) |
| 좌표 | 가상 스크린 물리 픽셀 정수 (`gaze_cursor`, `calib_point_shown`) |

타입 표기:

| 표기 | 뜻 |
|---|---|
| `string` · `int` · `long` · `number` · `boolean` · `object` | JSON 문자열 · 정수 · 정수(id, epoch millis) · 실수 · 불리언 · 객체 |
| `T[]` | `T` 의 배열 |
| `A \| B` | 열거값. 이 값 중 하나 |
| `?` | 선택 필드. 없을 수 있다 |
| `\| null` | 값이 `null` 일 수 있다 |

### 4.2 `/ws/fe` — FE → BE

| `type` | `data` | 설명 |
|---|---|---|
| `reg_start` | `{replaceGestureId?: long}` | 커스텀 제스처 등록 시작. `replaceGestureId` 가 있으면 그 제스처의 동작 재촬영 |
| `reg_stop` | `{tempId: string}` | 등록 구간 종료. 3회차 촬영이 끝난 뒤 FE 가 보낸다 |
| `macro_assign` | 아래 상세 | 매크로 지정 · 저장 |
| `wakeword_enroll_start` | `{}` | 이름 불러보기 시작 |
| `command_enroll_start` | `{}` | 명령 문장 말하기 시작 |
| `voice_reg_start` | `{}` | 보이스 등록 시작 |
| `voice_sentence_retry` | `{tempId: string}` | 현재 문장 다시 |
| `voice_reg_retry` | `{tempId: string}` | 1번 문장부터 다시 |
| `voice_accept_anyway` | `{tempId: string}` | 음질 경고를 무시하고 진행 |
| `voice_commit` | `{tempId: string, name?: string, deviceLabel?: string}` | 보이스 프로필 확정. `name` 생략 시 `내 목소리 N`. `deviceLabel` 은 실제 녹음에 쓴 마이크의 OS 장치 이름 |
| `voice_reg_cancel` | `{tempId: string}` | 보이스 등록 중단 |
| `calib_start` | `{}` | 시선 보정 시작 |
| `calib_point_shown` | `{n: int, x: int, y: int}` | 점 n 표시 완료. `x, y` 는 실제로 그린 점의 좌표 (화면 3×3 중 n 번째 칸의 중앙점) |
| `calib_restart` | `{}` | 재측정. 세션당 최대 3회 |
| `calib_commit` | `{name?: string \| null, deviceLabel?: string}` | 보정 프로필 확정. `name` 생략 시 `내 보정 N`. `deviceLabel` 은 실제 보정에 쓴 카메라의 OS 장치 이름 |
| `calib_cancel` | `{}` | 보정 중단. 이전 보정 유지 |
| `user_choice` | `{choiceId?: string, n?: int, cancelled?: boolean}` | `notice(kind: choices)` 의 응답. BE 는 검사 없이 AI 로 중계 |

#### `macro_assign`

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:-:|---|
| `tempId` | string | O | 진행 중 등록의 id. 다르면 `error`. `reg_start {replaceGestureId}` 로 시작한 등록이면 신규 대신 그 제스처를 갱신한다 (재촬영 경로) |
| `take` | int | | 1~3. 기본 1. 이 회차의 미리보기가 제스처 영상이 되고 AI 도 이 회차로 템플릿을 확정한다 |
| `name` | string | O | 공백 불가. 같은 (HAND, context, name) 조합의 커스텀 제스처가 있으면 갱신. 기본 제공 제스처와 같은 이름은 `error` |
| `label` | string | | UI 표시용 이름 |
| `context` | string | | 적용 컨텍스트 (`video` · `youtube` 등). 검증 없이 그대로 저장하고, 생략하면 `null`. 재촬영 경로에서는 무시한다 |
| `description` | string | | 설명 |
| `repeatable` | boolean | | 생략 시 `false` |
| `steps` | object[] | 신규 등록 시 O | 1~5개. 순서대로 실행. 재촬영 경로에서는 생략 · `[]` 이면 기존 단계를 유지한다 |
| `steps[].tool` | string | O | `GET /api/tools` 에 있는 이름. `window.close` · `files.delete` 금지 |
| `steps[].args` | object | | 생략 시 `{}` |
| `steps[].delayMs` | int | | 그 스텝 실행 전 대기(ms) |

```json
{
  "type": "macro_assign",
  "data": {
    "tempId": "9f3a2c17",
    "take": 2,
    "name": "손가락 하트",
    "label": "음악 재생",
    "steps": [
      { "tool": "app.launch", "args": { "appRef": "app:music" } },
      { "tool": "files.open", "args": { "path": "C:\\Users\\me\\Music\\집중.m3u" }, "delayMs": 300 }
    ]
  }
}
```

검증 실패 시 `error` 의 `message`:

| message | 조건 |
|---|---|
| `제스처 이름이 필요합니다` | `name` 없음 · 공백 |
| `각 단계에는 tool 이 필요합니다` | `steps[].tool` 없음 · 공백 |
| `진행 중인 제스처 등록이 없습니다. 등록을 다시 시작해 주세요` | `tempId` 가 진행 중 등록과 다르다 |
| `제스처 템플릿이 아직 도착하지 않았습니다. 잠시 후 다시 시도해 주세요` | AI 의 `PUT /api/agent/gestures/{tempId}/npz` 가 아직 없다 |
| `매크로에는 최소 한 단계가 필요합니다` | 신규 등록에 `steps` 가 없거나 `[]` |
| `매크로 단계는 최대 5개까지 쌓을 수 있습니다` | 6개 이상 |
| `등록되지 않은 도구입니다: <tool>` | `GET /api/tools` 에 없는 이름 |
| `사용자 동의가 필요한 도구는 제스처로 실행할 수 없습니다: <tool>` | `window.close` · `files.delete` |
| `기본 제공 제스처와 같은 이름은 쓸 수 없어요: <name>` | 신규 등록의 이름이 기본 제공 제스처와 같다 |
| `기본 제공 제스처는 켜기/끄기와 기능 변경만 가능합니다` | 재촬영 대상이 기본 제공 제스처 |
| `이미 같은 이름의 제스처가 있어요` | 재촬영 경로에서 바꾼 이름이 다른 제스처와 겹친다 |

```json
{ "type": "voice_commit", "data": { "tempId": "9f3a2c17", "name": "스튜디오 보이스", "deviceLabel": "마이크(Realtek(R) Audio)" } }
```
```json
{ "type": "calib_commit", "data": { "name": null, "deviceLabel": "HD Webcam" } }
```
```json
{ "type": "user_choice", "data": { "choiceId": "c-7f31", "n": 1 } }
```

### 4.3 `/ws/fe` — BE → FE

#### 세션 · 실행

| `type` | `data` | 설명 |
|---|---|---|
| `listening` | `{}` | 호출어 감지 |
| `session_state` | 아래 상세 | 세션 상태 |
| `tool_result` | `{tool: string, outcome: EXECUTED \| BLOCKED \| FAILED, caller: LLM \| GESTURE, message?: string, latencyMs: long}` | 개별 도구 실행 결과. `message` 는 사유가 있을 때만 |
| `gesture_result` | 아래 상세 | 제스처 매크로 실행 결과 |
| `notice` | 아래 상세 | AI 안내 · 결과 문구 (AI 페이로드 그대로). 예외로 BE 가 직접 보내는 건 한 가지, 확장 부재 안내다 (프로토콜.md §6.6) |
| `voice_rejected` | `{message: string}` | 화자 게이트 기각. `"등록된 목소리로 한 명령이 아닙니다."` |
| `gaze_cursor` | `{x: int, y: int}` | 시선 커서 좌표 |
| `capture_saved` | `{path: string, url: string, width: int, height: int}` | `screen.capture` · `screen.capture_region` 저장 완료 |

#### 제스처 등록

| `type` | `data` | 설명 |
|---|---|---|
| `reg_state` | `{tempId: string, phase: MODE_STARTED \| RECORDING \| REJECTED \| CAPTURED \| ENCODING, reason?: string, similarTo?: string, similarity?: number}` | 등록 진행 상태. `reason` · `similarTo` · `similarity` 는 `REJECTED` 에만 |
| `reg_take` | `{tempId: string, take: int, phase: COUNTDOWN \| RECORDING \| DONE}` | 촬영 회차 진행 |
| `reg_frame` | `{tempId: string, take: int, seq: long, jpegB64: string}` | 실시간 미리보기 프레임 (JPEG base64) |
| `reg_recorded` | `{tempId: string, takes: {take: int, webmUrl: string \| null}[], reason?: string}` | 회차별 미리보기 webm. 전 회차 실패면 `reason` |
| `macro_saved` | `{id: long, name: string, videoUrl: string \| null}` | 매크로 저장 완료 |

#### 온보딩 · 보이스

| `type` | `data` | 설명 |
|---|---|---|
| `wakeword_progress` | `{n: int, total: int}` | 이름 불러보기 진행 (total 10) |
| `wakeword_done` | `{}` | 호출어 모델 생성 완료 |
| `command_sentence` | `{n: int, total: int}` | 읽을 명령 문장의 순번 (total 5). 원문은 FE 상수 |
| `command_progress` | `{n: int, total: int}` | 명령 문장 n 완료 |
| `command_done` | `{}` | 명령 문장 수집 완료 |
| `voice_sentence` | `{n: int, total: int}` | 읽을 낭독 문장의 순번 (total 5). 원문은 FE 상수 |
| `voice_progress` | `{n: int, total: int}` | 문장 n 낭독 완료 |
| `voice_quality_warn` | `{tempId: string, reason: string, noise: 낮음 \| 높음 \| null}` | 음질 미달 |
| `voice_review` | `{tempId: string, sampleUrl: string \| null, durationSec: number \| null, quality: string \| null, noise: string \| null}` | 녹음 확인. `sampleUrl` 은 `/api/voice-reg/{tempId}/sample` |
| `voice_saved` | `{id: long, name: string, active: boolean}` | 보이스 프로필 저장 완료 |
| `voice_reg_denied` | `{message: string}` | 등록 불가 (프로필 4개 초과) |

#### 시선 보정

| `type` | `data` | 설명 |
|---|---|---|
| `calib_precheck` | `{face: boolean, distance: ok \| near \| far, lighting: ok \| low}` | 위치 확인 상태 |
| `calib_point` | `{n: int, total: int}` | 점 n 표시 지시 (total 9). 좌표는 FE 가 정한다 |
| `calib_result` | 아래 상세 | 보정 결과 |
| `calib_limit` | `{message: string, remeasuresUsed: int}` | 재측정 한도 초과 |
| `calib_saved` | `{id: long, name: string, avgErrorPx: number, active: boolean}` | 보정 프로필 저장 완료 |
| `calib_denied` | `{message: string}` | 보정 시작 불가 (프로필 4개 초과) |

#### 모델 · 연결 · 설정

| `type` | `data` | 설명 |
|---|---|---|
| `model_progress` | `{name: string, pct: int}` | 다운로드 진행률. 5% 단위 |
| `model_downloaded` | `{name: string}` | 다운로드 · sha256 검증 완료 |
| `model_ready` | `{}` | 모델 1개 적재 완료. 모델마다 1회 |
| `model_error` | `{name: string, reason: string}` | 다운로드 2회 실패 또는 AI 적재 실패 |
| `agent_status` | `{connected: boolean}` | AI 연결 상태 변화 |
| `ext_status` | `{connected: boolean}` | 브라우저 확장 연결 상태 변화 |
| `settings_sync` | `{settingsVersion: int, agentSyncedVersion: int \| null}` | 설정 반영 상태 |
| `error` | `{message: string, of?: string}` | 직전 메시지 처리 실패. 보낸 소켓에만 |

#### `session_state` (BE → FE, BE → AI 공통)

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:-:|---|
| `state` | `ACTIVE` \| `PASSIVE` | O | |
| `sessionId` | long | ACTIVE 일 때 | |
| `deadlineMs` | long | ACTIVE 일 때 | 만료 시각 (epoch millis) |
| `remainingSec` | int | ACTIVE 일 때 | 남은 초 |
| `reason` | `EXPIRED` \| `STOPPED` \| `WATCHDOG` \| `SHUTDOWN` | PASSIVE 종료 시 | 부팅 완료 시의 초기 PASSIVE 에는 없다 |

```json
{ "type": "session_state", "data": { "state": "ACTIVE", "sessionId": 128, "deadlineMs": 1788148327913, "remainingSec": 15 } }
```
```json
{ "type": "session_state", "data": { "state": "PASSIVE", "reason": "EXPIRED" } }
```

#### `gesture_result` (BE → FE, BE → AI 공통)

BE 가 `gesture_exec` 의 이름으로 `gesture` · `gesture_step` 매핑을 조회해 실행한 뒤 보내는 보고다. 매핑은 BE 만 안다. AI 는 인식한 이름만 보내고, 이 결과로 무엇이 실행됐는지 알게 된다. 사용자 표시는 FE 가 같은 페이로드로 한다.

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:-:|---|
| `name` | string | O | 요청한 제스처 이름 |
| `ok` | boolean | O | 모든 스텝이 `EXECUTED` 면 `true` |
| `message` | string | O | BE 가 제스처의 `label` 로 만든 문장. 성공은 `'<label>' 동작을 실행했습니다`, 실패는 실패 사유. FE 가 그대로 표시한다 |
| `steps` | object[] | O | BE 가 실제로 실행한 스텝. 매핑 순서대로이며 실패한 스텝 뒤는 없다. 미등록 · 꺼진 제스처, 그리고 세션 게이트에 막힌 매크로는 `[]` (프로토콜 §8.6 — 게이트는 매크로 단위라 첫 스텝도 실행되지 않는다) |
| `steps[].tool` | string | O | |
| `steps[].outcome` | `EXECUTED` \| `BLOCKED` \| `FAILED` | O | |
| `steps[].message` | string | | 사유가 있을 때만 |

```json
{ "type": "gesture_result", "data": { "name": "손가락 하트", "ok": true, "message": "'음악 재생' 동작을 실행했습니다", "steps": [ { "tool": "app.launch", "outcome": "EXECUTED" }, { "tool": "files.open", "outcome": "EXECUTED" } ] } }
```
```json
{ "type": "gesture_result", "data": { "name": "Thumb_Up", "ok": false, "message": "세션이 활성화되지 않았습니다", "steps": [] } }
```

#### `notice` (AI → BE → FE, 페이로드 그대로 중계)

거의 언제나 AI 가 소유하는 채널이다. **예외는 하나** — 확장이 없어 접근성으로 본문을 읽었을 때 BE 가 `{message}` 만 담아 직접 보낸다 (프로토콜.md §6.6). 확장 부재는 대화가 아니라 시스템 상태여서 AI 가 언급을 생략해도 사용자가 알아야 하기 때문이다. FE 는 발신자를 구분하지 않고 똑같이 표시한다.

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:-:|---|
| `message` | string | O | 표시할 문장 |
| `kind` | `confirm` \| `unknown_command` \| `choices` | | 없으면 일반 안내 |
| `transcript` | string | | `unknown_command` 일 때 인식된 발화 원문 |
| `choiceId` | string | `choices` 일 때 | 질문 식별자. `user_choice` 가 되돌려 보낸다 |
| `choices` | object[] | `choices` 일 때 | `{n: int, label: string, detail?: string}` |
| `timeoutSec` | int | `choices` 일 때 | FE 카운트다운 표시용 |

AI ↔ FE 계약이므로 표에 없는 필드가 더 붙어 올 수 있다. BE 는 해석하지 않는다.

```json
{ "type": "notice", "data": { "kind": "choices", "choiceId": "c-7f31", "message": "어떤 것을 닫을까요?", "choices": [ { "n": 1, "label": "동영상 플레이어", "detail": "시선 89% · 우측 상단" }, { "n": 2, "label": "Chrome — 문서", "detail": "시선 8% · 현재 활성 창" } ], "timeoutSec": 12 } }
```

#### `calib_result` (BE → FE)

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:-:|---|
| `avgErrorPx` | number \| null | O | 평균 오차 |
| `maxErrorPx` | number \| null | O | 최대 오차 |
| `points` | object[] \| null | O | `{n: int, dx: number, dy: number}`. 목표점을 원점으로 둔 오차 벡터. AI 가 보내지 않았으면 `null` |
| `grade` | string \| null | O | `excellent \| good \| poor`. AI 가 판정한 오차 등급 |
| `pass` | boolean \| null | O | AI 판정. 기준값은 AI 서버가 관리하므로 BE 는 계산하지 않는다 |
| `remeasuresUsed` | int | O | 지금까지 쓴 재측정 횟수 |
| `remeasuresLeft` | int | O | 남은 재측정 횟수. 0 이면 [다시 측정] 비활성화 |

```json
{ "type": "calib_result", "data": { "avgErrorPx": 38.0, "maxErrorPx": 62.0, "points": [ { "n": 1, "dx": 11, "dy": 12 } ], "grade": "good", "pass": true, "remeasuresUsed": 1, "remeasuresLeft": 2 } }
```

그 밖의 예시:

```json
{ "type": "tool_result", "data": { "tool": "window.resize", "outcome": "BLOCKED", "caller": "GESTURE", "message": "관리자 권한으로 실행된 창은 제어할 수 없습니다", "latencyMs": 3 } }
```
```json
{ "type": "reg_state", "data": { "tempId": "9f3a2c17", "phase": "REJECTED", "reason": "이미 등록된 제스처와 너무 비슷해요", "similarTo": "주먹 쥐기", "similarity": 0.87 } }
```
```json
{ "type": "reg_recorded", "data": { "tempId": "9f3a2c17", "takes": [ { "take": 1, "webmUrl": "/api/previews/9f3a2c17-1.webm" }, { "take": 2, "webmUrl": "/api/previews/9f3a2c17-2.webm" }, { "take": 3, "webmUrl": null } ] } }
```
```json
{ "type": "voice_review", "data": { "tempId": "9f3a2c17", "sampleUrl": "/api/voice-reg/9f3a2c17/sample", "durationSec": 4.2, "quality": "양호", "noise": "낮음" } }
```
```json
{ "type": "capture_saved", "data": { "path": "C:\\Users\\me\\Pictures\\SIA\\capture_20260902_041230.png", "url": "/api/captures/capture_20260902_041230.png", "width": 1920, "height": 1080 } }
```
```json
{ "type": "error", "data": { "message": "제스처 이름이 필요합니다", "of": "macro_assign" } }
```

### 4.4 `/ws/agent` — AI → BE

#### 접속 · 세션

| `type` | `data` | 설명 |
|---|---|---|
| `hello` | `{agentVersion?: string}` | 접속 직후 1회. `agentVersion` 을 생략하면 저장된 버전을 유지한다 |
| `wakeword_detected` | `{}` | 호출어 감지 |
| `session_open` | `{trigger: WAKEWORD \| UI}` | 명시적 세션 개시. 다른 값이면 `error` |
| `session_renew` | `{sessionId?: long}` | 세션 갱신. 생략 시 현재 활성 세션 |
| `session_end` | `{sessionId?: long, reason?: EXPIRED \| STOPPED \| WATCHDOG \| SHUTDOWN}` | 세션 종료. `reason` 생략 시 `STOPPED`. 다른 세션이 활성인데 `sessionId` 가 그 세션이 아니면 해당 행만 종료 처리하고 `session_state` 는 보내지 않는다 |
| `recognition_started` | `{}` | 상시 인식 가동 완료 |
| `model_loaded` | `{name: string}` | 모델 적재 성공 |
| `model_load_failed` | `{name: string, reason: string}` | 모델 적재 실패 |

#### 실행 · 중계

| `type` | `data` | 설명 |
|---|---|---|
| `gesture_exec` | `{name: string, hwnd?: long, context?: string}` | 제스처 매크로 실행 요청. AI 는 인식한 이름만 보내고 매핑 조회는 BE 가 한다. 즉시 응답 없음. 결과는 `gesture_result` |
| `notice` | §4.3 `notice` 와 같음 | FE 에 그대로 중계 |
| `gaze_cursor` | `{x: int, y: int}` | FE 에 그대로 중계. 설정 `gazeCursor` 가 `true` 일 때만 보낸다 |
| `voice_rejected` | `{}` | 화자 게이트 기각 |

#### 제스처 등록

| `type` | `data` | 설명 |
|---|---|---|
| `reg_started` | `{tempId: string}` | 등록 모드 진입 완료 |
| `reg_take` | `{tempId: string, take: int, phase: COUNTDOWN \| RECORDING \| DONE}` | 회차 진행 |
| `reg_frame` | `{tempId: string, take: int, seq: long, tsMs: long, jpegB64: string}` | 압축 프레임. `take` 생략 시 1. `tsMs` 는 재생 타이밍 근거 |
| `reg_rejected` | `{tempId: string, reason: string, similarTo?: string, similarity?: number}` | 품질 검증 미달 |
| `reg_captured` | `{tempId: string}` | 템플릿 후보 생성 완료. npz 를 `PUT /api/agent/gestures/{tempId}/npz` 로 먼저 올린 뒤 보낸다 |

#### 온보딩 · 보이스

| `type` | `data` | 설명 |
|---|---|---|
| `wakeword_sample` | `{n: int, total: int}` | 호출어 샘플 수집 진행 (total 10) |
| `wakeword_done` | `{}` | 호출어 모델 생성 완료. 모델은 미리 `PUT /api/agent/blobs/wakeword` |
| `command_ready` | `{}` | 명령 문장 수집 준비 완료 |
| `command_progress` | `{n: int}` | 명령 문장 n 완료 |
| `command_done` | `{}` | 명령 문장 수집 완료 |
| `voice_ready` | `{tempId: string}` | 보이스 녹음 준비 완료 |
| `voice_progress` | `{tempId: string, n: int}` | 문장 n 낭독 완료 |
| `voice_quality_warn` | `{tempId: string, reason: string, noise: 낮음 \| 높음}` | 음질 미달 |
| `voice_captured` | `{tempId: string, durationSec: number, quality: string, noise: string}` | 임베딩 완료. 샘플 · npz 를 REST 로 먼저 올린 뒤 보낸다 |

#### 시선 보정

| `type` | `data` | 설명 |
|---|---|---|
| `calib_precheck` | `{face: boolean, distance: ok \| near \| far, lighting: ok \| low}` | 위치 확인 상태. 바뀔 때마다 |
| `calib_point_ready` | `{n: int, total: int}` | 점 n 수집 준비. 좌표는 싣지 않는다 |
| `calib_point_done` | `{n: int}` | 점 n 완료 |
| `calib_result` | `{tempId: string, avgErrorPx: number, maxErrorPx: number, points: {n: int, dx: number, dy: number}[], grade: string, pass: boolean}` | 학습 결과. `grade` 는 `excellent \| good \| poor` 이고 기준은 AI 서버가 관리한다. npz 를 `PUT /api/agent/calibs/{tempId}/npz` 로 먼저 올린 뒤 보낸다 |

```json
{ "type": "hello", "data": { "agentVersion": "0.4.2" } }
```
```json
{ "type": "gesture_exec", "data": { "name": "Open_Palm", "hwnd": 3212344, "context": "youtube" } }
```
```json
{ "type": "reg_frame", "data": { "tempId": "9f3a2c17", "take": 2, "seq": 41, "tsMs": 1788148327913, "jpegB64": "/9j/4AAQ…" } }
```
```json
{ "type": "voice_captured", "data": { "tempId": "9f3a2c17", "durationSec": 4.2, "quality": "양호", "noise": "낮음" } }
```
```json
{ "type": "calib_result", "data": { "tempId": "b81d203e", "avgErrorPx": 38.0, "maxErrorPx": 62.0, "points": [ { "n": 1, "dx": 11, "dy": 12 } ], "grade": "good", "pass": true } }
```

### 4.5 `/ws/agent` — BE → AI

#### 동기화 · 세션

| `type` | `data` | 설명 |
|---|---|---|
| `hello_ack` | `{settingsVersion: int, blobs: Blobs}` | `hello` 응답 |
| `model_load` | `{name: string, path: string}` | 모델 적재 지시. 모델마다 1회 |
| `recognition_start` | `{settingsVersion: int, settings: object, blobs: Blobs, disabledGestures: string[]}` | 상시 인식 시작. 정확히 1회 |
| `settings_changed` | `{settingsVersion: int, settings: object, blobs: Blobs, disabledGestures: string[]}` | 설정 · blob · 프로필 활성 교체 · 제스처 켜기/끄기 — 넷 모두에서 나간다. 프로필 교체와 제스처 토글에는 `voice_changed` · `calib_changed` · `gesture_toggled` 가 **먼저** 가고 `settings_changed` 가 뒤따른다. AI 는 둘 중 어느 쪽만 들어도 상태를 놓치지 않는다 |
| `session_state` | §4.3 상세와 같음 | 세션 상태 |
| `wipe` | `{}` | 전체 삭제. 로컬 캐시 삭제 |
| `error` | `{message: string, of?: string}` | 직전 메시지 처리 실패 |

`settings` 는 `GET /api/settings` 의 `settings` 객체와 같다 (§1.2). `Blobs`:

| 필드 | 타입 | 규칙 |
|---|---|---|
| `gestures` | `{id: long, name: string, sha256: string}[]` | 템플릿을 가진 커스텀 제스처 전부. 없으면 `[]`. 목록에 없는 로컬 템플릿은 삭제하고, sha256 이 다른 것만 `GET /api/agent/gestures/{id}/npz` 로 다시 받는다 |
| `wakeword` | string \| null | 호출어 모델 npz 의 sha256. `null` 이면 로컬 캐시 삭제 |
| `voice` | `{id: long, sha256: string}` \| null | 활성 보이스 프로필 |
| `calib` | `{id: long, sha256: string, screenW: int \| null, screenH: int \| null}` \| null | 활성 보정 프로필 |

```json
{ "type": "recognition_start", "data": { "settingsVersion": 5, "settings": { "wakeWord": "시아", "sessionSeconds": 15, "autoStart": true, "gazeCursor": false, "micDevice": "마이크(Realtek(R) Audio)", "cameraDevice": "HD Webcam", "micDeviceId": "{0.0.1.00000000}.{a53af75a…}", "cameraDeviceId": "\\?\usb#vid_046d…" }, "blobs": { "gestures": [{ "id": 14, "name": "손가락 하트", "sha256": "8c22b1de44a0…" }], "wakeword": "b02f11ac37d9…", "voice": { "id": 1, "sha256": "a17c04ff9b32…" }, "calib": { "id": 2, "sha256": "3f5a9c21e0b7…", "screenW": 1920, "screenH": 1080 } }, "disabledGestures": ["V_Sign"] } }
```

#### 제스처

| `type` | `data` | 설명 |
|---|---|---|
| `reg_mode_start` | `{tempId: string, takes: int, countdownSec: int, takeDurationSec: int, replaceGestureName?: string}` | 등록 모드 진입 지시. 값은 3 · 3 · 2 |
| `reg_finish` | `{tempId: string}` | 등록 구간 종료 지시 |
| `gesture_registered` | `{tempId: string, take: int, id: long, name: string, label: string \| null, sha256: string}` | 매크로 지정 완료. `take` 회차 템플릿이 `id` 로 확정됐다. `GET /api/agent/gestures/{id}/npz` 로 내려받아 적재한다 |
| `gesture_renamed` | `{id: long, oldName: string, newName: string}` | 이름 변경. `id` 의 이름표만 바꾼다. npz 재업로드 없음 |
| `gesture_removed` | `{id: long, name: string}` | 삭제. `id` 의 로컬 템플릿을 지운다. npz 재업로드 없음 |
| `gesture_toggled` | `{name: string, context: string \| null, enabled: boolean}` | 켜기 / 끄기 |
| `gesture_result` | §4.3 상세와 같음 | 매크로 실행 결과 |

#### 온보딩 · 보이스

| `type` | `data` | 설명 |
|---|---|---|
| `wakeword_enroll_start` | `{}` | 이름 불러보기 시작 지시 |
| `command_enroll_start` | `{}` | 명령 문장 말하기 시작 지시 |
| `command_collect` | `{n: int}` | 명령 문장 n 수집 시작. 원문은 AI 상수의 n 번째 |
| `voice_reg_start` | `{tempId: string, total: int}` | 보이스 등록 모드 진입. `total` 은 5 |
| `voice_collect` | `{tempId: string, n: int}` | 문장 n 수집 시작. 같은 n 이 다시 오면 교체 수집 |
| `voice_finalize` | `{tempId: string}` | 음질 경고 무시. 현재 수집분으로 마무리 |
| `voice_reg_cancel` | `{tempId: string}` | 등록 중단. 수집물 폐기 |
| `voice_registered` | `{id: long, name: string, active: boolean}` | 보이스 프로필 확정 |
| `voice_changed` | `{id: long, sha256: string}` | 활성 보이스 교체. `GET /api/agent/voices/active/npz` 로 갱신 |

#### 시선 보정

| `type` | `data` | 설명 |
|---|---|---|
| `calib_start` | `{tempId: string}` | 보정 실행 지시 |
| `calib_collect_start` | `{n: int, x: int, y: int}` | 점 n 수집 시작. `x, y` 는 FE 가 그린 점의 좌표 — AI 가 오차를 재는 기준점 |
| `calib_restart` | `{tempId: string}` | 재측정 |
| `calib_cancel` | `{tempId: string}` | 보정 중단 |
| `calib_registered` | `{id: long, active: boolean}` | 보정 프로필 확정 |
| `calib_changed` | `{id: long, sha256: string, screenW: int \| null, screenH: int \| null}` | 활성 보정 교체. `GET /api/agent/calibs/active/npz` 로 갱신 |

#### 중계 · 회신

| `type` | `data` | 설명 |
|---|---|---|
| `user_choice` | `{choiceId?: string, n?: int, cancelled?: boolean}` | FE 클릭의 무해석 중계 |

```json
{ "type": "reg_mode_start", "data": { "tempId": "9f3a2c17", "takes": 3, "countdownSec": 3, "takeDurationSec": 2, "replaceGestureName": "손가락 하트" } }
```
```json
{ "type": "gesture_registered", "data": { "tempId": "9f3a2c17", "take": 2, "id": 14, "name": "손가락 하트", "label": "음악 재생", "sha256": "8c22b1de44a0…" } }
```
```json
{ "type": "voice_collect", "data": { "tempId": "9f3a2c17", "n": 2 } }
```
```json
{ "type": "calib_changed", "data": { "id": 3, "sha256": "0d4e55aa19cc…", "screenW": 2560, "screenH": 1440 } }
```
```json
```

### 4.6 `/ws/ext` — 브라우저 확장 ↔ BE

| 방향 | `type` | `data` | 설명 |
|---|---|---|---|
| 확장 → BE | `hello` | `{extVersion: string}` | 접속 직후 1회 |
| 확장 → BE | `dom_text` | `{requestId: string, available: boolean, url?: string, title?: string, text?: string, truncated?: boolean, reason?: string}` | 본문 응답. `text` 는 20,000자 이하 |
| 확장 → BE | `browser_open` | `{requestId: string, ok: boolean, url?: string, title?: string, tabId?: number, reason?: string}` | 탭 열기 결과. `title` 은 2.5초 안에 로딩이 끝났을 때만 채워진다 |
| 확장 → BE | `ping` | `{}` | 20초 주기 하트비트 |
| BE → 확장 | `dom_text_request` | `{requestId: string}` | 활성 탭 본문 요청 |
| BE → 확장 | `browser_open_request` | `{requestId: string, url: string}` | 새 탭으로 `url` 열기 요청. `url` 은 항상 `http(s)` 다 (§3.23) |
| BE → 확장 | `pong` | `{}` | `ping` 응답 |
| BE → 확장 | `error` | `{message: string, of?: string}` | `type` 이 없는 메시지, 또는 처리 중 예외. 보낸 소켓에만 |

`reason` 은 `활성 탭이 웹 페이지가 아닙니다` · `페이지에서 읽을 본문이 없습니다` · `이 페이지에서는 본문을 읽을 수 없습니다` 중 하나다. 확장이 `available: false` 에 `reason` 을 생략하면 BE 가 `본문을 추출하지 못했습니다` 로 채워 `browser.dom_text` 를 실패시킨다.

```json
{ "type": "dom_text", "data": { "requestId": "5c1d90aa", "available": true, "url": "https://news.example.com/article/12345", "title": "반도체 수출 3개월 연속 증가", "text": "지난달 반도체 수출액이 …", "truncated": false } }
```

---

## 5. 부록 — 엔드포인트 · 이벤트 색인

### REST (FE)

| 메서드 | 경로 | 절 |
|---|---|---|
| GET | `/api/status` | §1.1 |
| GET | `/api/settings` | §1.2 |
| PUT | `/api/settings` | §1.3 |
| GET | `/api/tools` | §1.4 |
| GET | `/api/apps/scan` | §1.5 |
| POST | `/api/apps/scan` | §1.5 |
| GET | `/api/apps` | §1.6 |
| POST | `/api/apps` | §1.7 |
| POST | `/api/apps/verify` | §1.8 |
| DELETE | `/api/apps/{appKey}` | §1.9 |
| GET | `/api/gestures` | §1.10 |
| GET | `/api/gestures/{id}` | §1.11 |
| GET | `/api/gestures/{id}/video` | §1.12 |
| GET | `/api/gestures/{id}/npz` | §1.12 |
| PATCH | `/api/gestures/{id}` | §1.13 |
| PUT | `/api/gestures/{id}` | §1.14 |
| DELETE | `/api/gestures/{id}` | §1.15 |
| GET | `/api/tool-calls` | §1.16 |
| GET | `/api/sessions` | §1.17 |
| GET | `/api/dashboard/overview` | §1.19 |
| GET | `/api/dashboard/accuracy` | §1.20 |
| GET | `/api/dashboard/latency` | §1.21 |
| GET | `/api/dashboard/usage` | §1.22 |
| GET | `/api/dashboard/apps` | §1.23 |
| GET | `/api/dashboard/summary` | §1.24 |
| GET | `/api/dashboard/timeseries` | §1.25 |
| GET | `/api/previews/{tempId}-{take}.webm` | §1.26 |
| GET | `/api/export/blobs/{name}` | §1.27 |
| DELETE | `/api/data` | §1.28 |
| GET | `/api/voices` | §1.29 |
| GET | `/api/voices/{id}/sample` | §1.29 |
| GET | `/api/voices/{id}/npz` | §1.29 |
| PATCH | `/api/voices/{id}` | §1.29 |
| POST | `/api/voices/{id}/activate` | §1.29 |
| DELETE | `/api/voices/{id}` | §1.29 |
| GET | `/api/voice-reg/{tempId}/sample` | §1.29 |
| GET | `/api/calibs` | §1.30 |
| GET | `/api/calibs/{id}` | §1.30 |
| GET | `/api/calibs/{id}/npz` | §1.30 |
| PATCH | `/api/calibs/{id}` | §1.30 |
| POST | `/api/calibs/{id}/activate` | §1.30 |
| DELETE | `/api/calibs/{id}` | §1.30 |
| GET | `/api/devices` | §1.35 |
| POST | `/api/devices/remap` | §1.32 |
| GET | `/api/models` | §1.33 |
| POST | `/api/models/{name}/redownload` | §1.33 |
| GET | `/api/captures/{file}` | §1.34 |

### REST (AI)

| 메서드 | 경로 | 절 |
|---|---|---|
| PUT | `/api/agent/blobs/{name}` | §2.1 |
| GET | `/api/agent/blobs/{name}` | §2.2 |
| POST | `/api/agent/events` | §2.3 |
| PUT | `/api/agent/voices/{tempId}/npz` | §2.4 |
| PUT | `/api/agent/voices/{tempId}/sample` | §2.5 |
| PUT | `/api/agent/voices/active/sample` | §2.6 |
| GET | `/api/agent/voices/active/npz` | §2.7 |
| PUT | `/api/agent/calibs/{tempId}/npz` | §2.8 |
| GET | `/api/agent/calibs/active/npz` | §2.9 |
| PUT | `/api/agent/gestures/{tempId}/npz` | §2.10 |
| GET | `/api/agent/gestures/{id}/npz` | §2.11 |

### MCP

| 도구 | S | C | 절 |
|---|:-:|:-:|---|
| `context.get` | | | §3.2 |
| `app.list` | | | §3.3 |
| `app.launch` | ● | | §3.4 |
| `browser.search` | ● | | §3.23 |
| `browser.dom_text` | ● | | §3.24 |
| `window.list` | | | §3.5 |
| `window.focus` · `window.minimize` · `window.maximize` · `window.restore` | ● | | §3.6 |
| `window.resize` | ● | | §3.7 |
| `window.close` | ● | ● | §3.8 |
| `window.next` · `window.prev` | ● | | §3.9 |
| `explorer.items` | | | §3.10 |
| `scroll.step` | ● | | §3.11 |
| `media.play_pause` · `media.mute_toggle` · `media.next` · `media.prev` | ● | | §3.12 |
| `volume.step` | ● | | §3.13 |
| `volume.set` | ● | | §3.22 |
| `files.open` | ● | | §3.14 |
| `files.delete` | ● | ● | §3.15 |
| `files.save` | ● | | §3.16 |
| `system.lock` | ● | | §3.17 |
| `screen.capture` | ● | | §3.20 |
| `screen.capture_region` | ● | | §3.21 |
| `session.extend` | ● | | §3.18 |
| `session.cancel` | ● | | §3.19 |

### WebSocket 이벤트

| 채널 | 방향 | `type` | 절 |
|---|---|---|---|
| `/ws/fe` | FE → BE | `reg_start` · `reg_stop` · `macro_assign` · `wakeword_enroll_start` · `command_enroll_start` · `voice_reg_start` · `voice_sentence_retry` · `voice_reg_retry` · `voice_accept_anyway` · `voice_commit` · `voice_reg_cancel` · `calib_start` · `calib_point_shown` · `calib_restart` · `calib_commit` · `calib_cancel` · `user_choice` | §4.2 |
| `/ws/fe` | BE → FE | `listening` · `session_state` · `tool_result` · `gesture_result` · `notice` · `voice_rejected` · `gaze_cursor` · `capture_saved` · `reg_state` · `reg_take` · `reg_frame` · `reg_recorded` · `macro_saved` · `wakeword_progress` · `wakeword_done` · `command_sentence` · `command_progress` · `command_done` · `voice_sentence` · `voice_progress` · `voice_quality_warn` · `voice_review` · `voice_saved` · `voice_reg_denied` · `calib_precheck` · `calib_point` · `calib_result` · `calib_limit` · `calib_saved` · `calib_denied` · `model_progress` · `model_downloaded` · `model_ready` · `model_error` · `agent_status` · `ext_status` · `settings_sync` · `error` | §4.3 |
| `/ws/agent` | AI → BE | `hello` · `wakeword_detected` · `session_open` · `session_renew` · `session_end` · `recognition_started` · `model_loaded` · `model_load_failed` · `gesture_exec` · `notice` · `gaze_cursor` · `voice_rejected` · `reg_started` · `reg_take` · `reg_frame` · `reg_rejected` · `reg_captured` · `wakeword_sample` · `wakeword_done` · `command_ready` · `command_progress` · `command_done` · `voice_ready` · `voice_progress` · `voice_quality_warn` · `voice_captured` · `calib_precheck` · `calib_point_ready` · `calib_point_done` · `calib_result` | §4.4 |
| `/ws/agent` | BE → AI | `hello_ack` · `model_load` · `recognition_start` · `settings_changed` · `session_state` · `wipe` · `error` · `reg_mode_start` · `reg_finish` · `gesture_registered` · `gesture_renamed` · `gesture_removed` · `gesture_toggled` · `gesture_result` · `wakeword_enroll_start` · `command_enroll_start` · `command_collect` · `voice_reg_start` · `voice_collect` · `voice_finalize` · `voice_reg_cancel` · `voice_registered` · `voice_changed` · `calib_start` · `calib_collect_start` · `calib_restart` · `calib_cancel` · `calib_registered` · `calib_changed` · `user_choice` | §4.5 |
| `/ws/ext` | 확장 → BE | `hello` · `dom_text` · `browser_open` · `ping` | §4.6 |
| `/ws/ext` | BE → 확장 | `dom_text_request` · `browser_open_request` · `pong` · `error` | §4.6 |

Swagger UI: BE 기동 중 `http://127.0.0.1:8080/swagger-ui.html` 에서 REST 표면을 확인할 수 있다. WebSocket 은 Swagger 에 나타나지 않는다.
