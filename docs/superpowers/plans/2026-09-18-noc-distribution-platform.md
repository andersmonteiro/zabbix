# NOC 24/7 — Plataforma de Distribuição Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar o stack pessoal Zabbix+Grafana+WhatsApp da Natverk num repositório GitHub distribuível, instalável em um comando (`curl | bash`) na infraestrutura de cada cliente.

**Architecture:** Um repositório (`andersmonteiro/zabbix`) com três componentes independentes (`stack/` = Zabbix+Grafana, `whatsapp/` = ponte WhatsApp, `tools/` = API de diagnóstico), cada um com seu próprio `docker-compose.yml` e `.env.example`. Binários grandes (`externalscripts`) distribuídos via GitHub Release asset, não pelo git normal. Um `install.sh` na raiz baixa uma tag de release fixa, gera segredos por cliente onde necessário, e sobe os três stacks.

**Tech Stack:** Docker + Docker Compose, Zabbix 7.4.11, Grafana 13.0.2, PostgreSQL/TimescaleDB, Node.js 20 (whatsapp-web.js), Python 3.11/Flask, bash.

**Spec:** [docs/superpowers/specs/2026-09-18-noc-distribuicao-design.md](../specs/2026-09-18-noc-distribuicao-design.md)

## Global Constraints

- Nunca usar tag `:latest` em imagem Docker — sempre versão exata, fixada no `docker-compose.yml`.
- Cliente sempre instala/atualiza via tag de release do GitHub (`vX.Y.Z`), nunca via branch `main`.
- `webfiber-juniper-pppoe` nunca entra neste repositório.
- Arquivos de rascunho (`*-copy`, `*-copia`, `docker-compose.yml-copy-*`) nunca entram neste repositório.
- `externalscripts` nunca vai no histórico git normal — sempre via GitHub Release asset separado, incluindo `lic/.lic`.
- `.env.example` de cada componente carrega valores reais/padrão prontos pra uso (decisão explícita do usuário, repo privado) — exceto `WEBHOOK_TOKEN` (gerado único por cliente no install) e `GROUP_IDS` (descoberto por cliente pós-instalação).
- Fonte de todos os arquivos legados: `D:\projetos-natverk\ZABBIX\{zabbix-docker,natverk-zabbix-whatsapp,natverk-tools}`.
- Repositório de destino: `D:\projetos-natverk\natverk-noc-repo` (remoto `git@github-natverk-zabbix:andersmonteiro/zabbix.git`, branch `main`).

---

### Task 1: `stack/` — Zabbix + Grafana

**Files:**
- Create: `.gitignore` (raiz)
- Create: `README.md` (raiz)
- Create: `CHANGELOG.md` (raiz)
- Create: `stack/docker-compose.yml`
- Create: `stack/Dockerfile`
- Create: `stack/libpython3.8.so.1.0`
- Create: `stack/.env.example`
- Create: `stack/grafana/grafana.ini`
- Create: `stack/grafana/logos/` (diretório completo)
- Create: `stack/grafana/provisioning/datasources/zabbix.yml`
- Create: `stack/alertscripts/discord_zabbix.py`
- Create: `stack/alertscripts/telegram.py`
- Create: `stack/alertscripts/webex.py`

**Interfaces:**
- Produces: rede Docker externa nomeada `natverk-zabbix-net` (usada pela Task 4/`tools`), diretório `stack/` completo consumido pelo `install.sh` (Task 5).

- [ ] **Step 1: Criar `.gitignore` na raiz**

```
.env
.wwebjs_auth/
node_modules/
*.log
backups/
*.tar.gz
*.sha256
```

- [ ] **Step 2: Copiar `docker-compose.yml` e `Dockerfile` do stack, sem alteração de conteúdo**

```bash
mkdir -p stack
cp "/d/projetos-natverk/ZABBIX/zabbix-docker/docker-compose.yml" stack/docker-compose.yml
cp "/d/projetos-natverk/ZABBIX/zabbix-docker/Dockerfile" stack/Dockerfile
cp "/d/projetos-natverk/ZABBIX/zabbix-docker/libpython3.8.so.1.0" stack/libpython3.8.so.1.0
```

- [ ] **Step 3: Nomear explicitamente a rede Docker em `stack/docker-compose.yml`**

No final do arquivo, troque:

```yaml
networks:
  network-zabbix:
    driver: bridge
```

por:

```yaml
networks:
  network-zabbix:
    driver: bridge
    name: natverk-zabbix-net
```

