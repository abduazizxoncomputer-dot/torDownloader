# Contabo (Ubuntu 24.04) ga deploy qilish

Bu qo'llanma botni `systemd` service sifatida doimiy ishlaydigan qilib
o'rnatadi (server qayta yuklansa ham avtomatik ko'tariladi).

## 0. Serverga ulanish

```sh
ssh root@SERVER_IP
```

## 1. Tizimni yangilash va kerakli paketlarni o'rnatish

```sh
apt update && apt upgrade -y
apt install -y python3-venv python3-pip ufw
```

## 2. Bot uchun alohida (root bo'lmagan) foydalanuvchi yaratish

Botni root sifatida ishlatish xavfli — alohida xizmat foydalanuvchisi yaratamiz.

```sh
adduser --system --group --home /opt/utube_bot utubebot
```

## 3. Kodni yuborish (GitHub'siz, to'g'ridan-to'g'ri scp orqali)

O'zingizning kompyuteringizda (loyiha papkasida), serverga yuborishdan oldin
keraksiz narsalarni (`.git`, `.venv`, `downloads`, sessiya fayllari, `.env`)
chetlab o'tib arxiv yasaymiz:

```sh
cd "D:/Loyihalar/utube_bot"
tar --exclude=.git --exclude=.venv --exclude=__pycache__ \
    --exclude=downloads --exclude=.env \
    --exclude=sessions/*.session --exclude=sessions/*.session-journal \
    -czf utube_bot.tar.gz .
scp utube_bot.tar.gz root@SERVER_IP:/tmp/
```

Keyin serverda:

```sh
mkdir -p /opt/utube_bot
tar -xzf /tmp/utube_bot.tar.gz -C /opt/utube_bot
rm /tmp/utube_bot.tar.gz
cd /opt/utube_bot
```

## 4. Virtual muhit va bog'liqliklar

```sh
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-bot.txt
.venv/bin/pip install -e .
```

`libtorrent` odatda PyPI'dan tayyor wheel sifatida o'rnatiladi (yuqoridagi
`pip install` shuning ichida). Agar xatolik chiqsa (kamdan-kam, masalan
noodatiy CPU arxitekturasida), muqobil yo'l — tizim paketidan foydalanish:

```sh
apt install -y python3-libtorrent
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements-bot.txt --no-deps  # libtorrent'ni qayta o'rnatmaslik uchun
.venv/bin/pip install python-telegram-bot[all] python-dotenv asyncclick rich pyrogram tgcrypto
.venv/bin/pip install -e .
```

## 5. `.env` faylini sozlash

```sh
cp .env.example .env
nano .env
```

Kamida `BOT_TOKEN` ni to'ldiring. Katta fayllar (>50MB) uchun userbot relay
kerak bo'lsa, `API_ID`/`API_HASH` ni ham shu bosqichda yozing (6-bosqichga
qarang).

## 6. (Ixtiyoriy) Userbot relay — 50MB dan katta fayllar uchun

Bu bosqich interaktiv (telefon raqami, SMS kod so'raladi), shuning uchun
alohida, to'g'ridan-to'g'ri terminal orqali bajarilishi kerak:

```sh
cd /opt/utube_bot
sudo -u utubebot .venv/bin/python scripts/create_userbot_session.py
sudo -u utubebot .venv/bin/python scripts/setup_storage_channel.py
```

Ikkinchisi `.env` fayliga `STORAGE_CHAT_ID` ni avtomatik yozadi.

## 7. Egalikni to'g'rilash

```sh
chown -R utubebot:utubebot /opt/utube_bot
```

## 8. systemd service o'rnatish

```sh
cp /opt/utube_bot/deploy/utube-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now utube-bot
```

Holatini va loglarni tekshirish:

```sh
systemctl status utube-bot
journalctl -u utube-bot -f
```

## 9. Firewall (ixtiyoriy, lekin torrent tezligi uchun tavsiya etiladi)

Bot Telegram bilan long-polling orqali ishlaydi (faqat chiquvchi ulanish
kerak), lekin torrent P2P protokoli uchun kiruvchi ulanishlar ko'proq
peer topishga yordam beradi. `.env`dagi `BASE_PORT`/`PORT_POOL_SIZE`
oralig'ini oching:

```sh
ufw allow 22/tcp
ufw allow 6881:7380/tcp
ufw allow 6881:7380/udp
ufw enable
```

(Diapazonni o'zingizdagi `BASE_PORT` va `PORT_POOL_SIZE` qiymatlariga
moslashtiring: `BASE_PORT` dan `BASE_PORT + PORT_POOL_SIZE - 1` gacha.)

## 10. Local Bot API Server (ixtiyoriy — 45MB'dan katta fayllarni shaxsiy
akkount ishlatmasdan yuborish uchun)

