# Changelog

## [1.0.0] - 2026-09-18
- Estrutura inicial do repositório de distribuição (stack, whatsapp, tools)
- Instalador de um comando (install.sh)
- Provisionamento automático do datasource Zabbix no Grafana
- Autoheal para o serviço WhatsApp (substitui restart via cron)
- Autenticação e validação por allowlist no natverk-tools
- Correção: senha do Admin do Zabbix agora é aplicada corretamente via API (campo `passwd` + `current_passwd`, com checagem de erro)
- Correção: TimescaleDB fixado em versão exata (`2.30.1-pg18`), não mais `:latest-pg18`
- Correção: autoheal fixado em versão exata (`1.2.0`), não mais `:latest`
- Correção: instalador é obtido via GitHub Release em vez da branch `main`
