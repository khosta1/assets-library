@echo off
REM Double-click me, or pass arguments through to shot.py.
setlocal
call "%~dp0_findpython.cmd"
if not defined PY goto done
%PY% "%~dp0shot.py" %*
if errorlevel 1 echo.& echo   shot.py reported a problem - see above.
:done
if "%~1"=="" pause
endlocal
