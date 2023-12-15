import vertexai
from vertexai.preview.generative_models import GenerativeModel, ChatSession, Part, Content

MODEL_GEMINI_PRO = "gemini-pro"

def init(project_id: str, location:str = "us-central1"):
    vertexai.init(project=project_id, location=location)

def build_history(chat_messages: [str]) -> [Content]:
    history = []

    if len(chat_messages) > 0:
        for message in chat_messages:
            history.append(Content(role="user", parts=[Part.from_text(message['user'])]))
            history.append(Content(role="model", parts=[Part.from_text(message['bot'])]))

    return history

def send_message(model: str, prompt: str, chat_messages: [str]) -> str:
    history = build_history(chat_messages)
    model = GenerativeModel(model)
    chat = model.start_chat(history=history)
    response = chat.send_message(prompt)
    return response.text