# BE(jpackage)·AI(PyInstaller)를 빌드해서 Tauri sidecar 규칙에 맞는 이름으로
# src-tauri/binaries/ 에 배치하고, 이어서 `tauri build`로 최종 설치파일까지 만든다.
# `npm run build:sidecars`로 실행 (사이드카만 필요하면 `-SkipTauriBuild` 옵션).
#
# 전제(Agents.md "현재 임시 계약"과 동일):
#   - sidecar 논리 이름: sia-backend, sia-ai
#   - Windows 타깃 트리플: x86_64-pc-windows-msvc
#   - 최종 파일명: sia-backend-x86_64-pc-windows-msvc.exe / sia-ai-x86_64-pc-windows-msvc.exe
#
# 필요 도구: JDK 17+ (jpackage 포함, 이 프로젝트는 toolchain 21), Python + pyinstaller
# (pip install pyinstaller), 둘 다 PATH에 있어야 한다.
#
# [해결됨, 2026-09-21 재확인] AI/assistant.py·brain.py의 사용자 데이터 경로 문제는
# AI/paths.py 도입으로 이미 고쳐졌다 — frozen 상태에서는 `%APPDATA%\SIA\ai`(data_path)
# 를 쓰고, 읽기 전용 모델만 `_MEIPASS`(asset_path)를 본다. 온보딩 데이터가 재시작마다
# 사라지는 문제는 더 이상 없다. 이 스크립트로 사이드카를 새로 만들 때 추가로 손볼 것 없음.
#
# !!! 이 스크립트가 못 고치는, 여전히 남은 문제 — Integration/Agents.md 참고 !!!
# jpackage app-image로 만든 BE는 `<beName>.exe` 옆에 `app/`·`runtime/` 폴더가 상대경로로
# 같이 있어야 실행된다. 이 스크립트는 그 셋을 `src-tauri/binaries/`에 나란히 복사해서
# [5/5]의 로컬 `tauri build`(디버그)까지는 되게 만들지만, `tauri.conf.json`의
# `bundle.resources`에는 AI onedir 보조 폴더만 등록돼 있고 BE의 `binaries/app`·
# `binaries/runtime`은 아직 등록하지 않았다.
# Tauri의 `externalBin`은 sidecar 실행파일 하나만 최종 설치 번들에 넣고 옆 폴더는 자동으로
# 안 넣으므로, 이 상태로 만든 설치 파일(인스톨러)에서는 BE가 `app/`·`runtime/`을 못 찾아
# 실행이 깨질 수 있다. `bundle.resources`를 채우는 작업이 먼저 필요하다.

