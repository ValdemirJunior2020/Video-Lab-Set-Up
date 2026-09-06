FROM python:3.11-slim-bookworm

WORKDIR /service
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir --retries 5 --timeout 240 \
    "pydantic-ai>=1,<2" \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.30,<1"

COPY scene_planner_service/service.py /service/service.py

EXPOSE 4130

CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "4130"]
