<div dir="rtl">

# API مانیکس — نسخهٔ 1.1.0

API متعلق به **همان یک سرور/مالک** است. مسیرها relative به دامنهٔ HTTPS پنل‌اند. Swagger عمومی در برنامه فعال نیست؛ این فایل مرجع خواندنی است. Source of truth: `panel/main.py`، `panel/extras.py` و `panel/security.py`.

## احراز هویت

### نشست مرورگر

`POST /api/login` با JSON:

```json
{"username":"admin","password":"YOUR_PRIVATE_PASSWORD","otp":""}
```

اگر TOTP فعال است، `otp` کد شش‌رقمی استفاده‌نشده یا یک کد بازیابی است. پاسخ موفق `csrf`، `username`، `version` و cookie `manix_session` می‌دهد. cookie HttpOnly/SameSite=Strict و با HTTPS Secure است.

تمام نوشتن‌های authenticated با cookie باید این header را داشته باشند:

```text
X-CSRF-Token: <csrf returned by login/session>
```

`GET /api/session` وضعیت نشست/CSRF را می‌دهد. `POST /api/logout` همان نشست را لغو می‌کند. در مسیر login هم Origin خارجی رد می‌شود. کدها/رمز را در URL یا log نگذار.

### API Key

از صفحهٔ حساب، با رمز فعلی، نام/Scope/اعتبار کلید را تعیین کن. token فقط یک بار نمایش داده می‌شود. درخواست:

```bash
curl https://panel.example.com/api/status \
  -H "Authorization: Bearer $MANIX_API_KEY"
```

- کلید به cookie/CSRF نیاز ندارد؛ اگر Origin ارائه شده باشد باید same-origin باشد.
- اگر Authorization نامعتبر یا کم‌دسترسی باشد، **به cookie مالک fallback نمی‌کند**.
- حساب، MFA، مدیریت کلید، session، audit، addons، نصب/حذف runtime، پک و Taskها با کلید قابل‌مدیریت نیستند. صرف Scope `settings.write` به آن‌ها دسترسی نمی‌دهد.
- سقف ۲۰ کلید، اعتبار ۱–۳۶۵ روز، hash-only storage؛ last-used با throttle حدود ۳۰ ثانیه به‌روزرسانی می‌شود.
- تغییر رمز از UI یا تغییر واقعی credential Environment، همهٔ کلیدها را لغو می‌کند؛ logout-all فقط نشست‌ها را لغو می‌کند.
- `files.write` به معنی قدرت نوشتن فایل‌های بازی، از جمله JAR است؛ Scopeهای HTTP، sandbox کد/OS یا نقش انسانی نیستند.

### Scopeها

| Scope | محدوده |
|---|---|
| `status` | `/api/status` |
| `console.read` | GET کنسول/دانلود لاگ |
| `console.write` | ارسال دستور Minecraft |
| `power` | Start/Stop/Restart/Kill |
| `files.read` | GET فایل‌ها/متن/دانلود/search و فهرست دنیاها |
| `files.write` | تغییر فایل‌ها/batch، ساخت/import/select/delete/export دنیا |
| `backups.read` | GET فهرست/دانلود بکاپ و `/api/exports/download` |
| `backups.write` | create/import/restore/delete بکاپ و `/api/world/export` |
| `players.read` | فهرست بازیکن و فایل‌های وضعیت |
| `players.write` | مدیریت بازیکن/Whitelist/IP/دستور هدفمند |
| `settings.read` | GET settings/properties/startup |
| `settings.write` | PATCH settings/properties |

خروجی ZIP دنیا در `/api/exports/download` به `backups.read` نیاز دارد، حتی اگر Job ساخت آن را با `files.write` در `/api/worlds/export` آغاز کرده باشی. برای export/دانلود با کلید Scopeهای لازم را ترکیب کن.

## مسیرهای عمومی

| Method | مسیر | معنی |
|---|---|---|
| GET | `/` و `/static/*` | پوستهٔ UI/دارایی محلی؛ API محافظت‌شده است |
| GET | `/healthz` | سلامت وب‌اپ، نه اثبات روشن بودن بازی یا تخصیص منابع |
| POST | `/api/login` | ورود rate-limited |
| GET | `/packs/<32-hex-id>.zip` | دانلود ZIP یک ریسورس‌پک با URL تصادفی؛ بدون cookie برای کلاینت MC |

پک‌ها دادهٔ عمومی قابل‌دانلود توسط دارندهٔ لینک‌اند. فهرست/مدیریت آن‌ها public نیست و مسیر arbitrary فایل بازی یا panel از این URL ساخته نمی‌شود.

