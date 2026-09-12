; ClipStash installer
;
; Build with Inno Setup 6 (free, https://jrsoftware.org/isdl.php):
;
;     python build.py --onedir --with-ffmpeg --installer
;
; or by hand, after a PyInstaller build has populated dist\ClipStash\ :
;
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; Output lands in installer_output\ClipStash-Setup-<version>.exe

#define AppName        "ClipStash"
#ifndef AppVersion
  #define AppVersion   "1.0.0"
#endif
#define AppPublisher   "ClipStash"
#define AppExeName     "ClipStash.exe"

; Where PyInstaller put the build. A folder build (--onedir) is expected here;
; see the Files section for the single-file alternative.
#define DistDir        "dist\ClipStash"

[Setup]
; A stable, unique GUID. Windows uses this to recognise upgrades and to find
; the app for uninstall, so it must NOT change between releases.
AppId={{8C3F1A67-2D94-4E5B-9A71-63C0F2E4B8D5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=installer_output
OutputBaseFilename=ClipStash-Setup-{#AppVersion}
; Artwork is optional. A missing BMP used to abort the whole compile, which is
; a poor trade for a decorative banner - so each file is probed first and the
; directive is only emitted when it's actually there. Generate them with:
;     python assets\make_icons.py
#define AssetDir AddBackslash(SourcePath) + "assets\"
#if FileExists(AssetDir + "icon.ico")
  #define HaveIcon
#endif
#if FileExists(AssetDir + "wizard-large.bmp") && FileExists(AssetDir + "wizard-small.bmp")
  #define HaveWizardArt
#endif

#ifdef HaveIcon
SetupIconFile=assets\icon.ico
#endif

#ifdef HaveWizardArt
; Inno requires BMP, not PNG, and picks the closest size for the user's display
; scaling - hence several of each.
WizardImageFile=assets\wizard-large.bmp,assets\wizard-large-192x386.bmp,assets\wizard-large-246x459.bmp,assets\wizard-large-328x628.bmp,assets\wizard-large-410x797.bmp
WizardSmallImageFile=assets\wizard-small.bmp,assets\wizard-small-83.bmp,assets\wizard-small-110.bmp,assets\wizard-small-138.bmp
#else
#pragma message "assets\wizard-*.bmp not found - building with Inno's default artwork"
#endif

; Compression level is a real time/size trade here, because bundling ffmpeg
; means feeding roughly 250 MB of binaries through the compressor, and Inno
; prints nothing while a single large file is being processed.
;   lzma2/max     smallest, but can take 10+ minutes on this much data
;   lzma2/normal  a few percent larger, several times faster  <- chosen
;   lzma2/fast    faster again, noticeably larger
;   none          instant, installer roughly the size of dist\
; If you build without ffmpeg, lzma2/max costs almost nothing - switch back.
Compression=lzma2/normal

; ffmpeg.exe and ffprobe.exe share most of their code, so compressing them as
; one stream saves a great deal more than it costs.
SolidCompression=yes

; Lets the compressor run outside the 32-bit compiler process, so it can use
; more memory than ISCC could address on its own.
LZMAUseSeparateProcess=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

; Default to a per-user install so it works without admin rights, which matters
; on managed work and school machines. The user can still choose a machine-wide
; install, which triggers a UAC prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Lets Setup detect a running ClipStash. The app creates this same named mutex
; at startup, so an update launched from inside the app can wait for it to exit
; rather than failing on locked files.
AppMutex=ClipStashRunningMutex
CloseApplications=yes
RestartApplications=yes

; Refuse to downgrade over a newer install.
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; --- Folder build (--onedir), the default. The wildcard picks up ClipStash.exe
;     along with the _internal tree, so it must not be listed separately.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- Single-file build (--onefile) alternative. Comment out the line above and
;     uncomment this one if you built with --onefile.
; Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller's onefile bootloader and the updater both write outside {app}.
; Without this, uninstalling leaves the downloaded yt-dlp behind.
Type: filesandordirs; Name: "{localappdata}\{#AppName}"

[Code]

{ Inno's TColor is BGR rather than RGB, in the form $00BBGGRR. The navy
  written #1B2436 in CSS must therefore appear here as $0036241B. Each constant
  notes its original RGB value alongside.

  Careful when editing these comments: ISPP is a text preprocessor that runs
  before any Pascal parsing, and it treats a line whose first non-blank
  character is a hash as a directive, even inside braces. Never let a colour
  code begin a line. }
const
  clBrandNavy  = $0036241B;  { #1B2436 - icon background }
  clBrandLight = $00F6EEE8;  { #E8EEF6 - primary text }
  clBrandMuted = $00BEA493;  { #93A4BE - secondary text }
  clBrandSand  = $0084B5E0;  { #E0B584 - the sack }
  clBrandRed   = $003C45D9;  { #D9453C - the beanie }

{ Only the header band and the welcome/finish headings are recoloured.
  Deliberately conservative: the body pages carry native edit boxes, list boxes
  and buttons that Windows draws itself and that ignore these settings, so
  darkening those pages would leave black text on a dark background. The header
  is safe because it contains nothing but two labels and our small bitmap,
  which already has a matching navy background and so blends into it. }
procedure InitializeWizard();
begin
  WizardForm.MainPanel.Color := clBrandNavy;

  WizardForm.PageNameLabel.Color := clBrandNavy;
  WizardForm.PageNameLabel.Font.Color := clBrandLight;
  WizardForm.PageNameLabel.Font.Style := [fsBold];

  WizardForm.PageDescriptionLabel.Color := clBrandNavy;
  WizardForm.PageDescriptionLabel.Font.Color := clBrandMuted;

  { The thin divider under the header, tinted to match rather than left grey. }
  WizardForm.Bevel1.Visible := False;

  { Welcome and Finish pages sit beside the tall banner and stay light, so the
    headings take the dark navy for contrast instead. }
  WizardForm.WelcomeLabel1.Font.Color := clBrandNavy;
  WizardForm.WelcomeLabel1.Font.Style := [fsBold];

  WizardForm.FinishedHeadingLabel.Font.Color := clBrandNavy;
  WizardForm.FinishedHeadingLabel.Font.Style := [fsBold];
end;

{ Refuse to install over a newer version - otherwise a stale installer silently
  downgrades the app and the user loses updates with no warning. }
function GetInstalledVersion(var Version: String): Boolean;
var
  Key: String;
begin
  { The literal AppId GUID. Kept in sync with [Setup] above by hand - using
    SetupSetting here is unreliable because AppId's leading brace is escaped. }
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
         '{8C3F1A67-2D94-4E5B-9A71-63C0F2E4B8D5}_is1';
  Result := RegQueryStringValue(HKCU, Key, 'DisplayVersion', Version) or
            RegQueryStringValue(HKLM, Key, 'DisplayVersion', Version);
end;

function InitializeSetup(): Boolean;
var
  Installed: String;
begin
  Result := True;
  if GetInstalledVersion(Installed) then
  begin
    if CompareStr(Installed, '{#AppVersion}') > 0 then
    begin
      if MsgBox('A newer version of {#AppName} (' + Installed + ') is already installed.'
                + #13#10#13#10 + 'Install the older version {#AppVersion} anyway?',
                mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

{ Offer to keep the downloaded yt-dlp, so reinstalling doesn't force a re-download. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\{#AppName}');
    if DirExists(DataDir) then
    begin
      if MsgBox('Remove downloaded yt-dlp updates and settings as well?'
                + #13#10#13#10 + 'Choose No to keep them for a future reinstall.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
