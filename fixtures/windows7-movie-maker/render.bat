@echo off
REM the pilot entry point. builds the project, then hands the fragile part to
REM autohotkey. every failure exits with its own code so the fixture can tell
REM "movie maker refused the project" from "the save dialog never appeared".
python build_project.py || exit /b 2
if not exist "%ProgramFiles%\AutoHotkey\AutoHotkeyU32.exe" (
  echo autohotkey missing: the guest image recipe must install it 1>&2
  exit /b 3
)
"%ProgramFiles%\AutoHotkey\AutoHotkeyU32.exe" render.ahk || exit /b 4
if not exist cut.mp4 (
  echo no cut.mp4: the render never finished 1>&2
  exit /b 6
)
exit /b 0
