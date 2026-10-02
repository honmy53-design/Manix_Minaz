<div dir="rtl">

# گزارش تست مانیکس — نسخهٔ 1.1.0

تاریخ تهیه/بررسی: **۲۰۲۶-۱۰-۰۲**. این گزارش نتیجهٔ کارهای واقعاً اجراشده را از کارهای اجرا‌نشده جدا می‌کند. ضمانت کارکرد همهٔ مودها/MCهای تاریخی، امنیت certified یا پلن Railway نیست.

## بررسی محلی نسخهٔ جدید

| بررسی | نتیجهٔ واقعی |
|---|---|
| `python -m pytest -q` | **98 passed**؛ 48 تست قبلی + 50 تست/حالت جدید |
| `ruff check panel tests scripts` | موفق |
| `node --check panel/static/app.js` | موفق |
| `node --check panel/static/features.js` | موفق |
| Chromium، HTTPS/TestClient | ورود/فایل/تنظیمات/DNS/نسخه/بکاپ و مسیرهای جدید موفق |
| موبایل 390×844 و تبلت 820×1024 | صفحه‌های جدید و نبود overflow افقی document موفق |
| دارایی محلی/JS/CSP | بدون خطای غیرمنتظرهٔ مرورگر؛ فونت/CSS/JS محلی |

Backend این محیط Python 3.13 است؛ image و CI Python 3.12 استفاده می‌کنند. یک deprecation warning مربوط به Starlette TestClient/httpx دیده شد؛ شکست تست نبود. ساخت image/اجرای CI در این محیط انجام نشده، بنابراین هماهنگی image نهایی را با workflow خود Repo دوباره بررسی کن.

### پوشش تست‌های Python

- ورود/CSRF/Origin، cookie Secure HTTPS، scrypt، rate limit، logout و reset credential Environment.
- تغییر رمز UI و حفظ پس از Redeploy، لغو session/key و recovery با Environment جدید.
- پروفایل contact-only و دستگاه‌ها؛ logout-all، تاریخچهٔ auth مستقل از صد رویداد دیگر.
- TOTP vector از RFC 6238، enrollment session-bound، replay، recovery یک‌بارمصرف و هم‌زمانی دو مصرف‌کننده، disable.
- Bearer scope، عدم fallback به cookie ادمین، hash-only token، revoke و write بدون CSRF با scope درست.
- path traversal، symlink، ZIP خطرناک/محدودیت‌ها، root protection، UTF-8/properties.
- batch copy/move/delete/search؛ preflight تداخل/کپی به خود، symlink، rollback خطای دومین move و gate release.
- World ZIP ساختاری، select/export/delete، محافظت دنیای فعال، ambiguous/traversal ZIP، rollback خطای registry.
- pack format قدیمی/tuple جدید، SHA-1، public scoped download بدون نشست، HTTPS base validation، active delete guard و inclusion/registry بعد از Restore.
- بازیابی فرمت بکاپ قبلی، Safety و manifest shape نامعتبر؛ upload پک بعد از Restore آرشیو قدیمیِ بدون پوشهٔ پک.
- timezone تهران/روزانه/هفتگی/DST ساعت ناموجود، toggle/edit، command validation، claim بدون replay، skipped missed و نتیجهٔ job-running persistence failure.
- start/stop/restart و فرمان تقویمی از handler مشترک، `list` کنسول و join مشاهده‌شده.
- termination واقعی یک subprocess آزمایشی با SIGKILL، پورت ساخته‌شده در properties و live-change guard، JVM allowlist و deny flags.
- metadata JAR دستی/Spigot و cleanup غیرِفعال؛ installer بدون Main-Class رد می‌شود. rollback قبل از commit و حفظ JAR فعال در خطای بعد از ثبت config یا Audit، با سه حالت تزریق خطا بررسی شد.
- migration SQLite schema قبلی، mode 0600، node/network shape و خطای ثبت Job/dیسک بدون قفل دائمی.

**مرز تست:** کنترل فرایند از executable کوچک شبیه Java استفاده می‌کند؛ World test از byteهای مصنوعی به‌جای NBT واقعی، و JAR دستی از فایل ساختاری آزمایشی استفاده می‌کند. این تست‌ها routing، safety، lifecycle و metadata را بررسی می‌کنند، نه اینکه یک Spigot واقعی یا سیو کامل واقعاً بازی کرده باشد. Modrinth/dependency tests نیز پاسخ‌های fixture دارند، نه بازی واقعی افزونه‌ها.

### جریان مرورگر جدید

