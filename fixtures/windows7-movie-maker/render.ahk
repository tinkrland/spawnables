; drive movie maker's own save dialog. this is the fragile bridge, and the
; fixture says so: gui-automation, determinism interactive.
;
; unverified on purpose: window titles and control positions differ between
; wmm 2.6 and wmm 2012, and the first run in a real guest is what settles it.
Run, %A_ScriptDir%\.build\cut.wlmp
WinWaitActive, Movie Maker,, 90
if ErrorLevel
    ExitApp, 4
WinMenuSelectItem, Movie Maker,, File, Save movie, For computer
WinWaitActive, Save Movie,, 60
if ErrorLevel
    ExitApp, 5
ControlSetText, Edit1, %A_ScriptDir%\cut.mp4
ControlClick, Button1
WinWaitActive, Movie Maker,, 300
ExitApp, 0
