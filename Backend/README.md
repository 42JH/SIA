# SIA — Spring 백엔드

> 모션·시선·음성으로 Windows 를 조작하는 로컬 어시스턴트의 백엔드(BE) 프로세스.
> **FE·AI 가 붙는 계약의 정의는 `docs/` 3종** — `API명세서.md`(REST · MCP · WS 양식) ·
> `프로토콜.md`(채널 · 세션 · 시나리오) · `ERD.md`(스키마) 다.
> 그 원천인 확정 와이어프레임 · 시퀀스 다이어그램 4장(2026-09-01 확정) · `API.md` · `PROTOCOL.md` ·
> `BLUEPRINT.md` · `ERD.sql` 은 레포 밖 내부 문서다 — 아래 본문과 코드 주석의 `API.md §6.3` 류 참조는 전부 그쪽을 가리킨다.

## 스택

| 항목 | 값 | 비고 |
|---|---|---|
| Java | 21 (toolchain) | |
| Spring Boot | **4.1.1** | Boot 4 는 기술별 자동구성이 분리됐다 — Flyway 는 `spring-boot-starter-flyway` 여야 돈다 |
| Spring AI | **2.0.1** (BOM) | `@McpTool`/`@McpToolParam` 은 `org.springframework.ai.mcp.annotation` (1.1 의 org.springaicommunity 아님) |
| DB | SQLite (`sia.db`) + Flyway V1 | 전부 JdbcTemplate — JPA 엔티티 없음 (`starter-jdbc`) |
| Windows 제어 | JNA 5.14 (`jna-platform`) | User32 SendInput·EnumWindows, 탐색기 항목은 COM 레이트 바인딩 + UIA, 휴지통은 `Desktop.moveToTrash` |
| webm 인코딩 | JAVE2 번들 ffmpeg (win64) | 등록 미리보기. +약 30MB (배포 명세 합의) |
| Jackson | **3** (`tools.jackson`) | Boot 4 컨버터 · MCP SDK 와 같은 버전으로 통일(2026-09-09). `ObjectMapper` 는 Boot 가 등록한 빈을 주입받는다 |
| API 문서 | springdoc-openapi 3.1.0 | `/swagger-ui.html` |

## 실행

```bash
./gradlew bootRun
```

- **작업 디렉터리는 반드시 `Backend/`** — DB URL 이 상대 경로(`jdbc:sqlite:sia.db`)라 실행 위치에 DB 가 생긴다.
  `bootRun` 은 자동으로 맞고, IDE 는 커밋된 공유 실행 설정(`.run/Backend bootRun.run.xml`, `.run/Backend.run.xml`)을 쓴다.
- `127.0.0.1:8080` 에만 바인딩된다 — 이 프로세스는 창을 닫고 파일을 지운다. LAN 에 열면 그 권한이 네트워크로 나간다.
- 첫 기동에 Flyway 가 스키마와 설정 싱글턴 시드를 만들고, `ToolCatalogSync` 가 코드의 도구 목록
  (`ToolCatalog` 30개 + `@McpTool` 설명·스키마)을 tool 테이블에 UPSERT 하며, 그 뒤
  `DefaultGestureBootstrap` 이 기본 제공 제스처 9종 중 없는 이름을 gesture 테이블에 넣는다 (기능은 빈칸).
- AI 파트는 `%APPDATA%/SIA/runtime.json` 의 `{token, port, pid}` 를 읽어 접속한다.

| 환경변수 | 기본값 | 용도 |
|---|---|---|
| `SIA_DB_URL` | `jdbc:sqlite:sia.db` | DB 위치 |
| `SIA_DATA_DIR` | `%APPDATA%/SIA` (없으면 `~/.sia`) | runtime.json · `previews/`(등록 미리보기 webm) · `gestures/`(제스처 등록 영상) · `models/` |
| `SIA_AGENT_TOKEN` | `sia-mcp-server` | MCP Bearer 토큰 |

```bash
./gradlew test
```

## 표면

