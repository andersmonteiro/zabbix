/**
 * Natverk — Zabbix → WhatsApp Webhook
 * Envia alertas do Zabbix para grupos do WhatsApp com screenshot do gráfico.
 */

require('dotenv').config();
const express = require('express');
const fs      = require('fs');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const qrcodeImage = require('qrcode');
const puppeteer = require('puppeteer');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ─── Helpers ──────────────────────────────────────────────────────────────────
function log(level, msg) {
    const ts = new Date().toISOString();
    console.log(`[${ts}] [${level}] ${msg}`);
}

// Rede de segurança: uma promise rejeitada sem .catch em qualquer lugar
// (inclusive dentro do whatsapp-web.js/puppeteer, fora do nosso controle)
// derruba o processo Node inteiro por padrão -- foi exatamente assim que
// um bug de serialização do whatsapp-web.js (msg.getChat()) matava o bot
// a cada mensagem recebida, sem nunca chegar a responder (o container só
// reiniciava sozinho depois, sem logar nada útil sobre a causa real).
// Só loga e segue vivo -- a reconexão de verdade (sessão caiu de fato)
// continua sendo tratada pelo listener 'disconnected' do client.
process.on('unhandledRejection', (err) => {
    log('ERROR', `Promise rejeitada sem tratamento: ${err?.stack || err}`);
});

// ─── Limpa locks do Chromium no startup ──────────────────────────────────────
const lockFiles = [
    './.wwebjs_auth/session/SingletonLock',
    './.wwebjs_auth/session/SingletonCookie',
    './.wwebjs_auth/session/SingletonSocket',
];
lockFiles.forEach(f => {
    try {
        fs.unlinkSync(f);
        log('INFO', `Lock removido: ${f}`);
    } catch (e) {
        // Arquivo não existe — normal
    }
});

// ─── Configurações ────────────────────────────────────────────────────────────
const PORT          = process.env.PORT          || 3000;
const WEBHOOK_TOKEN = process.env.WEBHOOK_TOKEN || '';
const GROUP_IDS     = (process.env.GROUP_IDS    || '').split(',').map(s => s.trim()).filter(Boolean);
const ZABBIX_URL    = (process.env.ZABBIX_URL   || '').replace(/\/$/, '');
const ZABBIX_USER   = process.env.ZABBIX_USER   || '';
const ZABBIX_PASS   = process.env.ZABBIX_PASS   || '';
const CHART_PERIOD  = parseInt(process.env.CHART_PERIOD || '3600', 10);
const CHART_WIDTH   = parseInt(process.env.CHART_WIDTH  || '900',  10);
const CHART_HEIGHT  = parseInt(process.env.CHART_HEIGHT || '200',  10);

// ─── IA (agent.natverk.com.br) ────────────────────────────────────────────────
// Token de um cliente cadastrado em /admin/clients no painel do agente central
// (ex: nome "whatsapp") -- sem ele, a integração fica desligada e mensagens
// recebidas são só ignoradas (não quebra o resto do serviço).
const AI_AGENT_URL          = process.env.AI_AGENT_URL          || 'https://agent.natverk.com.br/chat';
const AI_AGENT_TOKEN        = process.env.AI_AGENT_TOKEN        || '';
const AI_CHAT_ENABLED       = AI_AGENT_TOKEN !== '';
// Vazio = responde qualquer DM (e grupos, se mencionado). Preenchido = só
// responde os chats/grupos nessa lista (IDs no formato "5511999999999@c.us"
// ou "XXXXXXXXXX@g.us", iguais aos retornados por GET /groups).
const AI_ALLOWED_CHATS      = (process.env.AI_ALLOWED_CHATS || '').split(',').map(s => s.trim()).filter(Boolean);
const AI_REQUEST_TIMEOUT_MS = parseInt(process.env.AI_REQUEST_TIMEOUT_MS || '60000', 10);
// Cadastro simples "quem é quem" pra o agente poder chamar a pessoa pelo
// nome -- formato "numero:Nome,numero:Nome". O número pode ser colado como
// a pessoa realmente fala o próprio número (com +55, espaço, traço,
// parênteses, com ou sem o DDD do país) -- normalizeDigits() e o
// comparador por sufixo abaixo cuidam de casar isso com o id de verdade do
// WhatsApp ("5551999999999@c.us"), sem precisar saber esse formato.
// Editar exige redeploy; se isso virar algo usado com frequência, vale uma
// tela própria no painel em vez de só variável de ambiente.
function normalizeDigits(value) {
    return String(value).replace(/\D/g, '');
}

