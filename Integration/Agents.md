# Integration 작업 합의

이 문서는 `Integration/` 작업을 이어가는 에이전트와 개발자가 따라야 할 현재 합의다.
Backend, AI, Frontend의 세부 구현 문서가 아니라 Tauri 데스크톱 통합 범위만 다룬다.

## 현재 단계

- `Integration/`은 Tauri v2 기반 데스크톱 셸 스캐폴딩이다.
- Frontend 화면을 WebView에 표시하고 Backend와 AI를 sidecar로 실행하는 구조다.
- Backend와 AI의 최종 배포 파일은 아직 준비되지 않았다.
- Backend, AI, Frontend는 각자의 `dev/*` 작업에서 독립적으로 정리하고 개발한다.
- 각 파트를 `integration` 브랜치로 합친 뒤 최종 실행 인자, 포트, 리소스 배치를 확정한다.

## 현재 임시 계약

- sidecar 논리 이름은 임시로 `sia-backend`, `sia-ai`를 사용한다.
- Windows 빌드가 기대하는 임시 파일명은 다음과 같다.
  - `sia-backend-x86_64-pc-windows-msvc.exe`
  - `sia-ai-x86_64-pc-windows-msvc.exe`
- 실제 바이너리는 `src-tauri/binaries/`에 두며 Git에 커밋하지 않는다.
- Backend가 먼저 실행되고 준비 완료가 확인된 후 AI를 실행한다.
- 창의 닫기 버튼은 창만 숨기고, 트레이의 종료 메뉴가 sidecar까지 종료한다.

## Backend 준비 확인

고정 시간 대기는 사용하지 않는다. 현재 구현은 다음 조건을 모두 만족해야 Backend가
준비된 것으로 판단한다.

1. `%APPDATA%/SIA/runtime.json`을 읽을 수 있다.
2. `runtime.json`의 PID가 이번에 Tauri가 실행한 Backend PID와 같다.
3. `runtime.json`의 포트에서 `GET /api/status`가 HTTP 200을 반환한다.

45초 안에 준비되지 않으면 Backend를 종료하고 AI는 실행하지 않는다. 오래된
`runtime.json`을 현재 Backend로 오인하지 않도록 PID 대조를 유지한다.

## 포트 정책

- 각 파트가 독립 개발 중인 현재 단계에서는 기존 기본 포트 `8080`을 유지한다.
- 지금은 Backend, Frontend, AI, Extension의 포트를 일괄 변경하지 않는다.
- 최종 포트 정책은 각 파트를 `integration` 브랜치에 합친 뒤 적용한다.
- 통합 시 Tauri를 포트 설정의 기준점으로 삼는 방향을 우선 검토한다.
- 포트를 변경할 때는 다음 연결 지점을 한 번에 맞춰야 한다.
  - Backend 실행 인자 또는 환경변수
  - Frontend REST 주소와 `/ws/fe`
  - AI가 읽는 `runtime.json`
  - Extension의 `/ws/ext`
- AI와 Tauri의 준비 확인은 이미 `runtime.json`의 포트를 사용한다. Frontend와
  Extension에는 현재 `8080` 하드코딩이 남아 있다.

## 검증

최종 sidecar가 없어도 다음 명령으로 Tauri/Rust 코드와 준비 확인 테스트를 검증한다.

```powershell
cd Integration
npm install
npm run check
npm test
```

- `npm run check`는 검증 중에만 `externalBin`을 비워 Rust 전체 타깃을 컴파일한다.
- `npm test`는 `runtime.json` 파싱과 `/api/status` 성공 판정을 검사한다.
- 2026-09-16 기준 Windows에서 위 검사와 Frontend 포함 Tauri 디버그 빌드가 성공했다.
- `npm run dev`와 `npm run build`는 실제 sidecar 파일이 준비된 뒤 사용한다.

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

## 아직 확정하지 않는 항목

- Backend의 jpackage/jlink 최종 구성과 동반 런타임 폴더 구조
- AI의 PyInstaller 최종 spec, 숨은 import, 모델 포함 범위
- 최종 sidecar 이름과 실행 인자
- 동적 포트 또는 고정 포트 선택
- Frontend 및 Extension의 포트 주입 방식
- **[위험, 우선 처리 필요] Tauri `bundle.resources`에 포함할 Backend/AI 보조
  파일** — `tauri.conf.json`의 `bundle`에 `resources` 키가 아직 없다.
  `scripts/build-sidecars.ps1`은 jpackage 산출물(`<sidecar>.exe` + `app/` +
  `runtime/`)을 로컬 `src-tauri/binaries/`에 나란히 배치하지만, Tauri의
  `externalBin`은 이름·타깃트리플이 맞는 sidecar 실행파일 하나만 최종 설치
  번들에 포함시키고 옆의 `app/`·`runtime/` 폴더는 자동으로 넣어주지 않는다.
  지금 설정 그대로 `tauri build`를 돌리면 설치된 앱에서 BE가 이 폴더들을 못
  찾아 실행에 실패할 가능성이 높다. `bundle.resources`에 `binaries/app`,
  `binaries/runtime`을 명시적으로 추가해야 한다. 다른 항목과 달리 포트
  정책과 무관하게 지금 바로 고칠 수 있다.

위 항목(마지막 리소스 항목 제외)은 Backend와 AI 파일 정리가 끝나기 전에
임의로 확정하지 않는다.
