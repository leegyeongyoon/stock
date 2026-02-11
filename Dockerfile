FROM python:3.11-slim

WORKDIR /app

# Timezone 설정 (한국 시간)
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev tzdata && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY src/ src/
COPY migrations/ migrations/
COPY main.py .
COPY run_server.py .

EXPOSE 8088

CMD ["python", "run_server.py"]