const AI_SENDER_NAMES = (process.env.AI_SENDER_NAMES || '')
    .split(',')
    .map((pair) => pair.trim())
    .filter(Boolean)
    .map((pair) => {
        const idx = pair.indexOf(':');
        return [normalizeDigits(pair.slice(0, idx)), pair.slice(idx + 1).trim()];
    })
    .filter(([digits, name]) => digits && name);

function lookupSenderName(senderId) {
    const senderDigits = normalizeDigits(senderId);
    const match = AI_SENDER_NAMES.find(([digits]) => senderDigits.endsWith(digits));
    return match ? match[1] : null;
}

if (process.env.ZABBIX_INSECURE === '1') {
    process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
    log('WARN', 'Verificação SSL desativada (ZABBIX_INSECURE=1)');
}

// ─── Cliente WhatsApp ─────────────────────────────────────────────────────────
let clientReady = false;
let consecutiveErrors = 0;
const MAX_CONSECUTIVE_ERRORS = 3;

function createClient() {
    return new Client({
        authStrategy: new LocalAuth({ dataPath: './.wwebjs_auth' }),
        puppeteer: {
            headless: true,
            protocolTimeout: 60000,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ],
        },
    });
}

let client = createClient();
// Guarda o texto cru do QR mais recente -- qrcode-terminal só desenha no
// console (inútil remotamente); GET /qr (abaixo) renderiza ESTE valor como
// imagem de verdade pra escanear a partir de qualquer lugar. None depois
// que a sessão autentica, pra /qr não ficar mostrando um código vencido.
let latestQr = null;

function setupClientEvents(c) {
    c.on('qr', (qr) => {
        latestQr = qr;
        log('INFO', 'Escaneie o QR Code abaixo com o WhatsApp (ou acesse GET /qr):');
        qrcode.generate(qr, { small: true });
    });

    c.on('authenticated', () => {
        latestQr = null;
        log('INFO', 'WhatsApp autenticado!');
    });

    c.on('ready', () => {
        clientReady = true;
        consecutiveErrors = 0;
        latestQr = null;
        log('INFO', `WhatsApp pronto! Porta ${PORT}`);
        log('INFO', `Grupos: ${GROUP_IDS.length ? GROUP_IDS.join(', ') : 'nenhum configurado'}`);
        log('INFO', `Zabbix: ${ZABBIX_URL || 'desabilitado'}`);
    });

    c.on('disconnected', (reason) => {
        clientReady = false;
        log('WARN', `WhatsApp desconectado: ${reason}`);
        log('INFO', 'Reiniciando processo em 5 segundos...');
        setTimeout(() => process.exit(1), 5000);
    });
}

