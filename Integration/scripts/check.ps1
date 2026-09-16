$ErrorActionPreference = "Stop"

# Backend/AI 최종 산출물이 없는 동안에도 Tauri와 Rust 코드 자체를 검증한다.
$env:TAURI_CONFIG = '{"bundle":{"externalBin":[]}}'

cargo check --manifest-path "$PSScriptRoot\..\src-tauri\Cargo.toml" --all-targets
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
