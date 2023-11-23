import openai_utils
import config
import asyncio

MIN_TOKENS = 30

def _model_name(model, api_type):
    if api_type == "azure":
        return model.replace(".", "")
    return model

def resolve_model(model, num_prompt_tokens:int):
    original_model = model
    max_tokens = openai_utils.max_context_tokens(model)
    # if model == openai_utils.MODEL_GPT_4 and num_prompt_tokens > max_tokens:
    #     model = openai_utils.MODEL_GPT_4_32K
    print(f"resolve_model {original_model} > {model}, num_tokens={num_prompt_tokens}")
    return model
    
def build_prompt(system_prompt, dialog_messages, new_message, model, max_tokens: int = None):
    n_dialog_messages_before = len(dialog_messages)
    n_first_dialog_messages_removed = 0
    prompt = None
    num_prompt_tokens = None
    max_tokens = openai_utils.max_context_tokens(model) if max_tokens is None else min(max_tokens, openai_utils.max_context_tokens(model))

    while num_prompt_tokens is None or num_prompt_tokens >= max_tokens:
        if prompt is not None:
            # forget first message in dialog_messages
            dialog_messages = dialog_messages[1:]
            n_first_dialog_messages_removed = n_dialog_messages_before - len(dialog_messages)
        prompt = openai_utils.prompt_from_chat_messages(system_prompt, dialog_messages, new_message, model)
        num_prompt_tokens = openai_utils.num_tokens_from_messages(prompt, model)
        # retain the first message from context
        if len(dialog_messages) < 1:
            break
    return prompt, num_prompt_tokens, n_first_dialog_messages_removed

def cost_factors(model):
    if model == openai_utils.MODEL_GPT_4:
        return 10, 15
    # elif model == openai_utils.MODEL_GPT_4_32K:
    #     return 20, 20
    return 0.5, 1

async def send_message(prompt, model=openai_utils.MODEL_GPT_35_TURBO, max_tokens=None, stream=False, api_type=None):
    num_prompt_tokens = openai_utils.num_tokens_from_messages(prompt, model)
    max_output_tokens = openai_utils.max_output_tokens(model, num_context_tokens=num_prompt_tokens)
    max_tokens = max_output_tokens if max_tokens is None else min(max_output_tokens, max_tokens)
    max_tokens = max(MIN_TOKENS, max_tokens)

    answer = None
    finish_reason = None

    r = await openai_utils.create_request(prompt, _model_name(model, api_type), max_tokens=max_tokens, stream=stream, api_type=api_type)

    if stream:
        async for buffer in r:
            content_delta, finish_reason = openai_utils.reply_content(buffer, model, stream=True)
            if not content_delta:
                continue
            if answer is None:
                answer = content_delta
            else:
                answer += content_delta

            if model == openai_utils.MODEL_GPT_4:
                # WORKAROUND: avoid reaching rate limit
                await asyncio.sleep(0.1)
            yield False, answer, None
    else:
        answer = openai_utils.reply_content(r, model)

    num_completion_tokens = openai_utils.num_tokens_from_string(answer, model) if answer is not None else 0
    num_total_tokens = num_prompt_tokens + num_completion_tokens

    if answer is None:
        print(f"Invalid answer, num_prompt_tokens={num_prompt_tokens}, num_completion_tokens={num_completion_tokens}, finish_reason={finish_reason}")
        raise Exception(finish_reason)

    # TODO: handle finish_reason == "length"

    yield True, answer, num_completion_tokens
        