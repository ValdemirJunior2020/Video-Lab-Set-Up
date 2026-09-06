FROM python:3.11-slim-bookworm
WORKDIR /service
ENV PYTHONUNBUFFERED=1 HF_HOME=/models/huggingface TRANSFORMERS_CACHE=/models/huggingface
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git libsndfile1 build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --retries 5 --timeout 240 "chatterbox-tts==0.1.7" "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1" "python-multipart>=0.0.9" "soundfile>=0.12" "pydantic>=2,<3"
COPY chatterbox_service/chatterbox_service.py /service/chatterbox_service.py
EXPOSE 4123
CMD ["uvicorn","chatterbox_service:app","--host","0.0.0.0","--port","4123"]
