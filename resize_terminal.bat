@echo off
REM Resize terminal to a larger size (columns x lines)
REM Usage: resize_terminal.bat [columns] [lines]

set COLS=%1
set LINES=%2

if "%COLS%"=="" set COLS=200
if "%LINES%"=="" set LINES=60

echo Resizing terminal to %COLS%x%LINES%...

REM Windows Terminal / Command Prompt resize
mode con cols=%COLS% lines=%LINES%

echo Current terminal size: %COLS% columns x %LINES% lines
