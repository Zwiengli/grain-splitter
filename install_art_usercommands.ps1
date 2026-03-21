$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$MainScript = Join-Path $ProjectRoot "main.py"
$InstallerScript = Join-Path $ProjectRoot "integrations\art\installer.py"
$VenvPythonW = Join-Path $ProjectRoot "venv\Scripts\pythonw.exe"
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"

if (Test-Path $VenvPythonW) {
    $TargetPython = $VenvPythonW
} elseif (Test-Path $VenvPython) {
    $TargetPython = $VenvPython
} else {
    $TargetPythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($null -eq $TargetPythonCommand) {
        $TargetPythonCommand = Get-Command python.exe -ErrorAction Stop
    }
    $TargetPython = $TargetPythonCommand.Source
}

if (Test-Path $VenvPython) {
    $RunnerPython = $VenvPython
} else {
    $RunnerPythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $RunnerPythonCommand) {
        $RunnerPython = $RunnerPythonCommand.Source
    } else {
        $RunnerPython = $TargetPython
    }
}

& $RunnerPython $InstallerScript `
    --project-root $ProjectRoot `
    --target-python $TargetPython `
    --target-script $MainScript `
    @args