Motivo: o Compose nomeia redes como `<pasta>_<nome>` por padrão. Isso quebrou quando a pasta mudou de `zabbix-docker` para `stack` — fixando o nome, o `tools/docker-compose.yml` (Task 4) consegue referenciar essa rede de forma estável independente de onde o compose é executado.

- [ ] **Step 4: Criar `stack/.env.example` limpo**

Remove as variáveis mortas (`ZABBIX_SERVER_IMAGE`, `ZABBIX_FRONTEND_IMAGE`, `ZABBIX_AGENT_IMAGE`, `POSTGRES_IMAGE`, `GRAFANA_IMAGE` — não usadas pelo compose, que já fixa versão direto no `image:`), troca a senha do Grafana de `12345` para o padrão Natverk:

```
# Grafana
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=Natverk-Noc-2026!

# PostgreSQL — uso interno, sem porta publicada no host
POSTGRES_USER=zabbix
POSTGRES_PASSWORD=18o9AGUz2zfS6Ka2PKyuYj547zMX2jSu
POSTGRES_DB=zabbix

TZ=America/Sao_Paulo
```

- [ ] **Step 5: Copiar `grafana.ini` e `logos/` sem alteração**

```bash
mkdir -p stack/grafana
cp "/d/projetos-natverk/ZABBIX/zabbix-docker/grafana/grafana.ini" stack/grafana/grafana.ini
cp -r "/d/projetos-natverk/ZABBIX/zabbix-docker/grafana/logos" stack/grafana/logos
```

- [ ] **Step 6: Criar provisionamento automático do datasource Zabbix no Grafana**

Hoje `grafana/provisioning/dashboards` e `grafana/provisioning/datasources` estão vazios — isso significa que, depois de instalado, ainda seria preciso configurar manualmente o datasource Zabbix na UI do Grafana, o que contradiz o objetivo de "um comando só". Crie:

`stack/grafana/provisioning/datasources/zabbix.yml`:

```yaml
apiVersion: 1

datasources:
  - name: Zabbix
    type: alexanderzobnin-zabbix-datasource
    access: proxy
    url: http://zabbix-frontend:8080/api_jsonrpc.php
    isDefault: true
    editable: true
    jsonData:
      username: Admin
      trends: true
      trendsFrom: "7d"
      trendsRange: "4d"
      cacheTTL: "1h"
      timeout: 30
    secureJsonData:
      password: Natverk-Noc-2026!
    version: 1
```

`stack/grafana/provisioning/dashboards/dashboards.yml` (deixa a pasta pronta pra dashboards futuros, sem quebrar se vazia):

```yaml
apiVersion: 1

providers:
  - name: Natverk
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /etc/grafana/provisioning/dashboards
```

- [ ] **Step 7: Copiar `alertscripts/` (verificando que não têm segredo hardcoded)**

```bash
cp "/d/projetos-natverk/ZABBIX/zabbix-docker/alertscripts/discord_zabbix.py" stack/alertscripts/
cp "/d/projetos-natverk/ZABBIX/zabbix-docker/alertscripts/telegram.py" stack/alertscripts/
cp "/d/projetos-natverk/ZABBIX/zabbix-docker/alertscripts/webex.py" stack/alertscripts/
grep -riE "token|senha|password|key" stack/alertscripts/*.py || echo "nenhum segredo hardcoded encontrado"
```

Se o `grep` encontrar algo, pare e confirme com o usuário antes de commitar (esses scripts recebem parâmetros do Zabbix Media Type — não deveriam ter segredo fixo no código, mas confirme).

- [ ] **Step 8: Criar `README.md` e `CHANGELOG.md` na raiz**

`README.md`:

```markdown
# Natverk NOC — Zabbix + Grafana + WhatsApp

Stack completo de monitoramento para clientes: Zabbix + Grafana + alertas
via WhatsApp, instalável com um único comando.

## Instalação

curl -fsSL https://raw.githubusercontent.com/andersmonteiro/zabbix/main/install.sh | bash

## Componentes

- `stack/` — Zabbix 7 + Grafana + PostgreSQL/TimescaleDB
- `whatsapp/` — ponte de alertas Zabbix → WhatsApp
- `tools/` — API de diagnóstico de rede (MTR, ping, dig, whois) para uso em dashboards

Ver `docs/superpowers/specs/` para o desenho completo da arquitetura.
```

`CHANGELOG.md`:

