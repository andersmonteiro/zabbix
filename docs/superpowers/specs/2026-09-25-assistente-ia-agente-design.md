# Assistente de IA com Acesso a Equipamentos — Design

**Data:** 2026-09-25
**Status:** Em revisão

## Contexto e objetivo

Hoje o operador do NOC só enxerga o que o Zabbix já coletou — e vimos nesta
mesma plataforma casos reais onde isso não basta: os 16 switches
Datacom/DTC não têm telemetria óptica no Zabbix (o template deles não faz
discovery de SFP), e itens do tipo trapper (alimentados por script externo)
às vezes nunca recebem dado. A ideia é dar ao operador — e depois ao
cliente final — uma forma de perguntar em linguagem natural ("qual o sinal
da porta 3 do switch X", "quantos PPPoE estão online", "essa interface
caiu quando?") e receber a resposta consultando o equipamento **direto**,
sem depender só do que o Zabbix já tem coletado.

A Natverk já opera múltiplos clientes, cada um com sua própria instalação
isolada (VM, Zabbix, banco, `map/` — via `install.sh`, v1.x). A meta
explícita deste projeto é que o agente escale para essa carteira inteira
desde o desenho inicial, não só para o cliente atual.

## Decisões já tomadas (não revisar)

- **Só consulta, nunca alteração.** O agente roda comandos de leitura
  (`display`, `print`, etc.) e nunca comandos de configuração. Mudar
  parâmetros de rede via IA é uma possibilidade explicitamente adiada — se
  vier, é um módulo separado, com seu próprio fluxo de confirmação, fora
  desta spec.
- **Nunca comando livre gerado pelo modelo.** Cada "ferramenta" que o
  modelo pode chamar já nasce com o comando exato embutido no código,
  testado manualmente contra o equipamento real antes de entrar no
  catálogo. O modelo escolhe **qual** ferramenta chamar e com quais
  parâmetros (host, porta) — nunca compõe o texto do comando.
- **Acesso via SSH + CLI**, não NETCONF — mais simples de validar no MVP;
  frágil a mudança de firmware é um risco aceito conscientemente, mitigado
  pelo catálogo ser pequeno e testado manualmente.
- **MVP cobre dois fabricantes**: Huawei VRP (NE8000) e Mikrotik
  RouterOS — os dois já presentes no backbone real do primeiro cliente.
- **Modelo de IA: Claude Sonnet 5.** Ver seção "Modelo de IA e custo" para
  o raciocínio completo (benchmarks de tool-calling, comparação de preço
  com Gemini/GPT, e por que não usar Opus ou um modelo "mini/nano" agora).
- **Arquitetura centralizada desde o início** (não uma instância isolada
  por cliente, ao contrário do resto da plataforma — ver justificativa na
  próxima seção). Roda numa VM da própria Natverk, já disponível.
- **Chat substitui o mapa como tela inicial.** O mapa passa a ser um item
  próprio da barra lateral (ver seção "Interface de chat").
- **Fases de acesso**: Fase 1 só equipe Natverk; Fase 2 abre para o
  cliente final, cada um só enxergando os próprios equipamentos.
- **Sem áudio no MVP.** Mencionado na ideia original, mas é uma camada de
  complexidade separada (Web Speech API ou upload+transcrição) que não
  bloqueia nenhum caso de uso real — fica para depois do MVP validado.

## Por que centralizado (ao contrário do mapa/Zabbix, que é descentralizado)

A spec do mapa de circuitos (`2026-09-22-network-circuit-map-design.md`)
decidiu o oposto para o Zabbix/Grafana: "centralizar exigiria proxy/VPN
por cliente, concentra risco de segurança, cria ponto único de falha, e
não escala". Essa lógica continua válida para dados operacionais —
mas o agente de IA tem uma variável diferente: **a chave da API do
Claude**, que é dinheiro real por token e uma credencial de alto valor.

Se o agente rodasse local em cada instalação (mesmo padrão do resto da
plataforma) usando uma chave compartilhada da Natverk, essa chave ficaria
fisicamente presente em **cada VM de cliente** — uma VM comprometida vaza
a chave mestra de todos os clientes, não só daquele. Duas saídas:

1. **Chave própria por cliente, agente continua local.** Mais simples,
   resolve o risco (uma VM comprometida só vaza a própria chave), mas não
   dá visão agregada de custo/uso e escala mal em número de chaves a
   gerenciar conforme a carteira cresce.
2. **Agente de verdade centralizado**, rodando fora das VMs de cliente.
   Única chave, nunca sai da infra da Natverk. Cada VM de cliente só
   expõe endpoints de ferramentas (SSH/Zabbix), autenticados por token
   próprio daquele cliente — as credenciais de equipamento (SSH, Zabbix)
   nunca saem da VM do cliente, só a decisão "qual ferramenta chamar" é
   centralizada.

**Escolhido: opção 2**, por pedido explícito do usuário — a meta é
escalar para toda a carteira de clientes, não só validar com um.
O trade-off aceito conscientemente: um ponto único de falha novo (se o
serviço central cair, todos os clientes perdem o agente ao mesmo tempo) e
uma peça de infraestrutura a mais para manter no ar. A VM onde esse
serviço roda já existe (infra própria da Natverk, fora das VMs de
cliente).

## Arquitetura

Dois lados, dois repositórios/deploys diferentes:

```
┌─────────────────────────────┐         ┌──────────────────────────────┐
│  VM do Cliente (ex: WNP)     │         │  VM da Natverk (nova)         │
│  já rodando via install.sh   │         │  agente-central/               │
│                               │         │                                │
│  map/                        │         │  chat.py                      │
│    static/assistente.html    │◄───────►│    -- recebe pergunta,        │
│    (tela de chat, novo)      │  HTTPS  │       identifica cliente pelo  │
│                               │ +token  │       AGENT_TOKEN             │
│  agent_tools/ (novo)         │         │  claude_agent.py               │
│    ssh_catalog.py            │◄───────►│    -- roda o tool-calling do   │
│    ssh_client.py             │  HTTPS  │       Claude (única chave,     │
│    routes_agent_tools.py     │ +token  │       só existe aqui)          │
│    (POST /api/agent-tools/*) │         │  clients.py                   │
│                               │         │    -- registro: URL + token   │
│  (credenciais SSH/Zabbix      │         │       de cada cliente         │
│   nunca saem daqui)           │         │  audit.py                     │
│                               │         │    -- log agregado de todos   │
└─────────────────────────────┘         │       os clientes             │
                                          └──────────────────────────────┘
```

### Fluxo de uma pergunta

1. Operador digita a pergunta na tela de chat, dentro da VM do cliente.
2. O frontend manda a pergunta pro serviço central
   (`POST https://agente.natverk.com.br/chat`), com o `AGENT_TOKEN`
   daquele cliente identificando quem está perguntando.
3. O serviço central roda `client.beta.messages.tool_runner(...)`
   (Claude Sonnet 5, tools = catálogo de capacidades) — única chave,
   mora só aqui.
4. Quando o modelo decide chamar uma ferramenta (ex: `sinal_optico`,
   `porta=3`), o serviço central chama de volta
   `https://vm-cliente.natverk.com.br/api/agent-tools/sinal_optico?porta=3`,
   autenticado com o **token daquele cliente especificamente** — o
   serviço central só consegue rodar ferramentas na VM de quem já tem
   token cadastrado, nunca em outra.
5. A VM do cliente roda o comando SSH real (ou consulta o Zabbix local
   primeiro, se o dado já estiver fresco lá — ver "Ordem de fontes"),
   devolve o resultado ao serviço central.
6. O serviço central formata a resposta em português e transmite de
   volta ao chat via streaming (Server-Sent Events).

### Ordem de fontes por ferramenta

Cada ferramenta primeiro tenta o Zabbix local do cliente (rápido, já
coletado); só cai para SSH direto no equipamento quando o dado não existe
ou está manifestamente obsoleto (mesma lógica de `lastclock == '0'` já
usada no mapa para trapper items nunca coletados). Isso significa que a
"VM do cliente" no diagrama acima, ao receber uma chamada de ferramenta,
decide internamente Zabbix-ou-SSH — o serviço central não precisa saber
qual fonte foi usada, só recebe o resultado.

## Catálogo de ferramentas (capacidades × fabricantes)

Baseado nos exemplos concretos dados ao longo desta conversa:

| Capacidade | Huawei VRP | Mikrotik RouterOS |
|---|---|---|
| `sinal_optico(porta)` | `display interface {porta} optical-info` | `/interface ethernet monitor {porta} once` |
| `status_interface(porta)` | `display interface {porta}` | `/interface print detail where name={porta}` |
| `uptime_equipamento()` | `display device` | `/system resource print` |
| `erros_interface(porta)` | `display interface {porta} \| include error` | `/interface print stats where name={porta}` |
| `pppoe_online()` | `display access-user online-total-number` | `/ppp active print count-only` |
| `prefixos_bgp(vizinho_ip)` | `display bgp routing-table peer {ip} advertised-routes` | `/routing bgp advertisements print peer={ip}` |
| `ip_vlan(vlan_id)` | `display interface Vlanif{vlan_id}` | `/ip address print where interface=vlan{vlan_id}` |
| `logs_equipamento(data)` | `display logbuffer` (filtrado por data) | `/log print where time>={data}` |
| `ultimo_status_interface(porta)` | `display trap-buffer \| include {porta}` | `/log print where topics~"interface" and message~"{porta}"` |
| `historico_trafego(porta, horas)` | reaproveita `GET /api/segments/<id>/history` já existente no mapa (Zabbix) | idem |
| `grafico_trafego(porta, horas)` | reaproveita o sparkline SVG já construído no mapa, renderizado como PNG | idem |

Cada linha desta tabela precisa ser validada manualmente contra um
equipamento real antes de entrar em produção — os comandos acima são o
ponto de partida, não comandos já testados.

**Nota técnica em aberto:** `grafico_trafego` precisa converter o
sparkline (hoje um `<svg>` gerado em JS, renderizado no navegador) em uma
imagem PNG enviável dentro da conversa — isso roda no serviço central ou
no lado do cliente, e a técnica exata (ex: renderizar o mesmo SVG
server-side com uma lib Python, ou gerar o gráfico direto em Python sem
reaproveitar o JS) fica para o plano de implementação decidir.

## Modelo de segurança

1. **Sem geração de comando pelo modelo** (já coberto acima).
2. **Usuário SSH read-only dedicado**, separado do usuário administrativo
   já cadastrado, quando o equipamento suportar perfil de só-leitura.
3. **Auditoria centralizada**: toda chamada de ferramenta grava, no
   serviço central, quem perguntou (usuário + cliente), qual ferramenta,
   host/porta, comando exato executado do lado do cliente, resposta
   resumida, timestamp.
4. **Timeout e rate limit por host**, evitando que uma conversa abra
   muitas conexões SSH simultâneas no mesmo equipamento.
5. **Token por cliente** (`AGENT_TOKEN`, gerado pelo `install.sh` do
   mesmo jeito que `WEBHOOK_TOKEN` já é hoje) — o serviço central mantém
   um cadastro simples de `cliente → (URL da VM, token)`; sem esse
   cadastro, nenhuma VM de cliente aceita chamada do serviço central.
6. **Escopo por usuário (Fase 2)**: usuários do tipo `usuario_cliente` só
   podem perguntar sobre hosts associados a eles (reaproveitando os
   `hostgroups` do Zabbix ou uma tabela de associação nova); usuários
   `equipe_natverk` não têm essa restrição. Toda ferramenta recebe o
   usuário autor da pergunta e valida escopo antes de rodar qualquer
   coisa.

## Interface de chat

Substitui `index.html` como tela inicial; o mapa se move para uma rota
própria (`/mapa.html`) e ganha seu próprio item na barra lateral.

- Mensagem de boas-vindas com 3-4 sugestões clicáveis, orientando o que a
  ferramenta sabe responder.
- Resposta em streaming (SSE), mesma sensação de digitar do Claude.ai.
- Indicador de progresso enquanto uma ferramenta roda (ex: "consultando
  DTC-CARACOL-6 via SSH...") — uma consulta SSH real pode levar alguns
  segundos.
- Histórico persistido (`agent_messages`: usuário, papel, texto,
  ferramentas usadas, timestamp) — permite auditoria e retomar a conversa
  ao recarregar. Uma conversa contínua por usuário, sem múltiplas
  conversas nomeadas (YAGNI: adicionar depois se fizer falta).
- Reaproveita o design system já construído nesta sessão (Geist Mono
  maiúsculo, paleta oklch, cantos retos, barra dourada no topo).

## Modelo de IA e custo

**Claude Sonnet 5** ($2/$10 por milhão de tokens input/output), não Opus
nem um modelo "mini/nano" de outro provedor. Raciocínio, na ordem em que
foi discutido:

- O catálogo de ferramentas é pequeno (~10-15 capacidades) e bem definido
  — é "roteamento com contexto", não um problema difícil que justifique
  o custo do Opus.
- Em benchmarks agregados de tool-calling (BFCL e outros, 52 benchmarks),
  a família Claude Opus lidera com >99% de acurácia em tool-use padrão;
  Claude Opus 5.5 fica em 2º lugar geral (atrás só de um modelo lançado
  recentemente por outro provedor). O Gemini Flash não aparece entre os
  líderes desses benchmarks.
- Modelos "mini/nano/flash-lite" de outros provedores são
  significativamente mais baratos (até ~40x), mas totalizam menos
  confiabilidade em cadeias de tool-calling com parâmetros técnicos — o
  tipo de erro caro de descobrir depois (ferramenta certa, parâmetro
  errado), rodando contra equipamento real de produção de um ISP.
- Empresas de telecom em escala grande (Cisco, NVIDIA, SoftBank) tendem a
  usar modelos especializados/fine-tuned ou self-hosted para este tipo de
  tarefa — um caminho que exige treinar e hospedar modelo próprio,
  claramente fora de escopo para o estágio atual deste projeto.
- Migrar de Sonnet para Opus depois é uma troca de uma linha de código
  (mesmo SDK, mesma arquitetura de tools) — não é uma decisão que trava o
  projeto.

## Fora de escopo (Fase 2 ou além)

- Áudio como entrada.
- Aplicar mudanças de configuração via IA (só consulta no MVP).
- Múltiplas conversas nomeadas por usuário (uma conversa contínua basta
  por ora).
- Cobrança de uso por cliente (a chave é única, paga pela Natverk; se o
  volume justificar, rever depois).
- Fabricantes além de Huawei VRP e Mikrotik RouterOS (Datacom/DTC é o
  próximo candidato natural, dado que é o vendor com a lacuna real de
  telemetria hoje — mas fica para depois de validar o MVP nos dois
  primeiros).

## Dados/schema necessários

Novas tabelas, no banco de **cada cliente** (mesmo Postgres do `map/`):

- `agent_messages`: histórico de conversa (usuário, papel, texto,
  ferramentas usadas, timestamp).

Nova tabela, no banco do **serviço central**:

- `agent_clients`: cadastro de clientes (nome, URL da VM, `AGENT_TOKEN`).
- `agent_audit_log`: log agregado de todas as chamadas de ferramenta, de
  todos os clientes.

Novo campo em `whatsapp/.env`-equivalente de cada cliente (ou
`map/.env`): `AGENT_TOKEN`, gerado pelo `install.sh` do mesmo jeito que
`WEBHOOK_TOKEN` já é hoje.
