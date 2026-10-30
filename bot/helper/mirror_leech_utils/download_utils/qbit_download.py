from aiofiles.os import remove, path as aiopath
from aiofiles import open as aiopen
from asyncio import sleep, TimeoutError
from base64 import b32decode
from hashlib import sha1
from re import search as re_search
from aioqbt.api import AddFormBuilder
from aioqbt.exc import AQError
from aiohttp.client_exceptions import ClientError

from .... import (
    task_dict,
    task_dict_lock,
    LOGGER,
    qb_torrents,
)
from ....core.config_manager import Config
from ....core.torrent_manager import TorrentManager
from ...ext_utils.bot_utils import bt_selection_buttons
from ...ext_utils.task_manager import check_running_tasks
from ...listeners.qbit_listener import on_download_start
from ...mirror_leech_utils.status_utils.qbit_status import QbittorrentStatus
from ...telegram_helper.message_utils import (
    send_message,
    delete_message,
    send_status_message,
)

"""
Only v1 torrents
#from hashlib import sha1
#from base64 import b16encode, b32decode
#from bencoding import bencode, bdecode
#from re import search as re_search
def _get_hash_magnet(mgt: str):
    hash_ = re_search(r'(?<=xt=urn:btih:)[a-zA-Z0-9]+', mgt).group(0)
    if len(hash_) == 32:
        hash_ = b16encode(b32decode(hash_.upper())).decode()
    return hash_

def _get_hash_file(fpath):
    with open(fpath, "rb") as f:
        decodedDict = bdecode(f.read())
        return sha1(bencode(decodedDict[b'info'])).hexdigest()
"""



def _bencode_string(data, pos):
    colon = data.index(b":", pos)
    size = int(data[pos:colon])
    start = colon + 1
    end = start + size
    return data[start:end], end


def _bencode_skip(data, pos):
    token = data[pos:pos + 1]
    if token.isdigit():
        return _bencode_string(data, pos)[1]
    if token == b"i":
        return data.index(b"e", pos) + 1
    if token in (b"l", b"d"):
        pos += 1
        while data[pos:pos + 1] != b"e":
            if token == b"d":
                _, pos = _bencode_string(data, pos)
            pos = _bencode_skip(data, pos)
        return pos + 1
    raise ValueError("Invalid bencoded torrent data")


def _torrent_info_hash(link):
    match = re_search(r"(?:^|[?&])xt=urn:btih:([A-Za-z0-9]+)", link or "", flags=0)
    if match:
        value = match.group(1)
        if len(value) == 40:
            return value.lower()
        if len(value) == 32:
            try:
                return b32decode(value.upper()).hex()
            except ValueError:
                return None

    try:
        with open(link, "rb") as torrent_file:
            data = torrent_file.read()
        if not data.startswith(b"d"):
            return None
        pos = 1
        while data[pos:pos + 1] != b"e":
            key, pos = _bencode_string(data, pos)
            start = pos
            end = _bencode_skip(data, pos)
            if key == b"info":
                return sha1(data[start:end]).hexdigest()
            pos = end
    except (OSError, ValueError, IndexError):
        return None
    return None


