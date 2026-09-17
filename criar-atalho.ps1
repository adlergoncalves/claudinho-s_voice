# Cria o atalho do painel na área de trabalho e no menu Iniciar.
#
# O atalho aponta para o wscript, não para o pythonw: quando o Windows Terminal
# é o terminal padrão do sistema, ele intercepta qualquer processo de console e
# abre uma aba com uma janela preta — trazendo junto as outras abas do perfil,
# inclusive o Teams. O Windows Script Host não aloca console nenhum, e o
# lancar-painel.vbs chama o pythonw com a janela escondida.

$ErrorActionPreference = 'Stop'

$raiz     = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw  = Join-Path $raiz '.venv\Scripts\pythonw.exe'
$lancador = Join-Path $raiz 'lancar-painel.vbs'
$wscript  = Join-Path $env:SystemRoot 'System32\wscript.exe'

if (-not (Test-Path $pythonw))  { Write-Error "pythonw.exe nao encontrado em $pythonw" }
if (-not (Test-Path $lancador)) { Write-Error "lancar-painel.vbs nao encontrado em $raiz" }

$destinos = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Microsoft\Windows\Start Menu\Programs')
)

$shell = New-Object -ComObject WScript.Shell
foreach ($pasta in $destinos) {
    if (-not (Test-Path $pasta)) { continue }
    $atalho = $shell.CreateShortcut((Join-Path $pasta "Claudinho's Voice.lnk"))
    $atalho.TargetPath       = $wscript
    $atalho.Arguments        = '"' + $lancador + '"'
    $atalho.WorkingDirectory = $raiz
    $atalho.Description      = 'Painel de controle da leitura por voz'
    $icone = Join-Path $raiz 'claudinho.ico'
    $atalho.IconLocation     = $(if (Test-Path $icone) { $icone } else { "$pythonw,0" })
    $atalho.Save()
    Write-Host "atalho criado em $pasta"
}