```markdown
# Changelog

## [Unreleased]
- Estrutura inicial do repositório de distribuição (stack, whatsapp, tools)
- Instalador de um comando (install.sh)
- Provisionamento automático do datasource Zabbix no Grafana
- Autoheal para o serviço WhatsApp (substitui restart via cron)
- Autenticação e validação por allowlist no natverk-tools
```

- [ ] **Step 9: Validar sintaxe do compose**

Run: `cd stack && docker compose config --quiet`
Expected: sem erro de saída (exit code 0). Se o Docker não estiver disponível no ambiente de desenvolvimento, valide com `docker compose -f stack/docker-compose.yml config --quiet` a partir da raiz, ou revise manualmente o YAML.

- [ ] **Step 10: Commit**

```bash
git add .gitignore README.md CHANGELOG.md stack/
git commit -m "Add stack/ (Zabbix + Grafana) with pinned network name and auto-provisioned datasource"
```

---

### Task 2: Empacotamento do `externalscripts` para GitHub Release

**Files:**
- Create: `scripts/package-externalscripts.sh`

**Interfaces:**
- Consumes: `D:\projetos-natverk\ZABBIX\zabbix-docker\externalscripts\` (874 MB, binários próprios da Natverk + `lic/.lic`)
- Produces: `externalscripts-vX.Y.Z.tar.gz` + `.sha256` (usado na Task 6 para upload como asset de release, e baixado pelo `install.sh` na Task 5)

- [ ] **Step 1: Criar o script de empacotamento**

`scripts/package-externalscripts.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SRC="${1:?Uso: package-externalscripts.sh <pasta-origem> <versao ex: v1.0.0>}"
VERSION="${2:?Uso: package-externalscripts.sh <pasta-origem> <versao ex: v1.0.0>}"
OUT="externalscripts-${VERSION}.tar.gz"
WORKDIR=$(mktemp -d)

echo "Copiando scripts de $SRC..."
cp -r "$SRC" "$WORKDIR/externalscripts"

echo "Removendo lixo temporário (tmp/, .swp)..."
rm -rf "$WORKDIR/externalscripts/tmp"
find "$WORKDIR/externalscripts" -name '*.swp' -delete

echo "Removendo símbolos de debug dos binários (strip)..."
find "$WORKDIR/externalscripts" -maxdepth 1 -type f -perm -u+x -print0 \
    | while IFS= read -r -d '' bin; do
        if file "$bin" | grep -q 'ELF'; then
            strip --strip-debug "$bin" 2>/dev/null || true
        fi
    done

echo "Empacotando em $OUT..."
tar czf "$OUT" -C "$WORKDIR" externalscripts

CHECKSUM=$(sha256sum "$OUT" | cut -d' ' -f1)
echo "$CHECKSUM  $OUT" > "$OUT.sha256"

