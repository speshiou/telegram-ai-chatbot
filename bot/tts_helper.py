import os
import re
import aiohttp
import json
import functools
import operator
from pydub import AudioSegment

import config

TEXT_MAX_LENGTH = 250
    
def _remove_emojis(data):
    emoj = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002500-\U00002BEF"  # chinese char
        u"\U00002702-\U000027B0"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001f926-\U0001f937"
        u"\U00010000-\U0010ffff"
        u"\u2640-\u2642" 
        u"\u2600-\u2B55"
        u"\u200d"
        u"\u23cf"
        u"\u23e9"
        u"\u231a"
        u"\ufe0f"  # dingbats
        u"\u3030"
                      "]+", re.UNICODE)
    return re.sub(emoj, '', data)

def _split_text(text, sep, max_length):
    result = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_length)
        if end == len(text):
            result.append(text[start:end])
            break
        elif text[end-1] in sep:
            result.append(text[start:end])
            start = end
        else:
            found = False
            for i in range(end-1, start-1, -1):
                if text[i] in sep:
                    result.append(text[start:i+1])
                    start = i+1
                    found = True
                    break
            if not found:
                result.append(text[start:end])
                start = end
    return result

async def _tts(voice_id, text, emotion="Neutral", speed=1):
    url = 'https://app.coqui.ai/api/v2/samples'
    headers = {
        'accept': 'application/json',
        'authorization': f'Bearer {config.COQUI_STUDIO_TOKEN}',
        'content-type': 'application/json',
    }
    payload = {
        "emotion": emotion,
        "speed": speed,
        "voice_id": voice_id,
        "text": text
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=json.dumps(payload)) as response:
            if response.status >= 200 and response.status < 300:
                data = await response.json()
                return data["id"], data["audio_url"]
            else:
                content = await response.text()
                print(content)
                raise Exception("temporary failure with the TTS server")

async def _download(url, filename):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            with open(filename, 'wb') as f:
                while True:
                    chunk = await response.content.read(1024)
                    if not chunk:
                        break
                    f.write(chunk)

    
async def tts(text, output, model):
    text = _remove_emojis(text)
    chunks = _split_text(text, ['.', '?', '!'], TEXT_MAX_LENGTH)

    basename, ext = os.path.splitext(output)
    format = ext[1:]

    emotion = "Happy"
    speed = 1

    if len(chunks) == 0:
        raise Exception("Voice messages only support English")
    elif len(chunks) == 1:
        print(f"tts_to_file len: {len(text)}")
        id, url = await _tts(model, text, emotion=emotion, speed=speed)
        await _download(url, output)
        final_seg = AudioSegment.from_file(output, format=format)
    else:
        filenames = []
        for i, chunk in enumerate(chunks):
            print(f"tts_to_file len: {len(chunk)}")
            filename = f"{basename}{i}{ext}"
            id, url = await _tts(model, chunk, emotion=emotion, speed=speed)
            await _download(url, filename)
            filenames.append(filename)
            print(f"tts_to_file {filename}")

        print(f"combine {len(filenames)} audios")
        segments = [AudioSegment.from_file(filename, format=format) for filename in filenames]
        combined = functools.reduce(operator.add, segments)
        combined.export(output, format=format)
        final_seg = combined

        # cleanup
        for filename in filenames:
            os.remove(filename)

    print(f"tts_to_file len: {len(text)}, duration: {final_seg.duration_seconds}s")
    return output

