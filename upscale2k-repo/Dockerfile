FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir opencv-contrib-python-headless numpy
WORKDIR /app
COPY . /app
ENV PORT=7860
EXPOSE 7860
CMD ["python", "server.py"]