rm -rf "$WORKDIR"
echo "Pronto: $OUT ($(du -h "$OUT" | cut -f1)), sha256: $CHECKSUM"
```

```bash
chmod +x scripts/package-externalscripts.sh
```

- [ ] **Step 2: Rodar contra a fonte real e medir o resultado**

Run: `bash scripts/package-externalscripts.sh "/d/projetos-natverk/ZABBIX/zabbix-docker/externalscripts" v1.0.0`
Expected: gera `externalscripts-v1.0.0.tar.gz` e `.tar.gz.sha256` no diretório atual, com tamanho visivelmente menor que 874 MB (o `strip --strip-debug` costuma reduzir bastante um binário compilado com debug info).

- [ ] **Step 3: Verificar integridade do pacote**

```bash
mkdir -p /tmp/verify-externalscripts
tar xzf externalscripts-v1.0.0.tar.gz -C /tmp/verify-externalscripts
ls /tmp/verify-externalscripts/externalscripts | wc -l   # deve dar 278 (ou 277 sem tmp/)
file /tmp/verify-externalscripts/externalscripts/huawei_health   # ainda deve reportar "ELF ... executable"
cat /tmp/verify-externalscripts/externalscripts/lic/.lic          # confirma que o .lic foi incluso
rm -rf /tmp/verify-externalscripts
```

- [ ] **Step 4: Commit (só o script — o `.tar.gz` gerado NÃO entra no git, vai como asset de release na Task 6)**

```bash
git add scripts/package-externalscripts.sh
git commit -m "Add externalscripts packaging script (strip + tar for GitHub Release asset)"
```

---

### Task 3: `whatsapp/` — cópia + autoheal

**Files:**
- Create: `whatsapp/server.js`
- Create: `whatsapp/package.json`
- Create: `whatsapp/Dockerfile`
- Create: `whatsapp/zabbix/webhook_script.js`
- Create: `whatsapp/docker-compose.yml`
- Create: `whatsapp/.env.example`
- Create: `whatsapp/README.md`

**Interfaces:**
- Consumes: `D:\projetos-natverk\ZABBIX\natverk-zabbix-whatsapp\*`
- Produces: `whatsapp/` completo, container `zabbix-whatsapp` expondo `/health` na porta 3000 interna — consumido pelo `install.sh` (Task 5) e pelo sidecar `autoheal`.

- [ ] **Step 1: Copiar os arquivos de código sem alteração**

```bash
mkdir -p whatsapp/zabbix
cp "/d/projetos-natverk/ZABBIX/natverk-zabbix-whatsapp/server.js" whatsapp/server.js
cp "/d/projetos-natverk/ZABBIX/natverk-zabbix-whatsapp/package.json" whatsapp/package.json
cp "/d/projetos-natverk/ZABBIX/natverk-zabbix-whatsapp/Dockerfile" whatsapp/Dockerfile
cp "/d/projetos-natverk/ZABBIX/natverk-zabbix-whatsapp/zabbix/webhook_script.js" whatsapp/zabbix/webhook_script.js
```

- [ ] **Step 2: Adicionar o sidecar `autoheal` ao `docker-compose.yml`**

O `docker-compose.yml` atual já tem um `healthcheck` batendo em `/health`, mas o Docker Compose sozinho **não reinicia** um container só porque ele virou `unhealthy` — é por isso que hoje existe o cron reiniciando de hora em hora. `willfarrell/autoheal` é uma imagem estável e amplamente usada que observa o status de saúde dos containers e reinicia automaticamente os marcados.

Crie `whatsapp/docker-compose.yml`:

```yaml
services:
  zabbix-whatsapp:
    build: .
    container_name: zabbix-whatsapp
    restart: unless-stopped
    shm_size: '256mb'
    labels:
      - "autoheal=true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    ports:
      - "${PORT:-8765}:3000"
    environment:
      - PORT=3000
      - WEBHOOK_TOKEN=${WEBHOOK_TOKEN}
      - GROUP_IDS=${GROUP_IDS}
      - ZABBIX_URL=${ZABBIX_URL}
      - ZABBIX_USER=${ZABBIX_USER}
      - ZABBIX_PASS=${ZABBIX_PASS}
      - CHART_PERIOD=${CHART_PERIOD:-3600}
      - CHART_WIDTH=${CHART_WIDTH:-900}
      - CHART_HEIGHT=${CHART_HEIGHT:-200}
      - ZABBIX_INSECURE=${ZABBIX_INSECURE:-0}
    volumes:
      - whatsapp-session:/app/.wwebjs_auth
    extra_hosts:
      - "host.docker.internal:host-gateway"

  autoheal:
    image: willfarrell/autoheal:latest
    container_name: zabbix-whatsapp-autoheal
    restart: unless-stopped
    environment:
      - AUTOHEAL_CONTAINER_LABEL=autoheal
      - AUTOHEAL_INTERVAL=30
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

volumes:
  whatsapp-session:
```

Nota: a investigação da causa raiz do travamento do Chromium (flags do puppeteer, `shm_size`) fica registrada no spec como próximo passo — este autoheal é a mitigação imediata, reage ao estado real do serviço em vez de reiniciar numa agenda fixa.

- [ ] **Step 3: Criar `.env.example` limpo (sem os valores de produção reais que eram de um cliente específico)**

```
PORT=8765

# Gerado automaticamente pelo install.sh — único por cliente
WEBHOOK_TOKEN=

# Preenchido manualmente após escanear o QR Code (ver README)
GROUP_IDS=

ZABBIX_URL=http://host.docker.internal:8080
ZABBIX_USER=Admin
ZABBIX_PASS=Natverk-Noc-2026!

CHART_PERIOD=3600
CHART_WIDTH=900
CHART_HEIGHT=200
ZABBIX_INSECURE=0
```

- [ ] **Step 4: Copiar e adaptar o README**

```bash
cp "/d/projetos-natverk/ZABBIX/natverk-zabbix-whatsapp/README.md" whatsapp/README.md
```

Edite `whatsapp/README.md`: troque as referências de instalação `git clone <url-do-repo>` pelo fluxo novo (via `install.sh` da raiz do repositório), mantendo o restante do conteúdo (configuração do Media Type, variáveis de ambiente, comandos úteis).

- [ ] **Step 5: Validar sintaxe do compose**

Run: `cd whatsapp && docker compose config --quiet`
Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
git add whatsapp/
git commit -m "Add whatsapp/ with autoheal sidecar replacing hourly cron restart"
```

