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
