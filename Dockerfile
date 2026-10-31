FROM python:3.11.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY task_cre_50 ./task_cre_50
COPY tests/fixtures ./tests/fixtures

ENTRYPOINT ["python", "-m", "task_cre_50"]
