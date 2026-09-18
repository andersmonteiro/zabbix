# NOC 24/7 — Plataforma de Distribuição Zabbix + Grafana + WhatsApp

**Data:** 2026-09-18
**Status:** Em revisão

## Contexto e objetivo

A Natverk quer vender monitoramento de infraestrutura para clientes (provedores de
internet / ISPs) como um serviço "NOC 24/7". A base técnica já existe e está em uso
hoje, de forma não produtizada, em `D:\projetos-natverk\ZABBIX`:

- **`zabbix-docker`** — stack Docker com Zabbix 7 (server/frontend/agent) +
  PostgreSQL/TimescaleDB + Grafana, mais 278 scripts externos (binários ELF
  compilados, próprios da Natverk) cobrindo monitoramento de OLTs, switches,
  roteadores, CMTS, DWDM, PPPoE, CGNAT, geradores e integrações com sistemas de
  gestão de provedor (IXC, Hubsoft), GLPI, Graylog.
- **`natverk-zabbix-whatsapp`** — serviço Node.js (whatsapp-web.js) que recebe
  webhook de alerta do Zabbix, anexa print do gráfico do item e envia para
  grupo(s) de WhatsApp. Já funcional, com doc de instalação (systemd/Docker).
- **`natverk-tools`** — API Flask simples para diagnóstico de rede (MTR) sob
  demanda.

O objetivo deste projeto é transformar essa base pessoal/single-tenant numa
**plataforma distribuível**: um repositório GitHub privado
(`github.com/andersmonteiro/zabbix`) que serve como ponto central de
distribuição, e um instalador de um comando (`curl | bash`) que sobe o stack
completo na infraestrutura de cada cliente.

`webfiber-juniper-pppoe` (monitoramento dedicado de um cliente específico com
Juniper MX5) **fica fora** deste projeto — não é genérico, não vai para o
GitHub, permanece como referência local caso outro cliente use Juniper no
futuro.

## Fora de escopo (fases futuras)

- Abertura automática de chamados nas operadoras (com ou sem agente de IA) —
  precisa de análise por operadora, não entra nesta fase.
- Aproveitamento de métricas/IA nativa do Zabbix 8 para alertas
  personalizados — especulativo até o Zabbix 8 estabilizar; a política de
  versão (abaixo) já prepara o terreno para adoção quando fizer sentido.

## Estrutura do repositório

Repositório novo, local em `D:\projetos-natverk\natverk-noc-repo`, remoto
`git@github.com:andersmonteiro/zabbix.git` (privado):

```
zabbix/
├── install.sh                    # instalador único, curl | bash
├── CHANGELOG.md
├── stack/                        # ex-zabbix-docker
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── .env.example              # chaves + valores padrão (ver "Segredos")
│   ├── grafana/
│   │   ├── grafana.ini
│   │   └── provisioning/
│   └── alertscripts/              # discord_zabbix.py, telegram.py, webex.py
├── whatsapp/                     # ex-natverk-zabbix-whatsapp
│   ├── server.js, package.json, Dockerfile, docker-compose.yml
│   ├── .env.example
│   └── zabbix/webhook_script.js
└── tools/                        # ex-natverk-tools, endurecido
    ├── app.py, Dockerfile, docker-compose.yml
```

`externalscripts` (874 MB de binários próprios da Natverk, com `lic/.lic`
necessário para funcionamento) **não vai no histórico do git normal** — vira
asset de uma *GitHub Release* (ex: `externalscripts-v1.0.0.tar.gz`), incluindo
o `.lic` como está. Motivo: git versiona mal binário grande recompilado
(infla o histórico permanentemente a cada rebuild); manter fora do clone
normal mantém o `git clone`/`git pull` rápido. Os binários serão processados
com `strip` antes de empacotar, para reduzir o tamanho sem alterar
funcionamento. O `install.sh` baixa os dois pacotes (código + externalscripts)
separadamente.

Arquivos de rascunho (`*-copy`, `*-copia`, `docker-compose.yml-copy-*`) não
entram — são lixo de desenvolvimento local, sem função.

`net-snmp` não entra como source tree completa — só o subdiretório `mibs/`
(usado via bind-mount no `docker-compose.yml`), que é pequeno e é o único
pedaço realmente consumido em runtime.

## Segredos e `.env`

Decisão explícita do cliente (Anderson): como o repositório é **privado** e
o objetivo é instalar com um único comando sem precisar gerar/rastrear
credencial por cliente, os `.env.example` carregam **valores reais e fixos**
para as credenciais que a Natverk usa para dar suporte — não são
placeholders vazios. Variáveis não utilizadas pelo `docker-compose.yml`
(`ZABBIX_SERVER_IMAGE`, `ZABBIX_FRONTEND_IMAGE`, `ZABBIX_AGENT_IMAGE`,
`POSTGRES_IMAGE`, `GRAFANA_IMAGE` — o compose já fixa versão direto no
`image:`) são removidas do `.env` por serem mortas/confusas.

