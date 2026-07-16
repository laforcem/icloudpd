FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY bot ./bot
RUN pip install --no-cache-dir --disable-pip-version-check .
EXPOSE 8090
ENTRYPOINT ["python", "-m", "bot.main"]
