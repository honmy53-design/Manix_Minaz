<div dir="rtl">

# امنیت مانیکس / Manix

مانیکس **یک مالک و یک سرور Minecraft Java در یک کانتینر** دارد. این پروژه tenant isolation، کسب‌وکار هاست عمومی، SSH/Shell عمومی یا سامانهٔ چندکاربرهٔ سخت‌سازی‌شده نیست. تأیید/آزمون نفوذ مستقل ندارد.

## کنترل‌های پیاده‌شده

- رمز پیش‌فرض قابل‌استفاده وجود ندارد؛ placeholder راه‌اندازی رد می‌شود. رمز با scrypt و salt تصادفی (`n=16384,r=8,p=1`) ذخیره و با مقایسهٔ constant-time بررسی می‌شود.
- رمز bootstrap/recovery از Environment اپراتور است. رمز عوض‌شدهٔ UI بعد از Redeploy معمولی حفظ می‌شود؛ تغییر واقعی Environment credential، نشست‌ها/کلیدها را لغو می‌کند.
- توکن نشست و API Key تصادفی؛ فقط SHA-256 token ذخیره می‌شود. cookie HttpOnly/SameSite=Strict، روی HTTPS Secure، انقضای سروری، لغو تکی/همه.
- mutation با cookie نیاز به CSRF دارد. Origin خارجی، از جمله login، رد می‌شود. Bearer معتبر فقط route/Scope مجاز دارد و به cookie مالک fallback نمی‌کند.
- تلاش‌های ناموفق ورود/reauth/MFA محدودند. محدودیت اندازهٔ request/upload و مدل ورودی؛ JSON معمولی حدود ۲ MB، login حدود ۸ KB، multipart upload سقف قابل‌تنظیم.
- TOTP استاندارد RFC 6238، پنجرهٔ محدود ساعت و replay protection؛ هشت recovery code تصادفی، فقط digest، مصرف یک‌باره در SQLite transaction. enrollment محدود به همان نشست و ۱۰ دقیقه؛ Secret تا تأیید، ۲FA را فعال نمی‌کند.
- ورود و عملیات credential/MFA/صدور کلید در سرویس تک-worker سریال‌اند. تغییر رمز به‌صورت تراکنشی password/pending enrollment/session/API Key را تغییر/لغو می‌کند.
- دیتابیس پنل mode 0600 و پوشه‌های اختصاصی؛ symlink در مسیرهای داده/SQLite رد می‌شود. entrypoint با umask 077 فقط مالکیت mount را initialize و سپس به UID غیر-root تغییر می‌دهد.
- Console فقط stdin فرایند Java است، نه system shell. فرمان اجرا argv ساخته‌شده، نه startup-shell قابل‌ویرایش؛ flags JVM allowlist و محدود به تعداد/بازه‌اند. Java agent/URL config دلخواه از UI پذیرفته نمی‌شود.
- فایل‌منیجر فقط game root؛ مسیر نسبی، جلوگیری از traversal و symlink. panel DB/session/runtime جدا و در فایل‌منیجر بازی قابل‌دسترسی نیستند.
- ZIP: مسیر، نام تکراری، symlink، فایل خاص، encryption، تعداد و حجم بازشده کنترل می‌شوند؛ stage/rollback و بکاپ قبل از تغییرهای خطرناک مشخص استفاده می‌شوند. game mutation فقط JVM خاموش و یک Job mutable هم‌زمان.
- Backup restore با Safety و recovery journal؛ کد اجرای موتور از metadata ذخیره‌شدهٔ معتبر گرفته می‌شود، نه فرمان arbitrary در manifest ورودی.
- دانلود هسته/Modrinth با HTTPS host allowlist، سقف redirect/حجم و checksum تولیدکننده در صورت ارائه. endpoint دانلود دلخواه URL/SSRF در UI نیست.
- فایل‌های UI/فونت/آیکن محلی، بدون CDN JS؛ CSP، nosniff، textContent برای نام فایل/log/metadata؛ downloadها attachment هستند، نه اجرای HTML آپلودشده.
- Stop معمولی ابتدا فرمان ذخیره/توقف، سپس timeout/fallback. Kill فقط درخواست صریح مالک/Scope power و با هشدار از دست رفتن save.

## مهم‌ترین مرز اعتماد: JARها

**مود، پلاگین و JAR سرور کد اجرایی‌اند.** Minecraft با همان کاربر کانتینر پنل اجرا می‌شود؛ کد مخرب می‌تواند فایل/network و بالقوه `/data/panel` یا Environment را بخواند/تغییر دهد. محدودیت مسیر وب جلوی JAR مخرب را نمی‌گیرد. هیچ sandbox جدا، UID جدا یا کانتینر جدا برای Minecraft ساخته نشده است.

