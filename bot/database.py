from datetime import datetime
from typing import Any

import pymongo
from bson import ObjectId

import config


class Database:
    def __init__(self):
        self.client = pymongo.MongoClient(config.MONGODB_URI)
        self.db = self.client["chatgpt_telegram_bot"]

        self.user_collection = self.db["users"]
        self.chat_collection = self.db["chats"]
        self.role_collection = self.db["roles"]
        self.message_collection = self.db["chat_messages"]
        self.stat_collection = self.db["stats"]

    def check_if_user_exists(self, user_id: int, raise_exception: bool = False):
        if self.user_collection.count_documents({"_id": user_id}) > 0:
            return True
        else:
            if raise_exception:
                raise ValueError(f"User {user_id} does not exist")
            else:
                return False
        
    def add_new_user(
        self,
        user_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
        referred_by: int = None,
    ):
        data = {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,

            "last_interaction": datetime.now(),
            "first_seen": datetime.now(),

            "used_tokens": 0,
            "total_tokens": config.FREE_QUOTA,

            "referred_by": referred_by,
            "referred_count": 0,
        }

        query = {"_id": user_id}
        update = {
            "$setOnInsert": data,
        }

        self.user_collection.update_one(query, update, upsert=True)

    def upsert_chat(self, chat_id: int, chat_mode=config.DEFAULT_CHAT_MODE, clear_messages=True):
        default_data = {
            "first_seen": datetime.now(),
            "used_tokens": 0,
        }

        data = {
            "current_chat_mode": chat_mode,
            "last_interaction": datetime.now(),
        }

        if clear_messages:
            data["messages"] = []
            data["context"] = None
            data["context_src"] = None
        else:
            default_data["messages"] = []

        query = {"_id": chat_id}
        update = {
            "$set": data,
            "$setOnInsert": default_data,
        }

        self.chat_collection.update_one(query, update, upsert=True)

    def get_chat_attribute(self, chat_id: int, key: str):
        return self.get_chat_attributes(chat_id, [key])[0]
    
    def get_chat_attributes(self, chat_id: int, keys: list):
        doc = self.chat_collection.find_one({"_id": chat_id})

        ret = []
        for key in keys:
            ret.append(doc[key] if doc is not None and  key in doc else None)

        return ret
    
    def get_chat_rate_limit(self, chat_id: int):
        rate_limit_start, rate_count = self.get_chat_attributes(chat_id, ["rate_limit_start", "rate_count"])
        rate_count = rate_count if rate_count is not None else 0
        return rate_limit_start, rate_count
    
    def inc_chat_rate_count(self, chat_id: int):
        self.chat_collection.update_one({"_id": chat_id}, {"$inc": { 'rate_count': 1}})

    def set_chat_attribute(self, chat_id: int, field: str, value):
        self.set_chat_attributes(chat_id, {field: value})

    def set_chat_attributes(self, chat_id: int, fields: dict):
        self.chat_collection.update_one({"_id": chat_id}, {
            "$set": fields
        })
    
    def reset_chat_rate_limit(self, chat_id: int):
        self.chat_collection.update_one({"_id": chat_id}, {
            "$set": { 
                'rate_limit_start': datetime.now(),
                'rate_count': 1,
            }
        })

    def get_current_chat_mode(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'current_chat_mode') or config.DEFAULT_CHAT_MODE
    
    def set_current_model(self, chat_id: int, model: str):
        self.set_chat_attribute(chat_id, 'current_model', model)

    def set_chat_context(self, chat_id: int, context: str, context_src: str):
        self.set_chat_attributes(chat_id, {
            'context': context,
            'context_src': context_src,
            'messages': [],
        })

    def get_chat_context(self, chat_id: int):
        return self.get_chat_attributes(chat_id, ['context', 'context_src'])

    def get_current_model(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'current_model') or config.DEFAULT_MODEL
    
    def get_chat_voice_mode(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'voice_mode') or "text"
    
    def get_chat_timeout(self, chat_id: int):
        # timeout = self.get_chat_attribute(chat_id, 'timeout')
        # return timeout if timeout is not None else config.DEFAULT_CHAT_TIMEOUT
        return config.DEFAULT_CHAT_TIMEOUT
    
    def get_chat_lang(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'preferred_lang')

    def reset_chat(self, chat_id: int, chat_mode=None):
        self.upsert_chat(chat_id, chat_mode)

    def get_last_chat_time(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'last_interaction')
    
    def get_chat_messages(self, chat_id: int):
        return self.get_chat_attribute(chat_id, 'messages')

    def pop_chat_messages(self, chat_id: int):
        filter = {"_id": chat_id}
        
        self.chat_collection.update_one(
            filter,
            {"$pop": {"messages": 1}}
        )

    def update_chat_last_interaction(self, chat_id: int):
        filter = {"_id": chat_id}
        data = {
            "last_interaction": datetime.now()
        }

        self.chat_collection.update_one(
            filter,
            {
                "$set": data,
            }
        )

    def push_chat_messages(self, chat_id: int, new_dialog_message, max_message_count: int=-1):
        filter = {"_id": chat_id}
        data = {
            "last_interaction": datetime.now()
        }
        if max_message_count > 0:
            self.chat_collection.update_one(
                filter,
                {
                    "$set": data,
                    "$push": {"messages": {
                        "$each": [ new_dialog_message ],
                        "$slice": -max_message_count,
                    }}
                }
            )
        else:
            self.chat_collection.update_one(
                filter,
                {
                    "$set": data,
                    "$push": {"messages": new_dialog_message}
                }
            )

    def get_user_attribute(self, user_id: int, key: str):
        self.check_if_user_exists(user_id, raise_exception=True)
        return self.get_user_attributes(user_id, [key])[0]
    
    def get_user_attributes(self, user_id: int, keys: list):
        self.check_if_user_exists(user_id, raise_exception=True)
        user_dict = self.user_collection.find_one({"_id": user_id})

        ret = []
        for key in keys:
            if key not in user_dict:
                raise ValueError(f"User {user_id} does not have a value for {key}")
            ret.append(user_dict[key] if key in user_dict else None)

        return ret
    
    def get_user_preferred_language(self, user_id: int):
        try:
            return self.get_user_attribute(user_id, 'preferred_lang')
        except:
            return None
    
    def get_user_remaining_tokens(self, user_id: int):
        total_tokens, used_tokens = self.get_user_attributes(user_id, ['total_tokens', 'used_tokens'])
        return total_tokens - used_tokens

    def inc_user_referred_count(self, user_id: int):
        self.user_collection.update_one({"_id": user_id}, {"$inc": { 'referred_count': 1}})

    def inc_user_used_tokens(self, user_id: int, used_token: int):
        self.user_collection.update_one({"_id": user_id}, {"$inc": { 'used_tokens': used_token}})

    def is_user_generating_image(self, user_id: int):
        try:
            timeout = config.IMAGE_TIMEOUT
            last_imaging_time = self.get_user_attribute(user_id, 'last_imaging_time')
            diff = (datetime.now() - last_imaging_time).total_seconds()
            if last_imaging_time is None or diff > timeout:
                return False
            return timeout - diff
        except Exception as e:
            pass
        return False
    
    def mark_user_is_generating_image(self, user_id: int, generating: bool):
        self.set_user_attribute(user_id, 'last_imaging_time', datetime.now() if generating else None)

    def set_user_attribute(self, user_id: int, key: str, value: Any):
        self.check_if_user_exists(user_id, raise_exception=True)
        self.user_collection.update_one({"_id": user_id}, {"$set": {key: value}})

    def cache_chat_message(self, message):
        data = {
            '_id': ObjectId(),
            'message': message,
            "date": datetime.now(),
        }

        result = self.message_collection.insert_one(data)
        new_doc_id = result.inserted_id
        return new_doc_id
    
    def get_cached_message(self, id):
        doc = self.message_collection.find_one({ '_id': ObjectId(id) })
        return doc["message"] if doc else None
    
    def get_custom_roles(self, user_id: int):
        filter = {
            'user_id': user_id
        }

        projection = {
            'name': 1
        }

        return list(
            self.role_collection.find(filter, projection)
        )

    def get_role_prompt(self, chat_id, _id):
        filter = {
            '_id': _id,
            'user_id': chat_id,
        }

        projection = {
            'name': 1,
            'prompt': 1,
        }

        doc  = self.role_collection.find_one(filter, projection)
        return doc["prompt"] if doc else ""

    def inc_stats(self, field: str, amount: int = 1):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        default_data = { 
            "new_users": 0,
            "referral_new_users": 0,
        }

        if field not in default_data:
            raise ValueError(f"Invalid field `{field}` for stats")
        
        # prevent conflict field
        default_data.pop(field, None)

        inc = { field: amount }

        query = {"_id": today}
        update = {
            "$setOnInsert": default_data,
            "$inc": inc,
        }

        self.stat_collection.update_one(query, update, upsert=True)

