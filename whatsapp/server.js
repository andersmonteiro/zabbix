/**
 * Natverk — Zabbix → WhatsApp Webhook
 * Envia alertas do Zabbix para grupos do WhatsApp com screenshot do gráfico.
 */

require('dotenv').config();
const express = require('express');
const fs      = require('fs');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ─── Helpers ──────────────────────────────────────────────────────────────────
function log(level, msg) {
    const ts = new Date().toISOString();
    console.log(`[${ts}] [${level}] ${msg}`);
}

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

function setupClientEvents(c) {
    c.on('qr', (qr) => {
        log('INFO', 'Escaneie o QR Code abaixo com o WhatsApp:');
        qrcode.generate(qr, { small: true });
    });

    c.on('authenticated', () => log('INFO', 'WhatsApp autenticado!'));

    c.on('ready', () => {
        clientReady = true;
        consecutiveErrors = 0;
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

setupClientEvents(client);
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
            return window.require('WAWebCollections').Chat.getModelsArray()
                .filter((c) => c.isGroup)
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
    log('INFO', 'GET  /health     → status');
});
