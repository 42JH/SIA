; sia-desktop.iss — SIA Desktop 설치 프로그램 (Inno Setup)
;
; NSIS(makensis)·WiX(light.exe)는 둘 다 32비트 컴파일러라 sia-ai-support
; (CUDA torch 포함, 수 GB급 payload)를 통째로 mmap 하려다 주소공간을 넘겨서
; 실패한다. GPU torch를 유지해야 하는 이 프로젝트는 용량을 줄이는 대신
; Inno Setup(스트리밍 압축, 이런 mmap 한계가 보고되지 않음)으로 최종 설치본을
; 만든다.
;
; 빌드 전제 (build-sidecars.ps1 [1/5]~[4/5]가 먼저 끝나 있어야 함):
;   - src-tauri\target\release\app.exe                       (Rust+임베디드 프런트엔드)
;   - src-tauri\binaries\sia-backend-x86_64-pc-windows-msvc.exe
;   - src-tauri\binaries\sia-ai-x86_64-pc-windows-msvc.exe
;   - src-tauri\binaries\app\        (BE jpackage app-image)
;   - src-tauri\binaries\runtime\    (BE 전용 JRE)
;   - src-tauri\binaries\sia-ai-support\ (AI PyInstaller onedir 지원 폴더)
;
; 컴파일: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" sia-desktop.iss
; (build-sidecars.ps1 [5/5]가 자동으로 호출한다 — 보통 직접 실행할 필요 없음)

#define MyAppName "SIA Desktop"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "SIA"
#define MyAppExeName "app.exe"
#define SrcTauri "..\src-tauri"

[Setup]
; Tools > Generate GUID 로 새로 만든 고유 GUID로 교체 권장 (설치본 업그레이드 인식용)
AppId={{9F1B0B9E-2B7E-4B7C-9B8B-5C6B0A1B2C3D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Program Files(관리자 설치 경로)에 깔면 이 PC의 백신/EDR 정책 때문에
; jpackage 런처가 JVM(jvm.dll)을 못 띄운다 ("Failed to launch JVM") — 실행 파일
; 자체는 멀쩡하고, C:\temp 등 다른 경로에서는 정상 기동되는 걸로 확인됨(2026-09-22).
; 그래서 관리자 권한이 필요 없는 사용자 폴더에 설치한다 — 이러면 BE가 상대경로로
; 만드는 sia.db(application.yml 참고, data-dir과 안 묶여 있음)도 쓰기 권한 문제 없이
; 같이 해결된다.
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=sia-desktop-{#MyAppVersion}-setup
SetupIconFile={#SrcTauri}\icons\icon.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
WizardStyle=modern
DisableWelcomePage=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

; --- 실제 파일들 ---
; app.exe(Rust 셸 + 임베디드 프런트엔드)와 두 사이드카 exe는 설치 루트({app})에,
; app\·runtime\·sia-ai-support\는 tauri.conf.json의 기존 bundle.resources 매핑과
; 동일하게 설치 루트 밑 같은 이름 폴더로 들어간다 — 런타임에서 실행 파일 옆(resource_dir)
; 을 찾는 로직과 100% 동일한 상대 경로 구조라 코드 수정이 필요 없다.
[Files]
Source: "{#SrcTauri}\target\release\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcTauri}\binaries\sia-backend-x86_64-pc-windows-msvc.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcTauri}\binaries\sia-ai-x86_64-pc-windows-msvc.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcTauri}\binaries\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcTauri}\binaries\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcTauri}\binaries\sia-ai-support\*"; DestDir: "{app}\sia-ai-support"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
