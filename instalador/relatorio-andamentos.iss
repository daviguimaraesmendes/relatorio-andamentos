; Instalador do Relatório de Andamentos (Windows). Gerado com o Inno Setup 6:
;   iscc /DAppVersion=1.0.0 instalador\relatorio-andamentos.iss
; Antes, rode instalador\montar.ps1 (cria build\app com o Python embutido).
; Instala só para o usuário atual (sem pedir administrador). Dados de clientes
; (pasta projetos) e config.json nunca são tocados pelo instalador nem pelo desinstalador.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Relatório de Andamentos"

[Setup]
AppId={{6E5B6C0A-3F7D-4B8E-9A52-C1D4F0A7B913}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Relatório de Andamentos
DefaultDirName={localappdata}\Programs\RelatorioAndamentos
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Instalar-Relatorio-de-Andamentos-{#AppVersion}
SetupIconFile=..\assets\icone.ico
UninstallDisplayIcon={app}\assets\icone.ico
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalhodesktop"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\build\app\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "config.json,projetos\*"
Source: "..\assets\icone.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

[Dirs]
Name: "{app}\projetos"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\python.exe"; Parameters: """{app}\src\abrir_painel.py"""; WorkingDir: "{app}\src"; IconFilename: "{app}\assets\icone.ico"; Comment: "Abre o painel no navegador (mantenha esta janela aberta)"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\python\python.exe"; Parameters: """{app}\src\abrir_painel.py"""; WorkingDir: "{app}\src"; IconFilename: "{app}\assets\icone.ico"; Tasks: atalhodesktop

[Run]
; Navegador de automação (Chromium do Playwright, ~150 MB): baixado agora porque o instalador não o embute.
Filename: "{app}\python\python.exe"; Parameters: "-m playwright install chromium"; WorkingDir: "{app}"; StatusMsg: "Baixando o navegador de automação (cerca de 150 MB)..."; Flags: waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: """{app}\src\abrir_painel.py"""; WorkingDir: "{app}\src"; Description: "Abrir o {#AppName} agora"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; só o que o instalador e o pip criaram; projetos\ e config.json (dados do escritório) ficam
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\assets"
