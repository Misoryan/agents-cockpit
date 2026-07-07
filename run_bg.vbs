' run_bg.vbs - Agents Cockpit background launcher (ASCII only).
' Launches supervisor.py HIDDEN and DETACHED, then exits without waiting.
' Invoked by start.cmd via:  wscript run_bg.vbs
'   Run(cmd, 0, False):  0 = SW_HIDE (no window), False = do not block.
' The supervisor becomes an independent process with no console, so it survives
' the start.cmd window closing. wscript returns at once.
Set sh = CreateObject("WScript.Shell")
here = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
sh.Run "python """ & here & "\supervisor.py""", 0, False
