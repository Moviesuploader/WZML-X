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
    """Render the detailed multi-task dashboard with task-name headings."""
    tasks = await get_specific_tasks(status, sid if is_user else None)
    status_limit = max(1, int(Config.STATUS_LIMIT or 10))
    tasks_no = len(tasks)
    pages = (max(tasks_no, 1) + status_limit - 1) // status_limit
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
        status_dict[sid]["page_no"] = page_no
    elif page_no < 1:
        page_no = max(1, pages - (abs(page_no) % pages))
        status_dict[sid]["page_no"] = page_no
    start_position = (page_no - 1) * status_limit
    buttons = ButtonMaker()
    bot_limit = max(0, int(Config.BOT_MAX_TASKS or 0))
    msg = (
        "<b>Tasks Dashboard</b>\n"
        f"<b>Tasks:</b> {tasks_no}/{bot_limit or '∞'} · <b>Per page:</b> {status_limit}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    def progress_dots(value, width=12):
        try:
            numeric = float(str(value).strip().rstrip("%"))
        except (TypeError, ValueError):
            numeric = 0.0
        filled = min(width, max(0, round(min(100.0, max(0.0, numeric)) / 100 * width)))
        return "■" * filled + "□" * (width - filled)

    def status_label(value):
        labels = {
            MirrorStatus.STATUS_UPLOAD: "Upload",
            MirrorStatus.STATUS_DOWNLOAD: "Download",
            MirrorStatus.STATUS_QUEUEDL: "Queued",
            MirrorStatus.STATUS_QUEUEUP: "Queued Upload",
            MirrorStatus.STATUS_PAUSED: "Paused",
            MirrorStatus.STATUS_CLONE: "Clone",
            MirrorStatus.STATUS_EXTRACT: "Extract",
            MirrorStatus.STATUS_ARCHIVE: "Archive",
            MirrorStatus.STATUS_SPLIT: "Split",
            MirrorStatus.STATUS_CONVERT: "Convert",
            MirrorStatus.STATUS_FFMPEG: "FFmpeg",
            MirrorStatus.STATUS_YT: "YouTube",
            MirrorStatus.STATUS_CHECK: "Checking",
            MirrorStatus.STATUS_SEED: "Seeding",
        }
        return labels.get(value, str(value))

    selected_tasks = tasks[start_position : status_limit + start_position]
    from ..telegram_helper.bot_commands import BotCommands

    for index, task in enumerate(selected_tasks, start=start_position + 1):
        if status != "All":
            tstatus = status
        elif iscoroutinefunction(task.status):
            tstatus = await task.status()
        else:
            tstatus = task.status()
        try:
            task_name = escape(str(task.name() or "Resolving task…"))
        except Exception:
            task_name = "Active task"
        try:
            elapsed = get_readable_time(max(0, time() - task.listener.message.date.timestamp()))
        except Exception:
            elapsed = "—"
        sender = getattr(task.listener.message, "from_user", None)
        sender_id = getattr(sender, "id", getattr(task.listener, "user_id", "—"))
        sender_name = escape(str(getattr(sender, "first_name", None) or getattr(sender, "username", None) or sender_id))
        raw_progress = task.progress()
        try:
            numeric_progress = float(str(raw_progress).strip().rstrip("%"))
        except (TypeError, ValueError):
            numeric_progress = 0.0
        progress_text = escape(str(raw_progress))
        processed = escape(str(task.processed_bytes()))
        size = escape(str(task.size()))
        speed = escape(str(task.speed()))
        eta = escape(str(task.eta()))
        engine = escape(str(task.engine))
        mode = getattr(task.listener, "mode", ()) or ()
        if not isinstance(mode, (tuple, list)):
            mode = (str(mode), "")
        in_mode = escape(str(mode[0] if mode else "—"))
        out_mode = escape(str(mode[1] if len(mode) > 1 else "—"))
        if getattr(task.listener, "is_leech", False):
            upload_label = "Telegram"
            if getattr(task.listener, "compress", False):
                upload_label += " as Zip"
            elif getattr(task.listener, "extract", False):
                upload_label += " after Extract"
            elif getattr(task.listener, "as_doc", False):
                upload_label += " as Document"
            elif getattr(task.listener, "as_med", False):
                upload_label += " as Media"
        else:
            upload_label = out_mode.lstrip("#")
        upload_label = escape(upload_label)
        msg += (
            f"<b>{index}. {task_name}</b>\n"
            f"╭ <i>{escape(status_label(str(tstatus)))}</i>\n"
            f"├ {progress_dots(numeric_progress)} {progress_text}\n"
            f"├ <b>Processed:</b> {processed}\n"
            f"├ <b>Size:</b> {size}\n"
            f"├ <b>Speed:</b> {speed}\n"
            f"├ <b>ETA:</b> {eta}\n"
            f"├ <b>Elapsed:</b> {escape(elapsed)}\n"
            f"├ <b>Upload:</b> {upload_label}\n"
            f"├ <b>Engine:</b> {engine}\n"
            f"├ <b>User:</b> {sender_name} ({escape(str(sender_id))})\n"
            f"├ <b>In Mode:</b> {in_mode}\n"
            f"├ <b>Out Mode:</b> {out_mode}\n"
        )
        if tstatus in (MirrorStatus.STATUS_DOWNLOAD, MirrorStatus.STATUS_PAUSED, MirrorStatus.STATUS_QUEUEDL) and (
            task.listener.is_torrent or task.listener.is_qbit or task.listener.is_nzb
        ):
            msg += f"├ <b>Select:</b> /{BotCommands.SelectCommand[1]}_{task.gid()[:8]}\n"
        msg += f"╰ <b>Cancel:</b> /{BotCommands.CancelTaskCommand[1]}_{task.gid()[:8]}\n\n"

    if tasks_no == 0:
        if status == "All":
            return None, None
        msg += f"No active {escape(status)} tasks.\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n<b>Bot Stats</b>\n"
    if not is_user:
        buttons.data_button("📜 TStats", f"status {sid} ov", position="header", style=ButtonStyle.PRIMARY)
    if tasks_no > status_limit:
        msg += f"<b>Page:</b> {page_no}/{pages} | <b>Tasks:</b> {tasks_no} | <b>Step:</b> {page_step}\n"
        buttons.data_button("<<", f"status {sid} pre", position="header")
        buttons.data_button(">>", f"status {sid} nex", position="header")
        if tasks_no > 30:
            for step in [1, 2, 4, 6, 8, 10, 15]:
                buttons.data_button(step, f"status {sid} ps {step}", position="footer")
    if status != "All" or tasks_no > 20:
        for label, status_value in list(STATUSES.items()):
            if status_value != status:
                buttons.data_button(label, f"status {sid} st {status_value}")
    buttons.data_button("♻️ Refresh", f"status {sid} ref", position="header", style=ButtonStyle.PRIMARY)
    free_space = disk_usage(DOWNLOAD_DIR).free
    msg += f"CPU: {cpu_percent()}% | FREE: {get_readable_file_size(free_space)}\nRAM: {virtual_memory().percent}% | UPTIME: {get_readable_time(time() - bot_start_time)}"
    return msg, buttons.build_menu(8)
