from flask import Flask, request, jsonify
import subprocess
import json
import re
import os

app = Flask(__name__)

HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9\-\.]{0,253}[A-Za-z0-9])?$')
TOOLS_TOKEN = os.environ.get('TOOLS_TOKEN', '')


@app.before_request
def require_token():
    if request.path == '/health':
        return None
    if not TOOLS_TOKEN:
        return None
    token = request.headers.get('X-Webhook-Token') or request.args.get('token')
    if token != TOOLS_TOKEN:
        return jsonify({"error": "Token inválido"}), 401


def run(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return None, "Timeout"
    except Exception as e:
        return None, str(e)


def validate_host(host):
    if not host or len(host) > 255:
        return False
    if host.startswith('-'):
        return False
    return bool(HOST_RE.match(host))


@app.route('/health')
def health():
    return jsonify({"status": "ok"})


@app.route('/mtr')
def mtr():
    host = request.args.get('host', '').strip()
    cycles = request.args.get('cycles', '5')

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    try:
        cycles = max(1, min(int(cycles), 20))
    except ValueError:
        cycles = 5

    stdout, stderr = run(
        ['mtr', '--no-dns', '--report', '--report-cycles', str(cycles), host],
        timeout=60
    )

    if stdout is None:
        return jsonify({"error": stderr}), 500

    # Parsear saída texto do MTR
    # Formato: "  1.|-- 172.18.0.1   0.0%   5   0.2   0.2   0.1   0.2   0.0"
    rows = []
    for line in stdout.strip().split('\n'):
        m = re.match(
            r'\s*(\d+)\.\|--\s+(\S+)\s+([\d.]+)%\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)',
            line
        )
        if m:
            rows.append({
                "hop":   int(m.group(1)),
                "host":  m.group(2),
                "loss%": float(m.group(3)),
                "snt":   int(m.group(4)),
                "last":  float(m.group(5)),
                "avg":   float(m.group(6)),
                "best":  float(m.group(7)),
                "worst": float(m.group(8)),
                "stdev": float(m.group(9)),
            })
        elif re.match(r'\s*(\d+)\.\|--\s+\?\?\?', line):
            hop = re.match(r'\s*(\d+)', line)
            rows.append({
                "hop":   int(hop.group(1)) if hop else 0,
                "host":  "???",
                "loss%": 100.0,
                "snt":   cycles,
                "last":  0.0,
                "avg":   0.0,
                "best":  0.0,
                "worst": 0.0,
                "stdev": 0.0,
            })

    return jsonify(rows)


@app.route('/ping')
def ping():
    host = request.args.get('host', '').strip()
    count = request.args.get('count', '5')

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    try:
        count = max(1, min(int(count), 20))
    except ValueError:
        count = 5

    stdout, stderr = run(
        ['ping', '-c', str(count), '-W', '2', host],
        timeout=30
    )

    if stdout is None:
        return jsonify({"error": stderr}), 500

    lines = stdout.strip().split('\n')
    results = []
    rtt_line = ""
    stats_line = ""

    for line in lines:
        if 'bytes from' in line:
            seq  = re.search(r'icmp_seq=(\d+)', line)
            ttl  = re.search(r'ttl=(\d+)', line)
            time = re.search(r'time=([\d.]+)', line)
            results.append({
                "seq":  seq.group(1)  if seq  else '',
                "ttl":  ttl.group(1)  if ttl  else '',
                "time": time.group(1) if time else '',
            })
        if 'rtt min' in line or 'round-trip' in line:
            rtt_line = line.strip()
        if 'packets transmitted' in line:
            stats_line = line.strip()

    rows = []
    for r in results:
        rows.append({
            "seq":   int(r["seq"]) if r["seq"] else 0,
            "ttl":   int(r["ttl"]) if r["ttl"] else 0,
            "ms":    float(r["time"]) if r["time"] else 0.0,
            "host":  host,
            "stats": stats_line,
            "rtt":   rtt_line,
        })
    return jsonify(rows)


@app.route('/dig')
def dig():
    host   = request.args.get('host', '').strip()
    qtype  = request.args.get('type', 'A').strip().upper()
    server = request.args.get('server', '').strip()

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    allowed_types = ['A', 'AAAA', 'MX', 'NS', 'PTR', 'TXT', 'SOA', 'CNAME', 'ANY']
    if qtype not in allowed_types:
        return jsonify({"error": f"Tipo inválido. Use: {', '.join(allowed_types)}"}), 400

    cmd = ['dig', '+noall', '+answer', '+stats', host, qtype]
    if server:
        if not validate_host(server):
            return jsonify({"error": "Servidor DNS inválido"}), 400
        cmd = ['dig', '+noall', '+answer', '+stats', f'@{server}', host, qtype]

    stdout, stderr = run(cmd, timeout=10)

    if stdout is None:
        return jsonify({"error": stderr}), 500

    answers = []
    query_time = ""
    server_used = ""

    for line in stdout.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith(';'):
            if 'Query time:' in line:
                m = re.search(r'Query time: (.+)', line)
                query_time = m.group(1) if m else ''
            if 'SERVER:' in line:
                server_used = line.replace(';; SERVER:', '').strip()
            continue
        parts = line.split()
        if len(parts) >= 5:
            answers.append({
                "name":  parts[0],
                "ttl":   parts[1],
                "class": parts[2],
                "type":  parts[3],
                "value": ' '.join(parts[4:]),
            })

    return jsonify({
        "host":       host,
        "type":       qtype,
        "server":     server_used,
        "query_time": query_time,
        "answers":    answers,
    })


@app.route('/whois')
def whois():
    host = request.args.get('host', '').strip()

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    stdout, stderr = run(['whois', host], timeout=15)

    if stdout is None:
        return jsonify({"error": stderr}), 500

    fields = {}
    important = [
        'inetnum', 'inet6num', 'netname', 'descr', 'country',
        'org', 'orgname', 'aut-num', 'asname', 'abuse-mailbox',
        'route', 'origin', 'mnt-by',
        'netrange', 'cidr', 'nettype', 'organization',
        'orgid', 'address', 'stateid',
    ]

    for line in stdout.split('\n'):
        if ':' not in line or line.startswith('%') or line.startswith('#'):
            continue
        key, _, value = line.partition(':')
        key = key.strip().lower()
        value = value.strip()
        if key in important and value and key not in fields:
            fields[key] = value

    return jsonify({
        "host":   host,
        "fields": fields,
        "raw":    stdout,
    })



@app.route('/ping/raw')
def ping_raw():
    host = request.args.get('host', '').strip()
    count = request.args.get('count', '5')

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    try:
        count = max(1, min(int(count), 20))
    except ValueError:
        count = 5

    stdout, stderr = run(
        ['ping', '-c', str(count), '-W', '2', host],
        timeout=30
    )

    if stdout is None:
        return jsonify([{"linha": f"Erro: {stderr}"}])

    rows = [{"linha": line} for line in stdout.split('\n') if line.strip()]
    return jsonify(rows)


@app.route('/mtr/raw')
def mtr_raw():
    host = request.args.get('host', '').strip()
    cycles = request.args.get('cycles', '5')

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    try:
        cycles = max(1, min(int(cycles), 20))
    except ValueError:
        cycles = 5

    stdout, stderr = run(
        ['mtr', '--no-dns', '--report', '--report-cycles', str(cycles), host],
        timeout=60
    )

    if stdout is None:
        return jsonify([{"output": f"Erro: {stderr}"}])

    rows = [{"linha": line} for line in stdout.split('\n') if line.strip()]
    return jsonify(rows)


@app.route('/whois/raw')
def whois_raw():
    host = request.args.get('host', '').strip()

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    stdout, stderr = run(['whois', host], timeout=15)

    if stdout is None:
        return jsonify([{"output": f"Erro: {stderr}"}])

    rows = [{"linha": line} for line in stdout.split('\n') if line.strip()]
    return jsonify(rows)


@app.route('/dig/raw')
def dig_raw():
    host   = request.args.get('host', '').strip()
    qtype  = request.args.get('type', 'A').strip().upper()
    server = request.args.get('server', '').strip()

    if not validate_host(host):
        return jsonify({"error": "Host inválido"}), 400

    allowed_types = ['A', 'AAAA', 'MX', 'NS', 'PTR', 'TXT', 'SOA', 'CNAME', 'ANY']
    if qtype not in allowed_types:
        return jsonify([{"output": f"Tipo inválido. Use: {', '.join(allowed_types)}"}])

    cmd = ['dig', host, qtype]
    if server:
        if not validate_host(server):
            return jsonify([{"output": "Servidor DNS inválido"}])
        cmd = ['dig', f'@{server}', host, qtype]

    stdout, stderr = run(cmd, timeout=10)

    if stdout is None:
        return jsonify([{"output": f"Erro: {stderr}"}])

    return jsonify([{"output": stdout}])


@app.route('/nslookup')
def nslookup():
    host   = request.args.get('host', '').strip()
    server = request.args.get('server', '').strip()

    if not validate_host(host):
        return jsonify([{"linha": "Host inválido"}])

    cmd = ['nslookup', host]
    if server:
        if not validate_host(server):
            return jsonify([{"linha": "Servidor DNS inválido"}])
        cmd = ['nslookup', host, server]

    stdout, stderr = run(cmd, timeout=10)

    output = stdout if stdout else stderr
    rows = [{"linha": line} for line in output.split('\n') if line.strip()]
    return jsonify(rows)


@app.route('/lg/he')
def lg_he():
    import urllib.request, urllib.parse, re as re2

    host    = request.args.get('host', '').strip()
    command = request.args.get('command', 'bgproute').strip()
    router  = request.args.get('router', 'core3.lax2.he.net').strip()

    if not validate_host(host):
        return jsonify([{"linha": "Host inválido"}])

    allowed_commands = ['bgproute', 'bgpsummary4', 'bgpsummary6', 'ping', 'traceroute']
    if command not in allowed_commands:
        return jsonify([{"linha": f"Comando inválido. Use: {', '.join(allowed_commands)}"}])

    try:
        # Passo 1: GET pra pegar o token
        req = urllib.request.Request(
            'https://lg.he.net/',
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='replace')

        token_match = re2.search(r'<input[^>]+name="token"[^>]+value="([^"]+)"', html)
        if not token_match:
            return jsonify([{"linha": "Erro: não foi possível obter o token"}])

        token = token_match.group(1)

        # Passo 2: POST com o token
        params = urllib.parse.urlencode({
            'token':     token,
            'routers[]': router,
            'command':   command,
            'ip':        host,
        }).encode('utf-8')

        req2 = urllib.request.Request(
            'https://lg.he.net/',
            data=params,
            headers={
                'User-Agent':   'Mozilla/5.0',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer':      'https://lg.he.net/',
            }
        )
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            html2 = resp2.read().decode('utf-8', errors='replace')

        # Extrair resultado — fica dentro de <pre> ou <table>
        pre_match = re2.search(r'<pre[^>]*>(.*?)</pre>', html2, re2.DOTALL)
        if pre_match:
            text = re2.sub(r'<[^>]+>', '', pre_match.group(1)).strip()
            rows = [{"linha": line} for line in text.split('\n') if line.strip()]
            return jsonify(rows)

        # Tentar extrair tabela
        table_match = re2.search(r'<table[^>]*>(.*?)</table>', html2, re2.DOTALL)
        if table_match:
            text = re2.sub(r'<[^>]+>', ' ', table_match.group(1))
            text = re2.sub(r'\s+', ' ', text).strip()
            rows = [{"linha": line.strip()} for line in text.split('  ') if line.strip()]
            return jsonify(rows)

        return jsonify([{"linha": "Sem resultado — verifique o host/prefixo"}])

    except Exception as e:
        return jsonify([{"linha": f"Erro: {str(e)}"}])


@app.route('/lg/he/debug')
def lg_he_debug():
    import urllib.request, urllib.parse, re as re2

    host    = request.args.get('host', '8.8.8.8').strip()
    command = request.args.get('command', 'bgproute').strip()
    router  = request.args.get('router', 'core3.lax2.he.net').strip()

    try:
        req = urllib.request.Request('https://lg.he.net/', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='replace')

        token_match = re2.search(r'<input[^>]+name="token"[^>]+value="([^"]+)"', html)
        token = token_match.group(1) if token_match else ''

        params = urllib.parse.urlencode({
            'token': token, 'routers[]': router,
            'command': command, 'ip': host,
        }).encode('utf-8')

        req2 = urllib.request.Request('https://lg.he.net/', data=params,
            headers={'User-Agent': 'Mozilla/5.0',
                     'Content-Type': 'application/x-www-form-urlencoded',
                     'Referer': 'https://lg.he.net/'})
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            html2 = resp2.read().decode('utf-8', errors='replace')

        # Retorna trecho relevante do HTML
        start = html2.find('lg_status')
        return jsonify({"html": html2[start:start+3000]})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/rbl')
def rbl():
    import ipaddress

    host = request.args.get('host', '').strip()

    if not validate_host(host):
        return jsonify([{"lista": "Erro", "status": "Host inválido", "listado": ""}])

    # Verificar se é IP válido
    try:
        ip = ipaddress.ip_address(host)
        # Inverter octetos para consulta DNS
        if ip.version == 4:
            reversed_ip = '.'.join(reversed(host.split('.')))
        else:
            return jsonify([{"lista": "Erro", "status": "Apenas IPv4 suportado", "listado": ""}])
    except ValueError:
        return jsonify([{"lista": "Erro", "status": "IP inválido — use um endereço IPv4", "listado": ""}])

    rbls = [
        ("Spamhaus ZEN",          "zen.spamhaus.org"),
        ("Spamhaus SBL",          "sbl.spamhaus.org"),
        ("Spamhaus XBL",          "xbl.spamhaus.org"),
        ("Spamhaus PBL",          "pbl.spamhaus.org"),
        ("SpamCop",               "bl.spamcop.net"),
        ("SORBS DNSBL",           "dnsbl.sorbs.net"),
        ("Barracuda",             "b.barracudacentral.org"),
        ("PSBL",                  "psbl.surriel.com"),
        ("UCEprotect L1",         "dnsbl-1.uceprotect.net"),
        ("UCEprotect L2",         "dnsbl-2.uceprotect.net"),
        ("UCEprotect L3",         "dnsbl-3.uceprotect.net"),
        ("NordSpam",              "combined.njabl.org"),
        ("DNSBL.tornevall",       "dnsbl.tornevall.org"),
        ("Abuse.ch",              "abuse.ch"),
        ("BlockList.de",          "bl.blocklist.de"),
        ("RATS-Dyna",             "dyna.spamrats.com"),
        ("RATS-NoPtr",            "noptr.spamrats.com"),
        ("RATS-Spam",             "spam.spamrats.com"),
        ("Mailspike BL",          "bl.mailspike.net"),
        ("Mailspike Z",           "z.mailspike.net"),
    ]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def check_rbl(name, rbl):
        query = f"{reversed_ip}.{rbl}"
        stdout, stderr = run(['nslookup', query, '8.8.8.8'], timeout=5)
        if stdout and ('Address' in stdout or 'answer' in stdout.lower()) and 'NXDOMAIN' not in stdout and "can't find" not in stdout.lower():
            code_match = re.search(r'Address.*?(127\.\d+\.\d+\.\d+)', stdout)
            code = code_match.group(1) if code_match else "listado"
            return {"lista": name, "rbl": rbl, "status": f"⚠️ LISTADO ({code})", "listado": "Sim"}
        return {"lista": name, "rbl": rbl, "status": "✅ Limpo", "listado": "Não"}

    results = [None] * len(rbls)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_rbl, name, rbl): i for i, (name, rbl) in enumerate(rbls)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    return jsonify(results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)