// ─── Chat com o agente de IA central ──────────────────────────────────────────
// O agente formata a resposta em markdown (negrito **assim**, bloco de
// código ```assim```) pensando no chat web, que renderiza isso de verdade
// (ver agente.js) -- o WhatsApp tem sua PRÓPRIA sintaxe, diferente: um
// asterisco só pro negrito (*assim*), e nenhum suporte a crase simples
// pra código inline. Bloco de código com crase TRIPLA o WhatsApp já
// reconhece nativamente (mostra monoespaçado), por isso esse não é
// convertido -- só preservado intacto, pra não estragar a saída crua de
// equipamento que vem dentro dele.
function markdownToWhatsApp(text) {
    const parts = text.split(/(```[\s\S]*?```)/g);
    return parts.map((part) => {
        if (part.startsWith('```')) return part;
        return part
            .replace(/\*\*(.+?)\*\*/g, '*$1*')
            .replace(/`([^`]+)`/g, '$1');
    }).join('');
}

// ─── Resposta com bloco de código como imagem ─────────────────────────────────
// Consulta ao vivo num equipamento (config de interface, ARP, log) vem como
// saída crua dentro de um bloco ``` -- em texto puro do WhatsApp isso sai sem
// a formatação pensada pro chat web (negrito vira *um* asterisco, sem como
// caixa/cor de fundo). Em vez disso, renderiza a resposta inteira como uma
// imagem (mesmo visual do chat web) e manda como foto, com a frase-resumo
// como legenda. Reaproveita o mesmo motor Puppeteer que já é dependência do
// whatsapp-web.js, só que numa aba própria (não a aba do WhatsApp Web em si).
let renderBrowserPromise = null;
function getRenderBrowser() {
    if (!renderBrowserPromise) {
        renderBrowserPromise = puppeteer.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox'],
        });
    }
    return renderBrowserPromise;
}

function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function replyMarkdownToHtml(text) {
    const parts = text.split(/(```[\s\S]*?```)/g);
    return parts.map((part) => {
        if (part.startsWith('```')) {
            const inner = part.replace(/^```[^\n]*\n?/, '').replace(/```$/, '');
            return `<pre>${escapeHtml(inner)}</pre>`;
        }
        return escapeHtml(part)
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
    }).join('');
}

async function renderReplyAsImage(replyText) {
    const html = `<!doctype html><html><head><meta charset="utf-8"><style>
        * { box-sizing: border-box; }
        body {
            margin: 0; padding: 20px; width: 640px; background: #0a0a0a;
            font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 14px; line-height: 1.6; color: #d4d4d4;
        }
        strong { color: #fff; font-weight: 700; }
        code {
            font-family: "SF Mono", Consolas, monospace; font-size: 12.5px;
            background: #141414; border: 1px solid #333; border-radius: 4px; padding: 1px 5px;
        }
        pre {
            font-family: "SF Mono", Consolas, monospace; font-size: 12.5px; line-height: 1.5;
            background: #1a1a1a; border: 1px solid #333; border-left: 3px solid #888;
            border-radius: 8px; padding: 14px 16px; margin: 10px 0; white-space: pre-wrap;
            word-break: break-word; color: #fff;
        }
    </style></head><body>${replyMarkdownToHtml(replyText)}</body></html>`;

    const browser = await getRenderBrowser();
    const page = await browser.newPage();
    try {
        await page.setViewport({ width: 680, height: 100 });
        await page.setContent(html, { waitUntil: 'load' });
        const bodyHandle = await page.$('body');
        const box = await bodyHandle.boundingBox();
        await page.setViewport({ width: 680, height: Math.ceil(box.height) });
        return await page.screenshot({ type: 'png' });
    } finally {
        await page.close();
    }
}

// Primeiro parágrafo (antes do primeiro bloco ``` ou quebra dupla) -- vira a
// legenda da imagem, o que aparece na pré-visualização da conversa.
function replySummary(text) {
    const before = text.split('```')[0].trim();
    return before.split(/\n\s*\n/)[0].trim() || 'Resultado da consulta:';
}

