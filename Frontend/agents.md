# 0. 프로젝트 환경

- React + JavaScript
- Zustand (상태 관리)
- CSS Modules + CSS 변수 (스타일링)
- Axios (REST 통신)
- 네이티브 WebSocket (WS 통신, `/ws/fe`)
- **Tauri는 배포 시 패키징(감싸서 실행 파일로 만드는 것)에만 쓰인다. 개발 단계에서는 순수 웹 React 앱으로만 작업하며, Tauri API(`invoke`, 플러그인 등)를 코드에 넣지 않는다.** BE(Spring Boot)와 Python Runtime(AI 판단을 수행하는 별도 Python 프로세스)은 개발 중에도 각자 실행되어 있으며, **FE는 이 둘의 구현 방식을 신경 쓸 필요 없이 BE와의 REST · WS만 다루면 된다** (Python Runtime과 FE 사이 직접 연동은 없음)

# 1. 기본 원칙

- **프런트엔드는 백엔드(Spring Boot BE, Python Runtime)와 REST · WS 통신으로만 연동한다. 백엔드 쪽 코드(BE, Python Runtime 등 이 리포지토리 밖 혹은 별도 서버 코드)는 절대 수정 · 생성하지 않는다.** 백엔드 동작이 명세(ERD · API명세서 · 프로토콜)와 다르거나, 필요한 엔드포인트 · 이벤트가 없다면 코드를 직접 고치거나 임의로 우회하지 말고 다음 두 가지로 알릴 것:
  1. 답변(채팅)에서 어떤 명세와 다른지 · 무엇이 없는지를 바로 짚어서 설명한다
  2. 해당 지점의 FE 코드에 `// TODO(BE): <구체적인 불일치 · 누락 내용>` 형식의 주석을 남긴다 (나중에 `grep TODO(BE)`로 추적 가능하도록). 이 용도 외에 TODO 주석을 남발하지 않는다
- 동일한 역할의 Axios 인스턴스, WebSocket 연결, Zustand 스토어 중복 생성 금지
- 불필요한 추상화, 과도한 예외처리 금지
- 빌드 테스트는 수행하지 말 것. **실행·통신 확인은 사용자가 직접 BE를 붙여서 진행한다.** 그러므로 AI는 실제 동작 여부를 확인할 수 없다는 이유로 REST 응답 · WS 이벤트를 흉내 내는 가짜(mock) 데이터나 임시 성공 처리로 코드를 채우지 말 것 — 언제나 API명세서 · 프로토콜에 정의된 실제 엔드포인트 · 이벤트를 그대로 호출 · 구독하는 코드로 작성한다. 실제로 붙여봐야 확인되는 부분은 그 상태로 두고, 확인이 필요하다는 사실을 답변으로 알릴 것
- 라우터에 직접 연결되는 화면 컴포넌트는 pages 아래에 작성
- 필요한 API 함수는 src/api 내에 만들어야 하며 여기 있는 것을 import해서 사용
- WS 이벤트 구독 · 발신은 src/ws 내 파일을 통해서만 하며, 컴포넌트에서 소켓 객체를 직접 다루지 않음
- 로딩, 에러, 스켈레톤 처리는 필요하다면 추가할 것
- 공통 및 역할 분리 컴포넌트는 src/components 내에 작성
- BE 주소(`http://127.0.0.1:8080`, `ws://127.0.0.1:8080`)는 로컬 고정값이다. 개발 중에도 BE가 항상 로컬에서 별도로 실행되고 있다고 가정하며, 배포 환경별 주소 분기 로직을 만들지 말 것
- FE 쪽 REST · WS는 인증 헤더가 필요 없다 (MCP 토큰 · `X-Caller`는 AI 전용이며 FE 코드와 무관하다). Authorization 헤더를 붙이는 로직을 만들지 말 것

# 2. 주석

- 기능 변경으로 인해 주석 내용이 달라져야 하는 경우가 아니면 기존 주석을 수정하거나 제거 금지
- 새 주석은 한글 개조식으로 간단하게 작성하며 불필요한 주석 금지
- 주석에 파일명이나 폴더명을 설명하지 말 것

# 3. 공통 사용 폴더 및 파일 구조