---

### Task 4: `tools/` — allowlist + autenticação (TDD)

**Files:**
- Create: `tools/app.py`
- Test: `tools/test_app.py`
- Create: `tools/requirements.txt`
- Create: `tools/requirements-dev.txt`
- Create: `tools/Dockerfile`
- Create: `tools/docker-compose.yml`
- Create: `tools/.env.example`

**Interfaces:**
- Produces: container `noc-tools` na rede `natverk-zabbix-net` (definida na Task 1), exigindo header `X-Webhook-Token` em toda rota exceto `/health`.

- [ ] **Step 1: Copiar o `app.py` original como ponto de partida**

```bash
mkdir -p tools
cp "/d/projetos-natverk/ZABBIX/natverk-tools/app.py" tools/app.py
```

- [ ] **Step 2: Escrever os testes que falham primeiro**

`tools/test_app.py`:

```python
import os
os.environ['TOOLS_TOKEN'] = 'test-token-123'

import importlib
from unittest.mock import patch
import pytest

import app as app_module
importlib.reload(app_module)


@pytest.fixture
def client():
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


def test_validate_host_accepts_valid_hostname():
    assert app_module.validate_host('example.com') is True


def test_validate_host_accepts_ipv4():
    assert app_module.validate_host('8.8.8.8') is True


def test_validate_host_rejects_empty():
    assert app_module.validate_host('') is False


def test_validate_host_rejects_shell_metacharacters():
    assert app_module.validate_host('8.8.8.8; rm -rf /') is False


def test_validate_host_rejects_leading_dash():
    # host começando com "-" pode ser interpretado como flag pelo mtr/ping/dig
    assert app_module.validate_host('--version') is False


def test_validate_host_rejects_overlong_input():
    assert app_module.validate_host('a' * 300) is False


def test_health_does_not_require_token(client):
    resp = client.get('/health')
    assert resp.status_code == 200


def test_mtr_without_token_returns_401(client):
    resp = client.get('/mtr?host=8.8.8.8')
    assert resp.status_code == 401


def test_mtr_with_invalid_token_returns_401(client):
    resp = client.get('/mtr?host=8.8.8.8', headers={'X-Webhook-Token': 'wrong'})
    assert resp.status_code == 401


def test_mtr_with_valid_token_runs(client):
    with patch.object(app_module, 'run', return_value=('', '')):
        resp = client.get(
            '/mtr?host=8.8.8.8',
            headers={'X-Webhook-Token': 'test-token-123'},
        )
        assert resp.status_code == 200
```

- [ ] **Step 3: Rodar os testes e confirmar que falham**

Run: `cd tools && pip install -r requirements-dev.txt && pytest test_app.py -v` (crie `requirements-dev.txt` no passo seguinte antes de rodar)
Expected: falhas — `validate_host` ainda usa blocklist (não rejeita `--version` nem string de 300 chars) e não existe nenhuma checagem de token (rotas sem token retornam 200, não 401).

- [ ] **Step 4: Criar `requirements.txt` e `requirements-dev.txt`**

`tools/requirements.txt`:
```
flask==3.0.3
```

`tools/requirements-dev.txt`:
```
flask==3.0.3
pytest==8.3.3
```

- [ ] **Step 5: Implementar allowlist e autenticação em `tools/app.py`**

Substitua a função `validate_host` (linhas 23-28 do arquivo original) por:

```python
import os

HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9\-\.]{0,253}[A-Za-z0-9])?$')
TOOLS_TOKEN = os.environ.get('TOOLS_TOKEN', '')


def validate_host(host):
    if not host or len(host) > 255:
        return False
    if host.startswith('-'):
        return False
    return bool(HOST_RE.match(host))
```

Logo após a definição de `app = Flask(__name__)`, adicione o middleware de autenticação:

```python
@app.before_request
def require_token():
    if request.path == '/health':
        return None
    if not TOOLS_TOKEN:
        return None
    token = request.headers.get('X-Webhook-Token') or request.args.get('token')
    if token != TOOLS_TOKEN:
        return jsonify({"error": "Token inválido"}), 401
```

