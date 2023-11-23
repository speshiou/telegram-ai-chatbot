import re
import aiohttp
import functools
from urllib.parse import urlparse
from database import Database
import config
from telegram import PhotoSize
from typing import Tuple

async def http_post(url, data, result_type="json", headers=None):
    session_args = {}
    if headers is not None:
        session_args["headers"] = headers
    async with aiohttp.ClientSession(**session_args) as session:
        async with session.post(url, data=data) as response:
            if result_type == "json":
                return await response.json()
            else:
                return await response.text()

def is_uri(s):
    try:
        result = urlparse(s)
        return all([result.scheme, result.netloc])
    except:
        return False

def is_youtube_url(url: str):
    domain = urlparse(url).netloc
    return domain.endswith("youtube.com") or domain.endswith("youtu.be")

def parse_youtube_id(url: str)->str:
   data = re.findall(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
   if data:
       return data[0]
   return ""

def get_available_chat_modes(db: Database, chat_id: int):
    if chat_id > 0:
        # private chat
        roles = db.get_custom_roles(chat_id)
        def reduce(acc, current_role):
            id = str(current_role["_id"])
            current_role["id"] = id
            return {**acc, id: current_role}
        roles_dict = functools.reduce(reduce, roles, {})
        chat_modes = {**config.CHAT_MODES, **roles_dict}
    else:
        chat_modes = config.CHAT_MODES
    return chat_modes

def get_current_chat_mode(db: Database, chat_id: int, fallback: bool = True):
    chat_mode_id = db.get_current_chat_mode(chat_id)
    chat_modes = get_available_chat_modes(db, chat_id)
    if chat_mode_id in chat_modes:
        return chat_modes[chat_mode_id]
    
    if fallback:
        return config.CHAT_MODES[config.DEFAULT_CHAT_MODE]
    return None

# Telegram always provides various sizes of single photos.
def get_original_photo(photo: Tuple[PhotoSize]):
    largest_photo = photo[0]
    for photo_data in photo:
        if largest_photo.file_size < photo_data.file_size:
            largest_photo = photo_data
    return largest_photo