async function askAgent(message, conversationId) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), AI_REQUEST_TIMEOUT_MS);
    try {
        const response = await fetch(AI_AGENT_URL, {
            method:  'POST',
            headers: {
                'Content-Type':  'application/json',
                'X-Agent-Token': AI_AGENT_TOKEN,
            },
            body:   JSON.stringify({ message, conversation_id: conversationId }),
            signal: controller.signal,
        });

        if (!response.ok) {
            throw new Error(`Agente respondeu HTTP ${response.status}`);
        }

        // O agente responde em SSE (server-sent events): um registro por
        // pedaço de texto gerado, terminado em linha em branco. Um pedaço
        // com quebra de linha (comum em saída de equipamento: config, ARP,
        // log) vira VÁRIAS linhas "data: " dentro do MESMO registro (ver
        // sse_data() em chat.py) -- juntar só pegando "data: " solto sem
        // recolocar a quebra entre elas grudava tudo numa linha só. Junta
        // as linhas de um registro com "\n", e cada registro (um pedaço de
        // texto novo) concatena direto no texto acumulado, sem separador.
        const reader  = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let text   = '';
        let done   = false;
        while (!done) {
            const { done: readerDone, value } = await reader.read();
            if (readerDone) break;
            buffer += decoder.decode(value, { stream: true });

            let sepIndex;
            while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
                const record = buffer.slice(0, sepIndex);
                buffer = buffer.slice(sepIndex + 2);

                const lines = record.split('\n');
                const isDone = lines.some((l) => l.startsWith('event: done'));
                if (isDone) {
                    // O JSON do conversation_id vem nesse mesmo registro
                    // (ver chat.py) -- sem esse "if", ele aparecia colado
                    // no fim de toda resposta no WhatsApp.
                    done = true;
                    continue;
                }
                const dataLines = lines.filter((l) => l.startsWith('data: '));
                if (dataLines.length > 0) {
                    text += dataLines.map((l) => l.slice(6)).join('\n');
                }
            }
        }
        return text.trim() || '(sem resposta)';
    } finally {
        clearTimeout(timer);
    }
}

function setupAiChatHandler(c) {
    if (!AI_CHAT_ENABLED) {
        log('WARN', 'IA desabilitada: defina AI_AGENT_TOKEN no .env para responder mensagens do WhatsApp pelo chat.');
        return;
    }

    c.on('message', async (msg) => {
        // fromMe evita que o bot responda a si mesmo (inclusive os alertas
        // que ele mesmo manda pros grupos via /webhook). type !== 'chat'
        // ignora mídia/figurinhas/status sem texto de verdade pra mandar à IA.
        if (msg.fromMe || msg.type !== 'chat' || !msg.body?.trim()) return;

        // msg.getChat() CRASHA O PROCESSO INTEIRO nessa versão do
        // whatsapp-web.js -- mesmo bug de serialização já documentado em
        // GET /groups (getChatModel() interno quebra ao serializar o
        // Chat), só que aqui sem nenhum try/catch em volta, derrubando o
        // bot inteiro a cada mensagem recebida (confirmado em produção:
        // toda mensagem reiniciava o container sem nunca responder).
        // msg.from já traz tudo que esse handler precisa (id da conversa e
        // se é grupo, pelo sufixo "@g.us"), sem precisar buscar o Chat.
        const chatId = msg.from;
        const isGroup = chatId.endsWith('@g.us');

        if (AI_ALLOWED_CHATS.length > 0 && !AI_ALLOWED_CHATS.includes(chatId)) {
            return;
        }

        if (isGroup) {
            // Em grupo só responde se o bot foi mencionado -- senão toda
            // conversa do grupo (incluindo os próprios alertas do Zabbix)
            // dispararia uma resposta da IA, virando spam. getMentions()
            // não é o método que já confirmamos quebrando (era getChat()),
            // mas é outra serialização da mesma lib nessa mesma versão --
            // por precaução, uma falha aqui só pula a mensagem em vez de
            // arriscar derrubar o processo de novo.
            try {
                const mentions = await msg.getMentions();
                const botId = c.info?.wid?._serialized;
                const isMentioned = botId && mentions.some((m) => m.id._serialized === botId);
                if (!isMentioned) return;
            } catch (err) {
                log('WARN', `getMentions() falhou em ${chatId}, pulando: ${err.message}`);
                return;
            }
        }

        // Em grupo, quem mandou é msg.author (o número individual dentro
        // do grupo); numa DM, o remetente é o próprio chatId. Prefixo
        // simples no texto em vez de mexer no formato do /chat (repetido
        // em toda mensagem, não só na primeira, pra funcionar mesmo que o
        // histórico da conversa não seja carregado por algum motivo).
        const senderId = isGroup ? msg.author : chatId;
        const senderName = senderId && lookupSenderName(senderId);
        const messageForAgent = senderName ? `[Mensagem de ${senderName}]: ${msg.body}` : msg.body;

        try {
            const reply = await askAgent(messageForAgent, chatId);

            if (reply.includes('```')) {
                // Consulta ao vivo com saída crua de equipamento -- manda
                // como imagem formatada (negrito, caixa de código) em vez
                // de texto puro, que perderia essa formatação no WhatsApp.
                try {
                    const png = await renderReplyAsImage(reply);
                    const media = new MessageMedia('image/png', png.toString('base64'), 'resposta.png');
                    await msg.reply(media, undefined, { caption: replySummary(reply) });
                } catch (renderErr) {
                    log('WARN', `Falha ao renderizar imagem, mandando texto puro: ${renderErr.message}`);
                    await msg.reply(markdownToWhatsApp(reply));
                }
            } else {
                await msg.reply(markdownToWhatsApp(reply));
            }

            log('INFO', `IA respondeu em ${chatId}`);
        } catch (err) {
            log('ERROR', `IA falhou em ${chatId}: ${err.message}`);
            await msg.reply('Desculpe, não consegui falar com o assistente agora. Tente novamente em instantes.').catch(() => {});
        }
    });
}