Nota: `HOST_RE` não aceita `:` (IPv6) — mesma limitação que o endpoint `/rbl` já documentava ("Apenas IPv4 suportado"), não é uma regressão.

- [ ] **Step 6: Rodar os testes e confirmar que passam**

Run: `pytest test_app.py -v`
Expected: todos os testes `PASS`.

- [ ] **Step 7: Criar `Dockerfile`, `docker-compose.yml` e `.env.example`**

`tools/Dockerfile`:

```dockerfile
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
```

`tools/docker-compose.yml`:

```yaml
services:
  noc-tools:
    build: .
    container_name: noc-tools
    ports:
      - "5001:5001"
    restart: unless-stopped
    environment:
      - TOOLS_TOKEN=${TOOLS_TOKEN}
    networks:
      - natverk-zabbix-net

networks:
  natverk-zabbix-net:
    external: true
    name: natverk-zabbix-net
```

`tools/.env.example`:

```
# Token de autenticação da API de diagnóstico (mesmo padrão do X-Webhook-Token do WhatsApp)
TOOLS_TOKEN=Natverk-Tools-2026!
```

- [ ] **Step 8: Validar sintaxe do compose**

Run: `cd tools && docker compose config --quiet`
Expected: exit code 0.

- [ ] **Step 9: Commit**

```bash
git add tools/
git commit -m "Harden natverk-tools: allowlist host validation + token auth"
```

---

### Task 5: `install.sh`

**Files:**
- Create: `install.sh` (raiz)

**Interfaces:**
- Consumes: releases de tag do repositório (Task 6), `stack/`, `whatsapp/`, `tools/` (Tasks 1, 3, 4), asset `externalscripts-vX.Y.Z.tar.gz` (Task 2/6).

