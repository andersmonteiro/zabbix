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

> **Remova o token do repositório clonado.** O `git clone` com o token na URL
> grava esse token em texto puro em `/opt/natverk-noc/.git/config` — de forma
> permanente, não só durante o clone. Logo após clonar:
>
> ```bash
> cd /opt/natverk-noc
> git remote set-url origin https://github.com/andersmonteiro/zabbix.git
> ```
>
> A partir daí o token passa a ser fornecido por invocação (via variável de
> ambiente), como no fluxo de atualização abaixo.

### Atualizar uma instalação existente

Como o token não fica mais salvo no `.git/config`, ele precisa ser fornecido
novamente neste momento:

```bash
cd /opt/natverk-noc
git -c http.extraHeader="Authorization: Bearer $GITHUB_TOKEN" fetch --tags
git checkout "$(git tag --sort=-creatordate | head -1)"
GITHUB_TOKEN=ghp_xxx ./install.sh
```

## Componentes

- `stack/` — Zabbix 7 + Grafana + PostgreSQL/TimescaleDB
- `whatsapp/` — ponte de alertas Zabbix → WhatsApp
- `tools/` — API de diagnóstico de rede (MTR, ping, dig, whois) para uso em dashboards
- `map/` — mapa geográfico dos circuitos de rede, com status ao vivo por segmento e editor de trajeto

Ver `docs/superpowers/specs/` para o desenho completo da arquitetura.
