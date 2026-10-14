@echo off
REM Build the distributable archive: the app plus its bundled runtime, ready
REM for a reader to unzip and run. Roughly 300 MB in, rather less out.
REM
REM     release --dry-run     what would be packed, and what it costs
REM     release               write dist\AssetLibrary-<sha>.zip
REM
REM What travels is decided by assetlib\deploy.py, the same rules as
REM "Create a new library..." - not by a second list in here. Attach the result
REM to a GitHub release: runtime\ is gitignored, so a clone alone can never
REM give anybody something that runs.
setlocal
call "%~dp0_findpython.cmd"
if not defined PY goto done

%PY% "%~dp0release.py" %*
if errorlevel 1 echo.& echo   release.py reported a problem - see above.

:done
REM Only pause when double-clicked, so the file list stays on screen.
if "%~1"=="" pause
endlocal
