# SIA Integration (Tauri 셸)

Frontend/Backend/AI 세 프로세스를 하나의 데스크톱 앱으로 묶는 Tauri v2
프로젝트. 실제 UI는 없고(`Frontend/dist`를 그대로 로드), 이 프로젝트가
하는 일은:

1. 앱 시작 시 BE sidecar 실행 → `runtime.json`의 실행 ID와 `/api/status`를 확인 → AI sidecar 실행
2. 창의 X 버튼은 종료가 아니라 숨기기 (트레이로 감춤)
3. 트레이 아이콘: "열기"(대시보드 다시 표시) / "종료"(sidecar까지 확실히 kill 후 종료)
4. BE의 `/ws/fe` 알림을 overlay 창(`notify_bridge.rs` + `overlay/index.html`)으로
   중계해서 토스트/진행상태 표시 — 네이티브 OS 토스트는 안 쓰기로 결정, overlay 창 하나로 통합

## 아직 안 된 것 / 확정 안 된 것

- **sidecar 바이너리 자체가 없음** — `src-tauri/binaries/`에 놓을
  `sia-backend-*.exe`(jpackage), `sia-ai-*.exe`(PyInstaller onedir)를 만드는
  작업이 선행돼야 실제로 뜬다. AI는 exe 옆에 `sia-ai-support/`가 필요하다.
- **sidecar 파일명은 임시 계약** — 현재는 `sia-backend`와 `sia-ai`를 사용한다.
  최종 패키징 방식이 정해지면 실행 인자와 리소스 디렉터리까지 함께 확정해야 한다.
- ~~AI 사용자 데이터가 sidecar 재시작마다 사라짐~~ → 해결됨. `AI/paths.py`가
  자산(`asset_path`, frozen이면 `_MEIPASS`)과 사용자 데이터(`data_path`,
  frozen이면 `%APPDATA%\SIA\ai`)를 분리했고, `wake.npz`/`speaker.npz`/
  `calib.npz`는 전부 `data_path()`를 쓴다.
- ~~onboarding 최초 1회만 표시~~ → 구현됨 (`lib.rs`의 `spawn_sidecars`가 BE
  `/api/status`의 `activeVoiceId`·`activeCalibId`가 둘 다 있으면 메인 창 생성을
  생략한다). 다만 sidecar 바이너리가 없어 BE를 sidecar로 못 띄우는 지금은 이 판단
  자체가 실행되지 않아 실제 동작 검증은 아직 못 함.

## 빌드/검증

Windows에서 설치 파일을 다시 만들 때는 프로젝트 루트에서 아래 명령을 실행한다.
AI 빌드에는 `ai_env`의 Python을 명시한다. 이 명령은 Backend, AI, Frontend,
Tauri 앱을 다시 빌드하고 Inno Setup 설치 파일까지 만든다.

```powershell
cd C:\Users\SSAFY\Desktop\Projects\special_project\S15P21D106
powershell -NoProfile -ExecutionPolicy Bypass -File .\Integration\scripts\build-sidecars.ps1 -PythonExe "C:\Users\SSAFY\miniforge3\envs\ai_env\python.exe"
```

완료된 파일: `Integration\scripts\Output\sia-desktop-0.1.0-setup.exe`
`npx tauri build --no-bundle` 단계에서 `Frontend` 빌드도 자동 실행된다.

Windows에서 Tauri/Rust 코드와 준비 확인 테스트는 실제 sidecar 파일 없이도
검증할 수 있다.

```powershell
cd Integration
npm install
npm run check
npm test
```

`npm run dev`와 `npm run build`는 임시 이름의 실제 sidecar 파일이
`src-tauri/binaries/`에 들어온 뒤 사용한다. 2026-09-16 기준으로 Windows에서
`cargo check`, 준비 확인 단위 테스트 2개, Frontend를 포함한 Tauri 디버그 빌드가
성공했다. 디버그 빌드는 sidecar 목록만 일시적으로 비운 상태에서 검증했다.

## 구조

```
Integration/
├── package.json           # @tauri-apps/cli
└── src-tauri/
    ├── tauri.conf.json     # frontendDist, sidecar 등록(externalBin), 창 설정
    ├── Cargo.toml
    ├── capabilities/default.json   # sidecar 실행/kill, 알림 권한
    ├── binaries/           # sidecar 실행파일 놓는 자리 (README 참고)
    └── src/lib.rs          # 트레이/close-to-hide/sidecar 오케스트레이션
```
