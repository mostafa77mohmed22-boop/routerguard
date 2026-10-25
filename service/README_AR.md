# تشغيل RouterGuard في الخلفية — دليل خطوة بخطوة 🔥

## 1️⃣ التثبيت على Windows

1. افتح **PowerShell كمسؤول** (زر يمين على PowerShell ← تشغيل كمسؤول).
2. انتقل لمجلد المشروع ثم نفّذ سكربت التثبيت:
   ```powershell
   cd "C:\path\to\router-guard"
   .\service\windows\install_router_guard.ps1 -ProjectPath "C:\path\to\router-guard"
   ```
   - إن ظهر تحذير سياسة التنفيذ (ExecutionPolicy)، نفّذ أولاً:
     ```powershell
     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
     ```
3. ستظهر رسالة `✅ تم تثبيت RouterGuard بنجاح!`

### بدء الخدمة فوراً (اختياري)
```powershell
Start-ScheduledTask -TaskName RouterGuard
```

### التحقق أن الخدمة تعمل
```powershell
Get-ScheduledTask -TaskName RouterGuard | Select-Object TaskName, State
schtasks /query /tn RouterGuard /v /fo list | findstr "Last Result"
```
- `State` يجب أن تكون `Ready` أو `Running`.
- `Last Result` بقيمة `0` تعني أن آخر تشغيل نجح.
- للوحة التحكم: نقرة مزدوجة على `service\windows\start_dashboard.bat` ثم افتح المتصفح على العنوان الذي يطبعه `main.py`.

## 2️⃣ إلغاء التثبيت (Windows)

من PowerShell كمسؤول:
```powershell
.\service\windows\uninstall_router_guard.ps1
```
يحذف المهمة المجدولة فقط — ملفات المشروع تبقى كما هي.

## 3️⃣ التثبيت على Linux (systemd)

```bash
# 1) انسخ المشروع (مثال) ثم ملف الخدمة
sudo mkdir -p /opt/router-guard
sudo cp -r /path/to/router-guard/* /opt/router-guard/

# 2) انسخ ملف الخدمة وحدّث المسارات داخله إن غيّرت /opt/router-guard
sudo cp /opt/router-guard/service/linux/routerguard.service /etc/systemd/system/

# 3) فعّل وشغّل
sudo systemctl daemon-reload
sudo systemctl enable --now routerguard
```

### التحقق أن الخدمة تعمل
```bash
sudo systemctl status routerguard
sudo systemctl is-active routerguard      # يجب أن تطبع: active
sudo journalctl -u routerguard -f         # متابعة السجلات لحظياً
```

## 4️⃣ استكشاف سريع

| المشكلة | الحل |
|---|---|
| المهمة لا تبدأ على Windows | تأكد أن التشغيل كان كمسؤول، وأن `pythonw.exe` في PATH |
| الخدمة تتوقف فوراً على Linux | راجع `journalctl -u routerguard` — غالباً مسار خاطئ في `ExecStart` |
| لوحة التحكم لا تفتح | تأكد أن أمر `main.py dashboard` يعمل يدوياً أولاً |
