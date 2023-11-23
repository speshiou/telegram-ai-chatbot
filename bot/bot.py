import os
import logging
import traceback
import html
import json
import re
import math
from datetime import datetime

import telegram
from telegram import Message, Chat, BotCommand, Update, User, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode, ChatAction

from pydub import AudioSegment

from youtube_transcript_api import YouTubeTranscriptApi, _errors
import trafilatura

import config
import database
import openai_utils
import chatgpt
import tts_helper
import gen_image_utils
import api
import ui
import helper
import i18n
import bugreport

# setup
db = database.Database()
logger = logging.getLogger(__name__)

def get_commands(lang=i18n.DEFAULT_LOCALE):
    _ = i18n.get_text_func(lang)
    return [
        BotCommand("gpt", _("use GPT-3.5 model")),
        BotCommand("gpt4", _("use GPT-4 model")),
        BotCommand("chatgpt", _("switch to ChatGPT mode")),
        BotCommand("proofreader", _("switch to Proofreader mode")),
        BotCommand("dictionary", _("switch to Dictionary mode")),
        BotCommand("image", _("generate images")),
        BotCommand("reset", _("start a new conversation")),
        BotCommand("balance", _("check balance")),
        BotCommand("settings", _("settings")),
        # BotCommand("earn", _("earn rewards by referral")),
    ]

async def register_user_if_not_exists(update: Update, context: CallbackContext, referred_by: int = None):
    user = None
    if update.message:
        user = update.message.from_user
    elif update.edited_message:
        user = update.edited_message.from_user
    elif update.callback_query:
        user = update.callback_query.from_user
    if not user:
        print(f"Unknown callback event: {update}")
        return
    
    if not db.check_if_user_exists(user.id):
        if referred_by and (user.id == referred_by or not db.check_if_user_exists(referred_by)):
            # referred by unknown user or self, unset referral
            referred_by = None

        db.add_new_user(
            user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            referred_by=referred_by
        )
        db.inc_stats('new_users')
        if referred_by:
            db.inc_user_referred_count(referred_by)
            db.inc_stats('referral_new_users')
    return user

async def reply_or_edit_text(update: Update, text: str, parse_mode: ParseMode = ParseMode.HTML, reply_markup = None, disable_web_page_preview = None):
    if update.message:
        await update.message.reply_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    elif update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )

def get_text_func(user, chat_id):
    if user:
        lang = db.get_chat_lang(chat_id) or user.language_code
    else:
        lang = None
    return i18n.get_text_func(lang)

async def start_handle(update: Update, context: CallbackContext):
    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        return
    
    user_id = update.message.from_user.id
    is_new_user = not db.check_if_user_exists(user_id)

    # Extract the referral URL from the message text
    message_text = update.message.text
    m = re.match("\/start u(\d+)", message_text)
    referred_by = int(m[1]) if m else None

    user = await register_user_if_not_exists(update, context, referred_by=referred_by)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    await settings_handle(update, context, data="about")

    if is_new_user and update.message:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👛 " + _("Check balance"), callback_data="balance")]
        ])
        await update.message.reply_text(
            _("✅ {:,} free tokens have been credited").format(config.FREE_QUOTA), 
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            )
        await set_chat_mode(update, context, reason="start")

async def retry_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    messages = db.get_chat_messages(chat_id)
    if not messages or len(messages) == 0:
        await update.message.reply_text(_("😅 No conversation history to retry"))
        return

    last_dialog_message = messages.pop()
    db.pop_chat_messages(chat_id)  # last message was removed from the context

    await message_handle(update, context, message=last_dialog_message["user"], use_new_dialog_timeout=False)

def parse_command(message):
    if not message.strip():
        return None
    m = re.match(f"\/([^\s@]+)(@{config.TELEGRAM_BOT_NAME})?", message, re.DOTALL)
    if m:
        return m[1].strip()
    return None

def strip_command(message):
    if not message.strip():
        return None
    m = re.match(f"\/\w+(@{config.TELEGRAM_BOT_NAME})? (.*)", message, re.DOTALL)
    if m:
        return m[2].strip()
    return None

async def send_error(update: Update, context: CallbackContext, message: str = None, placeholder = None):
    text = "⚠️ " + message
    if placeholder is None:
        await update.effective_message.reply_text(text)
    else:
        await placeholder.edit_text(text)

async def send_openai_error(update: Update, context: CallbackContext, e: Exception, placeholder = None):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    text = _("Temporary OpenAI server failure, please try again later.")
    error_msg = f"{e}"
    if "RateLimitError" in error_msg:
        # openai.error.RateLimitError may contain sensitive data
        text += " " + _("Reason: Rate limit reached")
    elif "policy" in error_msg:
        # replace Microsoft warnings
        text = _("Your request may violate OpenAI's policies. Please modify your prompt and retry.")
    elif "JSONDecodeError" in error_msg:
        pass
    else:
        text += " " + _("Reason: {}").format(error_msg)

    await send_error(update, context, message=text, placeholder=placeholder)

    logger.error(error_msg)
    # printing stack trace
    traceback.print_exc()

async def send_insufficient_tokens_warning(update: Update, user: User, message: str = None, estimated_cost: int = None):
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("👛 " + _("Check balance"), callback_data="balance")]
    ])

    # TODO: show different messages for private and group chats
    text = "⚠️ " + _("Insufficient tokens.")
    if estimated_cost is not None:
        text += " " + _("Require {} tokens to process this message").format(i18n.currency(estimated_cost))
    await update.effective_message.reply_text(text, reply_markup=reply_markup)

async def check_balance(update: Update, estimated_cost: int, user: User):
    remaining_tokens = db.get_user_remaining_tokens(user.id)
    if remaining_tokens < estimated_cost:
        await send_insufficient_tokens_warning(update, user, estimated_cost=estimated_cost)
        return False
    return True

