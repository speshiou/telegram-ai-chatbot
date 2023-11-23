from urllib.parse import urlencode, parse_qs

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import config
import gen_image_utils
import i18n
from database import Database
import helper

def get_arg(path: str, key: str):
    if "?" not in path:
        return None
    query = path.split("?")[-1]
    query_params = parse_qs(query)
    return query_params[key][0] if key in query_params else None

def add_arg(path: str, key: str, value: str):
    base_path = path
    if "?" in path:
        base_path, query = path.split("?")
        query_params = parse_qs(query)
        # convert query params to a flat dictionary with string values
        query_params = {k:v[0] for k,v in query_params.items()}
    else:
        base_path = path
        query_params = {}
    query_params[key] = value
    query_string = urlencode(query_params)
    return base_path + "?" + query_string

def get_args(path: str):
    if "?" in path:
        base_path, query = path.split("?")
        query_params = parse_qs(query)
        # convert query params to a flat dictionary with string values
        query_params = {k:v[0] for k,v in query_params.items()}
    else:
        query_params = {}
    return query_params

def add_args(path: str, args: dict):
    base_path = path
    if "?" in path:
        base_path, query = path.split("?")
        query_params = parse_qs(query)
        # convert query params to a flat dictionary with string values
        query_params = {k:v[0] for k,v in query_params.items()}
    else:
        base_path = path
        query_params = {}
    query_params = {
        **query_params,
        **args,
    }
    query_string = urlencode(query_params)
    return base_path + "?" + query_string

def _chat_mode_features(chat_mode=None):
    if chat_mode is None:
        return ["🗣", "🌱", "⚡"]
    bonus = []
    role = config.CHAT_MODES[chat_mode]
    if chat_mode in config.TTS_MODELS:
        bonus.append("🗣")
    if "disable_history" in role:
        bonus.append("🌱")
    if chat_mode in config.DEFAULT_CHAT_MODES:
        bonus.append("⚡")
    return bonus

def _chat_mode_options(_):
    options = []
    for chat_mode, role in config.CHAT_MODES.items():
        label = "{} {}".format(role["icon"], _(role["name"]))
        features = _chat_mode_features(chat_mode)

        if len(features) > 0:
            label += " ({})".format("".join(features))
        options.append({ 
            "label": label, 
            "value": chat_mode, 
            "callback": "set_chat_mode|" + chat_mode 
        })
    return options

def _model_options(_):
    options = []
    for key, model in config.DEFAULT_MODELS.items():
        label = model["name"]

        options.append({ 
            "label": label, 
            "value": key, 
            "callback": "set_model|" + key 
        })
    return options

def chat_mode_tips(chat_mode, _):
    features = _chat_mode_features(chat_mode)
    tips = []
    for feature in features:
        tip = None
        if feature == "⚡":
            example = "/dictionary flower"
            if chat_mode == "chatgpt":
                example = "/chatgpt what can you do?"
            elif chat_mode == "proofreader":
                example = "/proofreader any text"
            tip = _("Instant access, ex: {}").format(example)
        elif feature == "🌱":
            tip = _("Low cost, no chat history")
        elif feature == "🗣":
            tip = _("Voice messages (English), check /settings")
        if tip is not None:
            tips.append(feature + " " + tip)

    if len(tips) == 0:
        return ""
    text = build_tips(tips, _, hide_bullet=True, title=_("<b>Features</b>"))
    if chat_mode is not None and "⚡" in features:
        text += "\n\n"
        text += build_tips([
            _("desktop: type /{}, then press TAB key").format(chat_mode[0]),
            _("mobile: type /{}, then long press the command").format(chat_mode[0]),
        ], _, title=_("<b>How to do instant access?</b>"))
    return text

