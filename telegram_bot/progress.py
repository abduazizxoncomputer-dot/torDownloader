def human_size(num_bytes):
    size = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def bar(percent, width=18):
    filled = int(width * percent / 100)
    return '█' * filled + '░' * (width - filled)


def format_progress(status, action_label=None):
    name = status.get('name') or 'Torrent'
    total = status.get('total_wanted') or 0

    if status.get('state') == 'fetching_metadata' or not total:
        lines = [
            f"📥 <b>{name}</b>",
            f"🔎 Fetching metadata... ({status.get('num_peers', 0)} connections)",
        ]
    else:
        done = status.get('total_done') or 0
        percent = done / total * 100
        lines = [
            f"📥 <b>{name}</b>",
            f"{bar(percent)} {percent:.1f}%",
            f"{human_size(done)} / {human_size(total)}",
            f"⬇️ {human_size(status.get('download_rate', 0))}/s  ⬆️ {human_size(status.get('upload_rate', 0))}/s",
            f"👥 {status.get('num_peers', 0)} peers  •  {status.get('state', '')}",
        ]

    if action_label:
        lines.append(action_label)
    return "\n".join(lines)


def format_upload_progress(name, done, total):
    # done<=0 — hali birorta ham real progress signali kelmagan (masalan
    # to'g'ridan-to'g'ri Bot API yuklashda buni umuman bermaydi). Soxta 0%
    # ko'rsatish o'rniga halol "Yuborilmoqda..." holatini chiqaramiz.
    if not total or done <= 0:
        return f"⬆️ <b>{name}</b>\nSending..."
    percent = done / total * 100
    return "\n".join([
        f"⬆️ <b>{name}</b>",
        f"{bar(percent)} {percent:.1f}%",
        f"{human_size(done)} / {human_size(total)}",
    ])


def format_upload_done(name):
    return f"✅ <b>{name}</b> sent."


def format_done(status):
    name = status.get('name') or 'Torrent'
    total = status.get('total_wanted') or 0
    return f"✅ <b>{name}</b> downloaded ({human_size(total)}). Sending files..."


def format_error(name, error):
    return f"❌ <b>{name}</b> failed to download:\n<code>{error}</code>"
