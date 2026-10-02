# راهنمای دقیق‌تر Railway برای مانیکس / Manix

## قبل از روشن کردن بازی، این چک‌لیست را بررسی کن

- [ ] Dockerfile در ریشهٔ درست Repo و Builder = Dockerfile
- [ ] هیچ Build یا Start Command ناسازگار از پروژهٔ قبلی باقی نمانده
- [ ] Volume متصل به همین سرویس، Mount Path = `/data`
- [ ] `DATA_DIR=/data` و Railway متغیر `RAILWAY_VOLUME_MOUNT_PATH` را در runtime فراهم کرده
- [ ] `PANEL_PASSWORD` یک رمز اختصاصی طولانی، نه متن نمونهٔ README
- [ ] Replicas = 1، یک worker، بدون scale افقی
- [ ] Sleeping / Serverless خاموش
- [ ] سهمیه RAM سرویس بالاتر از heap بازی و حافظه native/پنل
- [ ] Generate Domain برای HTTP روی `8080`
- [ ] TCP Proxy برای بازی روی `25565`
- [ ] EULA را مالک در پنل خودش پذیرفته
- [ ] قبل از تغییر مهم، بکاپ خارج از Railway گرفته شده

HTTP و TCP می‌توانند هم‌زمان روی یک سرویس Railway فعال شوند. Docker `EXPOSE` به‌تنهایی آدرس عمومی نمی‌سازد؛ بخش Networking را باید تنظیم کنی.

## رمز و دسترسی

نام کاربری اولیه `admin` است. رمز Environment bootstrap/recovery است؛ تغییر رمز از UI با Redeploy معمولی حفظ می‌شود. تغییر واقعی `PANEL_PASSWORD` در Railway و Redeploy، رمز را به مقدار جدید و نشست‌ها/API Keyها را باطل می‌کند. برای تغییر نام کاربری، `PANEL_USERNAME` را تغییر بده (credential bootstrap هم بازنشانی می‌شود). ثبت‌نام عمومی و حساب مشتری وجود ندارد. بازیابی MFA فقط با متغیر موقت `MANIX_RESET_2FA=true` است؛ بلافاصله پس از بازیابی حذفش کن. ایمیل تماس، reset ایمیلی نیست.

یک Volume متعلق به root ممکن است برای کاربر عادی قابل نوشتن نباشد؛ entrypoint اولیه root، مالکیت پوشه‌های داده را اصلاح می‌کند و بعد با `gosu panel` دسترسی root را کنار می‌گذارد. Java و وب‌اپ root اجرا نمی‌شوند. فایل‌های غیرقابل‌نوشتنِ واردشده از سرویس دیگری ممکن است به اصلاح مالکیت نیاز داشته باشند؛ Volume را به‌صورت کامل و بدون بررسی `chmod 777` نکن.

## دامنه‌ها

- پنل: Custom Domain در Railway با پورت HTTP و رکوردهای ارائه‌شدهٔ خود Railway.
- بازی: CNAME به آدرس Proxy و استفاده از **پورت عمومی Proxy**؛ برای اتصال Java بدون پورت، SRV.
- Cloudflare بازی: **DNS only**، نه HTTP proxy معمولی.
- رکورد SRV هدف را به خود hostname Railway Proxy بده، نه URL `https://...`.
- اگر Proxy را پاک و دوباره ایجاد کردی، پورت/هدف ممکن است تغییر کند؛ DNS و فرم پنل را اصلاح کن.
- نوشتن دامنه در پنل، ownership دامنه را تأیید یا DNS را تغییر نمی‌دهد.

بررسی SRV روی کامپیوتر خودت:

```bash
nslookup -type=SRV _minecraft._tcp.play.example.com
```

برای تست مشکل اتصال، اول با خود `proxy-domain:proxy-port` وارد بازی شو؛ اگر آن کار کرد ولی دامنه نه، مشکل معمولاً DNS/SRV است، نه بازی.

## جابه‌جایی و به‌روزرسانی

کد Repo را به‌روزرسانی کن؛ داده‌ها از Volume می‌آیند و داخل image نیستند. قبل از Deploy عمدی، بازی را از پنل خاموش کن، منتظر اتمام Stop بمان و بکاپ مهم را دانلود کن. پس از دیپلوی، اگر «بازیابی وضعیت روشن» فعال باشد، فقط بازی‌ای که پیش از قطع سرویس وضعیت مطلوب روشن داشته باشد از نو اجرا می‌شود. Stop دستی وضعیت مطلوب را خاموش ذخیره می‌کند.

