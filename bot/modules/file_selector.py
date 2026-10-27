from html import escape
from aiofiles.os import remove, path as aiopath
from asyncio import iscoroutinefunction

from .. import (
    task_dict,
    task_dict_lock,
    user_data,
    LOGGER,
    sabnzbd_client,
)
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..core.torrent_manager import TorrentManager
from ..helper.ext_utils.bot_utils import (
    bt_selection_buttons,
    new_task,
)
from ..helper.ext_utils.status_utils import get_task_by_gid, MirrorStatus
from ..helper.ext_utils.task_manager import limit_checker
from ..helper.telegram_helper.button_build import ButtonMaker
from pyrogram.enums import ButtonStyle
from ..helper.telegram_helper.message_utils import (
    send_message,
    send_status_message,
    delete_message,
)


@new_task
async def select(_, message):
    user_id = message.from_user.id
    text = message.text
    if " " in text.split("\n")[0]:
        text = text.replace(" ", "_", 1)
    msg = text.split("_", maxsplit=1)
    gid = None
    task = None
    if len(msg) > 1:
        cmd_data = msg[1].split("@", maxsplit=1)
        if len(cmd_data) > 1 and cmd_data[1].strip() != TgClient.BNAME:
            return
        gid = cmd_data[0].split()[0]
        if gid:
            task = await get_task_by_gid(gid)
            if task is None:
                await send_message(message, f"GID: <code>{gid}</code> Not Found.")
                return
    if task is None and (reply_to_id := message.reply_to_message_id):
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "This is not an active task!")
            return
    if task is None:
        msg = (
            "Reply to an active /cmd which was used to start the download or add gid along with cmd\n\n"
            + "This command mainly for selection incase you decided to select files from already added torrent/nzb. "
            + "But you can always use /cmd with arg `s` to select files before download start."
        )
        await send_message(message, msg)
        return
    if (
        Config.OWNER_ID != user_id
        and task.listener.user_id != user_id
        and (user_id not in user_data or not user_data[user_id].get("SUDO"))
    ):
        await send_message(message, "This task is not for you!")
        return
    if not iscoroutinefunction(task.status):
        await send_message(message, "The task has finished the download stage!")
        return
    if await task.status() not in [
        MirrorStatus.STATUS_DOWNLOAD,
        MirrorStatus.STATUS_PAUSED,
        MirrorStatus.STATUS_QUEUEDL,
    ]:
        await send_message(
            message,
            "Task should be in download or pause (in case message was deleted by mistake) or queued status (in case you have used torrent or nzb file)!",
        )
        return
    if task.name().startswith("[METADATA]") or task.name().startswith("Trying"):
        await send_message(message, "Try after downloading metadata finished!")
        return

    try:
        await task.update()
        id_ = task.hash() if task.listener.is_qbit else task.gid()
        if not task.queued:
            if task.listener.is_nzb:
                await sabnzbd_client.pause_job(id_)
            elif task.listener.is_qbit:
                await TorrentManager.qbittorrent.torrents.stop([id_])
            else:
                try:
                    await TorrentManager.aria2.forcePause(id_)
                except Exception as e:
                    LOGGER.error(
                        f"{e} Error in pause, this mostly happens after abuse aria2"
                    )
        task.listener.select = True
    except Exception:
        await send_message(message, "This is not a bittorrent or sabnzbd task!")
        return

    SBUTTONS = bt_selection_buttons(id_, message)
    msg = "<b>Download Paused!</b>\n\n<i>Select your files &amp; press <b>Done Selecting</b> to start.</i>"
    await send_message(message, msg, SBUTTONS)


