# sidecar 바이너리 위치

여기에 빌드된 sidecar 실행파일을 놓는다. Tauri는 파일명이
`<name>-<target-triple>.exe` 형식이어야 인식한다 (Windows 기준
`x86_64-pc-windows-msvc`).

- `sia-backend-x86_64-pc-windows-msvc.exe`
  — Backend를 jpackage(또는 jlink 커스텀 런타임)로 만든 JRE 내장 실행파일.
- `sia-ai-x86_64-pc-windows-msvc.exe`
  — AI를 PyInstaller로 얼리거나, 포터블 파이썬 + 래퍼로 만든 실행파일.
    (패키징 방식은 아직 미정 — AI 패키징 논의 결과에 따라 확정)

이 폴더 안의 실제 바이너리는 git에 커밋하지 않는다 (용량 큼, 빌드 산출물).
루트 `.gitignore`에 추가 필요 — 지금은 이 README만 커밋됨.

tauri.conf.json의 `bundle.externalBin`이 이 경로(확장자·타깃 트리플 제외한
이름)를 참조한다: `binaries/sia-backend`, `binaries/sia-ai`.
