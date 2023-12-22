import json
import gettext

DEFAULT_LOCALE = "en_US"
SUPPORTED_LOCALES = {}

with open('supported-languages.json') as file:
    SUPPORTED_LOCALES = json.load(file)

def mapping_tg_lang_code(code):
    if not code or code not in SUPPORTED_LOCALES:
        return DEFAULT_LOCALE
    
    lang_code = code
    lang = SUPPORTED_LOCALES[lang_code]
    locale_code = lang["id"]
    
    if "full_code" in lang:
        locale_code = lang["full_code"]
    elif len(locale_code) == 2:
        locale_code = locale_code + "_" + locale_code.upper()

    return locale_code

def get_text_func(lang):
    locale = mapping_tg_lang_code(lang)
    if locale == DEFAULT_LOCALE:
        return gettext.gettext
    t = gettext.translation('mybot', localedir='locales', languages=[locale])
    return t.gettext

def currency(number):
    return "{:,}".format(number)