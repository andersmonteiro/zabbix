# Mapa de Circuitos de Rede — Design

**Data:** 2026-09-22
**Status:** Em revisão

## Contexto e objetivo

A Natverk quer um mapa geográfico real mostrando o caminho físico dos
circuitos de rede dos clientes (fibra, rádio, etc.), com status ao vivo por
segmento e por equipamento. Serve dois propósitos: operação do NOC (ver
rápido onde está o problema, com detalhe de sinal óptico/throughput/erros
por porta) e vitrine comercial (visual bonito pra demonstrar a clientes em
potencial).

Hoje não existe relação "circuito → quais portas o compõem" registrada em
nenhum sistema — nasce do zero nesta ferramenta. Alguns clientes têm ERPs
(IXC, SGP, TopSapp) com dados de caixa FTTH que poderiam alimentar isso no
futuro, mas isso fica fora do escopo desta primeira versão.

## Fora de escopo (decisões já tomadas, não revisar)

- **Sem Zabbix/Grafana centralizado.** Cada cliente mantém seu stack
  dedicado, como já construído e publicado (v1.0.0). Centralizar exigiria
  proxy/VPN por cliente, concentra risco de segurança (todos os dados num
  banco só), cria ponto único de falha, e não escala o processamento
  conforme a carteira de clientes cresce.
- **Sem integração com IXC/SGP/TopSapp nesta versão.** Fica marcado como
  extensão futura da tela de Circuitos.
- **Sem Zabbix adicional pra visão agregada da Natverk nesta versão.**
  Confirmado como tecnicamente viável (item HTTP agent do Zabbix consultando
  a API `api_jsonrpc.php` de cada Zabbix de cliente), mas é trabalho futuro
  separado.

## Arquitetura

Novo componente `map/`, no mesmo repositório de distribuição
(`andersmonteiro/zabbix`), ao lado de `stack/`, `whatsapp/`, `tools/`,
instalado como mais um serviço do `install.sh`. **Decentralizado — uma
instância por cliente**, dentro do stack dele, lendo só do Zabbix local
daquele cliente (mesmo modelo do resto da plataforma).

- **Backend**: Flask (mesmo padrão do `tools/`), schema próprio no Postgres
  que já roda no stack do cliente.
- **Frontend**: estático, servido pelo próprio backend — Leaflet.js +
  plugin Leaflet-Geoman (edição de linha arrastando vértice).
- **Mapa base**: OpenStreetMap por padrão (grátis, sem conta, sem risco de
  cota por cliente). Provedor de tile é **configurável por instalação** —
  quem quiser o visual mais elaborado (Mapbox GL, 3D) pode configurar um
  token próprio via `.env`; sem token configurado, cai pro OpenStreetMap
  automaticamente. Decisão tomada assim porque o produto é vendido pra
  múltiplos clientes — depender de uma cota Mapbox compartilhada não escala
  com o negócio.
- Nenhuma coleta nova no Zabbix — reaproveita os itens que os
  `externalscripts` já coletam por vendor (sinal óptico, throughput, status
  de porta, contadores de erro).

## Modelo de dados

- **Ponto**: nome, coordenada (lat/lng), tipo:
  - `trajeto` — só visual, molda a linha do circuito seguindo rua/poste, sem
    nenhum dado de monitoramento associado
  - `equipamento` — associado a um host do Zabbix (`hostid`), tem modelo do
    equipamento (usado pra buscar a foto no popup) e coordenada
- **Circuito**: nome, lista ordenada de segmentos
- **Segmento**: dois pontos-equipamento nas pontas (origem/destino) + lista
  ordenada de pontos-trajeto entre eles (desenha a linha real) +
  `itemid`s do Zabbix que alimentam velocidade, throughput (in/out), sinal
  óptico (RX), contadores de erro daquele enlace + **limiar de sinal
  configurável** (dBm) que define quando o segmento fica laranja — varia
  por tipo de SFP/equipamento, não é um valor fixo do sistema

## Layout e interação (validado com mockups interativos)

- **Sidebar de navegação à esquerda**, estilo macOS: só texto (sem ícone
  colorido/emoji), item ativo com fundo azul sólido, fonte do sistema.
  Itens: Início (mapa), Circuitos (CRUD de circuito/segmento/ponto, inclui
  o campo de limiar de sinal), Configurações (imagens de equipamento por
  modelo, provedor de tile). Um quarto item ("Opções") apareceu na conversa
  mas seu conteúdo não foi definido — fica como espaço reservado na sidebar
  pra uma tela futura, sem funcionalidade nesta versão.
- **Mapa ocupa o centro inteiro** da tela.
- **Status por cor**, tanto em equipamento (círculo com halo suave) quanto
  em linha de circuito (linha com brilho suave por baixo, ponta
  arredondada): **verde** = up, **laranja** = alerta/sinal abaixo do limiar
  configurado, **vermelho** = down.
- **Hover**: tooltip leve e rápido — status, uptime, última queda, sinal
  óptico, velocidade/throughput no host; nome/IP/status/uptime/última queda
  no equipamento.
- **Clique**: abre popup centralizado na tela, com foto do equipamento (ou
  ícone genérico se o modelo não tiver foto cadastrada) no topo, seguido de
  uma **tabela** (linha por linha, zebrada, rótulo à esquerda/valor à
  direita) com todos os detalhes — porta, velocidade, throughput, sinal,
  uptime do enlace, última queda, erros (circuito) ou modelo, IP, status,
  CPU, uptime, última queda (equipamento).
- **Edição de trajeto**: botão "Editar trajeto" no popup do circuito
  habilita o modo de edição do Leaflet-Geoman — arrastar pontos existentes,
  clicar pra adicionar novo ponto de trajeto. Salvar grava a nova lista de
  pontos-trajeto do segmento via API.

## Atualização de dados ao vivo

O backend consulta a API do Zabbix do cliente **periodicamente (a cada
30–60s)**, não a cada requisição do navegador, e mantém um cache do último
valor de cada item monitorado. O frontend consulta só esse cache. Evita
sobrecarregar a API do Zabbix a cada abertura/interação do mapa.

## Tratamento de erro

- **Zabbix indisponível** (backend não consegue atualizar o cache): pontos
  e circuitos afetados ficam **cinza** com indicação de "dados desde X min
  atrás" — nunca mantém a última cor como se estivesse tudo bem.
- **Host/item referenciado foi apagado no Zabbix**: não quebra o mapa;
  aparece como aviso de configuração na aba Circuitos.
- **Coordenada inválida/faltando**: o ponto não é desenhado no mapa, mas
  aparece sinalizado na lista de circuitos pra correção.

## Testes

Mesmo padrão do `tools/`: TDD na lógica testável sem navegador — cálculo de
status (verde/laranja/vermelho a partir do valor bruto + limiar
configurado do segmento), CRUD de ponto/circuito/segmento na API. A parte
visual (mapa, arrastar linha, popups) é validada manualmente no navegador.

## Extensões futuras (fora desta spec)

- Integração com IXC/SGP/TopSapp pra puxar caixa FTTH automaticamente em
  vez de cadastro manual.
- Zabbix adicional só da Natverk, consultando via HTTP agent item a API de
  cada Zabbix de cliente, pra visão agregada entre clientes.
