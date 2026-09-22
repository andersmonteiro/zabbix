#!/usr/bin/env bash
set -euo pipefail

# Este repositório é PRIVADO. Este script espera rodar de dentro de um
# clone já no commit/tag desejado (git clone, não curl) — veja o README
# para o comando de clone com GITHUB_TOKEN. Ele não baixa mais o
# código-fonte via curl; git clone já é a forma de obter o código para um
# repositório privado. O único download HTTP que este script ainda faz é
# o asset binário de externalscripts, que nunca vai no git (não faz parte
# de um clone), via a API do GitHub com o mesmo token.
TZ_VALUE="${TZ:-America/Sao_Paulo}"

log() { echo "[natverk-noc] $*"; }
die() { echo "[natverk-noc] ERRO: $*" >&2; exit 1; }

: "${GITHUB_TOKEN:?GITHUB_TOKEN não definido. Repositório privado — gere um Personal Access Token (leitura de Contents neste repositório) e rode: GITHUB_TOKEN=ghp_xxx ./install.sh — a partir de um clone já no tag desejado (veja o README).}"
REPO="andersmonteiro/zabbix"
GH_AUTH_HEADER="Authorization: Bearer $GITHUB_TOKEN"

[ -f install.sh ] && [ -d stack ] && [ -d whatsapp ] && [ -d tools ] \
    || die "Rode este script de dentro de um clone do repositório (git clone ...), não isoladamente. Veja o README."

# ── Pré-requisitos ──
if ! command -v docker >/dev/null 2>&1; then
    log "Docker não encontrado — instalando via get.docker.com..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || die "Plugin 'docker compose' não encontrado mesmo após instalar o Docker."
command -v jq >/dev/null 2>&1 || { log "Instalando jq..."; apt-get update -y && apt-get install -y jq; }
command -v git >/dev/null 2>&1 || die "git não encontrado."
command -v curl >/dev/null 2>&1 || die "curl não encontrado."
command -v openssl >/dev/null 2>&1 || die "openssl não encontrado."

RELEASE_TAG=$(git describe --tags --exact-match 2>/dev/null || echo "")
[ -n "$RELEASE_TAG" ] || die "O diretório atual não está numa tag de release (rode 'git checkout <tag>' antes). Nunca instale a partir da branch main."
log "Instalando release $RELEASE_TAG"

# ── Baixa e extrai o pacote de externalscripts (asset de release separado — não faz parte do git clone) ──
log "Baixando externalscripts..."
EXTERNALSCRIPTS_ASSET_NAME="externalscripts-$RELEASE_TAG.tar.gz"
RELEASE_JSON=$(curl -sf -H "$GH_AUTH_HEADER" -H "Accept: application/vnd.github+json" "https://api.github.com/repos/$REPO/releases/tags/$RELEASE_TAG") \
    || die "Falha ao consultar a release $RELEASE_TAG na API do GitHub — verifique se o GITHUB_TOKEN é válido e tem acesso a este repositório."
ASSET_ID=$(echo "$RELEASE_JSON" | jq -r --arg NAME "$EXTERNALSCRIPTS_ASSET_NAME" '.assets[] | select(.name == $NAME) | .id')
[ -n "$ASSET_ID" ] && [ "$ASSET_ID" != "null" ] || die "Não encontrei o asset $EXTERNALSCRIPTS_ASSET_NAME na release $RELEASE_TAG."
curl -sfL -H "$GH_AUTH_HEADER" -H "Accept: application/octet-stream" "https://api.github.com/repos/$REPO/releases/assets/$ASSET_ID" -o externalscripts.tar.gz
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