| Variável | Tratamento | Motivo |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Fixo, igual em todo cliente | Postgres não expõe porta pro host no compose — só é alcançável de dentro da rede Docker do próprio stack. Reuso entre clientes não expõe nada externamente. |
| `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` (Grafana) | Fixo, igual em todo cliente | Acesso administrativo padrão da Natverk para suporte, sem precisar rastrear senha por cliente. Senha atual (`12345`) será trocada por algo padrão porém não trivial, já que a porta 3000 é exposta na rede do cliente. |
| Login Admin do Zabbix | Fixo, igual em todo cliente | Mesmo motivo acima — portas 8080/8443 expostas. |
| `WEBHOOK_TOKEN` (whatsapp) | **Gerado único por cliente** no install (`openssl rand -hex 32`) | É token de autenticação de API — cada instalação do serviço WhatsApp é independente por cliente; reuso quebraria o isolamento entre clientes. |
| `GROUP_IDS` (whatsapp) | **Descoberto por cliente**, pós-instalação | Só existe depois do QR Code escaneado naquele WhatsApp específico do cliente — não dá pra pré-preencher. O `install.sh` imprime o passo a passo. |
| `ZABBIX_PASS` (usado pelo serviço whatsapp pra logar na API do Zabbix e gerar print do gráfico) | Mesmo valor fixo do Admin do Zabbix | É a mesma conta administrativa reutilizada. |

## `install.sh` — instalador de um comando

Fluxo:

1. Verifica/instala pré-requisitos (Docker + plugin Docker Compose) — alvo
   inicial Ubuntu/Debian, alinhado com a documentação atual do
   `natverk-zabbix-whatsapp`.
2. Baixa uma **tag de release fixa** do repositório (ex: `v1.0.0`) — nunca
   a branch `main` diretamente, para garantir que o cliente nunca receba
   algo em estado intermediário/quebrado.
3. Baixa e extrai o asset de release `externalscripts-vX.Y.Z.tar.gz`
   (binários já com `strip` aplicado, incluindo `.lic`).
4. Copia `.env.example` → `.env` em cada componente (`stack/`, `whatsapp/`,
   `tools/`), preenchendo automaticamente `WEBHOOK_TOKEN` com valor único
   gerado na hora; demais variáveis usam os valores padrão já definidos nos
   `.env.example`.
5. Sobe os três `docker compose up -d` (stack, whatsapp, tools).
6. Imprime os próximos passos manuais: escanear o QR Code do WhatsApp
   (`docker logs -f` do container whatsapp), descobrir `GROUP_IDS` via
   `curl .../groups`, preencher no `.env` do whatsapp e reiniciar o
   container.
7. É **idempotente**: rodar de novo com uma tag nova atualiza (`docker
   compose pull && up -d`) sem apagar `.env` nem volumes de dados
   (Postgres, sessão do WhatsApp em `.wwebjs_auth/`).

## Política de versões

- `docker-compose.yml` continua fixando versão exata de imagem
  (`ubuntu-7.4.11`, `grafana:13.0.2`, etc.) — nunca `:latest`.
- Releases do GitHub com tags semânticas (`v1.0.0`, `v1.1.0`...) marcam
  pontos testados/estáveis. Cliente sempre instala/atualiza via tag, nunca
  via `main`.
- Quando Zabbix 8 sair estável (não beta/RC), a atualização vira uma nova
  release testada — não é troca automática via `latest`.

## Estabilidade do serviço WhatsApp

Problema atual: sob volume de alertas, o Chromium/puppeteer usado pelo
whatsapp-web.js trava (suspeita de vazamento de memória/cache). Mitigação
atual em produção é um cron reiniciando o container a cada hora, cega ao
estado real do serviço.

Mudança proposta: substituir o cron por **healthcheck no
`docker-compose.yml`** (`GET /health` em intervalo curto) combinado com
`restart: unless-stopped` — o Docker só reinicia quando o serviço
realmente está degradado, não numa agenda fixa que pode interromper um
envio em andamento. O volume `.wwebjs_auth/` é preservado no restart, então
não é necessário reescanear o QR Code a cada reinício.

Investigação da causa raiz (flags do Chromium como
`--disable-dev-shm-usage`, ajuste de `shm_size` do container) fica
registrada como próximo passo, fora do escopo de resolver por completo
nesta fase — a mitigação via healthcheck já é uma melhoria concreta sobre o
cron atual.

## `natverk-tools` — robustecimento

Hoje é uma API Flask com endpoint `/mtr` que valida o host recebido via
blocklist de caracteres perigosos. Antes de entrar na distribuição para
clientes, precisa de:

- Validação de entrada por **allowlist** de formato (IP ou hostname válido),
  não blocklist de caracteres.
- Autenticação por token nos endpoints, no mesmo padrão do
  `X-Webhook-Token` já usado pelo serviço WhatsApp.

## Acesso do Claude ao repositório

Chave SSH dedicada (`~/.ssh/id_claude_natverk`, já existente) cadastrada
como Deploy Key no GitHub com permissão de escrita, usada via alias SSH
`github-natverk-zabbix` configurado em `~/.ssh/config`. Pendente: usuário
adicionar a chave pública em
`github.com/andersmonteiro/zabbix/settings/keys`.

## Testes

- `install.sh` testado em VM limpa Ubuntu (instalação do zero) e em cima de
  uma instalação anterior (fluxo de update, idempotência).
- Verificar que containers sobem saudáveis (`docker compose ps`, healthcheck
  do whatsapp) e que o webhook do Zabbix chega no WhatsApp de teste
  (`/webhook` de teste do README atual).
- Verificar que `tools/` recusa host inválido e exige token.