async def common_command_handle(update: Update, context: CallbackContext):
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
    
    user = await register_user_if_not_exists(update, context)
    if not user:
        return
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    cached_msg_id = None

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action, cached_msg_id = query.data.split("|")
        message = db.get_cached_message(cached_msg_id)

        if not message:
            await update.effective_message.edit_text(update.effective_message.text, parse_mode=ParseMode.MARKDOWN, reply_markup=None)
            return
    else:
        message = update.message.text

    command = parse_command(message)
    message = strip_command(message)

    if command in config.DEFAULT_MODELS:
        await set_chat_model(update, context, command)
        return

    chat_mode = command if command in config.CHAT_MODES else None

    if not chat_mode:
        print(f"WARNING: invalid command: {command}")
        return

    if message:
        await message_handle(update, context, message=message, chat_mode_id=chat_mode, cached_msg_id=cached_msg_id)
    else:
        await set_chat_mode(update, context, chat_mode)
    return

def get_message_chunks(text, chuck_size=config.MESSAGE_MAX_LENGTH):
    return [text[i:i + chuck_size] for i in range(0, len(text), chuck_size)]

async def voice_message_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    placeholder = None
    try:
        voice = update.message.voice
        print(voice)
        duration = voice.duration

        # check balance
        estimated_cost = 0
        if duration > config.WHISPER_FREE_QUOTA:
            estimated_cost = (duration - config.WHISPER_FREE_QUOTA) * config.WHISPER_TOKENS

        if not await check_balance(update, estimated_cost, user):
            return
        
        placeholder = await update.effective_message.reply_text("🎙 " + _("Decoding voice message ..."))

        file_id = voice.file_id
        type = voice.mime_type.split("/")[1]
        new_file = await context.bot.get_file(file_id)
        src_filename = os.path.join(config.AUDIO_FILE_TMP_DIR, file_id)
        filename = src_filename
        await new_file.download_to_drive(src_filename)
        if type not in ['m4a', 'mp3', 'webm', 'mp4', 'mpga', 'wav', 'mpeg']:
            # convert to wav if source format is not supported by OpenAI
            wav_filename = src_filename + ".wav"
            seg = AudioSegment.from_file(src_filename, type)
            seg.export(wav_filename, format='wav')
            filename = wav_filename

        file_size = os.path.getsize(filename)
        print(f"size: {file_size}/{config.WHISPER_FILE_SIZE_LIMIT}")
        if file_size < config.WHISPER_FILE_SIZE_LIMIT:
            text = await openai_utils.audio_transcribe(filename)
            if estimated_cost > 0:
                print(f"voice used tokens: {estimated_cost}")
                db.inc_user_used_tokens(user.id, estimated_cost)
            await message_handle(update, context, text, placeholder=placeholder)
        else:
            await placeholder.edit_text("⚠️ " + _("Voice data size exceeds 20MB limit"))
        # clean up
        os.remove(filename)
        if os.path.exists(src_filename):
            os.remove(src_filename)
        
    except Exception as e:
        await send_openai_error(update, context, e, placeholder=placeholder)

def _build_youtube_prompt(url, _):
    video_id = helper.parse_youtube_id(url)
    print(f"parsing youtube {video_id} transcript ...")
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        for transcript in transcript_list:
            # the Transcript object provides metadata properties
            print(
                transcript.video_id,
                transcript.language,
                transcript.language_code,
                # whether it has been manually created or generated by YouTube
                transcript.is_generated,
                # whether this transcript can be translated or not
                transcript.is_translatable,
                # a list of languages the transcript can be translated to
                # transcript.translation_languages,
            )

            transcript_json = transcript.fetch()
            # strip redundant data to reduce prompt token usage
            for line in transcript_json:
                if "duration" in line:
                    del line["duration"]
            return json.dumps(transcript_json, indent=4)
    except _errors.TranscriptsDisabled as e:
        print("Youtube error: transcripts are disabled")
    except Exception as e:
        print(e)
    return None