setupClientEvents(client);
setupAiChatHandler(client);
client.initialize();

// ─── Sessão Zabbix ────────────────────────────────────────────────────────────
let cachedCookies = null;
let cookiesExpiry = 0;

async function zabbixLogin() {
    const form = new URLSearchParams({
        name:      ZABBIX_USER,
        password:  ZABBIX_PASS,
        autologin: '1',
        enter:     'Sign in',
    });

    const response = await fetch(`${ZABBIX_URL}/index.php`, {
        method:   'POST',
        headers:  {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent':   'natverk-zabbix-whatsapp/1.0',
        },
        body:     form.toString(),
        redirect: 'manual',
    });

    let setCookies = [];
    if (typeof response.headers.getSetCookie === 'function') {
        setCookies = response.headers.getSetCookie();
    } else {
        const raw = response.headers.get('set-cookie');
        if (raw) setCookies = [raw];
    }

    if (setCookies.length === 0) {
        throw new Error(`Sem cookies retornados (HTTP ${response.status}). Verifique ZABBIX_URL.`);
    }

    const cookieString = setCookies
        .map(c => c.split(';')[0].trim())
        .filter(Boolean)
        .join('; ');

    if (!/zbx_session/i.test(cookieString)) {
        throw new Error(`Cookie zbx_session ausente. Usuário/senha incorretos? Cookies: ${cookieString}`);
    }

    log('INFO', 'Login no Zabbix OK');
    return cookieString;
}

async function getZabbixCookies() {
    if (cachedCookies && Date.now() < cookiesExpiry) return cachedCookies;
    cachedCookies = await zabbixLogin();
    cookiesExpiry = Date.now() + 50 * 60 * 1000;
    return cachedCookies;
}

