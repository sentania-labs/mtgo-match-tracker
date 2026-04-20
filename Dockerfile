FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY app /app/app
COPY agent /app/agent
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
