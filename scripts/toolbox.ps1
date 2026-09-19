$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')

function Wait-Cn { [void](Read-Host '按回车键返回工具栏') }
function Get-Python { Join-Path (Get-Location) '.venv\Scripts\python.exe' }
function Require-Python {
    $python = Get-Python
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host '未找到虚拟环境，请先选择“安装/更新运行环境”。' -ForegroundColor Yellow
        Wait-Cn
        return $null
    }
    return $python
}
function Run-Python([string]$Script, [string[]]$Arguments) {
    $python = Require-Python
    if ($null -ne $python) { & $python $Script @Arguments; Wait-Cn }
}
function Manage-Anchors {
    $python = Require-Python
    if ($null -eq $python) { return }
    $config = & $python -c "import json; print(json.dumps(json.load(open('config/anchors.json', encoding='utf-8-sig')).get('anchors', []), ensure_ascii=False))" | ConvertFrom-Json
    Write-Host "当前主播：$(@($config).Count) 个"
    if ($config) { @($config) | ForEach-Object { Write-Host "- $($_.id) | $($_.name) | $($_.platform)" } }
    Write-Host 'a. 添加抖音主播（只需 UID）'
    Write-Host 'b. 添加 B 站主播（mid + room_id）'
    Write-Host 'd. 删除主播   q. 返回'
    $action = Read-Host '请选择操作'
    if ($action -eq 'a') {
        $uid = Read-Host '请输入抖音主播 UID'
        if ([string]::IsNullOrWhiteSpace($uid)) { Write-Host 'UID 不能为空。' -ForegroundColor Yellow; Wait-Cn; return }
        $extra = @('--uid', $uid)
        & $python 'scripts\manage_anchors.py' add @extra; Wait-Cn
    } elseif ($action -eq 'b') {
        $mid = Read-Host '请输入 B 站用户 mid'
        $room = Read-Host '请输入 B 站直播间 room_id'
        $name = Read-Host '请输入主播名称'
        if ([string]::IsNullOrWhiteSpace($mid) -or [string]::IsNullOrWhiteSpace($room)) { Write-Host 'mid 和 room_id 不能为空。' -ForegroundColor Yellow; Wait-Cn; return }
        if ([string]::IsNullOrWhiteSpace($name)) { $name = "B站主播 $mid" }
        & $python 'scripts\manage_anchors.py' add-bilibili --mid $mid --room-id $room --name $name; Wait-Cn
    } elseif ($action -eq 'd') {
        $id = Read-Host '请输入要删除的主播 ID'
        & $python 'scripts\manage_anchors.py' delete '--id' $id
        Wait-Cn
    }
}
function Show-Menu {
    Clear-Host
    Write-Host '========================================'
    Write-Host '        直播监控工具栏'
    Write-Host '========================================'
    Write-Host '  1. 安装/更新运行环境'
    Write-Host '  2. 安装 CUDA 加速组件'
    Write-Host '  3. 登录抖音（扫码）'
    Write-Host '  4. 打开状态窗口'
    Write-Host '  5. 检查配置和运行环境'
    Write-Host '  6. 运行离线模拟'
    Write-Host '  7. 运行日终摘要模拟'
    Write-Host '  8. 查看最近日志'
    Write-Host '  9. 管理主播（添加/删除）'
    Write-Host '  0. 退出'
    Write-Host '========================================'
}

while ($true) {
    Show-Menu
    $choice = Read-Host '请选择 [0-9]'
    if ([string]::IsNullOrWhiteSpace($choice)) { break }
    switch ($choice) {
        '1' {
            $python = Get-Python
            if (-not (Test-Path -LiteralPath $python)) {
                py -3.12 -m venv .venv 2>$null
                if (-not (Test-Path -LiteralPath $python)) { py -3.11 -m venv .venv 2>$null }
            }
            if (Test-Path -LiteralPath $python) {
                try {
                    & $python -m pip install --upgrade pip
                    if ($LASTEXITCODE -ne 0) { throw 'pip 升级失败' }
                    & $python -m pip install -r requirements.txt
                    if ($LASTEXITCODE -ne 0) { throw '项目依赖安装失败' }
                    & $python -m playwright install chromium
                    if ($LASTEXITCODE -ne 0) { throw 'Playwright 浏览器安装失败' }
                    Write-Host '运行环境安装完成。' -ForegroundColor Green
                } catch {
                    Write-Host "安装未完成：$($_.Exception.Message)" -ForegroundColor Red
                }
            } else { Write-Host '未找到 Python 3.11 或 3.12。' -ForegroundColor Red }
            Wait-Cn
        }
        '2' { $python = Require-Python; if ($null -ne $python) { & $python -m pip install --upgrade 'nvidia-cublas-cu12>=12' 'nvidia-cudnn-cu12>=9'; Wait-Cn } }
        '3' { Run-Python 'scripts\douyin_login.py' @() }
        '4' { $python = Require-Python; if ($null -ne $python) { $pythonw = Join-Path (Get-Location) '.venv\Scripts\pythonw.exe'; if (Test-Path $pythonw) { Start-Process $pythonw -ArgumentList 'scripts\status_window.py' } else { Start-Process $python -ArgumentList 'scripts\status_window.py' } } }
        '5' { Run-Python 'scripts\check_config.py' @() }
        '6' { Run-Python 'scripts\simulate.py' @() }
        '7' { Run-Python 'scripts\daily_summary.py' @('--dry-run','--simulate','--no-push') }
        '8' { if (Test-Path -LiteralPath 'logs') { Get-ChildItem logs -File -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 | Format-Table LastWriteTime,FullName -AutoSize } else { Write-Host '日志目录不存在。' }; Wait-Cn }
        '9' { Manage-Anchors }
        '0' { break }
        default { Write-Host '无效选择，请输入 0 到 9。' -ForegroundColor Yellow; Start-Sleep -Milliseconds 700 }
    }
}
