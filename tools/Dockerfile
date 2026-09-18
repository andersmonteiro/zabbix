FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    mtr \
    whois \
    traceroute \
    iputils-ping \
    dnsutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["python", "app.py"]