Docker o'rnating:

```sh
curl -fsSL https://get.docker.com | sh
```

Konteynerni **host va konteyner ichida bir xil yo'l bilan** ishga tushiring —
bu muhim, aks holda bot fayllarni to'g'ridan-to'g'ri diskdan o'qiy olmaydi
(pastga qarang):

```sh
docker run -d \
  --name telegram-bot-api \
  --restart unless-stopped \
  -p 127.0.0.1:8081:8081 \
  -v /var/lib/telegram-bot-api:/var/lib/telegram-bot-api \
  -e TELEGRAM_API_ID="<my.telegram.org dan API_ID>" \
  -e TELEGRAM_API_HASH="<my.telegram.org dan API_HASH>" \
  -e TELEGRAM_LOCAL=1 \
  aiogram/telegram-bot-api:latest
```

`.env`ga qo'shing:

```
LOCAL_BOT_API_BASE_URL=http://127.0.0.1:8081/bot
```

**`LOCAL_BOT_API_BASE_FILE_URL`ni SOZLAMANG** — local (`--local`) rejimda
server `getFile`ga javoban to'g'ridan-to'g'ri diskdagi absolyut yo'lni
qaytaradi, va `base_file_url` sozlansa, python-telegram-bot bu yo'lni
(noto'g'ri) URL bilan qo'shib, buzuq manzil hosil qiladi (`InvalidToken: Not
Found` xatosi bilan chiqadi). `base_file_url` sozlanmasa, bot faylni
to'g'ridan-to'g'ri diskdan nusxalaydi — tezroq va ishonchli.

**Muhim — ruxsatlar:** konteyner fayllarni Docker daemon boshqargan
foydalanuvchi nomidan (odatda tasodifiy UID, bu serverda `messagebus`
guruhiga to'g'ri kelgan) yozadi. `utubebot` bu fayllarni o'qiy olishi uchun
uni o'sha guruhga qo'shing (guruh nomi boshqacha bo'lishi mumkin — `ls -la
/var/lib/telegram-bot-api/` orqali tekshiring):

```sh
usermod -aG messagebus utubebot
systemctl restart utube-bot
```

Agar bu qadam o'tkazib yuborilsa, `.torrent` fayl yuborilganda (magnet-link
emas — u fayl yuklab olishni talab qilmaydi) botda hech qanday javob
chiqmaydi, log'da esa `telegram.error.InvalidToken: Not Found` ko'rinadi.

## Yangilash (keyingi deploylar)

Kodda o'zgarish qilganingizdan so'ng, mahalliy kompyuteringizda 3-bosqichdagi
`tar` + `scp` buyruqlarini qayta bajaring, so'ng serverda:

```sh
tar -xzf /tmp/utube_bot.tar.gz -C /opt/utube_bot
chown -R utubebot:utubebot /opt/utube_bot
cd /opt/utube_bot
sudo -u utubebot .venv/bin/pip install -r requirements-bot.txt
systemctl restart utube-bot
```
