# Integration 작업 합의

이 문서는 `Integration/` 작업을 이어가는 에이전트와 개발자가 따라야 할 현재 합의다.
Backend, AI, Frontend의 세부 구현 문서가 아니라 Tauri 데스크톱 통합 범위만 다룬다.

## 현재 단계

- `Integration/`은 Frontend 화면을 WebView에 표시하고 Backend와 AI를 sidecar로
  실행하는 Tauri v2 데스크톱 셸이다.
- `build-sidecars.ps1`이 Backend bootJar·jpackage, AI PyInstaller onedir,
  Frontend·Tauri release 빌드, Inno Setup 설치 파일 생성을 한 번에 수행한다.
- 2026-09-27 기준 로컬에서 두 sidecar와
  `scripts/Output/sia-desktop-0.1.0-setup.exe` 생성까지 완료했다.
- 빌드 산출물은 용량 때문에 Git에 커밋하지 않는다. 새 checkout에서는 아래 빌드
  절차로 다시 생성해야 한다.
- 2026-09-23 설치본 실행 로그에서 Backend·AI 기동, `/api/status`, `/ws/fe`,
  시선 보정 저장까지 확인했다. 2026-09-27에 다시 만든 최신 설치본은 재설치 후
  실행 검증이 남아 있다.

## 현재 배포 계약

- sidecar 논리 이름은 `sia-backend`, `sia-ai`다.
- Tauri가 빌드 입력으로 기대하는 Windows 파일명은 다음과 같다.
  - `sia-backend-x86_64-pc-windows-msvc.exe`
  - `sia-ai-x86_64-pc-windows-msvc.exe`
- Tauri release 출력과 설치 폴더에서는 각각 `sia-backend.exe`, `sia-ai.exe`가 된다.
- Backend는 jpackage의 `app/`·`runtime/`, AI는 PyInstaller onedir의
  `sia-ai-support/`와 함께 배치한다.
- 실제 바이너리는 `src-tauri/binaries/`에 두며 Git에 커밋하지 않는다.
- Backend가 먼저 실행되고 준비 완료가 확인된 후 AI를 실행한다.
- 창의 닫기 버튼은 창만 숨기고, 트레이의 종료 메뉴가 sidecar까지 종료한다.

## Backend 준비 확인

고정 시간 대기는 사용하지 않는다. 현재 구현은 다음 조건을 모두 만족해야 Backend가
준비된 것으로 판단한다.

1. `%APPDATA%/SIA/runtime.json`을 읽을 수 있다.
2. `runtime.json`의 `launchId`가 이번에 Tauri가 Backend에 전달한 실행 ID와 같다.
3. `runtime.json`의 포트에서 `GET /api/status`가 HTTP 200을 반환한다.

45초 안에 준비되지 않으면 Backend를 종료하고 AI는 실행하지 않는다. 오래된
`runtime.json`을 현재 Backend로 오인하지 않도록 실행 ID를 대조한다. jpackage
런처와 실제 JVM의 PID는 서로 달라 PID 대조는 사용할 수 없다.

## 포트 정책

- 현재 배포 계약은 루프백 고정 포트 `61015`다.
- Backend, Frontend REST·`/ws/fe`, Extension `/ws/ext`, Tauri 알림 브리지가
  모두 `127.0.0.1:61015`를 사용한다.
- AI와 Tauri의 Backend 준비 확인은 `runtime.json`의 포트를 사용한다.
- 동적 포트 주입은 아직 구현하지 않았다.
- 포트를 변경할 때는 다음 연결 지점을 한 번에 맞춰야 한다.
  - Backend 실행 인자 또는 환경변수
  - Frontend REST 주소와 `/ws/fe`
  - AI가 읽는 `runtime.json`
  - Extension의 `/ws/ext`
  - Tauri `notify_bridge.rs`와 overlay의 REST 자산 URL
- 알려진 불일치: `overlay/index.html`의 캡처 이미지 URL 한 곳은 아직 `8080`이라
  `61015`로 고쳐야 한다.

## 검증

최종 sidecar가 없어도 다음 명령으로 Tauri/Rust 코드와 준비 확인 테스트를 검증한다.

```powershell
cd Integration
npm install
npm run check
npm test
```

- `npm run check`는 검증 중에만 `externalBin`을 비워 Rust 전체 타깃을 컴파일한다.
- `npm test`는 `runtime.json` 파싱·실행 ID 대조, `/api/status`, 온보딩·자동 시작
  판정을 포함한 Rust 단위 테스트를 실행한다.
- 2026-09-27 기준 Windows에서 `npm run check`, Rust 테스트 8개, Backend 테스트가
  통과했다.
- `npm run dev`와 `npm run build`는 실제 sidecar 파일이 준비된 환경에서 사용한다.

## 해결된 항목 (2026-09-21 코드 확인)

아래 두 항목은 한때 "확정 안 된 것"으로 분류돼 있었으나, 코드 확인 결과 이미
구현이 끝나 있었다. 착오로 오래 남아있던 경고를 지운다.

- **AI 사용자 데이터 경로**: `AI/paths.py`가 `ASSET_DIR`(읽기 전용 모델,
  frozen이면 `_MEIPASS`)와 `DATA_DIR`(사용자 데이터, frozen이면
  `%APPDATA%\SIA\ai`)를 분리해뒀다. `wake.npz`/`speaker.npz`/`calib.npz`는
  전부 `data_path()`로, 모델 자산은 `asset_path()`로 읽는다. 자체
  `_selftest()`까지 있어 frozen 상태에서 사용자 데이터가 임시 추출 폴더로
  가지 않는지 검증한다. PyInstaller로 얼려도 온보딩 데이터가 재시작마다
  날아가는 문제는 없다.
- **네이티브 알림의 Frontend 연결**: `notify_bridge.rs`가 BE `/ws/fe`를
  그대로 overlay 창(`overlay/index.html`)으로 중계하고, overlay는
  Frontend의 `TopNotification.jsx`/`BootToast.jsx` 표시 로직을 포팅해
  kind별로 그린다. 오버레이 웹뷰가 리스너 등록을 마치기 전에 부팅 토스트가
  유실되는 문제도 `sia://overlay-ready` 핸드셰이크로 해결했다
  (`notify_bridge::resend_last_session_state`). 남은 의존성은 포트뿐이다.

## 남은 확인·정리

- 2026-09-27 생성 설치 파일을 새로 설치한 뒤 Backend·AI 기동, 온보딩 생략,
  트레이 종료까지 다시 검증한다.
- `overlay/index.html`의 캡처 이미지 URL에 남은 `8080`을 `61015`로 맞춘다.
- 현재는 고정 포트 `61015`를 사용한다. 동적 포트가 필요해질 때만 Frontend,
  Extension, Tauri 알림 브리지의 주입 방식을 함께 설계한다.

## 설치 리소스 배치 (2026-09-21 확정)

- Backend jpackage의 `app/`·`runtime/`과 AI onedir의 `sia-ai-support/`를
  `tauri.conf.json`의 `bundle.resources`에 등록했다.
- `build-sidecars.ps1`은 Tauri 최종 빌드 직전에 세 폴더가 모두 있는지 검사한다.
