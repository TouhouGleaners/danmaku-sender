; 接收来自 GitHub Actions 传递的动态版本号
#ifndef AppVersion
#define AppVersion "Unknown"
#endif

#define AppName "BiliDanmakuSender"
#define AppExeName "BiliDanmakuSender.exe"
#define AppPublisher "Miku_oso"
#define AppPublisherURL "https://github.com/Mikuoso"
#define AppSupportURL "https://touhougleaners.github.io/danmaku-sender/"
#define AppUpdatesURL "https://github.com/TouhouGleaners/danmaku-sender/releases"

[Setup]
AppId={{CD28BCC5-45C6-4824-8579-75A641BFABE3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppPublisherURL}
AppSupportURL={#AppSupportURL}
AppUpdatesURL={#AppUpdatesURL}

; AppData\Local\Programs\Miku_oso\BiliDanmakuSender
DefaultDirName={autopf}\Miku_oso\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

; 输出设置: 打包后的文件放在 dist 文件夹下
OutputDir=dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup-x64
SetupIconFile=assets\icon.ico

; 使用最高压缩率
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

; 安装语言设置
[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 指向 GitHub Actions 重命名后的 AppDist 目录
Source: "dist\AppDist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后允许用户勾选“立即运行”
Filename: "{app}\{#AppExeName}"; Description: "运行 {#AppName}"; Flags: nowait postinstall skipifsilent