- src/routes/router.jsx : 라우팅 관리
- src/api : REST 요청 관련 함수 모음 폴더
- src/api/httpClient.js : Axios 공통 인스턴스 (baseURL `http://127.0.0.1:8080`). 인증 헤더 없음
- src/api/errors.js : 서버 에러 응답(`{code, message, detail?}`)을 다루는 공통 처리 함수. `message`는 사용자 노출용, `detail`은 절대 화면에 노출하지 않음
- src/ws/feSocket.js : `/ws/fe` 연결 · 재연결 · 봉투(`{type, data}`) 파싱을 담당하는 단일 소켓 모듈
- src/ws/eventBus.js : WS `type`별 리스너 등록 · 해제. 모르는 `type`은 무시하고 별도 처리하지 않음
- src/store : Zustand 스토어 모음. 도메인별로 파일 분리 (예: sessionStore, settingsStore, gestureStore). 하나의 거대 스토어로 합치지 말 것
- src/styles/tokens.css : 색상 · 여백 · 폰트 등 디자인 토큰을 CSS 변수로 선언하는 파일. 컴포넌트 스타일은 이 변수를 참조하며, 추후 디자인 교체 시 이 파일 위주로 수정
- Component.module.css : 컴포넌트별 스타일은 같은 폴더의 `.module.css`로 분리하며, 컴포넌트 로직 파일(.jsx)에는 스타일을 직접 두지 않음

# 4. 통신 규칙

## 4.1 공통 규약

- REST 목록 응답 형식은 엔드포인트마다 다르다: `{page, pageSize, total, items}` / `{items}` / 순수 배열 세 가지가 있으므로, 아래 4.2 목록에서 해당 엔드포인트 형식을 그대로 따를 것 (임의로 통일하지 말 것)
- 시각 표기가 두 가지로 혼용된다: REST 응답 · DB 값은 UTC `yyyy-MM-dd HH:mm:ss.SSS` 23자 고정폭 문자열, WS의 `deadlineMs` · `tsMs` 같은 필드는 epoch millis 정수. 형식을 섞어서 계산하지 말 것
- WS 메시지는 `{type, data}` 봉투가 고정이며 `data`는 항상 객체다 (`null`로 오지 않음). 모르는 `type`은 무시
- AI(에이전트)와 FE 사이에는 직접 채널이 없다. 화면에 표시할 내용은 전부 BE가 `/ws/fe`로 중계한 이벤트(`notice`, `tool_result`, `gesture_result`, `session_state` 등)를 통해서만 들어온다. FE가 AI의 내부 상태를 추론하거나 별도로 캐시하지 말 것
- 결과 · 안내 문구를 화면에 표시하는 책임은 FE에 있다. 수신한 이벤트의 필드(`message` 등)를 그대로 표시하면 되고, 문구를 새로 만들어내지 말 것
- `GET /api/status`는 FE가 주기적으로 폴링하는 상태 요약 엔드포인트이며, 세션 · 연결 상태 등 화면 전역 상태의 기준으로 사용할 것
- REST 요청에는 `Authorization` · `X-MC-Token` · `X-Caller` 같은 헤더를 붙이지 말 것 (MCP · AI 전용, FE 무관)

## 4.2 REST(FE) 연동 대상 — `http://127.0.0.1:8080`

기능별로 API 함수를 나눠서 src/api 아래에 작성한다. 정확한 요청 · 응답 필드는 API명세서.md 해당 절을 그대로 따를 것.

