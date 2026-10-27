# the android lane

android spawns as a redroid container on a tenki sandbox (docker + adb inside the vm; the container route scales easiest and needs no nested virt). exec = `adb -s <serial> shell`, screen streams via ws-scrcpy, recipes key on the android family with `adb install` steps. the android-x86 vm route (pause works, freeze plausible) lands after the container lane is proven.

status: next after the linux lane goes green.
