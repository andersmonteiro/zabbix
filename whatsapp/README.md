# natverk-zabbix-whatsapp

Integração **Zabbix → WhatsApp** que envia alertas com screenshot do gráfico para grupos do WhatsApp.  
Sem Twilio, sem Meta Business API, sem custo.

---

## Funcionalidades

- Recebe alertas do Zabbix via webhook
- Anexa screenshot do gráfico do item automaticamente
- Envia para um ou mais grupos do WhatsApp
- Mensagem formatada com ícones por severidade
- Autenticação por token (`X-Webhook-Token`)
- Auto re-login quando a sessão Zabbix expira
- Logs com timestamp em todas as saídas
- Suporte a instalação via **systemd** ou **Docker**

---

## Instalação — Bare Metal (systemd)

### 1. Dependências

```bash
sudo apt-get update
sudo apt-get install -y nodejs npm \
    libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2t64 libnss3 libnspr4 \
    libatspi2.0-0t64 libgtk-3-0t64 libx11-xcb1 libxshmfence1
```

### 2. Instalar

Este diretório faz parte do repositório `natverk-noc-repo`. O fluxo recomendado é o instalador de um comando, executado a partir da raiz do repositório (ver README principal):

```bash
export GITHUB_TOKEN=ghp_xxx   # repositório privado — veja o README principal
git clone "https://$GITHUB_TOKEN@github.com/andersmonteiro/zabbix.git" /opt/natverk-noc
cd /opt/natverk-noc
git remote set-url origin https://github.com/andersmonteiro/zabbix.git   # tira o token do .git/config
git checkout "$(git tag --sort=-creatordate | head -1)"
./install.sh
```

> O `git clone` com o token na URL grava esse token em texto puro em
> `/opt/natverk-noc/.git/config` permanentemente — por isso o
> `git remote set-url` logo após clonar. Nas atualizações posteriores o token
> volta a ser fornecido por invocação:
> `git -c http.extraHeader="Authorization: Bearer $GITHUB_TOKEN" fetch --tags`
> (ver README principal).

Para uma instalação manual (apenas este componente, fora do fluxo Docker do `install.sh`):

```bash
git clone "https://$GITHUB_TOKEN@github.com/andersmonteiro/zabbix.git" /opt/natverk-noc
cd /opt/natverk-noc
git remote set-url origin https://github.com/andersmonteiro/zabbix.git   # tira o token do .git/config
cd whatsapp
npm install
```

### 3. Configurar

```bash
cp .env.example .env
nano .env
```

### 4. Primeiro boot — QR Code

```bash
node server.js
# Escaneie o QR Code: WhatsApp → Dispositivos vinculados → Vincular dispositivo
```

### 5. Descobrir ID do grupo

```bash
curl http://localhost:8765/groups \
  -H "X-Webhook-Token: SEU_TOKEN"
```

Cole o ID no `GROUP_IDS` do `.env` e reinicie.

### 6. Systemd

```bash
sudo nano /etc/systemd/system/zabbix-whatsapp.service
```

```ini
[Unit]
Description=Natverk Zabbix WhatsApp Webhook
After=network.target

[Service]
WorkingDirectory=/opt/natverk-noc/whatsapp
ExecStart=/usr/bin/node /opt/natverk-noc/whatsapp/server.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zabbix-whatsapp
```

---

## Instalação — Docker

### 1. Configurar

```bash
cp .env.example .env
nano .env
# ZABBIX_URL=http://host.docker.internal:8080
```

### 2. Primeiro boot — QR Code

```bash
docker compose up --build
# Escaneie o QR Code no terminal
```

### 3. Descobrir ID do grupo

```bash
curl http://localhost:8765/groups \
  -H "X-Webhook-Token: SEU_TOKEN"
```

Cole o ID no `GROUP_IDS` do `.env`.

### 4. Subir em background

```bash
docker compose down
docker compose up -d
docker logs -f zabbix-whatsapp
```