def load_settings(db: Database, chat_id: int, _):
    current_chat_mode = helper.get_current_chat_mode(db, chat_id)
    current_model = db.get_current_model(chat_id)
    voice_mode = db.get_chat_voice_mode(chat_id)
    timeout = db.get_chat_timeout(chat_id)
    lang = db.get_chat_lang(chat_id)
    if lang:
        lang = lang.lower()

    settings = {
        "current_model": {
            "icon": "💬",
            "name": _("AI Model"),
            "desc": chat_mode_tips(None, _) + "\n\n" + build_tips([
                _("🤥 Some characters are made up! Don't take them too seriously."),
                _("🤩 More roles are coming soon. Stay tuned!"),
            ], _, hide_bullet=True),
            "hide_tips_bullet": True,
            "value": current_model,
            "disable_check_mark": True,
            "num_keyboard_cols": 2,
            "options": _model_options(_),
        },
        "current_chat_mode": {
            "icon": "💬",
            "name": _("Chat Mode"),
            "desc": chat_mode_tips(None, _) + "\n\n" + build_tips([
                _("🤥 Some characters are made up! Don't take them too seriously."),
                _("🤩 More roles are coming soon. Stay tuned!"),
            ], _, hide_bullet=True),
            "hide_tips_bullet": True,
            "value": current_chat_mode,
            "disable_check_mark": True,
            "num_keyboard_cols": 2,
            "options": _chat_mode_options(_)
        },
        # "voice_mode": {
        #     "icon": "🗣",
        #     "name": _("Chat Voice"),
        #     "desc": _("This setting only applies to the character with 🗣 icon, see /role.")
        #             + "\n\n"
        #             + _("<b>Price:</b> {} tokens per second").format(config.COQUI_TOKENS)
        #             + "\n\n"
        #             + build_tips([
        #                 _("English only, please speak English to characters once you enable voice messages"),
        #                 _("It costs roughly 500,000 tokens to have a 30-minute voice chat."),
        #                 _("The maximum length of the text is 600 characters."),
        #             ], _),
        #     "value": voice_mode,
        #     "options": [
        #         {
        #             "label": _("Text Only"),
        #             "value": "text",
        #         },
        #         # {
        #         #     "label": _("Voice Only"),
        #         #     "value": "voice",
        #         # },
        #         {
        #             "label": _("Text and Voice"),
        #             "value": "text_and_voice",
        #         },
        #     ]
        # },
        # "timeout": {
        #     "icon": "⏳",
        #     "name": _("Chat Timeout"),
        #     "desc": _("Setting a proper timeout can help reduce token consumption. When a timeout occurs, the chatbot will not generate an answer based on previous chat history.\n\nYou can also use /reset to clear chat history manually."),
        #     "value": timeout,
        #     "options": [
        #         {
        #             "label": _("1 Hour"),
        #             "value": 60 * 60 * 1,
        #         },
        #         {
        #             "label": _("6 Hours"),
        #             "value": 60 * 60 * 6,
        #         },
        #         {
        #             "label": _("12 Hours"),
        #             "value": 60 * 60 * 12,
        #         },
        #         {
        #             "label": _("24 Hours"),
        #             "value": 60 * 60 * 24,
        #         },
        #         {
        #             "label": _("Never"),
        #             "value": 0,
        #         },
        #     ]
        # },
        "lang": {
            "icon": "🌐",
            "name": _("Language"),
            "desc": _("This setting won't effect the answers from the chatbot.\n\nPlease feedback to @{} if there is any translation errors.").format(config.SUPPORT_USER_NAME),
            "value": lang,
            "options": [
                {
                    "label": "English",
                    "value": "en",
                },
                {
                    "label": "Español",
                    "value": "es",
                },
                {
                    "label": "Français",
                    "value": "fr",
                },
                {
                    "label": "简体中文",
                    "value": "zh_CN",
                },
                {
                    "label": "繁體中文",
                    "value": "zh_TW",
                },
                {
                    "label": _("Not specify"),
                    "value": None,
                },
            ]
        },
    }

    return settings