اگر Volume را پاک/جدا کنی یا یک پروژهٔ تازه بسازی، سیو خودبه‌خود منتقل نمی‌شود. روی مقصد همان هسته و نسخه را نصب کن، بکاپ مانیکس را وارد و Restore کن. برای سیو ساده از صفحهٔ دنیاها ZIP را با نام تازه وارد کن؛ برای ZIPهای پیچیده فایل‌منیجر/Extract را به کار ببر. دیتابیس نشست و رمز پنل در بکاپ بازی نیست؛ رمز مقصد را دوباره در Variables تنظیم کن.

## CLI برای فایل‌های خیلی بزرگ

HTTP و پلن Railway ممکن است برای آپلود/دانلود بزرگ محدودیت مستقل داشته باشند. افزایش `MAX_UPLOAD_MB` محدودیت gateway را دور نمی‌زند. در صورت نیاز از امکانات فعلی Railway Volume CLI استفاده کن، مثلاً طبق مستندات:

```bash
railway login
railway link
railway volume browse /
```

یا دستورات `railway volume files list/download/upload`؛ قبل از اجرا مقصد Volume و سرویس را بررسی کن. فایل‌های اصلی بازی در `/server` **نسبت به ریشهٔ Volume** هستند؛ Mount داخل کانتینر `/data/server` است. فایل بزرگ ZIP دنیا را ابتدا با بازی خاموش بفرست و از فایل‌منیجر Extract کن. هیچ توکن Railway در پنل یا Repo لازم نیست.

## چرا قالب قدیمی railway.json در پروژه نیست؟

طبق مستندات فعلی Railway در ۲۰۲۶-۱۰-۰۲، Config as Code قدیمی deprecated است؛ سرویس‌های جدید از آن استفاده نمی‌کنند. روش این پروژه Dockerfile قابل‌تشخیص + تنظیمات دستی شفاف است. IaC پروژه را می‌توان با Railway CLI فعلی ایجاد/وارد کرد؛ برای آن به SDK/CLI فعلی، پروژهٔ واقعی و تأیید تغییرات نیاز داری. فایلِ حدسی با project ID یا secret آماده در این ZIP قرار نگرفته.

منابع:
- https://docs.railway.com/networking/tcp-proxy
- https://docs.railway.com/volumes
- https://docs.railway.com/builds/dockerfiles
- https://docs.railway.com/infrastructure-as-code
- https://docs.railway.com/variables


## ارتقای مانیکس با دادهٔ قبلی

Railway: همان Volume /data را نگه دار. Stop امن، پایان Job، بکاپ خارج از سرویس، سپس تغییر Source/Redeploy. Session cookie جدید ورود مجدد می‌خواهد؛ schema قبلی migrate و بکاپ قدیمی سازگار است. Profile/MFA/Task روی همان SQLite هستند، ولی در ZIP **بکاپ بازی** نیستند. Reset واقعی رمز از Environment، MFA را خودبه‌خود حذف نمی‌کند.

Compose محلی: تغییر برند/نام پروژه می‌تواند volume prefix را عوض کند. با `docker volume ls` نام واقعی قبلی را پیدا کن؛ سپس مثلاً `compose.override.yaml` بساز:

```yaml
volumes:
  manix-data:
    external: true
    name: REPLACE_WITH_YOUR_EXISTING_VOLUME_NAME
```

placeholder را با نام **volume موجود خودت** عوض کن؛ قبل از Start مطمئن شو به دادهٔ درست وصل شده‌ای. این فایل مثال migration است، نه چیزی که بدون بررسی باید اجرا شود. `docker compose down -v` برای upgrade نزن.

## تغییر پورت داخلی

در مانیکس با بازی خاموش پورت داخلی را تغییر بده؛ سپس Target Port TCP Proxy واقعی در Railway را به همان مقدار اصلاح کن. public proxy port توسط Railway مدیریت می‌شود. اگر proxy host/port عمومی عوض شد، فرم پنل و DNS/SRV را به‌روز کن. فرم پورت، allocation عمومی/چندport را provision نمی‌کند.

## آدرس پک و Taskها

پک به دامنهٔ HTTPS عمومی همین پنل نیاز دارد؛ پس از مهاجرت دامنه base URL را دوباره فعال کن. URL پک public و فقط برای فایل غیرخصوصی است. Taskها تنها تا زمانی کار می‌کنند که خود سرویس Railway بیدار/روشن باشد؛ نمی‌توانند حساب خاموش provider را از بیرون Start کنند. EULA/Java/منابع همچنان لازم است.
