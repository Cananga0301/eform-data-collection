FROM python:3.11-slim-buster AS builder

WORKDIR /app

RUN python -m pip install --upgrade pip
RUN pip install poetry gunicorn

COPY . /app

RUN poetry config virtualenvs.create false \
    && poetry install --no-root

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn_config.py", "wsgi:application"]