async def _show_qbit_file_page(query, task, gid, page=0):
    if not task.listener.is_qbit or TorrentManager.qbittorrent is None:
        await query.answer("Telegram file selection currently supports qBittorrent tasks.", show_alert=True)
        return
    try:
        files = await TorrentManager.qbittorrent.torrents.files(task.hash())
        if not files:
            await query.answer("Torrent file list is empty.", show_alert=True)
            return
        page_size = 8
        pages = max(1, (len(files) + page_size - 1) // page_size)
        page = min(max(0, int(page)), pages - 1)
        buttons = ButtonMaker()
        lines = [
            "⌬ <b>WZML-X · TELEGRAM FILE SELECTOR</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"📦 <b>{escape(str(task.name() or 'Torrent'))}</b>",
            f"Page <b>{page + 1}/{pages}</b> · Total files <b>{len(files)}</b>",
            "",
            "Tap a file to select or deselect it:",
        ]
        for item in files[page * page_size:(page + 1) * page_size]:
            idx = int(item.index)
            mark = "☑️" if int(item.priority) > 0 else "⬜"
            name = str(item.name).replace("\\", "/").rsplit("/", 1)[-1]
            label = f"{mark} {name}"
            if len(label) > 55:
                label = label[:52] + "..."
            buttons.data_button(label, f"sel tog {gid} {idx} {page}")
        if page > 0:
            buttons.data_button("⬅️ Previous", f"sel page {gid} {page - 1}", "footer")
        if page + 1 < pages:
            buttons.data_button("Next ➡️", f"sel page {gid} {page + 1}", "footer")
        hash_id = task.hash()
        buttons.data_button(
            "✅ Done Selecting", f"sel done {gid} {hash_id}",
            position="footer", style=ButtonStyle.SUCCESS,
        )
        buttons.data_button(
            "✖️ Cancel Task", f"sel cancel {gid}",
            position="footer", style=ButtonStyle.DANGER,
        )
        lines += ["", "Selected files download; deselected files are skipped."]
        await query.message.edit_text(
            "\\n".join(lines), reply_markup=buttons.build_menu(1),
            disable_web_page_preview=True,
        )
        await query.answer()
    except Exception as exc:
        LOGGER.exception("Telegram-native file selector failed")
        await query.answer(f"Selector error: {str(exc)[:120]}", show_alert=True)


async def _selection_limit_exceeded(task, message):
    mmsg = await limit_checker(task.listener)
    if not mmsg:
        return False
    await send_message(message, mmsg)
    await task.cancel_task()
    await delete_message(message)
    return True


@new_task
async def confirm_selection(_, query):
    user_id = query.from_user.id
    data = query.data.split()
    message = query.message
    task = await get_task_by_gid(data[2])
    if task is None:
        await query.answer("This task has been cancelled!", show_alert=True)
        await delete_message(message)
        return
    if user_id != task.listener.user_id:
        await query.answer("This task is not for you!", show_alert=True)
    elif data[1] in ("list", "page", "tog"):
        if not task.listener.is_qbit:
            await query.answer("Telegram file selector currently supports qBittorrent tasks.", show_alert=True)
            return
        try:
            hash_id = task.hash()
            files = await TorrentManager.qbittorrent.torrents.files(hash_id)
            if data[1] == "tog":
                idx = int(data[3])
                page = int(data[4]) if len(data) > 4 else 0
                item = next((x for x in files if int(x.index) == idx), None)
                if item is None:
                    await query.answer("File no longer exists.", show_alert=True)
                    return
                priority = 0 if int(item.priority) > 0 else 1
                await TorrentManager.qbittorrent.torrents.file_prio(
                    hash=hash_id, id=[idx], priority=priority
                )
                await _show_qbit_file_page(query, task, data[2], page)
                await query.answer("File deselected" if priority == 0 else "File selected")
            else:
                page = int(data[3]) if len(data) > 3 else 0
                await _show_qbit_file_page(query, task, data[2], page)
        except Exception as exc:
            LOGGER.exception("File selector callback failed")
            await query.answer(f"Selection error: {str(exc)[:120]}", show_alert=True)
    elif data[1] == "pin":
        await query.answer(data[3], show_alert=True)
    elif data[1] == "done":
        await query.answer()
        id_ = data[3]
        task.listener.files_selected = True
        if hasattr(task, "seeding"):
            if task.listener.is_qbit:
                tor_info = (
                    await TorrentManager.qbittorrent.torrents.info(hashes=[id_])
                )[0]
                path = tor_info.content_path.rsplit("/", 1)[0]
                res = await TorrentManager.qbittorrent.torrents.files(id_)
                for f in res:
                    if f.priority == 0:
                        f_paths = [f"{path}/{f.name}", f"{path}/{f.name}.!qB"]
                        for f_path in f_paths:
                            if await aiopath.exists(f_path):
                                try:
                                    await remove(f_path)
                                except Exception:
                                    pass
                tor_info = (
                    await TorrentManager.qbittorrent.torrents.info(hashes=[id_])
                )[0]
                task.listener.size = tor_info.size
                if await _selection_limit_exceeded(task, message):
                    return
                if not task.queued:
                    await TorrentManager.qbittorrent.torrents.start([id_])
            else:
                res = await TorrentManager.aria2.getFiles(id_)
                for f in res:
                    if f["selected"] == "false" and await aiopath.exists(f["path"]):
                        try:
                            await remove(f["path"])
                        except Exception:
                            pass
                task.listener.size = sum(
                    int(f["length"]) for f in res if f["selected"] == "true"
                )
                if await _selection_limit_exceeded(task, message):
                    return
                if not task.queued:
                    try:
                        await TorrentManager.aria2.unpause(id_)
                    except Exception as e:
                        LOGGER.error(
                            f"{e} Error in resume, this mostly happens after abuse aria2. Try to use select cmd again!"
                        )
        elif task.listener.is_nzb:
            if not task.queued:
                await sabnzbd_client.resume_job(id_)
        await send_status_message(message)
        await delete_message(message)
    else:
        await delete_message(message)
        await task.cancel_task()
