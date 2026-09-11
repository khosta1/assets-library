@echo off
rem Console launcher, for when something is wrong and you want to watch it.
rem For normal use double-click "Asset Library.vbs" instead - no window at all.
cd /d "%~dp0"
runtime\python.exe -m ui.app
if errorlevel 1 pause
