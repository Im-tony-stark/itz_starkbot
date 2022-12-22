from logging import getLogger, WARNING
from time import time
from threading import RLock, Lock

from bot import LOGGER, download_dict, download_dict_lock, config_dict, app, user_data
from bot.helper.ext_utils.bot_utils import get_readable_file_size
from ..status_utils.telegram_download_status import TelegramDownloadStatus
from bot.helper.telegram_helper.message_utils import sendMessage, sendStatusMessage, sendStatusMessage, sendFile
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.ext_utils.fs_utils import check_storage_threshold

global_lock = Lock()
GLOBAL_GID = set()
getLogger("pyrogram").setLevel(WARNING)


class TelegramDownloadHelper:

    def __init__(self, listener):
        self.name = ""
        self.size = 0
        self.progress = 0
        self.downloaded_bytes = 0
        self.__start_time = time()
        self.__listener = listener
        self.__id = ""
        self.__is_cancelled = False
        self.__resource_lock = RLock()

    @property
    def download_speed(self):
        with self.__resource_lock:
            return self.downloaded_bytes / (time() - self.__start_time)

    def __onDownloadStart(self, name, size, file_id):
        with global_lock:
            GLOBAL_GID.add(file_id)
        with self.__resource_lock:
            self.name = name
            self.size = size
            self.__id = file_id
        with download_dict_lock:
            download_dict[self.__listener.uid] = TelegramDownloadStatus(self, self.__listener, self.__id)
        self.__listener.onDownloadStart()
        sendStatusMessage(self.__listener.message, self.__listener.bot)

    def __onDownloadProgress(self, current, total):
        if self.__is_cancelled:
            app.stop_transmission()
            return
        with self.__resource_lock:
            self.downloaded_bytes = current
            try:
                self.progress = current / self.size * 100
            except ZeroDivisionError:
                pass

    def __onDownloadError(self, error):
        with global_lock:
            try:
                GLOBAL_GID.remove(self.__id)
            except:
                pass
        self.__listener.onDownloadError(error)

    def __onDownloadComplete(self):
        with global_lock:
            GLOBAL_GID.remove(self.__id)
        self.__listener.onDownloadComplete()

    def __download(self, message, path):
        try:
            download = message.download(file_name=path, progress=self.__onDownloadProgress)
            if self.__is_cancelled:
                self.__onDownloadError('Cancelled by user!')
                return
        except Exception as e:
            LOGGER.error(str(e))
            return self.__onDownloadError(str(e))
        if download is not None:
            self.__onDownloadComplete()
        elif not self.__is_cancelled:
            self.__onDownloadError('Internal error occurred')

    def add_download(self, message, path, filename):
        _dmsg = app.get_messages(message.chat.id, reply_to_message_ids=message.message_id)
        user_id = message.from_user.id
        media = _dmsg.document or _dmsg.video or _dmsg.audio or None
        if media is not None:
            with global_lock:
                # For avoiding locking the thread lock for long time unnecessarily
                download = media.file_unique_id not in GLOBAL_GID
            if filename == "":
                name = media.file_name
            else:
                name = filename
                path = path + name

            if download:
                size = media.file_size
                IS_USRTD = user_data[user_id].get('is_usertd') if user_id in user_data and user_data[user_id].get('is_usertd') else False
                if config_dict['STOP_DUPLICATE'] and not self.__listener.isLeech and IS_USRTD == False:
                    LOGGER.info('Checking File/Folder if already in Drive...')
                    smsg, button = GoogleDriveHelper().drive_list(name, True, True)
                    if smsg:
                        if config_dict['TELEGRAPH_STYLE']:
                            return sendMessage("File/Folder is already available in Drive.\nHere are the search results:", self.__listener.bot, self.__listener.message, button)
                        else:
                            return sendFile(self.__listener.bot, self.__listener.message, button, f"File/Folder is already available in Drive. Here are the search results:\n\n{smsg}")
                if config_dict['STORAGE_THRESHOLD']:
                    arch = any([self.__listener.isZip, self.__listener.extract])
                    acpt = check_storage_threshold(size, arch)
                    if not acpt:
                        msg = f'You must leave {STORAGE_THRESHOLD}GB free storage.'
                        msg += f'\nYour File/Folder size is {get_readable_file_size(size)}'
                        return sendMessage(msg, self.__listener.bot, self.__listener.message)
                self.__onDownloadStart(name, size, media.file_unique_id)
                LOGGER.info(f'Downloading Telegram file with id: {media.file_unique_id}')
                self.__download(_dmsg, path)
            else:
                self.__onDownloadError('File already being downloaded!')
        else:
            self.__onDownloadError('No document in the replied message')

    def cancel_download(self):
        LOGGER.info(f'Cancelling download on user request: {self.__id}')
        self.__is_cancelled = True
      