| 표면 | 주소 | 인증 |
|---|---|---|
| WS (AI) | `ws://127.0.0.1:8080/ws/agent` | 없음 — hello·세션·등록·캘리브레이션·모델·제스처 실행 |
| WS (FE) | `ws://127.0.0.1:8080/ws/fe` | 없음 — 미리보기 프레임·세션 상태·진행률·알림 |
| WS (확장) | `ws://127.0.0.1:8080/ws/ext` | 없음 — 브라우저 본문 텍스트 공급 (저장소 루트 `Extension/`) |
| MCP | `http://127.0.0.1:8080/mcp` | `Authorization: Bearer` + `X-Caller: LLM\|GESTURE` (Streamable HTTP) |
| REST (AI) | `http://127.0.0.1:8080/api/agent/**` | 없음 — npz·샘플 오디오 업/다운로드(ETag=sha256), 프로필 임시본, 통계 배치 |
| REST (FE) | `http://127.0.0.1:8080/api/**` | 없음 — 상태·설정·앱·제스처(페이지네이션·영상)·보이스/시선 프로필·장비 맵핑·기록·대시보드·백업·삭제 |

- WS 메시지는 전부 `{"type","data"}` 봉투다. 모르는 type 은 로그만 남기고 무시한다.
- CORS 는 `/api/**` 에만, 오리진은 `http://localhost:*`·`http://127.0.0.1:*` 뿐이다.

## 구조

```
com.sia.assistant
├── ws/            AgentHub·FeHub·ExtHub — 봉투 송수신, 수신은 스프링 이벤트로 발행
├── wsroutes/      채널별 type 스위치 (Agent·Fe·Ext)
├── bootstrap/     AgentBootstrapper — hello→모델 로드→recognition_start→PASSIVE (01 다이어그램)
├── registration/  제스처 3회 촬영·보이스 5문장·시선 보정(재측정 3회 카운트) 오케스트레이터 (03·04)
├── gestureexec/   BE 매크로 실행자 — 매핑 조회→enabled·컨텍스트 판별→스텝 실행 (03 실행부)
├── relay/         온보딩 이름 불러보기(호출어 샘플) 중계 + 카메라/마이크 미리보기(수명은 BE 관리) + AI 동기화 페이로드 조립(AgentSyncNotifier)
├── profile/       ★보이스·시선 보정 프로필 (각 최대 4개 — 사용 1·스톡 3, 장비 맵핑, 프로필별 정확도)
├── model/         HuggingFace 다운로드·sha256 검증·진행률 (01) — 목록 models.json 은 아직 빈 배열
├── mcp/           ToolCatalog(29)·ToolGate·RefResolver·ToolInvoker + tools/
├── context/       컨텍스트 체인 판별 (video·youtube·explorer …)
├── domtext/       확장 왕복 — requestId 상관, 4초 타임아웃, 20,000자 컷 + 미연결 시 접근성 폴백
├── control/process/ 앱 실행(화이트리스트)·앱 스캔·브라우저 검색(확장 탭 ↔ OS 기본 브라우저)
├── control/browser/ 확장 없을 때의 본문 공급 — UIA Document TextPattern (control/com 의 ComWorker 스레드)
├── session/       세션 타이머 — BE 소유, 만료를 능동 push (ACTIVE/PASSIVE + deadlineMs)
├── settings/      설정 싱글턴·blob(wakeword)·제스처 매핑(원천 테이블, 제스처별 템플릿 npz 포함)·전체 삭제
├── control/       JNA 창 제어·SendInput(휠·미디어 키)·앱 실행·휴지통·파일 저장·탐색기 항목(com/, explorer/)
├── logging/       tool_call 기록(REQUIRES_NEW)·usage_event 배치(멱등)·400일 보존
├── config/        WS·보안·토큰·CORS·HTTP 요청 로그·데이터 디렉터리
└── api/           agent(blobs·gestures·profiles·events) + web(FE REST 전체)
```

## 기본값

