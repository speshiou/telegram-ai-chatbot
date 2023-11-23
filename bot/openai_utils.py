import tiktoken
import openai
import config

MODEL_GPT_35_TURBO = "gpt-3.5-turbo-1106"
MODEL_GPT_4 = "gpt-4"
# MODEL_GPT_4_32K = "gpt-4-32k"

SUPPORTED_MODELS = set([
    MODEL_GPT_35_TURBO,
    MODEL_GPT_4,
    # MODEL_GPT_4_32K,
])

def print_gpt_models():
    # list models
    models = openai.Model.list()
    for model in models.data:
        if model.id.startswith("gpt"):
            print(model.id)

def num_tokens_from_string(string: str, model: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model)
    num_tokens = len(encoding.encode(string))
    return num_tokens

def max_output_tokens(model: str, num_context_tokens: int = None):
    if model == MODEL_GPT_35_TURBO:
        return 4096
    else:
        return max_context_tokens(model) - num_context_tokens

def max_context_tokens(model):
    if model == MODEL_GPT_35_TURBO:
        return 16384
    elif model == MODEL_GPT_4:
        return 8192
    # elif model == MODEL_GPT_4_32K:
    #     return 32768
    else:
        raise NotImplementedError(
            f"""max_context_tokens() is not implemented for model {model}."""
        )

# sample code from https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
def num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613"):
    """Return the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model in {
        "gpt-3.5-turbo-0613",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
        }:
        tokens_per_message = 3
        tokens_per_name = 1
    elif model == "gpt-3.5-turbo-0301":
        tokens_per_message = 4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif "gpt-3.5-turbo" in model:
        # print("Warning: gpt-3.5-turbo may update over time. Returning num tokens assuming gpt-3.5-turbo-0613.")
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613")
    elif "gpt-4" in model:
        # print("Warning: gpt-4 may update over time. Returning num tokens assuming gpt-4-0613.")
        return num_tokens_from_messages(messages, model="gpt-4-0613")
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens

def chatgpt_prompt(system_prompt, chat_messages, new_message):
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    # add chat context
    if len(chat_messages) > 0:
        for message in chat_messages:
            messages.append({
                "role": "user",
                "content": message['user'],
            })
            messages.append({
                "role": "assistant",
                "content": message['bot'],
            })

    # current message
    messages.append({
        "role": "user",
        "content": new_message,
    })

    return messages

def prompt_from_chat_messages(system_prompt, chat_messages, new_message, model="gpt-3.5-turbo"):
    if model in SUPPORTED_MODELS:
        return chatgpt_prompt(system_prompt, chat_messages, new_message)
    else:
        raise NotImplementedError(f"""prompt_from_chat_messages() is not implemented for model {model}.""")
    
def _reply_content_stream(response, model):
    if model in SUPPORTED_MODELS:
        delta = response.choices[0].delta
        return delta.content if "content" in delta else None, response.choices[0].finish_reason
    else:
        raise NotImplementedError(f"""reply_content() is not implemented for model {model}.""")
    
def reply_content(response, model, stream=False):
    if stream:
        return _reply_content_stream(response, model)
    
    if model in SUPPORTED_MODELS:
        return response.choices[0].message.content
    else:
        raise NotImplementedError(f"""reply_content() is not implemented for model {model}.""")
    
async def create_request(prompt, model, max_tokens=None, stream=False, api_type=None):
    args = {}
    if api_type == "azure":
        args["engine"] = model
        args["api_type"] = api_type
        args["api_base"] = config.AZURE_OPENAI_API_BASE
        args["api_version"] = config.AZURE_OPENAI_API_VERSION
        args["api_key"] = config.AZURE_OPENAI_API_KEY
    else:
        args["model"] = model
        args["api_type"] = config.DEFAULT_OPENAI_API_TYPE
        args["api_key"] = config.OPENAI_API_KEY

    return await openai.ChatCompletion.acreate(
        messages=prompt,
        # request_timeout=config.OPENAI_TIMEOUT,
        max_tokens=max_tokens,
        stream=stream,
        **args,
    )
    
async def create_image(prompt, num_images: int = 1):
    response = await openai.Image.acreate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=num_images,
        api_type=config.DEFAULT_OPENAI_API_TYPE,
        api_key=config.OPENAI_API_KEY,
    )
    return response['data']

async def audio_transcribe(filename):
    audio_file= open(filename, "rb")
    response = openai.Audio.transcribe(
        "whisper-1", 
        audio_file, 
        api_type=config.DEFAULT_OPENAI_API_TYPE,
        api_key=config.OPENAI_API_KEY,
        )
    return response['text']

async def moderation(prompt):
    response = await openai.Moderation.acreate(
        input=prompt
    )
    output = response["results"][0]
    return not output["flagged"]