---

## Configuração no Zabbix

### Media Type

- **Administration → Media Types → Criar**
- Type: `Webhook`
- Parâmetros obrigatórios:

| Nome | Valor |
|---|---|
| `webhook_url` | `http://IP_DO_SERVIDOR:8765/webhook` |
| `webhook_token` | seu token |
| `event_id` | `{EVENT.ID}` |
| `host` | `{HOST.NAME}` |
| `itemid` | `{ITEM.ID1}` |
| `message` | `{ALERT.MESSAGE}` |
| `severity` | `{TRIGGER.SEVERITY}` |
| `status` | `{TRIGGER.STATUS}` |
| `subject` | `{ALERT.SUBJECT}` |
| `timestamp` | `{EVENT.DATE} {EVENT.TIME}` |
| `trigger_name` | `{TRIGGER.NAME}` |
| `value` | `{ITEM.VALUE1}` |

- Cole o conteúdo de `zabbix/webhook_script.js` no campo **Script**

### Usuário

- **Administration → Users → Admin → aba Media → Add**
  - Type: `WhatsApp Webhook`
  - Send to: `ID_DO_GRUPO@g.us`
  - When active: `1-7,00:00-24:00`
  - Severidades: todas marcadas

### Action

- **Alerts → Actions → Trigger actions → Create action**
  - **Operations:** Admin via WhatsApp Webhook
  - **Recovery operations:** Admin via WhatsApp Webhook
  - **Update operations:** Admin via WhatsApp Webhook

---

## Variáveis de ambiente

| Variável | Obrigatório | Default | Descrição |
|---|---|---|---|
| `PORT` | ❌ | `3000` | Porta HTTP do servidor |
| `WEBHOOK_TOKEN` | ✅ | — | Token de autenticação (`openssl rand -hex 32`) |
| `GROUP_IDS` | ✅ | — | IDs dos grupos, separados por vírgula |
| `ZABBIX_URL` | ❌ | — | URL do frontend Zabbix (sem `/` final) |
| `ZABBIX_USER` | ❌ | — | Usuário Zabbix (leitura nos hosts) |
| `ZABBIX_PASS` | ❌ | — | Senha do usuário |
| `CHART_PERIOD` | ❌ | `3600` | Janela do gráfico em segundos |
| `CHART_WIDTH` | ❌ | `900` | Largura do PNG |
| `CHART_HEIGHT` | ❌ | `200` | Altura do PNG |
| `ZABBIX_INSECURE` | ❌ | `0` | `1` para ignorar SSL autoassinado |

---

## Endpoints

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/webhook` | Recebe alertas do Zabbix |
| `GET` | `/groups` | Lista grupos do WhatsApp |
| `GET` | `/test-chart?itemid=X` | Testa download de gráfico |
| `GET` | `/health` | Status do serviço |

Todos os endpoints (exceto `/health`) exigem o header `X-Webhook-Token`.

---

## Comandos úteis

```bash
# Testar webhook manualmente
curl -X POST http://localhost:8765/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: SEU_TOKEN" \
  -d '{"subject":"Teste","message":"Mensagem de teste","severity":"high","host":"srv-teste","itemid":""}'

# Verificar saúde
curl http://localhost:8765/health

# Listar grupos
curl http://localhost:8765/groups -H "X-Webhook-Token: SEU_TOKEN"
```

---

## Pontos de atenção

- Use um **chip dedicado** para o WhatsApp — não use o número pessoal
- A sessão fica salva em `.wwebjs_auth/` — faça backup desta pasta
- Se a sessão expirar, pare o serviço, rode `node server.js` manualmente, escaneie o QR e suba novamente
- Grafana usa a porta `3000` — use `8765` para o webhook
- Se o Zabbix rodar em container no mesmo host, use `http://host.docker.internal:PORTA` no `ZABBIX_URL`

---

**Natverk** — Infraestrutura & Telecomunicações