| 값 | 기본 | 출처 |
|---|---|---|
| 호출어 | `시아야` | V1 시드를 V4 가 갱신 (`seed/default-settings.json` 과 동일 값). 온보딩 녹음 문장과 같다 |
| 설정 키 | 6종 (`wakeWord`·`sessionSeconds`·`autoStart`·`gazeCursor`·`micDevice`·`cameraDevice`) | `settings/SettingsSchema` — 자유 JSON 이지만 이 키들은 유실·오타입이 막힌다. 옛 `screen` 은 삭제 |
| 세션 유지 | 15초 (기본, 변경 가능) | `settings.sessionSeconds` — 개시·갱신마다 다시 읽어 다음 세션부터 적용 |
| 도구 | 30개 | `ToolCatalog.SPECS` — 유일한 원천 (2026-09-01 `files.open`·`system.lock`, 2026-09-02 `screen.capture`·`screen.capture_region`, 2026-09-07 `volume.set`·`browser.search`, 2026-09-09 `browser.dom_text` 추가). 기동 시 `ToolCatalogSync` 가 tool 테이블에 UPSERT |
| 기본 제공 제스처 | 9종 (기능은 빈칸) | `DefaultGestures` — 기동마다 없는 이름만 주입(2026-09-11 확정). MediaPipe 기본 7종 + 좌우 스와이프, 전부 `context=NULL`·`hands=1`, 스와이프만 `motion=DYNAMIC`. 스텝이 없어 지정 전에는 `runnable=false` 이고, 어떤 기능을 걸지는 사용자가 `PUT /api/gestures/{id}` 로 정한다 |
| 기록 보존 | 400일 | 대시보드의 가장 긴 축이 12개월 |
| 프로필 | 보이스·시선 각 최대 4개 (사용 1+스톡 3) | 회의 확정 2026-09-01. 시선 재측정은 세션당 3회 (BE 카운트) |

### 마이그레이션

| | 내용 |
|---|---|
| V1 | ERD 의 SQLite 각색 + 설정 싱글턴 시드 (tool·기본 제스처는 기동 시 Java 가 넣는다) |
| V2 | `calib_profile.grade` — 보정 등급 판정을 AI 로 이관 |
| V3 | `gesture.hands`·`gesture.motion` — 한손/양손 × 정적/동적 형태 축 (AI 인식 파이프라인 요청). SQLite 의 `ADD COLUMN` 은 CHECK 를 못 받아 값 검증은 `GestureService` 가 단독으로 맡는다 |

2026-09-01 에 옛 V1~V6 을 V1 하나로 압축했고, **같은 날 와이어프레임 확정분(프로필 2테이블·gesture
3컬럼·usage_event.profile_id·blob 이름 축소)도 V1 에 그대로 흡수했다** — 여전히 커밋 전이라 이력이
존재하는 DB 가 없다. 그 전에 만들어진 로컬 `sia.db`(테스트 DB 포함)는 Flyway 검증에 실패하므로 지우고 재기동할 것.
같은 날 tool·기본 제스처 시드를 SQL 에서 기동 시 Java(`ToolCatalogSync`·`DefaultGestures`)로
옮겼다 — 도구 목록의 원천을 코드 하나로 유지하기 위해서다.

## 알려진 결정·함정

- **★ REST 본문은 `@RequestBody String` 으로 받고 `JsonBody.parse` 로 푼다.** 빈 본문 · 깨진 JSON ·
  객체가 아닌 본문의 400 메시지를 우리가 정한 문장(§0.4)으로 내기 위해서다. 컨버터에 맡기면 프레임워크
  메시지가 나간다. 2026-09-09 이전에는 이유가 하나 더 있었다 — Jackson 버전이 갈려 `@RequestBody JsonNode`
  가 500 으로 죽었다. Jackson 3 통일로 그 이유는 사라졌지만 규칙은 위 이유로 유지한다.
- **응답 본문에는 라이브러리 타입을 담지 않는다** — DB 의 JSON 텍스트는 `readValue`/`convertValue` 로
  `Map`·`List` 로 바꿔 담는 것이 안전하다. 직렬화가 깨져도 값은 정상이라 반환값 단언으로는 안 잡힌다 —
  `SettingsControllerJsonTest` 처럼 **응답 JSON 을 보는 테스트**가 그 층을 지킨다.
- **확인 게이트는 BE 에 없다.** 카탈로그의 C 플래그는 관문이 아니라 **AI 에게 주는 선언**이고 MCP
  `destructiveHint` 로 나간다. BE 는 승인이 끝난 요청으로 보고 실행한다 (`files.delete` 는 휴지통 이동만).
- **도구 성공이 세션을 연장하지 않는다** — 연장 경로는 `session.extend` 하나뿐이다.
- **ERD 대비 의도적 변경 1건**: `gesture.blob_name`(blob `gestures_custom` 한 파일 참조)을 없애고 `custom` 플래그 +
  `npz`/`npz_sha256`/`npz_bytes` 컬럼으로 — 흐름도 03 은 제스처별 npz 다 (2026-09-02, V1 헤더 · BLUEPRINT §9). canned 는 custom=0.
  스키마가 바뀌었으므로 **기존 로컬 `sia.db` 는 삭제 후 재기동**해야 한다 (Flyway 검증 실패).
