$ErrorActionPreference = "Stop"

# 테스트도 실제 sidecar 파일 없이 컴파일할 수 있게 외부 바이너리만 임시 제외한다.
$env:TAURI_CONFIG = '{"bundle":{"externalBin":[],"resources":[]}}'

cargo test --manifest-path "$PSScriptRoot\..\src-tauri\Cargo.toml" --lib
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
