<#
.SYNOPSIS
    تثبيت RouterGuard كخدمة خلفية على Windows عبر Scheduled Task.
.DESCRIPTION
    - يتحقق من وجود main.py في مسار المشروع.
    - يحذف مهمة "RouterGuard" القديمة إن وُجدت.
    - ينشئ مهمة مجدولة جديدة تعمل عند تسجيل الدخول (AtLogOn)
      بأعلى صلاحيات، وتُعاد المحاولة تلقائياً عند الفشل.
.NOTES
    شغّل هذا السكربت كمسؤول (Run as Administrator).
#>

param(
    # مسار مجلد مشروع RouterGuard (الذي يحتوي main.py)
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,

    # مفسر بايثون المستخدم للتشغيل الخلفي (بدون نافذة)
    [Parameter(Mandatory = $false)]
    [string]$PythonExe = "pythonw.exe"
)

$ErrorActionPreference = "Stop"
$TaskName = "RouterGuard"

# 1) التحقق من مسار المشروع ووجود main.py
if (-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) {
    Write-Error "❌ مسار المشروع غير موجود: $ProjectPath"
    exit 1
}
$MainPy = Join-Path $ProjectPath "main.py"
if (-not (Test-Path -LiteralPath $MainPy -PathType Leaf)) {
    Write-Error "❌ لم يتم العثور على main.py في: $ProjectPath"
    exit 1
}

# 2) حذف المهمة القديمة إن وُجدت
$oldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($oldTask) {
    Write-Host "🗑️  حذف المهمة القديمة '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 3) بناء إجراء التشغيل: pythonw.exe "مسار المشروع\main.py" run
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$MainPy`" run" `
    -WorkingDirectory $ProjectPath

# 4) المشغّل: عند تسجيل الدخول (أي مستخدم)
$trigger = New-ScheduledTaskTrigger -AtLogOn

# 5) الإعدادات: أعلى صلاحيات + العمل سواء كان المستخدم مسجلاً أم لا + إعادة المحاولة عند الفشل
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# 6) تسجيل المهمة
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "RouterGuard: مراقبة الراوتر والأجهزة المتصلة في الخلفية" | Out-Null

Write-Host ""
Write-Host "✅ تم تثبيت RouterGuard بنجاح!"
Write-Host "   المهمة: $TaskName"
Write-Host "   المشغّل: عند تسجيل الدخول (AtLogOn)"
Write-Host "   الأمر: $PythonExe `"$MainPy`" run"
Write-Host "   ستبدأ الخدمة تلقائياً عند تسجيل الدخول القادم."
Write-Host "   لبدئها الآن: Start-ScheduledTask -TaskName $TaskName"