param(
    # 사이드카(BE·AI)만 빌드해서 binaries/에 배치하고 끝낸다 — 최종 exe 패키징(tauri
    # build, [5/5])은 건너뛴다. 사이드카 갱신만 필요할 때(예: 반복 테스트) 씀.
    [switch]$SkipTauriBuild
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot\..\.."
$integrationDir = Resolve-Path "$PSScriptRoot\.."
$binariesDir = Join-Path $integrationDir "src-tauri\binaries"
$target = "x86_64-pc-windows-msvc"

if (-not (Test-Path $binariesDir)) {
    New-Item -ItemType Directory -Path $binariesDir | Out-Null
}

# ---------------------------------------------------------------------------
# [1/5] Backend 빌드 (bootJar)
# ---------------------------------------------------------------------------
Write-Host "=== [1/5] Backend 빌드 (gradlew bootJar) ===" -ForegroundColor Cyan
Push-Location (Join-Path $root "Backend")
try {
    & .\gradlew.bat bootJar
    if ($LASTEXITCODE -ne 0) { throw "gradlew bootJar 실패 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$jar = Get-ChildItem (Join-Path $root "Backend\build\libs\*.jar") |
    Where-Object { $_.Name -notlike "*-plain.jar" } |
    Select-Object -First 1
if (-not $jar) { throw "빌드된 BE 실행 가능 jar를 못 찾았습니다 (Backend\build\libs\*.jar, *-plain.jar 제외)" }
Write-Host "BE jar: $($jar.Name)"

# ---------------------------------------------------------------------------
# [2/5] Backend jpackage (app-image) -> src-tauri/binaries/
# ---------------------------------------------------------------------------
Write-Host "=== [2/5] Backend jpackage (app-image) ===" -ForegroundColor Cyan

if (-not (Get-Command jpackage -ErrorAction SilentlyContinue)) {
    throw "jpackage 를 PATH에서 못 찾았습니다. JDK 17+ (jpackage 포함) 설치 후 JAVA_HOME\bin을 PATH에 추가하세요."
}

$beName = "sia-backend-$target"
$bePackageOut = Join-Path $env:TEMP "sia-jpackage-out"
Remove-Item $bePackageOut -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $bePackageOut | Out-Null

# --name 을 최종 sidecar 이름으로 미리 맞춰서 만든다 — jpackage 런처 exe는 자기 파일명
# 기준으로 app\<이름>.cfg 를 상대경로로 찾기 때문에, 나중에 exe만 따로 rename하면 그
# cfg를 못 찾아서 실행이 깨진다. 처음부터 이 이름으로 만들면 rename이 필요 없다.
jpackage `
    --type app-image `
    --input $jar.DirectoryName `
    --main-jar $jar.Name `
    --name $beName `
    --dest $bePackageOut
if ($LASTEXITCODE -ne 0) { throw "jpackage 실패 (exit $LASTEXITCODE)" }

$beImageDir = Join-Path $bePackageOut $beName

# app-image 산출물은 <beName>.exe + app\ + runtime\ 세 가지가 서로 상대경로로 얽혀
# 있어서 통째로 옮겨야 한다. exe 하나만 binaries\ 최상단에 두고 app\·runtime\ 도
# 그 옆(형제 폴더)에 같이 둔다. AI onedir 보조 파일은 별도의
# `sia-ai-support\`를 쓰므로 이 두 폴더와 충돌하지 않는다.
foreach ($name in @("$beName.exe", "app", "runtime")) {
    $destPath = Join-Path $binariesDir $name
    Remove-Item $destPath -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $beImageDir $name) $destPath -Recurse
}
Write-Host "BE sidecar 배치 완료: $binariesDir\$beName.exe (+ app\, runtime\)"

# ---------------------------------------------------------------------------
# [3/5] AI 빌드 (PyInstaller --onedir)
# ---------------------------------------------------------------------------
Write-Host "=== [3/5] AI 빌드 (PyInstaller --onedir) ===" -ForegroundColor Cyan

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "pyinstaller 를 PATH에서 못 찾았습니다. 'pip install pyinstaller' 먼저 실행하세요."
}

$aiName = "sia-ai-$target"
Push-Location (Join-Path $root "AI")
try {
    # 내장 모델과 호출어 학습용 부정 뱅크는 읽기 전용 자산이라
    # onedir의 sia-ai-support 폴더에 같이 넣는다.
    # wake.npz·speaker.npz·calib.npz 같은 사용자 생성 파일은 빌드 시점에 존재하지
    # 않으므로 여기 안 들어간다. 해당 파일들은 AI/paths.py가 %APPDATA%\SIA\ai 아래에서
    # 별도로 관리한다.
    $requiredAiAssets = @(
        "models\face_landmarker.task",
        "models\gesture_recognizer.task",
        "models\pose_landmarker_full.task",
        "models\siaya_v2.onnx",
        "models\eth-xgaze_resnet18.pth",
        "models\wake_neg_bank.npz"
    )
    foreach ($asset in $requiredAiAssets) {
        if (-not (Test-Path $asset)) {
            throw "AI 빌드 자산을 못 찾았습니다: $asset"
        }
    }

    pyinstaller --noconfirm --onedir --contents-directory "sia-ai-support" --name $aiName `
        --add-data "models\face_landmarker.task;models" `
        --add-data "models\gesture_recognizer.task;models" `
        --add-data "models\pose_landmarker_full.task;models" `
        --add-data "models\siaya_v2.onnx;models" `
        --add-data "models\eth-xgaze_resnet18.pth;models" `
        --add-data "models\wake_neg_bank.npz;models" `
        assistant.py
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller 실패 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# [4/5] AI onedir 산출물 배치 -> src-tauri/binaries/
# ---------------------------------------------------------------------------
Write-Host "=== [4/5] AI onedir 산출물 배치 ===" -ForegroundColor Cyan
$aiDistDir = Join-Path $root "AI\dist\$aiName"
$aiExe = Join-Path $aiDistDir "$aiName.exe"
$aiSupport = Join-Path $aiDistDir "sia-ai-support"
if (-not (Test-Path $aiExe)) { throw "AI 빌드 산출물을 못 찾았습니다: $aiExe" }
if (-not (Test-Path $aiSupport)) { throw "AI onedir 보조 폴더를 못 찾았습니다: $aiSupport" }

Copy-Item $aiExe $binariesDir -Force
$aiSupportDest = Join-Path $binariesDir "sia-ai-support"
Remove-Item $aiSupportDest -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $aiSupport $aiSupportDest -Recurse
Write-Host "AI sidecar 배치 완료: $binariesDir\$aiName.exe (+ sia-ai-support\)"

Write-Host ""
Write-Host "=== 사이드카 배치 완료 — $binariesDir ===" -ForegroundColor Green
Get-ChildItem $binariesDir

# ---------------------------------------------------------------------------
# [5/5] 최종 패키징 (tauri build) -> src-tauri/target/release/bundle/
# ---------------------------------------------------------------------------
if ($SkipTauriBuild) {
    Write-Host ""
    Write-Host "=== [5/5] 건너뜀 (-SkipTauriBuild) — 사이드카만 배치하고 종료 ===" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "=== [5/5] 전체 패키징 (tauri build) ===" -ForegroundColor Cyan
Push-Location $integrationDir
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "tauri build 실패 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$bundleDir = Join-Path $integrationDir "src-tauri\target\release\bundle"
Write-Host ""
Write-Host "=== 전체 빌드 및 패키징 완료 — $bundleDir ===" -ForegroundColor Green
if (Test-Path $bundleDir) {
    Get-ChildItem $bundleDir -Recurse -File | Select-Object FullName, Length
}