| 기능 | 메서드 · 경로 |
|---|---|
| 상태 폴링 | GET `/api/status` |
| 설정 | GET `/api/settings`, PUT `/api/settings` |
| 도구 사전 | GET `/api/tools`, GET `/api/tools?all=true` |
| 앱 스캔 · 등록 | GET `/api/apps/scan`, POST `/api/apps/scan`, GET `/api/apps`, POST `/api/apps`, POST `/api/apps/verify`, DELETE `/api/apps/{appKey}` |
| 제스처 | GET `/api/gestures`, GET `/api/gestures/{id}`, GET `/api/gestures/{id}/video`, GET `/api/gestures/{id}/npz`, PATCH `/api/gestures/{id}`, PUT `/api/gestures/{id}`, DELETE `/api/gestures/{id}` |
| 실행 기록 | GET `/api/tool-calls`, GET `/api/sessions` |
| 대시보드 | GET `/api/dashboard/overview`, `/accuracy`, `/latency`, `/usage`, `/apps`, `/summary`, `/timeseries` |
| 미리보기 · 백업 · 초기화 | GET `/api/previews/{tempId}-{take}.webm`, GET `/api/export/blobs/{name}`, DELETE `/api/data` |
| 보이스 프로필 | GET `/api/voices`, GET `/api/voices/{id}/sample`, GET `/api/voices/{id}/npz`, PATCH `/api/voices/{id}`, POST `/api/voices/{id}/activate`, DELETE `/api/voices/{id}`, GET `/api/voice-reg/{tempId}/sample` |
| 시선 보정 프로필 | GET `/api/calibs`, GET `/api/calibs/{id}`, GET `/api/calibs/{id}/npz`, PATCH `/api/calibs/{id}`, POST `/api/calibs/{id}/activate`, DELETE `/api/calibs/{id}` |
| 장비 맵핑 | POST `/api/devices/remap` |
| 모델 | GET `/api/models`, POST `/api/models/{name}/redownload` |
| 캡처 이미지 | GET `/api/captures/{file}` |

- REST(AI)(`/api/agent/**`)와 MCP(`/mcp`)는 AI 에이전트 전용이다. FE 코드에서 절대 호출하지 않는다.
- `PATCH /api/voices/{id}` · `PATCH /api/calibs/{id}` · `POST /api/devices/remap` · `PATCH /api/gestures/{id}` · `PUT /api/gestures/{id}`는 본문 필드를 직접 읽는 엔드포인트라 빈 본문 · 비객체 본문 에러 메시지가 공통이다(4.4 참고). 나머지 엔드포인트는 각자 고유 메시지를 쓰므로 임의로 통일하지 말 것

## 4.3 WS(`/ws/fe`) 연동 대상 — `ws://127.0.0.1:8080/ws/fe`

소켓 연결 · 재연결 · 파싱은 src/ws/feSocket.js 하나로만 관리하고, 컴포넌트는 src/ws/eventBus.js를 통해 `type`별로 구독한다.

**FE → BE로 보내는 이벤트**: `reg_start` · `reg_stop` · `macro_assign` · `wakeword_enroll_start` · `command_enroll_start` · `voice_reg_start` · `voice_sentence_retry` · `voice_reg_retry` · `voice_accept_anyway` · `voice_commit` · `voice_reg_cancel` · `calib_start` · `calib_point_shown` · `calib_restart` · `calib_commit` · `calib_cancel` · `user_choice`

**BE → FE로 오는 이벤트**: `listening` · `session_state` · `tool_result` · `gesture_result` · `notice` · `voice_rejected` · `gaze_cursor` · `capture_saved` · `reg_state` · `reg_take` · `reg_frame` · `reg_recorded` · `macro_saved` · `wakeword_progress` · `wakeword_done` · `command_sentence` · `command_progress` · `command_done` · `voice_sentence` · `voice_progress` · `voice_quality_warn` · `voice_review` · `voice_saved` · `voice_reg_denied` · `calib_precheck` · `calib_point` · `calib_result` · `calib_limit` · `calib_saved` · `calib_denied` · `model_progress` · `model_downloaded` · `model_ready` · `model_error` · `agent_status` · `ext_status` · `settings_sync` · `error`

- 각 이벤트의 `data` 필드 구성은 API명세서.md §4.2 · §4.3을 그대로 따른다. 필드명을 임의로 축약하거나 새로 만들지 말 것
- `error`는 보낸 소켓에만 오는 처리 실패 알림이며, `of` 필드로 어떤 요청(`type`)이 실패했는지 알 수 있다 — 토스트 등으로 노출할 때 `of` 기준으로 분기할 것
- `notice`는 AI가 보낸 페이로드를 BE가 그대로 중계하는 것이라 표(§4.3)에 없는 필드가 더 붙어 올 수 있다. 모르는 필드는 무시하고 에러로 처리하지 말 것

## 4.4 공통 에러 코드 (REST)

모든 REST 오류는 `{code, message, detail?}` 형태로 온다. `message`는 그대로 화면에 표시 가능한 한국어 문장이고, `detail`은 절대 사용자에게 노출하지 않는다.

