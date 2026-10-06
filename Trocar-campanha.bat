@echo off
rem Troca a campanha ativa por menu. Duplo clique. Detalhes: qualificador\prospeccao_ia\trocar_campanha.py
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0qualificador\prospeccao_ia"
rem python so quando o py nao existe -- com "py ... || python ...", uma escolha recusada
rem (codigo 1) abria o menu de novo.
where py >nul 2>nul
if errorlevel 1 (python trocar_campanha.py) else (py -3 trocar_campanha.py)
echo.
pause