async def message_handle(update: Update, context: CallbackContext, message=None, use_new_dialog_timeout=True, chat_mode_id=None, placeholder: Message=None, cached_msg_id=None, upscale=False):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    
    # check if message is edited
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
        
    _ = get_text_func(user, chat_id)

    user_id = user.id
    chat = update.effective_chat
    reply_markup = None

    voice_mode = db.get_chat_voice_mode(chat_id)

    if chat_mode_id is None:
        chat_mode_id = db.get_current_chat_mode(chat_id)

    disable_history = False

    chat_modes = helper.get_available_chat_modes(db, chat_id)
    chat_mode = chat_modes[chat_mode_id] if chat_mode_id in chat_modes else None
    if chat_mode is None:
        # fallback to the default chat mode
        chat_mode_id = config.DEFAULT_CHAT_MODE
        chat_mode = chat_modes[chat_mode_id]
        await set_chat_mode(update, context, chat_mode_id, reason="timeout")
    elif "disable_history" in chat_mode:
        disable_history = True
        if cached_msg_id is None:
            cached_message = update.effective_message.text
            if not cached_message.startswith("/"):
                cached_message = "/{} {}".format(chat_mode_id, cached_message)
            cached_msg_id = db.cache_chat_message(cached_message)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(_("Retry"), callback_data=f"retry|{cached_msg_id}")]
        ])
    elif use_new_dialog_timeout:
        # determine if the chat is timed out
        last_chat_time = db.get_last_chat_time(chat_id)
        timeout = db.get_chat_timeout(chat_id)
        if last_chat_time is None:
            # first launch or the current chat mode is outdated
            await set_chat_mode(update, context, chat_mode_id, reason="timeout")
        elif timeout > 0 and (datetime.now() - last_chat_time).total_seconds() > timeout:
            # timeout
            await set_chat_mode(update, context, chat_mode_id, reason="timeout")
            # drop placeholder to prevent the answer from showing before the timeout message
            placeholder = None

    # flood control, must run after set_chat_mode
    rate_limit_start, rate_count = db.get_chat_rate_limit(chat_id)
    if rate_limit_start is None or  (datetime.now() - rate_limit_start).total_seconds() > 60:
        db.reset_chat_rate_limit(chat_id)
    else:
        db.inc_chat_rate_count(chat_id)

    rate_limit = 10 if chat.type == Chat.PRIVATE else 8
    # telegram flood control limit is 20 messages per minute, we set 12 to leave some budget
    if rate_count >= rate_limit:
        if rate_count < rate_limit + 3:
            await update.effective_message.reply_text(_("⚠️ This chat has exceeded the rate limit. Please wait for up to 60 seconds."), parse_mode=ParseMode.HTML)
        return

    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    # send typing action
    await update.effective_chat.send_action(action="typing")

    # load role
    if "prompt" not in chat_mode:
        # custom role list won't contain prompts by default
        chat_mode["prompt"] = db.get_role_prompt(chat_id, chat_mode["_id"])
    system_prompt = chat_mode["prompt"]
    # load model
    model_id = db.get_current_model(chat_id)
    model = openai_utils.MODEL_GPT_4 if model_id == "gpt4" else openai_utils.MODEL_GPT_35_TURBO 
    # load chat history to context
    messages = db.get_chat_messages(chat_id) if not disable_history else []

    context_content = None
    if message is None:
        message = update.effective_message.text
        # load long text to the context if any
        context_content, context_src = db.get_chat_context(chat_id)
        if context_content is not None:
            system_prompt = "You are an assistant to answer the questions about the content of {}.\n\ncontent:\n{}".format(context_src, context_content)
            upscale = True

    message = message.strip()
    # crawl link
    is_url = helper.is_uri(message)
    if is_url:
        url = message
        if helper.is_youtube_url(url):
            message = _build_youtube_prompt(url, _)
            if message is None:
                await update.effective_message.reply_text(_("⚠️ Transcripts for this video are not available, possibly due to access restrictions or transcript disablement."), parse_mode=ParseMode.HTML)
                return
        else:
            downloaded = trafilatura.fetch_url(url)
            message = trafilatura.extract(downloaded, include_comments=False)
            if message is None:
                await update.effective_message.reply_text(_("⚠️ Failed to fetch the website content, possibly due to access restrictions."), parse_mode=ParseMode.HTML)
                return
        upscale = True

    voice_placeholder = None    
    answer = None
    sent_answer = None
    num_completion_tokens = None
    # handle long message that exceeds telegram's limit
    n_message_chunks = 0
    current_message_chunk_index = 0
    n_sent_chunks = 0
    # handle too many tokens
    max_message_count = -1

    if upscale:
        model = chatgpt.resolve_model(model, openai_utils.num_tokens_from_string(system_prompt + " " + message, model))

    prompt_cost_factor, completion_cost_factor = chatgpt.cost_factors(model)
    remaining_tokens = db.get_user_remaining_tokens(user_id)
    max_affordable_tokens = int(remaining_tokens / prompt_cost_factor)
    # determine if enabling saving mode
    if remaining_tokens < 10000 or chat_mode_id not in config.DEFAULT_CHAT_MODES:
        # enable token saving mode for low balance users and external modes
        max_affordable_tokens = min(max_affordable_tokens, 2000)

    prompt, num_prompt_tokens, n_first_dialog_messages_removed = chatgpt.build_prompt(system_prompt, messages, message, model, max_affordable_tokens)
    if num_prompt_tokens > openai_utils.max_context_tokens(model):
        await update.effective_message.reply_text(_("⚠️ Sorry, the message is too long for {}. Please reduce the length of the input data.").format(model))
        return
    estimated_cost = int(num_prompt_tokens * prompt_cost_factor)
    if not await check_balance(update, estimated_cost, user):
        return
    
    if is_url:
        db.set_chat_context(chat_id, message, url)
        text = _("Now you can ask me about the content in the link:")
        text += "\n" + url
        text += "\n\n"
        text += ui.build_tips([
            _("The cost of the next answers will be more than {} tokens").format(i18n.currency(estimated_cost)),
            _("To reduce costs, you can use the /reset command to remove the data from the context"),
        ], _, title=_("Notice"))
        reply_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(_("Summarize"), callback_data="summarize"),
                InlineKeyboardButton(_("Cancel"), callback_data="reset"),
            ]
        ])
        await update.effective_message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        return
    # send warning if some messages were removed from the context
    if n_first_dialog_messages_removed > 0:
        # if n_first_dialog_messages_removed == 1:
        #     text = _("⚠️ The <b>first message</b> was removed from the context due to OpenAI's token amount limit. Use /reset to reset")
        # else:
        #     text = _("⚠️ The <b>first {} messages</b> have removed from the context due to OpenAI's token amount limit. Use /reset to reset").format(n_first_dialog_messages_removed)
        # await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
        print(f"removed {n_first_dialog_messages_removed} messages from context")
        max_message_count = len(messages) + 1 - n_first_dialog_messages_removed

    try:
        api_type = config.OPENAI_CHAT_API_TYPE
        # if api_type != config.DEFAULT_OPENAI_API_TYPE and "api_type" in config.CHAT_MODES[chat_mode]:
        #     api_type = config.CHAT_MODES[chat_mode]["api_type"]

        stream = chatgpt.send_message(
            prompt,
            model=model,
            max_tokens=max_affordable_tokens,
            stream=config.STREAM_ENABLED,
            api_type=api_type,
        )

        prev_answer = ""
        
        if api_type == "azure":
            stream_len = 150 if chat.type == Chat.PRIVATE else 200
        else:
            stream_len = 100 if chat.type == Chat.PRIVATE else 150

        if placeholder is None:
            placeholder = await update.effective_message.reply_text("...")
        
        async for buffer in stream:
            finished, answer, num_completion_tokens = buffer

            if not finished and len(answer) - len(prev_answer) < stream_len:
                # reduce edit message requests
                continue
            prev_answer = answer

            if finished:
                parse_mode = ParseMode.MARKDOWN
                final_reply_markup = reply_markup
            else:
                parse_mode = None
                final_reply_markup = None

            # send warning if the anwser is too long (based on telegram's limit)
            if len(answer) > config.MESSAGE_MAX_LENGTH:
                parse_mode = None

            # send answer chunks
            n_message_chunks = math.ceil(len(answer) / config.MESSAGE_MAX_LENGTH)
            for chuck_index in range(current_message_chunk_index, n_message_chunks):
                start_index = chuck_index * config.MESSAGE_MAX_LENGTH
                end_index = (chuck_index + 1) * config.MESSAGE_MAX_LENGTH
                message_chunk = answer[start_index:end_index]
                if not finished:
                    message_chunk += " ..."
                if current_message_chunk_index < n_message_chunks - 1 or placeholder is None:
                    # send a new message chunk
                    placeholder = await update.effective_message.reply_text(message_chunk, parse_mode=parse_mode, reply_markup=final_reply_markup)
                elif placeholder is not None:
                    # update last message chunk
                    try:
                        await placeholder.edit_text(message_chunk, parse_mode=parse_mode, reply_markup=final_reply_markup)
                    except telegram.error.BadRequest as e:
                        if str(e).startswith("Message is not modified"):
                            continue
                        # May encounter parsing errors, send plaintext instead
                        await placeholder.edit_text(message_chunk, parse_mode=None, reply_markup=final_reply_markup)
                        print("Telegram errors while editing text: {}".format(e))
                sent_answer = answer[0:end_index]
                current_message_chunk_index = chuck_index
                n_sent_chunks = chuck_index + 1

        # send warning if the anwser is too long (based on telegram's limit)
        if len(answer) > config.MESSAGE_MAX_LENGTH:
            await update.effective_message.reply_text(_("⚠️ The answer was too long, has been splitted into multiple unformatted messages"))
    except telegram.error.BadRequest as e:
        error_text = f"Errors from Telegram: {e}"
        logger.error(error_text)    
        if answer and n_sent_chunks < n_message_chunks:
            # send remaining answer chunks
            chunks = get_message_chunks(answer)
            for i in range(current_message_chunk_index + 1, n_message_chunks):
                chunk = chunks[i]
                # answer may have invalid characters, so we send it without parse_mode
                await update.effective_message.reply_text(chunk, reply_markup=final_reply_markup)
            sent_answer = answer
    except Exception as e:
        await send_openai_error(update, context, e)
    
    # TODO: consume tokens even if an exception occurs
    # consume tokens and append the message record to db
    if sent_answer is not None and num_completion_tokens is not None:
        if not disable_history:
            # update user data
            new_dialog_message = {"user": message, "bot": sent_answer, "date": datetime.now(), "num_context_tokens": num_prompt_tokens, "num_completion_tokens": num_completion_tokens}
            db.push_chat_messages(
                chat_id,
                new_dialog_message,
                max_message_count,
            )
        else:
            db.update_chat_last_interaction(chat_id)
        final_cost = int(num_prompt_tokens * prompt_cost_factor + num_completion_tokens * completion_cost_factor)
        # IMPORTANT: consume tokens in the end of function call to protect users' credits
        db.inc_user_used_tokens(user_id, final_cost)

        if voice_mode != "text":
            await send_voice_message(update, context, sent_answer, chat_mode_id, placeholder=voice_placeholder)