`scripts/browser_check.py` تمام درخواست‌های مرورگر را به FastAPI TestClient HTTPS می‌فرستد؛ سرور public باز نمی‌کند. تنها فهرست نسخه‌ها fixture است؛ عملیات فایل، بکاپ، world، pack، schedule و account به **handler واقعی** می‌روند.

در مرورگر اجرا شد: ورود، ساخت/ویرایش فایل، کپی گروهی و جستجو، نام/دامنه/DNS، نسخه، بکاپ، ساخت/انتخاب/واردکردن دنیا، آپلود/فعال‌سازی پک، ساخت/ویرایش/disable Task، پروفایل، صدور key و مصرف status، enroll TOTP، دریافت recovery، تغییر رمز و لغو key، ورود با رمز جدید + recovery، پاک‌شدن dialog secret، light/dark، مسیرهای جدید در موبایل/تبلت و CSP.

Screenshotها دادهٔ همین تست‌اند. نشان‌دهندهٔ provider حقیقی، پرداخت، IP اختصاصی یا بازی نصب‌شده نیستند. لینک دامنهٔ نمونه و جهان مصنوعی عمداً در README توضیح داده شده‌اند.

## بررسی‌های آنلاین هسته‌ها که از پایهٔ قبلی حفظ شده‌اند

لایهٔ دانلود/نصب رسمی پیش از این ارتقا واقعاً منابع زیر را خوانده، JAR/نصاب را دریافت و با Java واقعی **تا gate درخواست EULA** اجرا کرده است. در این ارتقا تست‌های Python/مرورگر دوباره اجرا شده‌اند؛ **تمام این native downloadها دوباره تکرار نشده‌اند**. جدول، رکورد تست قبلی همان لایهٔ رسمی حفظ‌شده است، نه ادعای build Docker جدید.

| هسته | Minecraft | بیلد مشاهده‌شده | Java | نتیجهٔ قبلی واقعی |
|---|---|---|---|---|
| Vanilla | 1.21.1 | 1.21.1 | 21 | دانلود + اجرا تا EULA موفق |
| Paper | 1.21.1 | 133 | 21 | دانلود + اجرا تا EULA موفق |
| Purpur | 1.21.1 | 2329 | 21 | دانلود + اجرا تا EULA موفق |
| Fabric | 1.21.1 | Loader 0.19.5 | 21 | دانلود + اجرا تا EULA موفق |
| Forge | 1.20.1 | 47.4.10 | 17 | نصاب رسمی + launch.args + EULA موفق |
| NeoForge | 1.21.1 | 21.1.252 | 21 | نصاب رسمی + launch.args + EULA موفق |
| Vanilla | 26.3 | 26.3 | 25 | دانلود + اجرا تا EULA موفق |
| Paper | 26.2 | 129 | 25 | دانلود + اجرا تا EULA موفق |
| Fabric | 26.3 | Loader 0.19.5 | 25 | دانلود + اجرا تا EULA موفق |

EULA در این اجراها **قبول نشده**، سرور عمومی باز نشده و world/player gameplay انجام نشده است. Paper 26.3 هنگام آن بررسی STABLE نداشت و نصبش عمداً رد شد؛ latest/بیلدها ممکن است بعداً تغییر کنند. Java 8 و همهٔ شاخه‌های تاریخی Forge native-tested نیستند.

## مواردی که هنوز اجرا/تأیید نشده‌اند

- Deploy روی حساب واقعی Railway کاربر، پرداخت/Volume/network/DNS/TCP، پورت عمومی یا quota provider.
- Build کامل Docker image اینجا؛ daemon Docker در دسترس نبود. workflow ساخت و بررسی Javaها داخل Repo است، نه نتیجهٔ اجراشدهٔ آن.
- push واقعی به GitHub یا اجرای GitHub Actions؛ token/حساب کاربر در اختیار پروژه قرار نگرفته.
- بازیکن واقعی، generation/repair NBT، سلامت save مهم، resource-pack client download در بازی، Spigot BuildTools/Spigot واقعی یا همهٔ پلاگین‌ها/commandها.
- مودپک بزرگ، upgrade/downgrade همهٔ نسخه‌ها، soak/load test طولانی، شبکهٔ Bedrock/UDP.
- penetration test مستقل، SLA/uptime، هزینهٔ مشخص، ظرفیت بازیکن یا چندمستاجری امن.

پیش از سیو مهم: CI image را بساز، سرویس آزمایشی با Volume واقعی راه بینداز، یک دنیای غیرِمهم تولید کن، از آدرس Proxy با Java Edition وصل شو و backup/restore/پک/Task را روی همان حساب امتحان کن. Data backup را خارج از Volume هم نگه دار.

</div>
