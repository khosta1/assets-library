@echo off
REM Double-click me, or pass arguments through to budget.py.
setlocal
call "%~dp0_findpython.cmd"
if not defined PY goto done
%PY% "%~dp0budget.py" %*
if errorlevel 1 echo.& echo   budget.py reported a problem - see above.
:done
if "%~1"=="" pause
endlocal