async def send_voice_message(update: Update, context: CallbackContext, message: str, chat_mode: str, placeholder = None):
    if chat_mode not in config.TTS_MODELS:
        return
    
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    full_message = message
    limit = 600
    if len(message) > limit:
        print("[TTS] message too long")
        message = message[:limit]

    # estimate token amount
    estimated_cost = config.TTS_ESTIMATED_DURATION_BASE * len(message) * config.COQUI_TOKENS
    print(f"[TTS] estimated used tokens: {estimated_cost}")
    if not await check_balance(update, estimated_cost, user):
        return

    if placeholder is None:
        placeholder = await update.effective_message.reply_text("🗣 " + _("Recording ..."))

    try:
        tts_model = config.TTS_MODELS[chat_mode]
        filename = os.path.join(config.AUDIO_FILE_TMP_DIR, "{}-{}-{}.wav".format(chat_id, user.id, datetime.now()))
        output = await tts_helper.tts(message, output=filename, model=tts_model)
        if output:
            seg = AudioSegment.from_wav(output)
            # recalculate real token amount
            estimated_cost = int(seg.duration_seconds * config.COQUI_TOKENS)
            ogg_filename = os.path.splitext(output)[0] + ".ogg"
            # must use OPUS codec to show spectrogram on Telegram
            seg.export(ogg_filename, format='ogg', codec="libopus")
            try:
                # in case the user deletes the placeholders manually
                if placeholder is not None:
                    await placeholder.delete()
            except Exception as e:
                print(e)
            
            cached_msg_id = db.cache_chat_message(full_message)
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(_("Text"), callback_data=ui.add_arg("show_message", "id", cached_msg_id))]])
            await update.effective_message.reply_voice(ogg_filename, reply_markup=reply_markup)
            db.inc_user_used_tokens(user.id, estimated_cost)
            print(f"[TTS] real used tokens: {estimated_cost}")
            # clean up
            if os.path.exists(output):
                os.remove(output)
            if os.path.exists(ogg_filename):
                os.remove(ogg_filename)
        else:
            text = "⚠️ " + _("The voice message could not be created. Voice messages are only valid in English.")
            try:
                # in case the user deletes the placeholders manually
                if placeholder is not None:
                    await placeholder.edit_text(text)
            except Exception as e:
                print(e)
                await update.effective_message.reply_text(text)
    except Exception as e:
        print(e)
        text = "⚠️ " + _("Failed to generate the voice message, please try again later.")
        text += " " + _("Reason: {}").format(e)
        await update.effective_message.reply_text(text)