async function fetchChart(itemId) {
    if (!ZABBIX_URL || !itemId) return null;

    const cookies = await getZabbixCookies();
    const url = `${ZABBIX_URL}/chart.php?itemids%5B0%5D=${itemId}&period=${CHART_PERIOD}&width=${CHART_WIDTH}&height=${CHART_HEIGHT}`;

    const response = await fetch(url, {
        headers: {
            'Cookie':     cookies,
            'User-Agent': 'natverk-zabbix-whatsapp/1.0',
        },
        redirect: 'manual',
    });

    if (response.status >= 300 && response.status < 400) {
        cachedCookies = null;
        throw new Error(`Sessão expirada (HTTP ${response.status}) — forçando novo login`);
    }

    if (!response.ok) {
        throw new Error(`Erro ao buscar gráfico: HTTP ${response.status}`);
    }

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.startsWith('image/')) {
        cachedCookies = null;
        const peek = (await response.text()).slice(0, 200);
        throw new Error(`Resposta não é imagem (${contentType}). Início: ${peek}`);
    }

    const buffer = await response.arrayBuffer();
    return Buffer.from(buffer);
}

// ─── Formatação da mensagem ───────────────────────────────────────────────────
function severityIcon(severity) {
    return {
        disaster:    '🔴',
        high:        '🟠',
        average:     '🟡',
        warning:     '🟢',
        information: '🔵',
        ok:          '✅',
    }[String(severity || '').toLowerCase()] || '⚠️';
}

function formatMessage(body) {
    const { subject, message, event_id, trigger_name, host, severity, status, value, timestamp } = body;

    if (subject && message) {
        return `*${subject}*\n\n${message}`;
    }

    const icon  = severityIcon(severity);
    const lines = ['*🔔 Alerta Zabbix — Natverk*'];
    if (status)       lines.push(`${icon} *Status:* ${status}`);
    if (trigger_name) lines.push(`📌 *Trigger:* ${trigger_name}`);
    if (host)         lines.push(`🖥️ *Host:* ${host}`);
    if (severity)     lines.push(`📊 *Severidade:* ${severity}`);
    if (value)        lines.push(`📈 *Valor:* ${value}`);
    if (event_id)     lines.push(`🆔 *Event ID:* ${event_id}`);
    if (timestamp)    lines.push(`🕐 *Horário:* ${timestamp}`);
    return lines.join('\n');
}

// ─── Middleware de autenticação ───────────────────────────────────────────────
function authMiddleware(req, res, next) {
    if (!WEBHOOK_TOKEN) return next();
    const token = req.headers['x-webhook-token'] || req.query.token;
    if (token !== WEBHOOK_TOKEN) {
        log('WARN', `Token inválido de ${req.ip}`);
        return res.status(401).json({ error: 'Token inválido' });
    }
    next();
}

// ─── Rotas ────────────────────────────────────────────────────────────────────

app.post('/webhook', authMiddleware, async (req, res) => {
    if (!clientReady) return res.status(503).json({ error: 'WhatsApp não está pronto ainda' });

    const body = req.body || {};
    log('INFO', `Webhook recebido: ${JSON.stringify(body)}`);

    if (Object.keys(body).length === 0) {
        return res.status(400).json({ error: 'Payload vazio' });
    }

    const text    = formatMessage(body);
    const targets = body.group_id ? [body.group_id] : GROUP_IDS;

    if (targets.length === 0) {
        return res.status(400).json({ error: 'Nenhum grupo destinatário configurado' });
    }

    let chartMedia = null;
    if (body.itemid && ZABBIX_URL) {
        try {
            const buffer = await fetchChart(body.itemid);
            if (buffer) {
                chartMedia = new MessageMedia('image/png', buffer.toString('base64'), `chart-${body.itemid}.png`);
                log('INFO', `Gráfico OK (${buffer.length} bytes)`);
            }
        } catch (err) {
            log('WARN', `Gráfico falhou: ${err.message}. Enviando só texto.`);
        }
    }

    const results = [];
    for (const groupId of targets) {
        try {
            if (chartMedia) {
                await client.sendMessage(groupId, chartMedia, { caption: text });
            } else {
                await client.sendMessage(groupId, text);
            }
            log('INFO', `Enviado para ${groupId}${chartMedia ? ' (com gráfico)' : ''}`);
            results.push({ groupId, status: 'sent', withChart: !!chartMedia });
            consecutiveErrors = 0;
        } catch (err) {
            log('ERROR', `Falha ao enviar para ${groupId}: ${err.message}`);
            results.push({ groupId, status: 'error', error: err.message });

            if (err.message.includes('timed out') || err.message.includes('Protocol error')) {
                consecutiveErrors++;
                log('WARN', `Erros consecutivos: ${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS}`);
                if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
                    log('ERROR', 'Limite de erros atingido — reiniciando processo em 3 segundos...');
                    setTimeout(() => process.exit(1), 3000);
                }
            }
        }
    }

    const allOk = results.every(r => r.status === 'sent');
    res.status(allOk ? 200 : 207).json({ results });
});