def build_tips(tips, _, title=None, hide_bullet=False):
    bullet = "- " if not hide_bullet else ""

    if title is None:
        title = _("<b>Tips</b>")

    text = title
    text += "\n"
    text += "\n".join(map(lambda tip: bullet + _(tip), tips))
    return text

def build_keyboard_rows(buttons, num_keyboard_cols):
    keyboard_rows = []
    num_buttons = len(buttons)
    for i in range(0, num_buttons, num_keyboard_cols):
        end = min(i + num_keyboard_cols, num_buttons)
        keyboard_rows.append(buttons[i:end])
    return keyboard_rows

def _menu_page(path: str, menu_data, _):
    path = path if path is not None else menu_data["key"]
    query = None
    if "?" in path:
        path, query = path.split("?")

    segs = path.split(">") if path else []
    data = None
    path_segs = []

    # find deepest menu page
    for key in segs:
        if data is None:
            # first layer
            data = menu_data
        elif "options" in data and isinstance(data["options"], dict):
            if key in data["options"]:
                data = data["options"][key]
            else:
                break
        else:
            break
        menu_page_key = key
        path_segs.append(key)

    keyboard = []
    num_keyboard_cols = data["num_keyboard_cols"] if "num_keyboard_cols" in data else 1
    reply_markup = None

    title_format = "<b>{}</b>"
    text = title_format.format(data["name"])
    if "icon" in data:
        text = "{} {}".format(data["icon"], text)
    if "desc" in data:
        text += "\n\n"
        text += data["desc"]

    if "options" in data:
        if isinstance(data["options"], dict):
            options = data["options"]
            for key, option in options.items():
                args = {}
                callback_data = None
                if "web_app" in option:
                    args["web_app"] = WebAppInfo(url=option["web_app"])
                elif "callback" in option:
                    callback_data = option["callback"]
                else:
                    option_path_segs = path_segs + [key]
                    callback_data = ">".join(option_path_segs)
                    if query:
                        callback_data += "?" + query
                if "args" in data:
                    callback_data = add_args(callback_data, data["args"])
                if callback_data is not None:
                    args["callback_data"] = callback_data

                label = option["name"]
                if "icon" in option:
                    label = "{} {}".format(option["icon"], label)
                
                keyboard.append(InlineKeyboardButton(label, **args))
        else:
            # array
            for option in data["options"]:
                label = option["label"]
                if "disable_check_mark" not in data and "value" in data and data["value"] == option["value"]:
                    label = "✅ " + label

                if "callback" in option:
                    callback_data = option["callback"]
                else:
                    callback_value = option["value"] if option["value"] is not None else ""
                    # back to previous menu after selecting an option
                    base_path = ">".join(path_segs[:-1])
                    callback_data = f"{base_path}|{menu_page_key}|{callback_value}"
                    if query:
                        callback_data += "?" + query
                if "args" in data:
                    callback_data = add_args(callback_data, data["args"])
                keyboard.append(InlineKeyboardButton(label, callback_data=callback_data))

    keyboard_rows = []
    if len(keyboard) > 0:
        keyboard_rows = build_keyboard_rows(keyboard, num_keyboard_cols=num_keyboard_cols)
    if len(segs) > 1:
        callback_data = ">".join(path_segs[:-1])
        if query:
            callback_data += "?" + query
        keyboard_rows.append([InlineKeyboardButton("< " + _("Back"), callback_data=callback_data)])
    else:
        keyboard_rows.append([InlineKeyboardButton(_("Close"), callback_data="close")])
    if len(keyboard_rows) > 0:
        reply_markup = InlineKeyboardMarkup(keyboard_rows)
    return text, reply_markup