## Jobها

کارهای طولانی معمولاً پاسخ سریع با این فیلدها می‌دهند:

```text
id, title, state=queued, created, message, download
```

هر حدود دو ثانیه `GET /api/status` بخوان. `job` فعال و `jobs` اخیر را دارد. state یکی از `queued/running/done/failed` است؛ در موفقیت بعضی عملیات `download` ارائه می‌شود. **HTTP 200 آغاز Job به معنی موفقیت عملیات نیست**؛ نتیجهٔ Job را بررسی کن. یک عملیات mutable در هر لحظه؛ تغییر فایل/هسته نیاز به بازی خاموش دارد. نتیجه/metadata ممکن است در پرشدن دیسک fail شود؛ RAM recent-job fallback به آزادشدن gate کمک می‌کند، ولی جای فضای سالم نیست.

کدهای معمول: `400` ورودی/شرط نامعتبر، `401` بدون ورود/کلید نامعتبر، `403` CSRF/Origin/Scope/reauth، `404` پیدا نشد، `409` بازی روشن/Job busy/تداخل فایل، `413` حجم، `422` schema، `429` تلاش بیش از حد، `502` منبع دانلود، `507` ثبت Job روی Volume ناموفق.

## وضعیت، قدرت و کنسول

| Method | مسیر | ورودی |
|---|---|---|
| GET | `/api/status` | بدون body؛ phase/running/name/engine/heap/metrics/node/warnings/job/jobs/آدرس‌ها |
| POST | `/api/power` | `{"action":"start"}`؛ stop/restart/kill هم مجاز |
| GET | `/api/console?after=0` | خطوط بعد از cursor؛ `reset` برای تعویض کانتینر |
| POST | `/api/console` | `{"command":"say Hello Manix"}`؛ فقط یک خط |
| GET | `/api/console/download` | لاگ چرخشی، attachment |

power فقط **بازی** را متوقف می‌کند. Kill فوراً SIGKILL است، خطر save دارد. دستور مستقیم stop/restart باید از power استفاده کند تا desired state درست ذخیره شود. Console کاربر مالک، دستورات Minecraft است و endpoint Shell سیستم‌عامل ندارد.

metrics: CPU/RSS Java، count/sample players، disk used/total/free، network RX/TX totals/rates و CPU سرویس. node: همین سرویس، region در صورت دادهٔ Environment، cgroup/fallback memory، uptime، CPU/quota و freshness. این‌ها billing/پلن/provider API نیستند.

## فایل‌ها

| Method | مسیر | ورودی/Query |
|---|---|---|
| GET | `/api/files?path=` | فهرست پوشهٔ نسبی server |
| GET | `/api/files/text?path=config.yml` | متن UTF-8 کوچک |
| PUT | `/api/files/text` | `{"path":"notes.txt","content":"مانیکس"}` |
| POST | `/api/files/mkdir` | `{"path":"folder"}` |
| POST | `/api/files/upload?path=mods&overwrite=false` | multipart یک `file` |
| GET | `/api/files/download?path=mods/file.jar` | attachment |
| POST | `/api/files/rename` | `{"source":"a.txt","target":"b.txt"}` |
| DELETE | `/api/files` | `{"path":"a.txt"}` |
| POST | `/api/files/extract` | `{"path":"save.zip","target":"world"}`؛ Job |
| POST | `/api/files/archive` | `{"path":"world"}`؛ Job/ZIP |
| GET | `/api/files/search?path=&q=config&recursive=true` | جستجوی **نام** فایل؛ `limited` اگر سقف رسید |
| POST | `/api/files/batch` | `{"action":"copy","paths":["a.txt"],"destination":"folder"}`؛ move/delete هم مجاز؛ Job |

Path نسبی داخل `/data/server`، بدون root mutation، traversal یا symlink. UI pagination ۵۰ مورد را روی نتیجه اجرا می‌کند. search سقف ۲۰k ورودی و ۱k نتیجه؛ batch حداکثر ۲۰۰ مسیر و copy با سقف حجم/فضای آزاد؛ فایل هم‌نام مقصد بازنویسی نمی‌شود. حذف گروهی backup قبل از حذف دارد، delete تکی معمولی نه.

## دنیاها، بکاپ و خروجی

