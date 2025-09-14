# Git push script for TradingJournal
# Uses Python 3.13 explicitly

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
    Write-Host "Application startup test failed. Aborting push." -ForegroundColor Red
    exit 1
}

Write-Host "Application startup test passed!" -ForegroundColor Green

# Get current branch
$currentBranch = git branch --show-current

# Push to origin
Write-Host "Pushing to origin/$currentBranch..." -ForegroundColor Yellow
git push origin $currentBranch

if ($LASTEXITCODE -eq 0) {
    Write-Host "Push successful!" -ForegroundColor Green
} else {
    Write-Host "Push failed!" -ForegroundColor Red
    exit 1
}
