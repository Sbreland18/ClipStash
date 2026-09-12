@echo off
REM ClipStash build launcher for Windows.
REM
REM Double-click this file. It finds a WORKING Python, runs build.py, and keeps
REM the window open afterwards so you can read what happened.
REM
REM Pass arguments through if you want something other than the default:
REM     build.bat --installer
REM     build.bat --clean --onedir --with-ffmpeg --installer

setlocal

cd /d "%~dp0"

echo ============================================
echo   ClipStash build
echo ============================================
echo.

set "PYTHON="
set "PYBROKEN="

REM Avoid referencing %ProgramFiles(x86)% directly inside a for-block: the
REM closing paren in the variable name confuses the batch parser.
set "PF32=%ProgramFiles(x86)%"

REM Each candidate is TESTED by actually running it. A command can exist on
REM PATH and still be unusable: the py launcher keeps a registry entry per
REM installed Python, and if one of those installs was deleted, or lived on a
REM drive that is no longer attached, py resolves to a path that isn't there.
REM Checking only for existence misses that completely.

call :try_cmd "py -3"
if not defined PYTHON where py >nul 2>&1 && set "PYBROKEN=1"
if not defined PYTHON call :try_cmd "python"
if not defined PYTHON call :try_cmd "python3"

REM Fall back to the usual install locations, newest first.
for %%V in (314 313 312 311 310 39) do (
    if not defined PYTHON call :try_path "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    if not defined PYTHON call :try_path "%ProgramFiles%\Python%%V\python.exe"
    if not defined PYTHON call :try_path "%PF32%\Python%%V\python.exe"
    if not defined PYTHON call :try_path "C:\Python%%V\python.exe"
)

if defined PYBROKEN if defined PYTHON (
    echo [note] The 'py' launcher is misconfigured on this computer and was
    echo        skipped. A working Python was found instead, so the build can
    echo        continue. See the end of this window for how to repair it.
    echo.
)

if not defined PYTHON goto nopython

echo Using: %PYTHON%
%PYTHON% --version
echo.

if "%~1"=="" (
    echo No options given - using the recommended first-time build:
    echo     --onedir --extras --with-ffmpeg
    echo.
    echo This installs optional extras and bundles ffmpeg, downloading a
    echo static build if none is on PATH. The download is large ^(~170 MB^).
    echo.
    echo Add --installer to also build the setup file.
    echo.
    %PYTHON% build.py --onedir --extras --with-ffmpeg
) else (
    %PYTHON% build.py %*
)

set EXITCODE=%ERRORLEVEL%
echo.
if "%EXITCODE%"=="0" (
    echo ============================================
    echo   Finished. Your build is in the dist folder.
    echo ============================================
) else (
    echo ============================================
    echo   Build failed - see the messages above.
    echo ============================================
)

if defined PYBROKEN (
    echo.
    echo --------------------------------------------
    echo  Repairing the 'py' launcher ^(optional^)
    echo --------------------------------------------
    echo  'py -3' points at a Python that no longer exists.
    echo  To see what it thinks is installed, run:
    echo.
    echo      py -0p
    echo.
    echo  Entries listing a missing drive or folder are stale. Reinstalling
    echo  Python from python.org, or repairing it from Settings, rewrites
    echo  those entries. The build works fine without doing this.
    echo --------------------------------------------
)

echo.
pause
exit /b %EXITCODE%


:nopython
echo [error] No working Python installation was found.
echo.
if defined PYBROKEN (
    echo   The 'py' launcher exists but points at a Python that is gone -
    echo   most likely installed on a drive that has been removed, or deleted
    echo   without being uninstalled properly.
    echo.
    echo   To see what it thinks is installed, run:   py -0p
    echo.
)
echo   Install Python from https://www.python.org/downloads/
echo.
echo   IMPORTANT, during installation:
echo     - tick "Add python.exe to PATH" on the first screen
echo     - tick "tcl/tk and IDLE" under Optional Features
echo.
echo   ClipStash cannot be built without tcl/tk.
echo.
pause
exit /b 1


REM --- helpers ---------------------------------------------------------------

REM Test a bare command such as "py -3" or "python". Deliberately unquoted so
REM any arguments inside the string are passed through.
:try_cmd
if defined PYTHON goto :eof
%~1 -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>&1
if errorlevel 1 goto :eof
set "PYTHON=%~1"
goto :eof

REM Test a full path to python.exe. Quoted, since Program Files has a space.
:try_path
if defined PYTHON goto :eof
if not exist "%~1" goto :eof
"%~1" -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>&1
if errorlevel 1 goto :eof
set PYTHON="%~1"
goto :eof