async def summarize_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    user_id = user.id
    context_content, context_src = db.get_chat_context(chat_id)
    if helper.is_uri(context_src):
        url = context_src
        if helper.is_youtube_url(context_src):
            prompt_pattern = _("summarize the transcript from {} containing abstract, list of key points and the conclusion\n\ntranscript:\n{}")
        else:
            prompt_pattern = _("summarize the content from {} containing abstract, list of key points and the conclusion\n\noriginal content:\n{}")
        message = prompt_pattern.format(url, context_content)
        await message_handle(update, context, message, upscale=True)

async def image_message_handle(update: Update, context: CallbackContext):
    if update.edited_message is not None:
        await edited_message_handle(update, context)
        return
    
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    user_id = user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())

    path = None
    cached_msg_id = None
    if update.callback_query:
        # from retry
        query = update.callback_query
        path = query.data
        await query.answer()
        cached_msg_id = ui.get_arg(path, "id")
        full_message = None
        if cached_msg_id:
            full_message = db.get_cached_message(cached_msg_id)
        if not full_message:
            # remove the retry button
            await update.effective_message.edit_caption(reply_markup=None)
            return
    else:
        full_message = update.message.text
        message = strip_command(full_message)
        if not message:
            text = _("💡 Please type /image and followed by the image prompt")
            text += "\n\n"
            text += ui.build_tips([
                _("<b>Example:</b>") + " /image a man wears spacesuit",
                _("Some AI Models only support English prompt"),
            ], _)

            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💡 " + _("Learn"), url="https://t.me/sd_prompts_lab"),
                ],
            ])
            await update.effective_message.reply_text(text, ParseMode.HTML, reply_markup=reply_markup)
            return
        result = await openai_utils.moderation(message)
        if not result:
            await update.effective_message.reply_text("⚠️ " + _("Inappropriate prompt. Please modify your prompt and retry."), ParseMode.HTML)
            return
        path = "image"
    
    if cached_msg_id is None:
        cached_msg_id = db.cache_chat_message(message)

    path = ui.add_arg(path, "id", cached_msg_id)
    text, reply_markup = ui.image_menu(_, path=path)
    await reply_or_edit_text(update, text, reply_markup=reply_markup)

async def gen_image_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    user_id = user.id

    query = update.callback_query
    path = query.data
    await query.answer()

    model = ui.get_arg(path, "m")
    width = int(ui.get_arg(path, "w"))
    height = int(ui.get_arg(path, "h"))
    cached_msg_id = ui.get_arg(path, "id")
    if cached_msg_id:
        prompt = db.get_cached_message(cached_msg_id)
        if not prompt:
            await reply_or_edit_text(update, "⚠️ " + _("Outdated command"))
            return
        
    estimated_cost = gen_image_utils.calc_cost(model, width, height)
    print(f"estimated cost: {estimated_cost}")
    if not estimated_cost:
        await reply_or_edit_text(update, "⚠️ " + _("Outdated command"))
        return

    if not await check_balance(update, estimated_cost, user):
        return
    
    remaing_time = db.is_user_generating_image(user_id)
    if remaing_time:
        await update.effective_message.reply_text(_("⚠️ It is only possible to generate one image at a time. Please wait for {} seconds to retry.").format(int(remaing_time)), parse_mode=ParseMode.HTML)
        return
    
    placeholder = None
    try:
        db.mark_user_is_generating_image(user_id, True)
        text = _("👨‍🎨 painting ...")
        if update.effective_message.photo:
            placeholder = await update.effective_message.reply_text(text)
        else:
            placeholder = await query.edit_message_text(text)

        result = await gen_image_utils.inference(model=model, width=width, height=height, prompt=prompt)
        try:
            # in case the user deletes the placeholders manually
            await placeholder.delete()
            placeholder = None
        except Exception as e:
            print("failed to delete placeholder")
            print(e)
        
        # send as a media group
        # media_group = map(lambda image_url: InputMediaPhoto(image_url), images)
        # media_group = list(media_group)
        # text = f"<code>{message}</code>"
        # await update.effective_message.reply_media_group(media=media_group, caption=text, parse_mode=ParseMode.HTML)

        # send each image as single message for better share experience
        for image_data in result:
            image = image_data["image"]
            seed = image_data["seed"] if "seed" in image_data else None
            buttons = [
                InlineKeyboardButton(_("Prompt"), callback_data=ui.add_arg("show_message", "id", cached_msg_id)),
                InlineKeyboardButton(_("Retry"), callback_data=query.data),
            ]
            if seed is not None:
                upscale_data = {
                    "prompt": prompt,
                    "model": model,
                    "width": width,
                    "height": height,
                    "seed": seed,
                }
                cached_msg_id = db.cache_chat_message(json.dumps(upscale_data))
                callback_data = ui.add_arg("upscale", "id", cached_msg_id)
                buttons.append(InlineKeyboardButton(_("Upscale"), callback_data=callback_data))
            reply_markup = InlineKeyboardMarkup([
                buttons
            ])
            # image can be a url string and bytes
            await context.bot.send_photo(chat_id, image, reply_markup=reply_markup)
        db.inc_user_used_tokens(user_id, estimated_cost)
        db.mark_user_is_generating_image(user_id, False)
    except Exception as e:
        db.mark_user_is_generating_image(user_id, False)
        error_message = _("Server error. Please try again later.")
        await send_error(update, context, message=error_message, placeholder=placeholder)
        raise e
    