به همین علت این پنل را برای مشتری ناشناس، فروش هاست چندمستاجری یا واگذاری file-write/console-write به فرد غیرِقابل‌اعتماد استفاده نکن. API Scope مرز HTTP است، نه جداسازی سیستم‌عامل. Scope `files.write` می‌تواند JAR در mods/plugins قرار دهد. فقط صاحب مورداعتماد باید دسترسی بگیرد.

## Secretها، بازیابی و دادهٔ شخصی

- Secret TOTP برای تولید کد باید قابل‌خواندن باشد و در SQLite محافظت‌شده **بدون encryption key مستقل** نگه‌داری می‌شود. حفاظت Volume و بکاپ خصوصی آن ضروری است.
- password، raw API token، recovery code و Secret در Activity Log ثبت نمی‌شوند؛ لاگ کنسول/پلاگین ممکن است رازهایی را که خودت در دستور/کانفیگ می‌گذاری داشته باشد.
- نام/IP بازیکن و IP/User-Agent نشست ممکن است در log/history باشند. retention bounded است، نه سیستم حریم خصوصی enterprise.
- reset رمز از دسترسی مدیریتی provider انجام می‌شود؛ ایمیل تماس هیچ احراز/verification/reset SMTP ندارد.
- `MANIX_RESET_2FA=true` فقط برای recovery یک‌بارهٔ اپراتور؛ بلافاصله بعد از recovery حذف شود. ماندن آن روی true، MFA را در هر boot حذف می‌کند.
- خروج همهٔ دستگاه‌ها فقط sessionها را لغو می‌کند؛ API Key مستقل را جدا revoke کن. تغییر رمز، هم نشست و هم کلید را لغو می‌کند.
- کپی متنی یک Secret ممکن است در clipboard سیستم‌عامل بماند؛ پاک‌کردن dialog، clipboard/فایل آفلاین تو را پاک نمی‌کند.

## ریسورس‌پک عمومی است

دانلود `/packs/<random-id>.zip` عمداً بدون login است تا کلاینت Minecraft بتواند فایل را بگیرد. ID تصادفی در برابر حدس کمک می‌کند اما **URL مجوز محرمانگی قوی/زمان‌دار نیست**؛ دارندهٔ لینک به ZIP دسترسی دارد. فایل خصوصی را در pack نگذار. فهرست/مدیریت pack authenticated است، مسیر فایل arbitrary public نمی‌شود و فقط شناسهٔ معتبر در پوشهٔ resourcepacks سرو می‌شود.

## محدودیت‌هایی که نباید به‌عنوان تضمین فهمیده شوند

- cgroup/heap guard همهٔ OOMها را پیشگیری نمی‌کند. quota واقعی توسط Railway/Compose اعمال می‌شود، نه فروش پلن پنل.
- هیچ بکاپی تضمین دفاع در برابر حذف Volume، provider failure، disk full، SIGKILL، mod مخرب یا downgrade فرمت دنیا نیست. بکاپ محلی همان Volume است؛ off-site داشته باش.
- copy/move/import از stage/rollback برای خطای حین اجرا استفاده می‌کنند؛ به‌جز journal مخصوص Restore، همهٔ کارهای چندفایلی تراکنش مقاوم در برابر قطع ناگهانی برق نیستند. قبل از Redeploy Jobها را تمام کن.
- Task claim پیش از اجرا، at-most-once و عدم replay stale است، نه exactly-once؛ قطع سرویس می‌تواند یک نوبت را از دست بدهد.
- پسوند JAR، Main-Class و checksum، اثبات امن بودن برنامه نیستند. ZIP/NBT ساختاری، تضمین سلامت یک دنیا/پک در بازی نیست.
- backend/billing/provider مستقل، registration، RBAC چندکاربر، SMTP و جداسازی نود پیاده نشده‌اند. یک replica/worker لازم است.

## استقرار امن

TLS عمومی ضروری است. Compose محلی HTTP را فقط loopback bind می‌کند. `FORWARDED_ALLOW_IPS=*` پیش‌فرض مسیر reverse proxy Railway است؛ بیرون از آن فقط proxyهای مورداعتماد را allow کن. بازکردن plain HTTP یا اعتماد به headerهای proxy از فرستندهٔ ناشناس می‌تواند cookie/IP/rate policy را ضعیف کند.

فقط HTTP پنل و TCP بازی را public کن؛ Query/RCON در startup کنترل‌شده خاموش‌اند. پلاگین‌ها ممکن است سرویس/دستور/پورت جدا باز کنند؛ خودت بررسی کن. DNS واقعی و پورت Proxy باید درست تنظیم شوند.

Dependency/imageهای upstream را بازبینی و به‌روز نگه دار، CI را اجرا و با دنیای غیرِمهم آزمایش کن. برای آسیب‌پذیری، خصوصی به مالک fork خودت گزارش بده؛ پروژه آدرس support/security ساختگی یا گواهی production اختراع نمی‌کند.

</div>