async def add_qb_torrent(listener, path, ratio, seed_time):
    if Config.DISABLE_TORRENTS:
        await listener.on_download_error("Torrents are disabled in the configuration.")
        return
    try:
        form = AddFormBuilder.with_client(TorrentManager.qbittorrent)
        if await aiopath.exists(listener.link):
            async with aiopen(listener.link, "rb") as f:
                data = await f.read()
                form = form.include_file(data)
        else:
            form = form.include_url(listener.link)
        form = form.savepath(path).tags([f"{listener.mid}"])
        add_to_queue, event = await check_running_tasks(listener)
        if add_to_queue:
            form = form.stopped(add_to_queue)
        if ratio:
            form = form.ratio_limit(ratio)
        if seed_time:
            form = form.seeding_time_limit(int(seed_time))
        try:
            await TorrentManager.qbittorrent.torrents.add(form.build())
        except (ClientError, TimeoutError, Exception, AQError) as e:
            status = getattr(e, "status", None)
            if status is None:
                status = getattr(getattr(e, "response", None), "status", None)
            if status == 409 or "status=409" in str(e) or "409" in str(e):
                existing = []
                info_hash = _torrent_info_hash(listener.link)
                if info_hash:
                    try:
                        existing = await TorrentManager.qbittorrent.torrents.info(
                            hashes=[info_hash]
                        )
                    except Exception as lookup_error:
                        LOGGER.warning(
                            "Could not inspect existing qBittorrent torrent (%s)",
                            type(lookup_error).__name__,
                        )
                if existing:
                    existing_torrent = existing[0]
                    progress = float(getattr(existing_torrent, "progress", 0) or 0) * 100
                    error_msg = (
                        "This torrent is already present in qBittorrent. "
                        f"Existing torrent: {existing_torrent.name} "
                        f"({progress:.1f}% complete). "
                        "Its existing download and files were left untouched. "
                        "Check the qBittorrent status/Web UI instead of adding it again."
                    )
                    LOGGER.info(
                        "Duplicate qBittorrent torrent detected: hash=%s name=%s progress=%.1f%%",
                        info_hash,
                        existing_torrent.name,
                        progress,
                    )
                else:
                    error_msg = (
                        "qBittorrent rejected this add request with HTTP 409 Conflict. "
                        "The torrent may already exist. No existing torrent or data was deleted. "
                        "Check the qBittorrent Web UI before retrying."
                    )
            else:
                error_msg = (
                    f"qBittorrent could not add this input. Use a valid magnet or direct "
                    f".torrent URL/file. API error: {e}"
                )
            LOGGER.error("%s. Task message ID: %s", error_msg, listener.mid)
            await listener.on_download_error(error_msg)
            return
        tor_info = await TorrentManager.qbittorrent.torrents.info(tag=f"{listener.mid}")
        if len(tor_info) == 0:
            while True:
                if add_to_queue and event.is_set():
                    add_to_queue = False
                tor_info = await TorrentManager.qbittorrent.torrents.info(
                    tag=f"{listener.mid}"
                )
                if len(tor_info) > 0:
                    break
                await sleep(1)
        tor_info = tor_info[0]
        listener.name = tor_info.name
        ext_hash = tor_info.hash

        async with task_dict_lock:
            task_dict[listener.mid] = QbittorrentStatus(listener, queued=add_to_queue)
        await on_download_start(f"{listener.mid}")

        if add_to_queue:
            LOGGER.info(f"Added to Queue/Download: {tor_info.name} - Hash: {ext_hash}")
        else:
            LOGGER.info(f"QbitDownload started: {tor_info.name} - Hash: {ext_hash}")

        await listener.on_download_start()

        if listener.select:
            if listener.link.startswith("magnet:"):
                metamsg = "<b>Fetching Metadata...</b>\n\n<i>Hold tight! You can select files once it's done.</i>\n\n<b>💡 Tip:</b> Use <code>.torrent</code> file instead to skip this wait."
                meta = await send_message(listener.message, metamsg)
                while True:
                    tor_info = await TorrentManager.qbittorrent.torrents.info(
                        tag=f"{listener.mid}"
                    )
                    if len(tor_info) == 0:
                        await delete_message(meta)
                        return
                    try:
                        tor_info = tor_info[0]
                        if tor_info.state not in [
                            "metaDL",
                            "checkingResumeData",
                            "stoppedDL",
                        ]:
                            await delete_message(meta)
                            break
                    except Exception:
                        await delete_message(meta)
                        return

            ext_hash = tor_info.hash
            if not add_to_queue:
                await TorrentManager.qbittorrent.torrents.stop([ext_hash])
            SBUTTONS = bt_selection_buttons(ext_hash, listener.message)
            msg = "<b>Download Paused!</b>\n\n<i>Select your files &amp; press <b>Done Selecting</b> to start !</i>"
            await send_message(listener.message, msg, SBUTTONS)
        elif listener.multi <= 1 and not listener.is_rss:
            await send_status_message(listener.message)

        if event is not None:
            if not event.is_set():
                await event.wait()
                if listener.is_cancelled:
                    return
                async with task_dict_lock:
                    task_dict[listener.mid].queued = False
                LOGGER.info(
                    f"Start Queued Download from Qbittorrent: {tor_info.name} - Hash: {ext_hash}"
                )
            await on_download_start(f"{listener.mid}")
            await TorrentManager.qbittorrent.torrents.start([ext_hash])
    except (ClientError, TimeoutError, Exception, AQError) as e:
        if f"{listener.mid}" in qb_torrents:
            del qb_torrents[f"{listener.mid}"]
        await listener.on_download_error(f"{e}")
    finally:
        if await aiopath.exists(listener.link):
            await remove(listener.link)