async def upscale_image_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    user_id = user.id

    query = update.callback_query
    path = query.data
    await query.answer()

    cached_msg_id = ui.get_arg(path, "id")
    if cached_msg_id:
        cached_data = db.get_cached_message(cached_msg_id)
        if not cached_data:
            await reply_or_edit_text(update, "⚠️ " + _("Outdated command"))
            return
        
    estimated_cost = config.UPSCALE_COST
    if not await check_balance(update, estimated_cost, user):
        return
        
    consent = ui.get_arg(path, "consent")
    if not consent:
        text = "ℹ️ " + _("Upscaling images with real-esrgan-4x can be expensive.")
        callback_data = ui.add_args("upscale", {"id": cached_msg_id, "consent": "ok"})
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(_("Upscale - {} tokens").format(config.UPSCALE_COST), callback_data=callback_data),]
        ])
        await update.effective_message.reply_text(text, reply_markup=reply_markup, reply_to_message_id=update.effective_message.message_id)
        return
        
    try:
        remaing_time = db.is_user_generating_image(user_id)
        if remaing_time:
            await update.effective_message.reply_text(_("⚠️ It is only possible to generate one image at a time. Please wait for {} seconds to retry.").format(int(remaing_time)), parse_mode=ParseMode.HTML)
            return
        
        db.mark_user_is_generating_image(user_id, True)
        args = json.loads(cached_data)
        text = _("👨‍🎨 painting ...")
        placeholder = await query.edit_message_text(text)
        photo = helper.get_original_photo(update.effective_message.reply_to_message.photo)
        photo_file = await context.bot.get_file(photo.file_id)
        buffer = await photo_file.download_as_bytearray()
        image = await gen_image_utils.upscale(buffer)
        try:
            # in case the user deletes the placeholders manually
            await placeholder.delete()
            placeholder = None
        except Exception as e:
            print("failed to delete placeholder")
            print(e)
        
        # # image can be a url string and bytes
        await context.bot.send_photo(chat_id, image)
        db.inc_user_used_tokens(user_id, estimated_cost)
        db.mark_user_is_generating_image(user_id, False)
    except Exception as e:
        db.mark_user_is_generating_image(user_id, False)
        error_message = _("Server error. Please try again later.")
        await send_error(update, context, message=error_message, placeholder=placeholder)
        raise e

