FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update
# for voice decoding
RUN apt-get install -y ffmpeg

COPY . /src
WORKDIR /src

# A temporary directory for processing voice files
RUN mkdir -p /src/tmp/voice
RUN pip install -r requirements.txt

CMD ["python", "bot/bot.py"]