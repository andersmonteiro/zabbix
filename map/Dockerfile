FROM python:3.11-slim

# iputils-ping -- usado por ping_poller.py pra checar disponibilidade ICMP
# direta de cada host, sem depender de um item do Zabbix configurado.
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