async def show_message_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    query = update.callback_query
    path = query.data
    await query.answer()
    cached_msg_id = ui.get_arg(path, "id")
    caption = None
    if cached_msg_id:
        message = db.get_cached_message(cached_msg_id)
        if message:
            caption = "<pre><code>{}</code></pre>".format(html.escape(message))
    # hide show message button
    inline_keyboard = []
    for row in update.effective_message.reply_markup.inline_keyboard:
        buttons = filter(lambda b: not b.callback_data.startswith("show_message"), row)
        buttons = list(buttons)
        if len(buttons) > 0:
            inline_keyboard.append(buttons)
    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    await update.effective_message.edit_caption(caption, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def reset_handle(update: Update, context: CallbackContext):
    await set_chat_mode(update, context, reason="reset")

async def show_chat_modes_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    user_id = update.message.from_user.id
    db.set_user_attribute(user_id, "last_interaction", datetime.now())
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    text, reply_markup = ui.settings(db, chat_id, _, "settings>current_chat_mode")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def set_chat_model(update: Update, context: CallbackContext, model = None):
    user = await register_user_if_not_exists(update, context)
    chat = update.effective_chat
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    if model not in config.DEFAULT_MODELS:
        # fallback to ChatGPT mode
        model = config.DEFAULT_MODEL

    db.set_current_model(chat_id, model)

    text = _("ℹ️ You are using {} model ...").format(config.DEFAULT_MODELS[model]["name"])

    if model == "gpt4":
        text += "\n\n"
        text += _("NOTE: GPT-4 is expensive, so please use it carefully.")

    reply_markup = None
    keyborad_rows = None
    if chat.type == Chat.PRIVATE:
        keyborad_rows = [
            [InlineKeyboardButton("💬 " + _("Change AI model"), web_app=WebAppInfo(os.path.join(config.WEB_APP_URL, "models?start_for_result=1")))]
        ]

    if keyborad_rows:
        reply_markup = InlineKeyboardMarkup(keyborad_rows)

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def set_chat_mode(update: Update, context: CallbackContext, chat_mode_id = None, reason: str = None):
    user = await register_user_if_not_exists(update, context)
    chat = update.effective_chat
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    if chat_mode_id is None:
        chat_mode = helper.get_current_chat_mode(db, chat_id)
        chat_mode_id = chat_mode["id"]
    else:
        chat_modes = helper.get_available_chat_modes(db, chat_id)
        if chat_mode_id in chat_modes:
            chat_mode = chat_modes[chat_mode_id]
        else:
            # fallback to ChatGPT mode
            chat_mode_id = config.DEFAULT_CHAT_MODE
            chat_mode = config.CHAT_MODES[chat_mode_id]

    # reset chat history
    db.reset_chat(chat_id, chat_mode_id)

    show_tips = reason is None
    if reason is not None and "disable_history" in chat_mode:
        # info the current mode only
        reason = None
        show_tips = False

    # to trigger roles to start the conversation
    send_empty_message = "greeting" not in chat_mode and reason is None
    reply_markup = None

    keyborad_rows = []
    if chat.type == Chat.PRIVATE:
        keyborad_rows = [
            [InlineKeyboardButton("💬 " + _("Change chat mode"), web_app=WebAppInfo(os.path.join(config.WEB_APP_URL, "roles?start_for_result=1")))]
        ]
    icon = chat_mode["icon"] if "icon" in chat_mode else "ℹ️"
    icon_prefix = icon + " "

    if reason == "reset":
        text = icon_prefix + _("I have already forgotten what we previously talked about.")
        keyborad_rows = []
    elif show_tips and "greeting" in chat_mode:
        text = icon_prefix + _(chat_mode["greeting"])
    # elif reason == "timeout":
    #     text = icon_prefix + _("It's been a long time since we talked, and I've forgotten what we talked about before.")
    #     keyborad_rows.append([InlineKeyboardButton("⏳ " + _("Timeout settings"), callback_data="settings>timeout")])
    else:
        model_id = db.get_current_model(chat_id)
        model = config.DEFAULT_MODELS[model_id]
        text = icon_prefix + _("You're now chatting with {} ({}) ...").format(chat_mode["name"], model["name"])

    if show_tips:
        tips = ui.chat_mode_tips(chat_mode_id, _)
        if tips:
            text += "\n\n" + tips

        chat = update.effective_chat
        if chat.type != Chat.PRIVATE:
            text += "\n\n"
            text += ui.build_tips([
                _("To continue the conversation in the group chat, please \"reply\" to my messages."),
                _("Please \"SLOW DOWN\" interactions with the chatbot as group chats can easily exceed the Telegram rate limit. "),
                _("Once this chat exceeds the rate limit, the chatbot won't respond temporarily."),
            ], _)

    if keyborad_rows:
        reply_markup = InlineKeyboardMarkup(keyborad_rows)

    await reply_or_edit_text(update, text, reply_markup=reply_markup)
    if send_empty_message:
        await message_handle(update, context, "")

async def set_chat_mode_handle(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    chat_mode = query.data.split("|")[1]
    await set_chat_mode(update, context, chat_mode)

async def show_balance_handle(update: Update, context: CallbackContext):
    query = update.callback_query
    if query:
        await query.answer()

    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)
    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        text = _("🔒 For privacy reason, your balance won't show in a group chat. Please use /balance command in @{}.").format(config.TELEGRAM_BOT_NAME)
        await reply_or_edit_text(update, text)
        return

    db.set_user_attribute(user.id, "last_interaction", datetime.now())

    used_tokens = db.get_user_attribute(user.id, "used_tokens")
    n_spent_dollars = used_tokens * (config.TOKEN_PRICE / 1000)

    text = _("👛 <b>Balance</b>\n\n")
    text += _("<b>{:,}</b> tokens left\n").format(db.get_user_remaining_tokens(user.id))
    text += _("<i>You used <b>{:,}</b> tokens</i>").format(used_tokens)
    text += "\n\n"
    text += ui.build_tips(
        [
            _("The longer conversation would spend more tokens"),
            _("/reset to clear history manually"),
        ], _
    )
    # text += f"You spent <b>{n_spent_dollars:.03f}$</b>\n"
    # text += f"You used <b>{used_tokens}</b> tokens <i>(price: ${config.TOKEN_PRICE} per 1000 tokens)</i>\n"

    tokens_packs = [
        {
            "payment_amount": 1.99,
            "tokens_amount": price_to_tokens(2),
        },
        {
            "payment_amount": 7.99,
            "tokens_amount": price_to_tokens(10),
            "caption": "-20%",
        },
        {
            "payment_amount": 13.99,
            "tokens_amount": price_to_tokens(20),
            "caption": "-30%",
        },
        {
            "payment_amount": 24.99,
            "tokens_amount": price_to_tokens(50),
            "caption": "-50%",
        },
    ]

    buttons = map(lambda pack: \
                  InlineKeyboardButton("+{:,} tokens - ${:,.2f}{}".format(pack["tokens_amount"], pack["payment_amount"], " ({})".format(pack["caption"]) if "caption" in pack else ""), \
                    callback_data="top_up|{}|{}".format(pack["payment_amount"], pack["tokens_amount"])), \
                        tokens_packs)
    rows = map(lambda button: [button], buttons)
    reply_markup = InlineKeyboardMarkup(list(rows))

    await reply_or_edit_text(update, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup, disable_web_page_preview=True)

def price_to_tokens(price: float):
    return int(price / config.TOKEN_PRICE * 1000)

async def show_payment_methods(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    query = update.callback_query
    await query.answer()
    c, amount, tokens_amount = query.data.split("|")

    amount = float(amount)

    if amount > 100 or amount < 0.1:
        text_not_in_range = _("💡 Only accept number between 0.1 to 100")
        await reply_or_edit_text(update, text_not_in_range)

    text = _("🛒 Choose the payment method\n\n")
    text += _("💳 Debit or Credit Card - support 200+ countries/regions\n")
    text += "\n"
    text += _("💎 Crypto - BTC, USDT, USDC, TON, BNB\n")
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(_("💳 Debit or Credit Card"), callback_data=f"payment|paypal|{amount}|{tokens_amount}")],
        [InlineKeyboardButton(_("💎 Crypto"), callback_data=f"payment|crypto|{amount}|{tokens_amount}")]
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def show_invoice(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    c, method, amount, token_amount = query.data.split("|")

    amount = float(amount)
    token_amount = int(float(token_amount))

    await query.edit_message_text(
        _("📋 Creating an invoice ..."),
        parse_mode=ParseMode.HTML,
    )

    result = await api.create_order(user_id, method, amount, token_amount)

    if result and result["status"] == "OK":
        text = _("📋 <b>Your invoice</b>:\n\n")
        text += "{:,} tokens\n".format(token_amount)
        text += "------------------\n"
        text += f"${amount}\n\n\n"

        text += _("💡 <b>Tips</b>:\n")

        tips = []

        button_text = ""
        if method == "paypal":
            tips.append(_("If you do not have a PayPal account, click on the button located below the login button to pay with cards directly."))
            button_text = _("💳 Pay with Debit or Credit Card")
        elif method == "crypto":
            tips.append(_("If you have any issues related to crypto payment, please contact the customer service in the payment page, or send messages to {} directly for assistance.").format("@cryptomus_support"))
            button_text = _("💎 Pay with Crypto")

        tips.append(_("Tokens will be credited within 10 minutes of payment."))
        tips.append(_("Please contact @{} if tokens are not received after 1 hour of payment.").format(config.SUPPORT_USER_NAME))

        text += "\n\n".join(map(lambda s: "• " + s, tips))

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(button_text, url=result["url"])]
        ])
    else:
        text = _("⚠️ Failed to create an invoice, please try again later.")
        reply_markup = None

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def settings_handle(update: Update, context: CallbackContext, data: str = None):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    chat_mode = db.get_current_chat_mode(chat_id)
    db.upsert_chat(chat_id, chat_mode, clear_messages=False)
    _ = get_text_func(user, chat_id)

    query = update.callback_query
    if query:
        await query.answer()

    if data is None:
        data = query.data if query else None

    if data and data.startswith("about"):
        text, reply_markup = ui.about(_)
    else:
        text, reply_markup = ui.settings(db, chat_id, _, data=data)

    await reply_or_edit_text(update, text, reply_markup=reply_markup, disable_web_page_preview=True)

