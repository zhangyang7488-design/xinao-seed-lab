#Requires AutoHotkey v2.0
#SingleInstance Force
#Warn All, StdOut

SetTitleMatchMode 1
SendMode "Input"
CoordMode "Mouse", "Client"

receiptPath := "D:\XINAO_RESEARCH_RUNTIME\state\pi\0.84.1\profiles\prime-s\input\numpad-enter-follow-last.tsv"
ownerPid := 0

for index, value in A_Args {
    if (value = "--owner-pid" && index < A_Args.Length)
        ownerPid := Integer(A_Args[index + 1])
}

if (A_Args.Length >= 1 && A_Args[1] = "--self-test") {
    if !InStr(receiptPath, "profiles\prime-s\input")
        ExitApp 2
    if (ClassifyPointerRoute(100, 1000) != "follow")
        ExitApp 3
    if (ClassifyPointerRoute(900, 1000) != "submit")
        ExitApp 4
    ExitApp 0
}

if (ownerPid > 0)
    SetTimer CheckOwner, 2000

CheckOwner() {
    global ownerPid
    if (ownerPid > 0 && !ProcessExist(ownerPid))
        ExitApp 0
}

GetInputZoneHeight(clientHeight) {
    ; Pi fullscreen docks the editor at the bottom. Keep the proven PrimeB
    ; pointer classifier proportional while bounding it to normal editor sizes.
    return Min(220, Max(110, Round(clientHeight * 0.16)))
}

ClassifyPointerRoute(mouseY, clientHeight) {
    return mouseY >= clientHeight - GetInputZoneHeight(clientHeight) ? "submit" : "follow"
}

GetPointerContext() {
    MouseGetPos &mouseX, &mouseY, &windowId
    WinGetClientPos &clientX, &clientY, &clientWidth, &clientHeight, "ahk_id " windowId
    return {
        mouseX: mouseX,
        mouseY: mouseY,
        clientWidth: clientWidth,
        clientHeight: clientHeight,
        inputZoneHeight: GetInputZoneHeight(clientHeight),
        route: ClassifyPointerRoute(mouseY, clientHeight)
    }
}

WriteTriggerReceipt(context) {
    global receiptPath
    SplitPath receiptPath, , &receiptDir
    if !DirExist(receiptDir)
        DirCreate receiptDir
    title := StrReplace(WinGetTitle("A"), "`t", " ")
    title := StrReplace(title, "`n", " ")
    pid := WinGetPID("A")
    action := context.route = "submit" ? "main-enter-submit" : "F12-alt-screen-bottom-follow"
    line := FormatTime(, "yyyy-MM-ddTHH:mm:ss") "`t" pid "`t" title "`tNumpadEnter`t" action "`t" context.route "`tmouse=" context.mouseX "," context.mouseY "`tclient=" context.clientWidth "x" context.clientHeight "`tinput-zone=" context.inputZoneHeight "`n"
    tempPath := receiptPath ".tmp"
    try FileDelete tempPath
    FileAppend line, tempPath, "UTF-8"
    FileMove tempPath, receiptPath, 1
}

; The Windows Terminal profile has a fixed tabTitle of "prime S". The helper
; never observes or remaps keys in another terminal window or application.
#HotIf WinActive("prime S ahk_exe WindowsTerminal.exe")
$NumpadEnter::{
    try context := GetPointerContext()
    catch {
        ; If geometry cannot be read, preserve the key's ordinary submit effect.
        Send "{Enter}"
        return
    }
    try WriteTriggerReceipt(context)
    if (context.route = "submit")
        Send "{Enter}"
    else
        Send "{F12}"
}
#HotIf
