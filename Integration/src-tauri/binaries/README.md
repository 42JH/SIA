# sidecar 바이너리 위치

여기에 빌드된 sidecar 실행파일을 놓는다. Tauri는 파일명이
`<name>-<target-triple>.exe` 형식이어야 인식한다 (Windows 기준
`x86_64-pc-windows-msvc`).

- `sia-backend-x86_64-pc-windows-msvc.exe`
  — Backend를 jpackage(또는 jlink 커스텀 런타임)로 만든 JRE 내장 실행파일.
- `app/`, `runtime/`
  — Backend exe가 사용하는 애플리케이션 파일과 Java 런타임. exe와 형제 경로를 유지해야 한다.
- `sia-ai-x86_64-pc-windows-msvc.exe`
  — AI를 PyInstaller onedir로 얼린 실행파일.
- `sia-ai-support/`
  — AI exe가 사용하는 Python 런타임·DLL·모델. exe와 형제 경로를 유지해야 한다.

이 폴더 안의 실제 바이너리는 git에 커밋하지 않는다 (용량 큼, 빌드 산출물).
루트 `.gitignore`가 이 폴더 전체를 제외하고 이 README만 추적하도록 설정돼 있다.

tauri.conf.json의 `bundle.externalBin`이 이 경로(확장자·타깃 트리플 제외한
이름)를 참조한다: `binaries/sia-backend`, `binaries/sia-ai`.
Tauri가 빌드 출력과 설치 폴더에 배치하는 이름은 각각 `sia-backend.exe`,
`sia-ai.exe`다. Backend jpackage 런처도 이 최종 이름으로 생성해
`app/sia-backend.cfg`와 짝을 맞춘다.
