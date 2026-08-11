# Run one List.am monitoring cycle locally (use with Windows Task Scheduler every 5 min).
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
Remove-Item Env:DRY_RUN -ErrorAction SilentlyContinue
python -m src.main --production
