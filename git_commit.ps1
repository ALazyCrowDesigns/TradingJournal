# Git commit script for TradingJournal
# Uses Python 3.13 explicitly

param(
    [Parameter(Mandatory=$true)]
    [string]$Message
)

Write-Host "Testing application startup with Python 3.13..." -ForegroundColor Yellow

# Test that the application can start without errors
py -3.13 -c "
try:
    from src.journal.dto import SymbolIn, TradeIn, DailyPriceIn, ProfileIn
    from src.journal.container import container
    print('All imports successful')
except Exception as e:
    print('Import failed:', str(e))
    exit(1)
"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Application startup test failed. Aborting commit." -ForegroundColor Red
    exit 1
}

Write-Host "Application startup test passed!" -ForegroundColor Green

# Add all changes
Write-Host "Adding changes to git..." -ForegroundColor Yellow
git add .

# Commit with the provided message
Write-Host "Committing with message: $Message" -ForegroundColor Yellow
git commit -m "$Message"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Commit successful!" -ForegroundColor Green
    Write-Host "To push to remote, run: git push origin $(git branch --show-current)" -ForegroundColor Cyan
} else {
    Write-Host "Commit failed!" -ForegroundColor Red
    exit 1
}
