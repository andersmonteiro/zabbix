FROM zabbix/zabbix-server-pgsql:ubuntu-7.4.11

USER root

# Instala Python 3.8, pip, snmp, MIBs e utilitários necessários
RUN apt update && \
    apt install -y software-properties-common curl && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt update && \
    apt install -y \
        python3.8 \
        python3.8-dev \
        python3.8-distutils \
        snmp \
        snmp-mibs-downloader \
        dos2unix && \
    ln -sf /usr/bin/python3.8 /usr/bin/python3 && \
    # Baixa MIBs
    download-mibs && \
    # Remove linha que desativa carregamento de MIBs
    sed -i '/^mibs\s*:/d' /etc/snmp/snmp.conf && \
    apt clean && rm -rf /var/lib/apt/lists/*

# Instala pip próprio para python3.8
RUN curl -sS https://bootstrap.pypa.io/pip/3.8/get-pip.py | python3.8

# Adiciona variáveis de ambiente para carregar todas as MIBs
ENV MIBS=ALL
ENV MIBDIRS=/usr/share/snmp/mibs

# Instala dependências Python
RUN python3.8 -m pip install --ignore-installed \
    aiohappyeyeballs==2.4.4 \
    aiohttp==3.10.11 \
    aiosignal==1.3.1 \
    async-timeout==5.0.1 \
    attrs==25.1.0 \
    bcrypt==4.2.1 \
    beautifulsoup4==4.13.3 \
    boto3==1.35.99 \
    botocore==1.35.99 \
    bs4==0.0.2 \
    cachetools==5.5.1 \
    certifi==2025.1.31 \
    cffi==1.17.1 \
    chardet==5.2.0 \
    charset-normalizer==3.4.1 \
    cryptography \
    dateutils==0.6.12 \
    discord==2.3.2 \
    "discord.py==2.5.0" \
    dnspython==2.6.1 \
    frozenlist==1.5.0 \
    future==1.0.0 \
    fuzzywuzzy==0.18.0 \
    google-auth==2.38.0 \
    google-auth-oauthlib==1.2.1 \
    gspread==6.1.4 \
    idna==3.10 \
    jmespath==1.0.1 \
    paramiko==3.5.1 \
    pillow==10.4.0 \
    prettytable==3.11.0 \
    propcache==0.2.0 \
    proxmoxer==2.2.0 \
    psycopg2-binary==2.9.10 \
    py-zabbix==1.1.7 \
    pyasn1==0.6.1 \
    pyasn1-modules==0.4.1 \
    pycparser==2.22 \
    PyJWT \
    pymongo==4.10.1 \
    PyNaCl==1.5.0 \
    pyTelegramBotAPI==4.23.0 \
    python-dateutil==2.9.0.post0 \
    python-Levenshtein==0.25.1 \
    pytz==2025.1 \
    questdb==2.0.3 \
    rapidfuzz==3.9.7 \
    reportlab==4.3.1 \
    requests==2.32.3 \
    requests-oauthlib==2.0.0 \
    requests-toolbelt==1.0.0 \
    rsa==4.9 \
    s3transfer==0.10.4 \
    typing_extensions==4.12.2 \
    Unidecode==1.3.8 \
    psutil

# Copia a lib para dentro do container
COPY libpython3.8.so.1.0 /usr/lib/libpython3.8.so.1.0
