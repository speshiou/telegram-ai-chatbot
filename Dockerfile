FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV GOOGLE_APPLICATION_CREDENTIALS=/.gcp_key.json

RUN apt-get update
# for voice decoding
RUN apt-get install -y ffmpeg

COPY . /src
WORKDIR /src

# A temporary directory for processing voice files
RUN mkdir -p /src/tmp/voice
RUN mkdir -p /src/tmp/images
RUN pip install -r requirements.txt

CMD ["python", "bot/bot.py"]