async def close_handle(update: Update, context: CallbackContext):
    await update.effective_message.delete()

async def show_earn_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    result = await api.earn(user.id)

    if result and result["status"] == "OK":
        referral_url = result['referral_url']

        text = _("<b>💰 Earn</b>\n\n")
        # text += "\n\n"
        text += _("Get %s%% rewards from the referred payments\n\n") % (result['commission_rate'] * 100)
        text += _("Unused rewards: ${:,.2f}\n").format(result['unused_rewards'])
        text += _("Total earned: ${:,.2f}\n\n").format(result['total_earned'])
        text += _("Referral link:\n")
        text += f'<a href="{referral_url}">{referral_url}</a>\n'
        text += _("<i>You have referred {:,} new users</i>\n\n").format(result['referred_count'])
        text += _("<i>💡 Refer the new users via your referral link, and you'll get a reward when they make a payment.</i>")
    else:
        text = _("⚠️ Server error, please try again later.")

    await reply_or_edit_text(update, text)

async def edited_message_handle(update: Update, context: CallbackContext):
    user = await register_user_if_not_exists(update, context)
    chat_id = update.effective_chat.id
    _ = get_text_func(user, chat_id)

    text = _("💡 Edited messages won't take effects")
    await update.edited_message.reply_text(text, parse_mode=ParseMode.HTML)

async def error_handle(update: Update, context: CallbackContext) -> None:
    # collect error message
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    callstacks = "".join(tb_list)

    if "Message is not modified" in callstacks:
        # ignore telegram.error.BadRequest: Message is not modified. 
        # The issue is caused by users clicking inline keyboards repeatedly
        return
    
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    chunks = get_message_chunks(callstacks, chuck_size=2000)
    update_str = update.to_dict() if isinstance(update, Update) else str(update)

    try:
        for i, chuck in enumerate(chunks):
            if i == 0:
                message = (
                    f"An exception was raised while handling an update\n"
                    f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
                    "</pre>\n\n"
                    f"<pre>{html.escape(chuck)}</pre>"
                )
            else:
                message = f"<pre>{html.escape(chuck)}</pre>"
            await bugreport.send_bugreport(message)
    except Exception as e:
        print(f"Failed to send bugreport: {e}")

async def app_post_init(application: Application):
    # setup bot commands
    await application.bot.set_my_commands(get_commands())
    await application.bot.set_my_commands(get_commands('zh_CN'), language_code="zh")

def run_bot() -> None:
    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(app_post_init)
        .build()
    )

    # add handlers
    if not config.ALLOWED_TELEGRAM_USERNAMES or len(config.ALLOWED_TELEGRAM_USERNAMES) == 0:
        user_filter = filters.ALL
    else:
        user_filter = filters.User(username=config.ALLOWED_TELEGRAM_USERNAMES)

    application.add_handler(CommandHandler("start", start_handle, filters=user_filter))
    application.add_handler(CommandHandler("reset", reset_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(reset_handle, pattern="^reset"))
    # application.add_handler(CommandHandler("role", show_chat_modes_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(set_chat_mode_handle, pattern="^set_chat_mode"))
    application.add_handler(CommandHandler("balance", show_balance_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(show_balance_handle, pattern="^balance"))
    application.add_handler(CallbackQueryHandler(show_payment_methods, pattern="^top_up\|(\d)+"))
    application.add_handler(CallbackQueryHandler(show_invoice, pattern="^payment\|"))
    application.add_handler(CommandHandler("earn", show_earn_handle, filters=user_filter))
    application.add_handler(CommandHandler("gpt", common_command_handle, filters=user_filter))
    application.add_handler(CommandHandler("gpt4", common_command_handle, filters=user_filter))
    application.add_handler(CommandHandler("chatgpt", common_command_handle, filters=user_filter))
    application.add_handler(CommandHandler("proofreader", common_command_handle, filters=user_filter))
    application.add_handler(CommandHandler("dictionary", common_command_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(common_command_handle, pattern="^retry"))
    application.add_handler(CallbackQueryHandler(summarize_handle, pattern="^summarize"))
    application.add_handler(CommandHandler("image", image_message_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(image_message_handle, pattern="^image"))
    application.add_handler(CallbackQueryHandler(gen_image_handle, pattern="^gen_image"))
    application.add_handler(CallbackQueryHandler(upscale_image_handle, pattern="^upscale"))
    application.add_handler(CallbackQueryHandler(show_message_handle, pattern="^show_message"))
    application.add_handler(CommandHandler("settings", settings_handle, filters=user_filter))
    application.add_handler(CallbackQueryHandler(settings_handle, pattern="^(settings|about)"))
    application.add_handler(CallbackQueryHandler(close_handle, pattern="^close"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, message_handle))
    application.add_handler(MessageHandler(filters.VOICE & user_filter, voice_message_handle))
    application.add_error_handler(error_handle)
    
    # start the bot
    application.run_polling()


if __name__ == "__main__":
    if not config.TELEGRAM_BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN not set")
    if not config.OPENAI_API_KEY:
        raise Exception("OPENAI_API_KEY not set")
    run_bot()