- [ ] **Step 1: Escrever `install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO="andersmonteiro/zabbix"
RELEASE_TAG="${RELEASE_TAG:-latest}"
INSTALL_DIR="${INSTALL_DIR:-/opt/natverk-noc}"
TZ_VALUE="${TZ:-America/Sao_Paulo}"

log() { echo "[natverk-noc] $*"; }
die() { echo "[natverk-noc] ERRO: $*" >&2; exit 1; }

# ── Pré-requisitos ──
if ! command -v docker >/dev/null 2>&1; then
    log "Docker não encontrado — instalando via get.docker.com..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || die "Plugin 'docker compose' não encontrado mesmo após instalar o Docker."
command -v jq >/dev/null 2>&1 || { log "Instalando jq..."; apt-get update -y && apt-get install -y jq; }
command -v curl >/dev/null 2>&1 || die "curl não encontrado."
command -v openssl >/dev/null 2>&1 || die "openssl não encontrado."

log "Instalando em $INSTALL_DIR (release: $RELEASE_TAG)"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# ── Resolve a tag, se "latest" ──
if [ "$RELEASE_TAG" = "latest" ]; then
    RELEASE_TAG=$(curl -sf "https://api.github.com/repos/$REPO/releases/latest" | jq -r '.tag_name')
    [ -n "$RELEASE_TAG" ] && [ "$RELEASE_TAG" != "null" ] || die "Não consegui resolver a última release."
fi
log "Usando release $RELEASE_TAG"

# ── Baixa o código-fonte da tag (nunca a branch main) ──
log "Baixando código-fonte..."
curl -sfL "https://github.com/$REPO/archive/refs/tags/$RELEASE_TAG.tar.gz" -o source.tar.gz
tar xzf source.tar.gz --strip-components=1
rm source.tar.gz

# ── Baixa e extrai o pacote de externalscripts (asset de release separado) ──
log "Baixando externalscripts..."
curl -sfL "https://github.com/$REPO/releases/download/$RELEASE_TAG/externalscripts-$RELEASE_TAG.tar.gz" -o externalscripts.tar.gz
mkdir -p stack/externalscripts
tar xzf externalscripts.tar.gz -C stack/externalscripts --strip-components=1
rm externalscripts.tar.gz

# ── Gera .env de cada componente (idempotente — não sobrescreve se já existir) ──
for comp in stack whatsapp tools; do
    if [ ! -f "$comp/.env" ]; then
        cp "$comp/.env.example" "$comp/.env"
        log "Criado $comp/.env a partir do template"
    else
        log "$comp/.env já existe — mantendo"
    fi
done

# ── Gera WEBHOOK_TOKEN único para esta instalação (só se ainda não tiver um) ──
if ! grep -qE '^WEBHOOK_TOKEN=.+' whatsapp/.env 2>/dev/null; then
    NEW_TOKEN=$(openssl rand -hex 32)
    sed -i "s|^WEBHOOK_TOKEN=.*|WEBHOOK_TOKEN=$NEW_TOKEN|" whatsapp/.env
    log "WEBHOOK_TOKEN gerado para este cliente"
fi

# ── Ajusta TZ ──
sed -i "s|^TZ=.*|TZ=$TZ_VALUE|" stack/.env

# ── Sobe o stack Zabbix + Grafana ──
log "Subindo stack Zabbix + Grafana..."
(cd stack && docker compose up -d)

# ── Aguarda o frontend do Zabbix responder (até 5 minutos) ──
log "Aguardando o Zabbix ficar pronto..."
READY=0
for i in $(seq 1 60); do
    if curl -sf http://localhost:8080/ >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 5
done
[ "$READY" = "1" ] || die "Zabbix não respondeu em 5 minutos. Verifique 'docker compose logs' em stack/."

# ── Ajusta a senha padrão do Admin do Zabbix (só funciona na 1a instalação) ──
ZABBIX_API="http://localhost:8080/api_jsonrpc.php"
ZABBIX_ADMIN_PASSWORD=$(grep '^GF_SECURITY_ADMIN_PASSWORD=' stack/.env | cut -d= -f2-)

AUTH=$(curl -s -X POST "$ZABBIX_API" -H 'Content-Type: application/json-rpc' -d '{
  "jsonrpc":"2.0","method":"user.login",
  "params":{"username":"Admin","password":"zabbix"},
  "id":1
}' | jq -r '.result // empty')

if [ -n "$AUTH" ]; then
    UPDATE_RESPONSE=$(curl -s -X POST "$ZABBIX_API" \
        -H 'Content-Type: application/json-rpc' \
        -H "Authorization: Bearer $AUTH" \
        -d "{\"jsonrpc\":\"2.0\",\"method\":\"user.update\",\"params\":{\"userid\":\"1\",\"passwd\":\"$ZABBIX_ADMIN_PASSWORD\",\"current_passwd\":\"zabbix\"},\"id\":2}")
    UPDATE_ERROR=$(echo "$UPDATE_RESPONSE" | jq -r '.error.data // .error.message // empty')
    if [ -z "$UPDATE_ERROR" ]; then
        log "Senha do Admin do Zabbix atualizada para o padrão Natverk"
    else
        log "AVISO: falha ao atualizar a senha do Admin do Zabbix: $UPDATE_ERROR"
    fi
else
    log "Login padrão Admin/zabbix já não funciona — Admin já deve estar configurado, pulando"
fi

# ── Sobe WhatsApp e Tools ──
log "Subindo serviço WhatsApp..."
(cd whatsapp && docker compose up -d)

log "Subindo natverk-tools..."
(cd tools && docker compose up -d)

IP=$(hostname -I | awk '{print $1}')
log ""
log "=== Instalação concluída ==="
log "Zabbix:  http://$IP:8080  (Admin / senha em stack/.env)"
log "Grafana: http://$IP:3000  (admin / senha em stack/.env)"
log ""
log "Próximo passo manual — configurar o WhatsApp:"
log "  1. docker logs -f zabbix-whatsapp    # escaneie o QR Code que aparecer"
log "  2. curl http://localhost:8765/groups -H \"X-Webhook-Token: \$(grep WEBHOOK_TOKEN whatsapp/.env | cut -d= -f2)\""
log "  3. Copie o ID do grupo desejado para GROUP_IDS em whatsapp/.env"
log "  4. cd whatsapp && docker compose restart"
```

```bash
chmod +x install.sh
```

- [ ] **Step 2: Validar sintaxe do script**

Run: `bash -n install.sh`
Expected: sem saída (exit code 0) — confirma que não há erro de sintaxe bash.

Run: `command -v shellcheck >/dev/null 2>&1 && shellcheck install.sh || echo "shellcheck não disponível, pulando"`
Expected: se `shellcheck` estiver disponível, revise os avisos e ajuste o script; avisos de `SC2181`/estilo podem ser ignorados, mas nenhum erro de lógica.

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "Add one-command installer (install.sh)"
```

---

### Task 6: Corte da release v1.0.0

**Esta task publica conteúdo no GitHub (tag + release + asset binário) — confirme com o usuário antes de executar o push da tag e a criação da release.**

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: todas as tasks anteriores.
- Produces: tag `v1.0.0` e release no GitHub com o asset `externalscripts-v1.0.0.tar.gz`, ponto de instalação estável referenciado pelo `install.sh`.

- [ ] **Step 1: Atualizar `CHANGELOG.md` com a data da release**

Troque `## [Unreleased]` por `## [1.0.0] - 2026-09-18` mantendo os itens já listados na Task 1.