| Method | مسیر | ورودی |
|---|---|---|
| GET | `/api/worlds` | active و فهرست اسم/حجم/ابعاد |
| POST | `/api/worlds/create` | `{"name":"world-new"}`؛ فقط پوشه، تولید با Start MC |
| POST | `/api/worlds/select` | `{"name":"world-new"}` |
| POST | `/api/worlds/import` | multipart: `name` تازه + `file` ZIP؛ Job |
| POST | `/api/worlds/export` | `{"name":"world-new"}`؛ Job |
| DELETE | `/api/worlds` | `{"name":"old-world"}`؛ Job/Safety؛ فعال حذف نمی‌شود |
| POST | `/api/world/export` | خروجی مجموعهٔ دنیاها؛ Job |
| GET | `/api/backups` | اسم، حجم، تاریخ، automatic |
| POST | `/api/backups` | بکاپ کامل بازی؛ Job |
| POST | `/api/backups/import` | multipart `file` بکاپ سازگار مانیکس/قبلی |
| GET | `/api/backups/download?name=...` | دانلود ZIP |
| POST | `/api/backups/restore` | `{"name":"...zip"}`؛ Job، بازی خاموش |
| DELETE | `/api/backups` | `{"name":"...zip"}` |
| GET | `/api/exports/download?name=...` | دانلود خروجی موقت |

world-name یک نام پوشهٔ ساده است. World ZIP باید `level.dat` در ریشه یا یک پوشهٔ اصلی داشته باشد؛ NBT کامل یا تبدیل فرمت تست/repair نمی‌شود. export/backup بازی روشن آن را موقتاً Stop و سپس Start می‌کند. بکاپ بازی account DB/Task/runtime ندارد؛ پک و index آن در server root شامل می‌شوند. فرمت جدید `.manix-backup.json` و `manix.backup.v1` است؛ خواندن فرمت قبلی نیز سازگار مانده است.

## بازیکن‌ها

`GET /api/players`: `online`، `source`، `online_info`، `known`، `count`، `whitelist`، `ops`، `banned` و `banned_ips`. source=`console-list` در تشخیص خروجی استاندارد `list`، وگرنه `status-sample`. زمان ورود ممکن است null باشد؛ هرگز از زمان API درخواست به‌جای ورود واقعی پر نمی‌شود. تاریخچهٔ مشاهده‌شده bounded است.

`POST /api/players/action` نمونه:

```json
{"action":"command","username":"Sample","command":"give {player} minecraft:diamond 1","reason":""}
```

actionهای مجاز: `op/deop/ban/pardon/kick/whitelist_add/whitelist_remove/whitelist_on/whitelist_off/ban_ip/pardon_ip/command`.

نام Minecraft: ۳–۱۶ کاراکتر لاتین/عدد/underscore؛ برای IP action آدرس IP معتبر؛ whitelist-on/off نام نمی‌خواهد. reason یک خط تا ۲۰۰ کاراکتر. **IP پشت Proxy ممکن است واقعی نباشد**. دستور ارسال‌شده، پاسخ موفق اجرا/سازگاری همهٔ commandهای همهٔ نسخه‌ها را تضمین نمی‌کند؛ کنسول را بخوان.

## تنظیمات و هسته/افزونه

| Method | مسیر | ورودی |
|---|---|---|
| GET/PATCH | `/api/settings` | config پنل؛ PATCH فقط فیلدهای تعریف‌شده |
| GET/PATCH | `/api/properties` | PATCH `{"values":{"motd":"مانیکس"}}`؛ کلیدهای پیشرفتهٔ موجود حفظ می‌شوند |
| GET | `/api/startup` | command و argv ساخته‌شده؛ editable_shell=false، نه endpoint Shell |
| GET | `/api/versions?kind=paper` | فهرست منبع رسمی |
| POST | `/api/versions/install` | `{"kind":"paper","version":"1.21.1","allow_downgrade":false}`؛ Job |
| GET | `/api/versions/installed` | فقط نشست؛ runtimeهای موجود |
| DELETE | `/api/versions/installed/<id>` | فقط نشست؛ حذف غیرِفعال با بازی خاموش |
| POST | `/api/versions/custom` | فقط نشست؛ multipart kind=spigot/custom، version، java=8/17/21/25، allow_downgrade، file=JAR؛ Job |
| GET | `/api/addons` | JARها و context سازگار |
| GET | `/api/addons/search?q=&offset=0` | Modrinth؛ ۱۲ نتیجه/صفحه |
| POST | `/api/addons/install` | `{"project_id":"..."}`؛ Job با required dependencies؛ update نیز همین مسیر |
| POST | `/api/addons/toggle` | `{"folder":"mods","file":"name.jar","enabled":false}` |
| GET | `/api/audit` | آخرین فعالیت‌ها، فقط نشست |

