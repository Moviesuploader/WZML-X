from asyncio import gather, iscoroutinefunction
from html import escape
from pyrogram.enums import ButtonStyle
from re import findall
from time import time

from psutil import cpu_percent, disk_usage, virtual_memory

from ... import (
    DOWNLOAD_DIR,
    bot_cache,
    bot_start_time,
    status_dict,
    task_dict,
    task_dict_lock,
)
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker

SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


class MirrorStatus:
    STATUS_UPLOAD = "Upload"
    STATUS_DOWNLOAD = "Download"
    STATUS_CLONE = "Clone"
    STATUS_QUEUEDL = "QueueDl"
    STATUS_QUEUEUP = "QueueUp"
    STATUS_PAUSED = "Pause"
    STATUS_ARCHIVE = "Archive"
    STATUS_EXTRACT = "Extract"
    STATUS_SPLIT = "Split"
    STATUS_CHECK = "CheckUp"
    STATUS_SEED = "Seed"
    STATUS_SAMVID = "SamVid"
    STATUS_CONVERT = "Convert"
    STATUS_FFMPEG = "FFmpeg"
    STATUS_YT = "YouTube"
    STATUS_METADATA = "Metadata"
    STATUS_SEEDR = "Seedr"


class EngineStatus:
    def __init__(self):
        ver = bot_cache.get("eng_versions", {})
        self.STATUS_ARIA2 = f"Aria2 v{ver.get('aria2', 'N/A')}"
        self.STATUS_AIOHTTP = f"AioHttp v{ver.get('aiohttp', 'N/A')}"
        self.STATUS_GDAPI = f"Google-API v{ver.get('gapi', 'N/A')}"
        self.STATUS_QBIT = f"qBit v{ver.get('qBittorrent', 'N/A')}"
        self.STATUS_TGRAM = f"WzPyro v{ver.get('wzgram', 'N/A')}"
        self.STATUS_MEGA = f"MegaSDK v{ver.get('mega', 'N/A')}"
        self.STATUS_YTDLP = f"yt-dlp v{ver.get('yt-dlp', 'N/A')}"
        self.STATUS_FFMPEG = f"ffmpeg v{ver.get('ffmpeg', 'N/A')}"
        self.STATUS_7Z = f"7z v{ver.get('7z', 'N/A')}"
        self.STATUS_RCLONE = f"RClone v{ver.get('rclone', 'N/A')}"
        self.STATUS_SABNZBD = f"SABnzbd+ v{ver.get('SABnzbd+', 'N/A')}"
        self.STATUS_QUEUE = "QSystem v2"
        self.STATUS_JD = "JDownloader v2"
        self.STATUS_YT = "Youtube-Api"
        self.STATUS_METADATA = "Metadata"
        self.STATUS_UPHOSTER = "Uphoster"
        self.STATUS_SEEDR = "Seedr"


STATUSES = {
    "ALL": "All",
    "DL": MirrorStatus.STATUS_DOWNLOAD,
    "UP": MirrorStatus.STATUS_UPLOAD,
    "QD": MirrorStatus.STATUS_QUEUEDL,
    "QU": MirrorStatus.STATUS_QUEUEUP,
    "AR": MirrorStatus.STATUS_ARCHIVE,
    "EX": MirrorStatus.STATUS_EXTRACT,
    "SD": MirrorStatus.STATUS_SEED,
    "CL": MirrorStatus.STATUS_CLONE,
    "CM": MirrorStatus.STATUS_CONVERT,
    "SP": MirrorStatus.STATUS_SPLIT,
    "SV": MirrorStatus.STATUS_SAMVID,
    "FF": MirrorStatus.STATUS_FFMPEG,
    "PA": MirrorStatus.STATUS_PAUSED,
    "CK": MirrorStatus.STATUS_CHECK,
}


async def get_task_by_gid(gid: str):
    async with task_dict_lock:
        for tk in task_dict.values():
            if hasattr(tk, "seeding"):
                await tk.update()
            if tk.gid() == gid or tk.gid().startswith(gid):
                return tk
        return None