app.get('/test-chart', authMiddleware, async (req, res) => {
    const itemid = req.query.itemid;
    if (!itemid) return res.status(400).json({ error: 'Passe ?itemid=XXXXX' });
    try {
        const buffer = await fetchChart(itemid);
        res.set('Content-Type', 'image/png').send(buffer);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.get('/groups', authMiddleware, async (req, res) => {
    if (!clientReady) return res.status(503).json({ error: 'WhatsApp não está pronto ainda' });
    try {
        // client.getChats() (== window.WWebJS.getChats() no navegador) vem
        // quebrando com um erro serializado ilegível ("r") -- o crash está no
        // getChatModel() interno da lib ao serializar cada chat (provavelmente
        // um getter lazy incompatível com esta versão do WhatsApp Web), não no
        // acesso aos dados em si. window.require('WAWebCollections').Chat é a
        // mesma coleção que getChats() usa por baixo (ver
        // node_modules/whatsapp-web.js/src/util/Injected/Utils.js) -- lendo os
        // modelos direto e extraindo só os campos que precisamos evita o
        // serializador problemático.
        const groups = await client.pupPage.evaluate(() => {
            // c.isGroup não aparece como propriedade própria enumerável nos
            // modelos deste build (confirmado inspecionando Object.keys) --
            // o sufixo do id é o sinal confiável: grupos terminam em
            // "@g.us", contatos em "@c.us"/"@lid".
            return window.require('WAWebCollections').Chat.getModelsArray()
                .filter((c) => c.id?._serialized?.endsWith('@g.us'))
                .map((c) => ({
                    id:           c.id._serialized,
                    name:         c.formattedTitle || c.name || '',
                    participants: c.groupMetadata?.participants?.length ?? 0,
                }));
        });
        res.json({ total: groups.length, groups });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.get('/qr', authMiddleware, async (req, res) => {
    if (clientReady) {
        return res.status(409).json({ error: 'WhatsApp já está conectado -- não há QR Code pra mostrar' });
    }
    if (!latestQr) {
        return res.status(503).json({ error: 'QR Code ainda não gerado, aguarde alguns segundos e tente de novo' });
    }
    try {
        const png = await qrcodeImage.toBuffer(latestQr, { width: 400, margin: 2 });
        res.set('Content-Type', 'image/png').send(png);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.get('/health', (req, res) => {
    res.json({
        status:  clientReady ? 'ready' : 'initializing',
        // Número vinculado a esta sessão -- útil pra confirmar de qual chip
        // adicionar aos grupos antes de rodar GET /groups.
        phone:   clientReady ? (client.info?.wid?.user || null) : null,
        zabbix:  !!ZABBIX_URL,
        groups:  GROUP_IDS.length,
        uptime:  process.uptime(),
        errors:  consecutiveErrors,
    });
});

app.listen(PORT, () => {
    log('INFO', `Servidor em http://0.0.0.0:${PORT}`);
    log('INFO', 'POST /webhook    → recebe alertas');
    log('INFO', 'GET  /test-chart → testa download (?itemid=X)');
    log('INFO', 'GET  /groups     → lista grupos');
    log('INFO', 'GET  /qr         → QR Code de pareamento (imagem)');
    log('INFO', 'GET  /health     → status');
});