settings شامل `server_name/game_port/jvm_args/memory_mb/java_override/eula_accepted/autostart/auto_restart/backup_hours/restart_hours/backup_keep/game_domain/panel_domain/proxy_host/proxy_port` است؛ startup-command اضافی رد می‌شود. Java/heap/port/flags نیاز به بازی خاموش دارند. جزییات allowlist در README.

## پک‌ها — فقط نشست مدیریت

| Method | مسیر | ورودی |
|---|---|---|
| GET | `/api/packs` | فهرست/active/properties |
| POST | `/api/packs/upload` | multipart یک file ZIP؛ بازی خاموش |
| POST | `/api/packs/activate` | `{"id":"...","base_url":"https://panel.example.com","required":false,"prompt":"مانیکس"}`؛ id خالی=disable |
| DELETE | `/api/packs/<id>` | فقط غیرِفعال، بازی خاموش |

مدیریت Bearer ندارد. فایل دانلود با URL عمومی جداست. SHA-1 اتوماتیک، index قابل‌بکاپ در server/resourcepacks. حداکثر ۵۰ پک.

## Taskها — فقط نشست

GET/POST `/api/schedules`، PUT/PATCH/DELETE `/api/schedules/<id>`.

نمونهٔ create/edit:

```json
{
  "name":"بکاپ شبانه مانیکس",
  "action":"backup",
  "mode":"daily",
  "timezone":"Asia/Tehran",
  "at":"",
  "time":"03:00",
  "weekday":4,
  "command":"",
  "enabled":true
}
```

action=start/stop/restart/backup/command؛ mode=once/daily/weekly. برای once، at یک ISO datetime آینده در منطقهٔ انتخاب‌شده. weekday=0 دوشنبه تا 6 یکشنبه. PATCH فقط `{"enabled":false}`. سقف ۵۰ Task؛ datastore next_run و claim؛ بعد از >۶۰۰ ثانیه دیرکرد، skip بدون replay. ساعت DST ناموجود skip و ambiguous fold اول است. Claim پیش از اجرا، سیاست at-most-once؛ شکست/Deploy می‌تواند یک نوبت را از دست بدهد. دیتابیس Task در بکاپ **بازی** نیست.

## حساب — فقط نشست، بعضی عملیات reauthentication

| Method | مسیر | ورودی |
|---|---|---|
| GET | `/api/account` | پروفایل، MFA status/remaining، login history، devices، API key metadata و scopes؛ بدون Secret/hash/token |
| PATCH | `/api/account` | `{"display_name":"مالک مانیکس","email":"owner@example.com"}`؛ contact-only |
| POST | `/api/account/password` | `password` فعلی + `new_password`، ۱۲–۲۵۶ کاراکتر؛ لغو نشست/کلید |
| POST | `/api/account/logout-all` | همهٔ نشست‌ها، از جمله current |
| DELETE | `/api/account/devices/<64-hex-id>` | لغو نشست؛ ID hash، نه cookie خام |
| POST | `/api/account/2fa/setup` | password فعلی؛ Secret/URI فقط برای enrollment همان نشست/۱۰ دقیقه |
| POST | `/api/account/2fa/confirm` | `{"code":"..."}`؛ ۸ recovery code فقط یک بار |
| POST | `/api/account/2fa/disable` | password + code مصرف‌نشده |
| POST | `/api/account/keys` | password، name، scopes list، days؛ token فقط یک بار |
| DELETE | `/api/account/keys/<id>` | لغو کلید |

لاگین/تغییر رمز/MFA/صدور کلید در سرویس تک-worker سریال‌اند. کد TOTP/Recovery در SQLite transaction فقط یک‌بارمصرف می‌شود. Reset رمز Environment، MFA را به‌خودی‌خود خاموش نمی‌کند؛ `MANIX_RESET_2FA` فقط Recovery اپراتوری موقت است. تغییر ایمیل SMTP/verification ندارد و account registration endpoint وجود ندارد.

## سقف‌ها و استقرار

پیش‌فرض آپلود ۵۱۲ MB و ZIP بازشده ۸ GB؛ کانتینر/Volume/gateway ممکن است سقف کمتر مستقل داشته باشند. درخواست JSON معمولی حدود ۲ MB سقف دارد؛ login حدود ۸ KB. ویرایش متن تا ۱ MB. لاگ/تاریخچه/Job bounded هستند؛ محدودیت دقیق کد مرجع است. endpoint Shell، DB provisioning، billing، node creation، public-port allocation یا user registration در مانیکس وجود ندارد.

[README](../README.md) · [امنیت](../SECURITY.md) · [تست](TESTING.md)

</div>
