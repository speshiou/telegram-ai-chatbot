import vertexai
from vertexai.preview.generative_models import GenerativeModel, ChatSession, Part, Content, Image

MODEL_GEMINI_VISION = "gemini-pro-vision"

def init(project_id: str, location:str = "us-central1"):
    vertexai.init(project=project_id, location=location)

def build_history(chat_messages: [str]) -> [Content]:
    history = []

    if len(chat_messages) > 0:
        for message in chat_messages:
            history.append(Content(role="user", parts=[Part.from_text(message['user'])]))
            history.append(Content(role="model", parts=[Part.from_text(message['bot'])]))

    return history

def send_message(model: str, prompt: str, chat_messages: [str], image: str = None) -> str:
    history = build_history(chat_messages)
    model = GenerativeModel(model)
    chat = model.start_chat(history=history)
    if image:
        image = Image.load_from_file(image)
        prompt = [
            prompt,
            Part.from_image(image),
        ]
        response = model.generate_content(prompt)
    else:
        response = chat.send_message(prompt)
    
    return response.text