# Natverk NOC — Zabbix + Grafana + WhatsApp

Stack completo de monitoramento para clientes: Zabbix + Grafana + alertas
via WhatsApp, instalável com um único comando.

## Instalação

Repositório privado — você precisa de um GitHub Personal Access Token com
permissão de leitura neste repositório (Settings → Developer settings →
Personal access tokens → escopo "Contents: Read-only" restrito a este
repositório).

```bash
export GITHUB_TOKEN=ghp_xxx   # seu token
git clone "https://$GITHUB_TOKEN@github.com/andersmonteiro/zabbix.git" /opt/natverk-noc
cd /opt/natverk-noc
git checkout "$(git tag --sort=-creatordate | head -1)"   # última release estável
./install.sh
```

### Atualizar uma instalação existente

```bash
cd /opt/natverk-noc
git fetch --tags
git checkout "$(git tag --sort=-creatordate | head -1)"
GITHUB_TOKEN=ghp_xxx ./install.sh
```

## Componentes

- `stack/` — Zabbix 7 + Grafana + PostgreSQL/TimescaleDB
- `whatsapp/` — ponte de alertas Zabbix → WhatsApp
- `tools/` — API de diagnóstico de rede (MTR, ping, dig, whois) para uso em dashboards
- `map/` — mapa geográfico dos circuitos de rede, com status ao vivo por segmento e editor de trajeto

Ver `docs/superpowers/specs/` para o desenho completo da arquitetura.