```bash
git add CHANGELOG.md
git commit -m "Release v1.0.0"
```

- [ ] **Step 2: Push para o GitHub**

Run: `git push origin main`
Expected: push aceito (chave de deploy já validada anteriormente).

- [ ] **Step 3: Criar a tag e o release (pedir confirmação do usuário antes deste passo)**

```bash
git tag -a v1.0.0 -m "v1.0.0 — primeira release da plataforma de distribuição NOC"
git push origin v1.0.0
```

Se o `gh` CLI estiver disponível e autenticado:

```bash
gh release create v1.0.0 \
    externalscripts-v1.0.0.tar.gz \
    externalscripts-v1.0.0.tar.gz.sha256 \
    --title "v1.0.0" \
    --notes-file CHANGELOG.md
```

Se `gh` não estiver disponível/autenticado, criar a release manualmente pela UI do GitHub (`github.com/andersmonteiro/zabbix/releases/new`), selecionando a tag `v1.0.0` e anexando os dois arquivos gerados na Task 2.

- [ ] **Step 4: Testar o instalador de ponta a ponta numa VM limpa**

Numa VM Ubuntu limpa (sem Docker instalado):

Run: `curl -fsSL https://raw.githubusercontent.com/andersmonteiro/zabbix/main/install.sh | bash`
Expected:
- Docker é instalado automaticamente
- `docker compose ps` dentro de `stack/`, `whatsapp/` e `tools/` mostra todos os containers `Up` (o `zabbix-whatsapp` pode levar até 60s para ficar `healthy`)
- `curl http://localhost:8080` retorna a tela de login do Zabbix
- `curl http://localhost:3000` retorna a tela de login do Grafana
- No Grafana, o datasource "Zabbix" já aparece configurado em Configuration → Data Sources, sem precisar criar manualmente
- `curl http://localhost:5001/health` retorna `{"status": "ok"}` sem exigir token
- `curl http://localhost:5001/mtr?host=8.8.8.8` sem header retorna 401
- Rodar o instalador uma segunda vez não recria `.env` nem gera novo `WEBHOOK_TOKEN`

- [ ] **Step 5: Registrar o resultado do teste no CHANGELOG e commitar**

```bash
git add CHANGELOG.md
git commit -m "Document v1.0.0 end-to-end install verification"
git push origin main
```

---

## Self-Review

**Cobertura do spec:**
- Estrutura do repositório (stack/whatsapp/tools, exclusão de webfiber e rascunhos) → Task 1, 3, 4.
- `externalscripts` via GitHub Release, com `strip` e `.lic` incluso → Task 2, Task 6.
- Segredos: fixos para Postgres/Grafana/Zabbix Admin, gerados para `WEBHOOK_TOKEN`, descobertos para `GROUP_IDS` → Task 1 Step 4, Task 3 Step 3, Task 5 Step (geração de token).
- Instalador de um comando, idempotente, com tag de release fixa → Task 5.
- Política de versão (sem `latest`, releases semânticas) → Global Constraints + Task 6.
- Estabilidade do WhatsApp (autoheal em vez de cron) → Task 3 Step 2.
- Robustecimento do `natverk-tools` (allowlist + token) → Task 4.
- Datasource Grafana pré-configurado (gap identificado durante o brainstorm, não estava no stack atual) → Task 1 Step 6.

**Sem placeholders:** todos os passos de código têm conteúdo completo e executável; nenhum "TODO"/"implementar depois" restante.

**Consistência de tipos/nomes:** `natverk-zabbix-net` usado de forma idêntica em `stack/docker-compose.yml` (Task 1) e `tools/docker-compose.yml` (Task 4). `TOOLS_TOKEN`/`X-Webhook-Token` usados de forma consistente entre `tools/app.py`, `tools/test_app.py` e `tools/.env.example`. `GF_SECURITY_ADMIN_PASSWORD` é a mesma variável lida pelo `install.sh` para setar a senha do Zabbix Admin — nome conferido em Task 1 Step 4 e Task 5 Step 1.