| code | HTTP | 상황 |
|---|:-:|---|
| `INVALID_REQUEST` | 400·405·415 | 본문 · 파라미터 형식 오류 |
| `APP_NOT_REGISTERED` | 400 | 등록되지 않은 앱 실행 |
| `APP_PATH_INVALID` | 400 | 등록된 실행 파일이 존재하지 않음 |
| `REF_NOT_FOUND` | 400 | `win:N` / `app:key` 참조 실패 |
| `UNAUTHORIZED` | 401 | (FE 경로에서는 발생하지 않음. MCP 전용) |
| `ELEVATED_WINDOW` | 403 | 관리자 권한 창 제어 |
| `NOT_FOUND` | 404 | 없는 경로 · 없는 appKey |
| `BLOB_NOT_FOUND` | 404 | 저장된 npz 없음 |
| `PROFILE_NOT_FOUND` | 404 | 없는 보이스 · 보정 프로필 |
| `FILE_NOT_FOUND` | 404 | 파일 없음 |
| `GESTURE_NOT_FOUND` | 404 | 없는 제스처 id |
| `SETTINGS_STALE` | 409 | 설정 낙관적 잠금 실패 — `GET /api/settings` 재조회 후 재시도 |
| `CALIB_RESOLUTION_MISMATCH` | 409 | 보정 해상도 불일치 |
| `SESSION_REQUIRED` | 409 | 활성 세션 없음 |
| `PROFILE_LIMIT` | 409 | 프로필 4개 초과 |
| `PROFILE_IN_USE` | 409 | 사용 중이거나 마지막 1개인 프로필 삭제 시도 |
| `INTERNAL_ERROR` | 500 | 그 외 |
| `MODEL_DOWNLOAD_FAILED` | 502 | 모델 다운로드 실패 |
| `EXTENSION_UNAVAILABLE` | 503 | 브라우저 확장 미연결 |

- 에러 처리 공통 함수(src/api/errors.js)는 `code` 기준으로 분기하고, 화면에는 `message`만 노출한다. HTTP 상태 코드로 분기하지 말 것 (같은 코드가 여러 상태에 걸쳐 있음)
- MCP 도구 호출 오류(HTTP 200 + `isError: true`)는 AI 쪽 계약이라 FE와 무관하다

# 5. 상태 관리 (Zustand)

- 스토어는 도메인별로 분리하고, 컴포넌트는 필요한 스토어의 훅만 구독해서 사용
- WS로 수신한 상태 변경 이벤트(`session_state`, `settings_sync` 등)는 반드시 스토어의 액션 함수를 통해서만 반영하고, 컴포넌트나 소켓 콜백에서 상태를 직접 변경하지 말 것

# 6. 스타일링 (CSS Modules)

- 지금 단계는 통신 · 로직 확인이 우선이므로 스타일은 최소한으로만 작성
- 다만 추후 디자인만 교체할 수 있도록, 색상 · 크기 값은 처음부터 하드코딩 대신 `src/styles/tokens.css`의 CSS 변수를 참조해서 작성할 것

# 7. Tauri 관련 (배포 전용, 개발 중엔 신경 쓰지 않음)

- Tauri는 **배포 시점에 FE(React 빌드 결과물) · BE(Spring Boot) · Python Runtime을 하나의 실행 파일로 감싸는 패키징 단계에서만 쓰인다.** 개발 단계에는 전혀 관여하지 않는다
- 그러므로 개발 중 FE 코드는 **일반 웹 React 앱과 동일하게** 작성한다. `@tauri-apps/api`의 `invoke`, 플러그인, Tauri 전용 window 객체 등을 코드에서 사용하지 않는다
- 파일 시스템 접근, 네이티브 다이얼로그 등 OS 레벨 기능이 필요해 보이는 경우에도, 지금 단계에서 Tauri API로 구현하지 말고 **BE에 해당 REST/WS가 있는지 먼저 API명세서.md에서 확인**한다. 명세에 없으면 1장의 규칙대로 채팅 설명 + `// TODO(BE)` 주석으로 남기고, 임의로 Tauri API를 끌어와 구현하지 않는다
- Tauri 패키징 관련 설정 파일(`tauri.conf.json`, `src-tauri/` 등)은 배포 담당자의 영역이므로 FE 작업에서 건드리지 않는다
