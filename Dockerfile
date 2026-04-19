FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/
COPY formica/ /app/formica/
RUN pip install --no-cache-dir -e ".[openai,ollama,bedrock]"

# Default: agent entrypoint. Overridden for controller pods.
ENV PYTHONUNBUFFERED=1
ENV FORMICA_COMPONENT=forager
CMD ["python", "-m", "formica.agents.entrypoint"]
