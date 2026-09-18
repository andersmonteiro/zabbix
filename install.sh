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
    curl -s -X POST "$ZABBIX_API" \
        -H 'Content-Type: application/json-rpc' \
        -H "Authorization: Bearer $AUTH" \
        -d "{\"jsonrpc\":\"2.0\",\"method\":\"user.update\",\"params\":{\"userid\":\"1\",\"password\":\"$ZABBIX_ADMIN_PASSWORD\"},\"id\":2}" \
        >/dev/null
    log "Senha do Admin do Zabbix atualizada para o padrão Natverk"
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
