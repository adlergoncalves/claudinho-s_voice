@echo off
rem Invólucro dos hooks no Windows.
rem Prefere o pythonw do venv do plugin; sem ele, cai no Python do sistema.
rem Falha aqui é silenciosa de propósito: hook que quebra atrapalha a sessão.
setlocal
set "RAIZ=%~dp0.."
if exist "%RAIZ%\.venv\Scripts\python.exe" (
  "%RAIZ%\.venv\Scripts\python.exe" "%~dp0cvoice-hook.py" %*
) else (
  python "%~dp0cvoice-hook.py" %*
)
exit /b 0
