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
# !!! 지금 시점에 알려진 문제 — 이 스크립트로 못 고침, AI 코드 쪽에서 먼저 고쳐야 함 !!!
# AI/assistant.py·brain.py의 `HERE = Path(__file__).parent`는 PyInstaller로 얼렸을 때
# 임시 추출 폴더를 가리키게 된다(onefile 모드는 매 실행마다 새 임시 폴더에 풀림).
# 그 경로 아래 models/wake.npz·speaker.npz·calib.npz 는 온보딩 때 새로 쓰는 사용자
# 데이터인데, frozen 상태에서는 앱을 재시작할 때마다 그 데이터가 사라진다 — 즉 지금
# 코드 그대로 얼리면 "온보딩을 매번 다시 해야 하는" 상태가 된다. `sys.frozen`일 때는
# `Path(sys.executable).parent`(또는 %APPDATA%처럼 BE의 runtime.json과 같은 방식의
# 고정 쓰기 위치)를 쓰도록 AI 쪽에서 먼저 고쳐야 이 스크립트의 산출물이 실제로 쓸 만하다.

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
# 그 옆(형제 폴더)에 같이 둔다 — sia-ai 쪽은 onefile이라 이 두 폴더를 안 쓰므로
# 이름 충돌 없음.
foreach ($name in @("$beName.exe", "app", "runtime")) {
    $destPath = Join-Path $binariesDir $name
    Remove-Item $destPath -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $beImageDir $name) $destPath -Recurse
}
Write-Host "BE sidecar 배치 완료: $binariesDir\$beName.exe (+ app\, runtime\)"

# ---------------------------------------------------------------------------
# [3/5] AI 빌드 (PyInstaller --onefile)
# ---------------------------------------------------------------------------
Write-Host "=== [3/5] AI 빌드 (PyInstaller --onefile) ===" -ForegroundColor Cyan

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "pyinstaller 를 PATH에서 못 찾았습니다. 'pip install pyinstaller' 먼저 실행하세요."
}

$aiName = "sia-ai-$target"
Push-Location (Join-Path $root "AI")
try {
    # 내장 모델(4개, models/*.task·*.onnx)은 읽기 전용 자산이라 exe 안에 같이 얼린다.
    # wake.npz·speaker.npz·calib.npz 같은 사용자 생성 파일은 빌드 시점에 존재하지
    # 않으므로 여기 안 들어간다 — 위 경고 블록 참고, 그 파일들의 런타임 저장 위치는
    # AI 코드가 frozen 여부를 구분해서 별도로 정해야 한다.
    pyinstaller --noconfirm --onefile --name $aiName `
        --add-data "models\face_landmarker.task;models" `
        --add-data "models\gesture_recognizer.task;models" `
        --add-data "models\pose_landmarker_full.task;models" `
        --add-data "models\siaya_v2.onnx;models" `
        assistant.py
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller 실패 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# [4/5] AI 산출물 배치 -> src-tauri/binaries/
# ---------------------------------------------------------------------------
Write-Host "=== [4/5] AI 산출물 배치 ===" -ForegroundColor Cyan
$aiExe = Join-Path $root "AI\dist\$aiName.exe"
if (-not (Test-Path $aiExe)) { throw "AI 빌드 산출물을 못 찾았습니다: $aiExe" }
Copy-Item $aiExe $binariesDir -Force
Write-Host "AI sidecar 배치 완료: $binariesDir\$aiName.exe"

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
