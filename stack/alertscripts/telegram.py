#!/usr/bin/env python3
# Este script utiliza encoding: utf-8
# Este script foi desenvolvido por Gabriel Moura Cantanhede e Edivaldo Segundo, disponível em gabemocan@gmail.com
# Todos os direitos reservados - Copyright © 2017-2024 MW Soluções

# ...=============================== Bibliotecas ================================...

import sys, re, os
import telebot

VERSION = '1.0.0'

# ...=============================== Parâmetros ================================...

# Obtendo ID do Chat e do Tópico.
dest  = sys.argv[1]                     # ID do chat
if '/' in dest:
    chat = dest.split('/')[0]
    thread = dest.split('/')[1]
else:   
    chat   = dest
    thread = None

# Monta a mensagem
subj   = sys.argv[2]   # Assunto da mensagem
body   = sys.argv[3]   # Corpo da mensagem

# ...=============================== Funções ================================...

def mround(match):
    return "{:.2f}".format(float(match.group()))

# ...=============================== Execução ================================...

# Obtém o token.
token = os.getenv("TELEGRAM_TOKEN", "")

# Autentica na API.
api = telebot.TeleBot(token)

# Monta a mensagem.
msg = subj + "\n" + re.sub(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", r"\3/\2/\1", re.sub(r"\d*\.\d{10}\d+", mround, body))

# Realiza o envio da mensagem.
if thread != None:
    api.send_message(dest, msg, message_thread_id=thread)
else:
    api.send_message(dest, msg)

sys.exit(0)
