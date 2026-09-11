@echo off
REM Double-click me. With no arguments this rebuilds every context pack into
REM context\, which takes a couple of minutes; with arguments it passes them
REM straight through to pack.py:
REM     pack water            just that pack
REM     pack water render     two of them
REM     pack --list           what each pack contains, and why
REM
REM Needs Node on PATH: the packs are built by repomix, fetched through npx on
REM every run. That fetch is most of the wait, not the packing.
setlocal
call "%~dp0_findpython.cmd"
if not defined PY goto done

where node >nul 2>nul
if errorlevel 1 (
    echo.
    echo   Node.js not found on PATH, and pack.py drives repomix through npx.
    echo   Install it from nodejs.org, then run this again.
    echo.
    goto done
)

%PY% "%~dp0pack.py" %*
if errorlevel 1 echo.& echo   pack.py reported a problem - see above.

:done
REM Only pause when double-clicked, so the token counts stay on screen instead
REM of vanishing with the window.
if "%~1"=="" pause
endlocal
