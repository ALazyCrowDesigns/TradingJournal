# Trading Journal GUI Launcher (PowerShell)
# This script launches the Trading Journal application using Python 3.13

Write-Host "Starting Trading Journal..." -ForegroundColor Green
Write-Host ""

# Change to the script directory
Set-Location $PSScriptRoot

try {
    # Run the application using Python 3.13
    & py -3.13 app.py
}
catch {
    Write-Host "An error occurred: $_" -ForegroundColor Red
    Write-Host "Press any key to continue..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