- tool 행은 **기동 시 `ToolCatalogSync` 만 만든다** (마이그레이션 시드 없음). 카탈로그에서 빠진 도구도
  행은 남기고 `available` 만 내린다 — `tool_call` 이 지난 기록의 FK 로 그 행을 요구한다.
  기본 제공 제스처 주입(`DefaultGestureBootstrap`)은 그 뒤다 — 스텝이 없어 `gesture_step.tool_name` FK 에 걸릴 일은
  없지만 시드 순서(도구 → 제스처)를 유지한다.
- 시각은 전부 UTC `yyyy-MM-dd HH:mm:ss.SSS` 23자. `common/Times` 가 유일한 출처이고 SQL 의 `datetime('now')` 는 금지다.
- `@EventListener(ApplicationReadyEvent)` 는 `@Order` 필수 — ToolCatalogSync(0) → 기본 제공 제스처 주입(5) → 세션 고아 정리(10) → 보존(20) → 모델(30).
- JNA COM: `getAutomationProperty` 는 VARIANT 가 아니라 IDispatch 를 준다. UIA 는 `GetCurrentPropertyValue`(vtable 10)
  경유로만 부른다 — 먼 인덱스는 오프바이원 시 JVM 이 죽는다.
- .NET Framework(WinPS 5.1) WebSocket 클라이언트는 Tomcat 의 `Connection: upgrade, keep-alive` 를 거부한다.
  스모크는 Node 내장 WebSocket 으로 할 것 — FE·AI·브라우저 클라이언트에는 영향 없다.
- 대시보드는 BE 쪽이 끝났고 **남은 건 AI 파트의 계측**이다. `usage_event.kind` 철자가 맞지 않으면 카드가 빈 채로 뜬다 (API.md §8).
- 삭제 되돌리기(Undo)·기본 제스처 확정은 아직 스코프 밖이다 (API.md §8). 화면 잠금은 `system.lock`, 캡처 결과물 저장·표시는
  `screen.capture`·`screen.capture_region`(좌상단·우하단 두 점 영역) + FE `capture_saved` + `GET /api/captures/{file}` (`~/Pictures/SIA/`), 모델 재다운로드 유도는
  `POST /api/models/{name}/redownload` 로 들어왔다 (2026-09-02, 흐름도 갭 해소).
- ★온보딩 낭독 문장 5개("명령하듯 말해보세요" = 보이스 등록, 별도의 명령 문장 단계는 없다)의 원문은 FE·AI 공통 상수다(불변·하드코딩) — BE 는 `n` 만 중계하고 `text` 를 보내지 않는다. 문장 단위 미달은 `voice_sentence_rejected` 로 사유만 중계한다.
- ★설정 JSON 은 자유 문서지만 **알려진 키 6종은 서버가 지킨다** — PUT 이 통째 교체라 부분 문서 한 번에 `micDevice` 가 사라지면 프로필 장비 맵핑이 영구히 깨진다. 빠진 키는 기존 값으로 채우고, 타입이 틀리면 400 (API.md §1.3).
- ★장치 이름은 **OS 원문 문자열** 하나로 통일한다(별도 id 없음). 설정이 `null`(시스템 기본)이면 프로필 확정 시 FE 가 `deviceLabel` 로 실명을 보내야 자동 맵핑 후보가 된다.
- ★보이스·시선 등록의 임시본은 **DB 가 아니라 오케스트레이터 메모리**다 — 커밋(voice_commit/calib_commit)만 프로필 행을 만든다. 재시작하면 진행 중이던 등록은 사라진다 (BLUEPRINT §7 판단 2).

## 검증

- `./gradlew test` — 49개 클래스 277개 통과 (2026-09-10).
- 기동 스모크 기록(2026-08-27~28, 도구가 25개이던 시점): Flyway 적용, MCP `initialize`→`tools/list`,
  `context.get` 실창 열거, `files.delete` 휴지통 이동, WS `hello`→`recognition_start`→세션 수명주기,
  `gesture_exec` 매크로 실행, 탐색기 항목 bounds 12/12, 확장 `/ws/ext` 왕복, `GET /api/apps/scan` 103건.
  **확인 게이트 제거·세션 15초 변경 이후로는 다시 돌리지 않았다** — 붙이기 전에 한 번 더 확인할 것.
