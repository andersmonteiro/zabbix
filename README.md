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
