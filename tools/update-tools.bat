@echo off
REM Re-copy the tools from the baseline, deliberately.
REM
REM These scripts are COPIED into each project rather than shared, so a clone
REM of this project is complete on its own and can be edited for this project.
REM The price of that is drift: a fix made in the baseline never arrives here.
REM This is how it arrives - when you ask, never behind your back.
REM
REM It shows what would change first, and copies only after you say yes. Files
REM you have edited locally show up in that list, so local changes are visible
REM before they are lost, not after.
REM
REM Baseline location: %AI_BASE_WORKFLOW%, or the default below.

setlocal
set BASE=%AI_BASE_WORKFLOW%
if "%BASE%"=="" set BASE=H:\Code\AI_base_workflow

set SRC=%BASE%\template\tools
if not exist "%SRC%" (
    echo.
    echo   Baseline not found at %SRC%
    echo   Set AI_BASE_WORKFLOW to where AI_base_workflow lives, or skip this
    echo   - the tools work fine without it, they just stop receiving updates.
    echo.
    goto done
)

echo Comparing %SRC%
echo      with %~dp0
echo.
robocopy "%SRC%" "%~dp0." *.py *.bat *.cmd _version.txt /L /NJH /NJS /NDL /NP /XX
echo.
echo The files above would be OVERWRITTEN. Anything you changed locally is
echo among them.
echo.

choice /C YN /M "Copy them"
if errorlevel 2 goto done

robocopy "%SRC%" "%~dp0." *.py *.bat *.cmd _version.txt /NJH /NJS /NDL /NP /XX
echo.
echo Done. Check _version.txt.

:done
pause
endlocal