def settings(db: Database, chat_id: int, _, data: str = None):
    if data and "|" in data:
        # TODO: move to update handle function
        # save settings
        path, setting_key, value = data.split("|")
        if not value:
            value = None
        elif value.isnumeric():
            value = int(value)
        settings = load_settings(db, chat_id, _)
        if setting_key in settings:
            db.set_chat_attribute(chat_id, setting_key, value)
        if setting_key == 'lang':
            _ = i18n.get_text_func(value)
    else:
        path = data

    settings = load_settings(db, chat_id, _)

    info = []
    for key, setting in settings.items():
        value = setting["value"]
        label = value
        if key == "current_chat_mode":
            label = value["name"]
        else:
            for option in setting["options"]:
                if value == option["value"]:
                    label = option["label"]

        info.append("<b>{}</b>: {}".format(setting["name"], label))
    desc = "\n".join(info)

    options = {}
    if chat_id > 0:
        options["settings"] = {
            "icon": "⚙️",
            "name": _("Configure"),
            "web_app": config.WEB_APP_URL,
        }

    options["about"] = {
        "icon": "ℹ️",
        "name": _("About"),
        "callback": "about",
    }

    menu_data = {
        "icon": "⚙️",
        "name": _("Settings"),
        "key": "settings",
        "desc": desc,
        "options": options,
        "num_keyboard_cols": 1,
    }

    return _menu_page(path, menu_data, _)

def about(_):
    text = _("Hi! My name is Nexia, an AI chatbot powered by OpenAI's GPT, DALL·E and Stable Diffusion models.")
    text += "\n\n"
    text += _("<b>What can I do for you?</b>\n")
    text += _("✉️ Writing\n")
    text += _("🌎 Translate\n")
    text += _("🤔 Provide ideas and solve problems\n")
    text += _("💻 Programming and debugging\n")
    text += "\n"
    text += _("<b>More than ChatGPT</b>\n")
    text += _("🧙‍♀️ Create custom versions of ChatGPT\n")
    text += _("🎙 Support voice messages\n")
    text += _("✍️ Proofreading (/proofreader)\n")
    text += _("📔 Dictionary (/dictionary)\n")
    text += _("🌐 Summarize the content of websites") + "\n"
    text += _("🎬 Summarize Youtube videos (up to 20 minutes long)") + "\n"
    text += _("👨‍🎨 Generate images (/image)\n")
    text += _("👥 Group chat - add @{} to a group chat, then use /chatgpt to start.\n").format(config.TELEGRAM_BOT_NAME)
    text += "\n\n"
    text += _("""By using this chatbot, you agree to our <a href="{}">terms of service</a> and <a href="{}">privacy policy</a>.""").format("https://tgchat.co/terms-of-service", "https://tgchat.co/privacy-policy")

    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ " + _("Settings"), web_app=WebAppInfo(url=config.WEB_APP_URL)),
            InlineKeyboardButton("💡 " + _("Learn"), url="https://t.me/ChatGPT_Prompts_Lab"),
        ],
        [
            InlineKeyboardButton("❓ " + _("FAQ"), url="https://tgchat.co/faq"),
            InlineKeyboardButton("✉️ " + _("Feedback"), url="https://t.me/{}".format(config.SUPPORT_USER_NAME)),
        ]
    ])

    return text, reply_markup

def image_menu(_, path = None):
    options = {}

    for key, value in gen_image_utils.MODELS.items():
        size_options = []
        sizes = value["size_options"]
        for size in sizes:
            width = size["width"]
            height = size["height"]
            cost = size["cost"]
            label = "{}x{} (💰 {:,.0f})".format(width, height, cost)
            callback_data = add_args("gen_image", {
                **get_args(path),
                "w": width,
                "h": height,
            })
            size_options.append({
                "label": label,
                "callback": callback_data
            })

        desc = _("Select the image size (width x height)")
        if "tips" in value:
            desc += "\n\n" + build_tips(value["tips"], _)

        options[key] = { 
            "icon": "🎨",
            "name": _(value["name"]),
            "desc": desc,
            "options": size_options,
            "args": {
                "m": key,
            },
        }

    menu_data = {
        "icon": "👨‍🎨",
        "name": _("Generate images"),
        "key": "image",
        "desc": _("Select painting style or AI model"),
        "options": {
            **options,
        },
    }
    return _menu_page(path, menu_data, _)
