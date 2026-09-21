# 사이드카 실행파일(sia-backend/sia-ai)이 아직 없을 때 tauri dev를 돌리기 위한 스크립트.
# check.ps1/test.ps1과 같은 방식: TAURI_CONFIG로 externalBin을 런타임에 빈 배열로 덮어써서
# tauri-build의 "리소스 존재 확인" 컴파일 타임 검사를 우회한다.
# BE/AI는 사이드카로 자동 기동되지 않으니, 따로 BE(gradlew bootRun)·AI(python assistant.py)를
# 직접 실행해서 붙여야 한다. 실제 sia-backend/sia-ai 바이너리가 생기면 이 스크립트 대신
# 그냥 `npm run dev`를 쓰면 된다.
$ErrorActionPreference = "Stop"
$env:TAURI_CONFIG = '{"bundle":{"externalBin":[],"resources":[]}}'
npx tauri dev
