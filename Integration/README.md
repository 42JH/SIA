# SIA Integration (Tauri 셸)

Frontend/Backend/AI 세 프로세스를 하나의 데스크톱 앱으로 묶는 Tauri v2
프로젝트. 실제 UI는 없고(`Frontend/dist`를 그대로 로드), 이 프로젝트가
하는 일은:

1. 앱 시작 시 BE sidecar 실행 → `runtime.json`의 PID와 `/api/status`를 확인 → AI sidecar 실행
2. 창의 X 버튼은 종료가 아니라 숨기기 (트레이로 감춤)
3. 트레이 아이콘: "열기"(대시보드 다시 표시) / "종료"(sidecar까지 확실히 kill 후 종료)
4. (다음 단계) FE의 WS 알림 수신 지점에서 `@tauri-apps/plugin-notification`으로
   네이티브 토스트 트리거

## 아직 안 된 것 / 확정 안 된 것

- **sidecar 바이너리 자체가 없음** — `src-tauri/binaries/`에 놓을
  `sia-backend-*.exe`(jpackage), `sia-ai-*.exe`(PyInstaller or 포터블
  파이썬) 를 만드는 작업이 선행돼야 실제로 뜬다.
- **sidecar 파일명은 임시 계약** — 현재는 `sia-backend`와 `sia-ai`를 사용한다.
  최종 패키징 방식이 정해지면 실행 인자와 리소스 디렉터리까지 함께 확정해야 한다.
- **FE 쪽 네이티브 알림 연동 미착수** — `TopNotification`/`BootToast`가
  WS 메시지를 받는 지점에 `invoke`로 알림 플러그인 호출을 추가해야 함.
- **onboarding 최초 1회만 표시** 로직은 BE/FE 쪽 작업(별도 트래킹) —
  이 프로젝트는 그 값을 참조해서 라우팅만 하면 됨.

## 빌드/검증

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
