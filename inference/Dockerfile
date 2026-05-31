# Dockerfile for deploying the Guava inference service to a Hugging Face Space.
# HF Spaces run the container and expose port 7860 by convention.
FROM python:3.11-slim

# ffmpeg is needed for audio decoding.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
