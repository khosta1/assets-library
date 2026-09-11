@echo off
REM Sets PY to a usable Python, or leaves it undefined and says why.
REM
REM Sourced by every .bat in this folder, so the wrappers themselves stay two
REM lines long and there is exactly one place that knows how Python is found
REM on a given machine.
REM
REM Order matters: the py launcher first, because it is the one thing that is
REM correct on a machine with three Pythons installed.

set PY=

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set PY=py -3
        goto :eof
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set PY=python
        goto :eof
    )
)

REM A project that bundles its own runtime wins over anything on PATH: it is
REM the version the project was actually built against.
if exist "%~dp0..\runtime\python.exe" (
    set PY="%~dp0..\runtime\python.exe"
    goto :eof
)

echo.
echo   No Python found on PATH.
echo   Install it from python.org, or put a runtime\ next to this project.
echo.