async def get_specific_tasks(status, user_id):
    if status == "All":
        if user_id:
            return [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        else:
            return list(task_dict.values())
    tasks_to_check = (
        [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        if user_id
        else list(task_dict.values())
    )
    coro_tasks = []
    coro_tasks.extend(tk for tk in tasks_to_check if iscoroutinefunction(tk.status))
    coro_statuses = await gather(*[tk.status() for tk in coro_tasks])
    result = []
    coro_index = 0
    for tk in tasks_to_check:
        if tk in coro_tasks:
            st = coro_statuses[coro_index]
            coro_index += 1
        else:
            st = tk.status()
        if (st == status) or (
            status == MirrorStatus.STATUS_DOWNLOAD and st not in STATUSES.values()
        ):
            result.append(tk)
    return result


async def get_all_tasks(req_status: str, user_id):
    async with task_dict_lock:
        return await get_specific_tasks(req_status, user_id)


def get_raw_file_size(size):
    num, unit = size.split()
    return int(float(num) * (1024 ** SIZE_UNITS.index(unit)))


def get_readable_file_size(size_in_bytes):
    if not size_in_bytes:
        return "0B"
    if size_in_bytes < 0:
        return "Unknown"

    index = 0
    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1

    return f"{size_in_bytes:.2f}{SIZE_UNITS[index]}"


def get_readable_time(seconds: int):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result


def get_raw_time(time_str: str) -> int:
    time_units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(
        int(value) * time_units[unit]
        for value, unit in findall(r"(\d+)([dhms])", time_str)
    )


def time_to_seconds(time_duration):
    try:
        parts = time_duration.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(float, parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = map(float, parts)
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = float(parts[0])
        else:
            return 0
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0


def speed_string_to_bytes(size_text: str):
    size = 0
    size_text = size_text.lower()
    if "k" in size_text:
        size += float(size_text.split("k")[0]) * 1024
    elif "m" in size_text:
        size += float(size_text.split("m")[0]) * 1048576
    elif "g" in size_text:
        size += float(size_text.split("g")[0]) * 1073741824
    elif "t" in size_text:
        size += float(size_text.split("t")[0]) * 1099511627776
    elif "b" in size_text:
        size += float(size_text.split("b")[0])
    return size


def get_progress_bar_string(pct):
    pct = float(str(pct).strip("%"))
    p = min(max(pct, 0), 100)
    cFull = int(p // 8)
    cPart = int(p % 8 - 1)
    p_str = "■" * cFull
    if cPart >= 0:
        p_str += ["▤", "▥", "▦", "▧", "▨", "▩", "■"][cPart]
    p_str += "□" * (12 - cFull)
    return f"[{p_str}]"


async def get_readable_message(sid, is_user, page_no=1, status="All", page_step=1):
    """Render compact premium task cards while preserving all status controls."""
    tasks = await get_specific_tasks(status, sid if is_user else None)
    status_limit = max(1, int(Config.STATUS_LIMIT or 10))
    tasks_no = len(tasks)
    pages = max(1, (tasks_no + status_limit - 1) // status_limit)
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
        status_dict[sid]["page_no"] = page_no
    elif page_no < 1:
        page_no = max(1, pages - (abs(page_no) % pages))
        status_dict[sid]["page_no"] = page_no

    start_position = (page_no - 1) * status_limit
    selected_tasks = tasks[start_position : start_position + status_limit]
    buttons = ButtonMaker()
    bot_limit = max(0, int(Config.BOT_MAX_TASKS or 0))

    def clean(value, limit=48):
        value = escape(str(value if value not in (None, "") else "—"))
        return value if len(value) <= limit else value[: limit - 1] + "…"

    def progress_value(value):
        try:
            return min(100.0, max(0.0, float(str(value).strip().rstrip("%"))))
        except (TypeError, ValueError):
            return 0.0

    def progress_bar(value, width=12):
        filled = round(progress_value(value) / 100 * width)
        return "█" * filled + "░" * (width - filled)

    def status_label(value):
        labels = {
            MirrorStatus.STATUS_UPLOAD: "UPLOADING",
            MirrorStatus.STATUS_DOWNLOAD: "DOWNLOADING",
            MirrorStatus.STATUS_QUEUEDL: "QUEUED",
            MirrorStatus.STATUS_QUEUEUP: "UPLOAD QUEUE",
            MirrorStatus.STATUS_PAUSED: "PAUSED",
            MirrorStatus.STATUS_CLONE: "CLONING",
            MirrorStatus.STATUS_EXTRACT: "EXTRACTING",
            MirrorStatus.STATUS_ARCHIVE: "ARCHIVING",
            MirrorStatus.STATUS_SPLIT: "SPLITTING",
            MirrorStatus.STATUS_CONVERT: "CONVERTING",
            MirrorStatus.STATUS_FFMPEG: "FFMPEG",
            MirrorStatus.STATUS_YT: "YOUTUBE",
            MirrorStatus.STATUS_CHECK: "CHECKING",
            MirrorStatus.STATUS_SEED: "SEEDING",
        }
        return labels.get(value, str(value).upper())

    from ..telegram_helper.bot_commands import BotCommands

    msg = (
        "<b>✦ WZML-X  /  TASK CENTER</b>\n"
        f"<code>{tasks_no} ACTIVE</code>  •  "
        f"<code>LIMIT {bot_limit or '∞'}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
    )

    for index, task in enumerate(selected_tasks, start=start_position + 1):
        if status != "All":
            tstatus = status
        elif iscoroutinefunction(task.status):
            tstatus = await task.status()
        else:
            tstatus = task.status()

        try:
            task_name = clean(task.name() or "Resolving task…", 105)
        except Exception:
            task_name = "Active task"

        raw_progress = task.progress()
        pct = progress_value(raw_progress)
        try:
            elapsed = get_readable_time(max(0, time() - task.listener.message.date.timestamp()))
        except Exception:
            elapsed = "—"

        sender = getattr(task.listener.message, "from_user", None)
        sender_id = getattr(sender, "id", getattr(task.listener, "user_id", "—"))
        sender_name = clean(
            getattr(sender, "first_name", None)
            or getattr(sender, "username", None)
            or sender_id,
            24,
        )
        processed = clean(task.processed_bytes(), 18)
        size = clean(task.size(), 18)
        speed = clean(task.speed(), 18)
        eta = clean(task.eta(), 14)
        engine = clean(task.engine, 24)

        mode = getattr(task.listener, "mode", ()) or ()
        if not isinstance(mode, (tuple, list)):
            mode = (str(mode), "")
        in_mode = clean(mode[0] if mode else "—", 16)
        out_mode = clean(mode[1] if len(mode) > 1 else "—", 16)

        if getattr(task.listener, "is_leech", False):
            destination = "Telegram"
            if getattr(task.listener, "compress", False):
                destination += " · ZIP"
            elif getattr(task.listener, "extract", False):
                destination += " · Extract"
            elif getattr(task.listener, "as_doc", False):
                destination += " · Document"
            elif getattr(task.listener, "as_med", False):
                destination += " · Media"
        else:
            destination = out_mode.lstrip("#")
        destination = clean(destination, 24)

        msg += (
            f"\n<b>┏  {index:02d}  {task_name}</b>\n"
            f"<code>{clean(status_label(str(tstatus)), 18)}</code>  "
            f"<b>{pct:.1f}%</b>\n"
            f"<code>{progress_bar(pct)}</code>\n"
            f"📦 <b>{processed}</b> / {size}   •   ⚡ <b>{speed}</b>\n"
            f"⏱ ETA <b>{eta}</b>   •   Elapsed <b>{clean(elapsed, 12)}</b>\n"
            f"⚙️ {engine}   •   {in_mode} → {destination}\n"
            f"👤 {sender_name}  <code>({clean(sender_id, 16)})</code>\n"
        )

        gid = task.gid()[:8]
        if (
            tstatus in (
                MirrorStatus.STATUS_DOWNLOAD,
                MirrorStatus.STATUS_PAUSED,
                MirrorStatus.STATUS_QUEUEDL,
            )
            and getattr(task.listener, "is_qbit", False)
        ):
            buttons.data_button(
                f"📁 Select #{index}", f"taskact select {gid}",
                position="f_body", style=ButtonStyle.SUCCESS,
            )
        buttons.data_button(
            f"✖ Cancel #{index}", f"taskact cancel {gid}",
            position="f_body", style=ButtonStyle.DANGER,
        )
        msg += "━━━━━━━━━━━━━━━━━━━━\n"

    if tasks_no == 0:
        if status == "All":
            return None, None
        msg += f"\nNo active {clean(status, 24)} tasks.\n"

    if tasks_no > status_limit:
        msg += f"\n<code>PAGE {page_no}/{pages}</code>  •  <code>STEP {page_step}</code>\n"
        buttons.data_button("‹ Prev", f"status {sid} pre", position="header")
        buttons.data_button("Next ›", f"status {sid} nex", position="header")
        if tasks_no > 30:
            for step in [1, 2, 4, 6, 8, 10, 15]:
                buttons.data_button(step, f"status {sid} ps {step}", position="footer")

    if not is_user:
        buttons.data_button("📊 Overview", f"status {sid} ov", position="header", style=ButtonStyle.PRIMARY)

    if status != "All" or tasks_no > 20:
        for label, status_value in list(STATUSES.items()):
            if status_value != status:
                buttons.data_button(label, f"status {sid} st {status_value}")

    buttons.data_button("↻ Refresh", f"status {sid} ref", position="header", style=ButtonStyle.PRIMARY)
    free_space = disk_usage(DOWNLOAD_DIR).free
    msg += (
        "\n<b>SERVER</b>  "
        f"CPU <b>{cpu_percent()}%</b>  •  "
        f"RAM <b>{virtual_memory().percent}%</b>\n"
        f"💾 Free <b>{get_readable_file_size(free_space)}</b>  •  "
        f"⏳ Up <b>{get_readable_time(time() - bot_start_time)}</b>"
    )
    return msg, buttons.build_menu(8, fb_cols=2)
