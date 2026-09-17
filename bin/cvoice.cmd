@echo off
rem Ponto de entrada do cvoice que existe ANTES do ambiente virtual.
rem Com o .venv pronto, so encaminha (e' o dia a dia: ativar e' instantaneo).
rem Sem ele, e' a primeira execucao: acha ou traz um Python, prepara tudo,
rem e so entao encaminha. Nunca deixa a pessoa com um comando que nao existe.
setlocal
set "RAIZ=%~dp0.."
if exist "%RAIZ%\.venv\Scripts\cvoice.exe" goto :roda
rem O Claude Code lanca isto pelo pwsh 7, e o powershell 5.1 herda o PSModulePath
rem dele: a pasta de modulos do 7 vem antes e o autoload carrega um modulo Security
rem incompativel -- qualquer Get-ExecutionPolicy (o instalador do uv usa) morre.
rem Vazio, o 5.1 reconstroi o caminho padrao dele e nunca ve os modulos do 7.
set "PSModulePath="
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0primeira-execucao.ps1" -Raiz "%RAIZ%"
if errorlevel 1 exit /b 1
rem Quem preparou sabe que foi a primeira vez; o cvoice, quando nascer, vai
rem encontrar tudo pronto e nao tem como saber. A variavel morre com o setlocal.
set "CVOICE_RECEM_PREPARADO=1"
if not exist "%RAIZ%\.venv\Scripts\cvoice.exe" (
  echo erro: o preparo terminou mas o cvoice nao apareceu em .venv\Scripts
  exit /b 1
)
:roda
"%RAIZ%\.venv\Scripts\cvoice.exe" %*
exit /b %ERRORLEVEL%
