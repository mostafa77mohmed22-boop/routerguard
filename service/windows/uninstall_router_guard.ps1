<#
.SYNOPSIS
    إلغاء تثبيت خدمة RouterGuard الخلفية من Windows.
.DESCRIPTION
    يحذف المهمة المجدولة باسم "RouterGuard" إن وُجدت.
    لا يحذف ملفات المشروع — فقط المهمة المجدولة.
.NOTES
    شغّل هذا السكربت كمسؤول (Run as Administrator).
#>

$ErrorActionPreference = "Stop"
$TaskName = "RouterGuard"

# البحث عن المهمة وحذفها إن وُجدت
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "🗑️  حذف المهمة '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "✅ تم إلغاء تثبيت RouterGuard بنجاح."
}
else {
    Write-Host "ℹ️  لا توجد مهمة باسم '$TaskName' — لا شيء لحذفه."
}
