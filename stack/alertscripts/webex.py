#!/usr/bin/env python3
# Este script utiliza encoding: utf-8
# Este script foi desenvolvido por Gabriel Moura Cantanhede, disponível em gabemocan@gmail.com
# Todos os direitos reservados - Copyright © 2017-2022 MW Soluções

################################ BIBLIOTECAS ################################

import sys, re, os
from webexteamssdk import WebexTeamsAPI, ApiError

################################ PARÂMETROS #################################

dest  = sys.argv[1]                     # ID da sala
token = os.getenv("WEBEX_TOKEN", "")    # Token de acesso

################################# FUNÇÕES ###################################

def mround(match):
    return "{:.2f}".format(float(match.group()))

################################# EXECUCÃO ##################################

# Autentica na API
api = WebexTeamsAPI(access_token=token)

# Checa a execução
if dest == 'listar':
    rooms = api.rooms.list()
    print("\n" + "Lista das salas e seus respectivos IDs" + "\n")
    for room in rooms:
        print(room.title + ': ' + room.id)
    print()
    sys.exit(0)
# Envia mensagem se for o caso
else:
    # Monta a mensagem
    subj = sys.argv[2] # Assunto da mensagem
    body = sys.argv[3] # Corpo da mensagem
    msg  = subj + "\n" + re.sub(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", r"\3/\2/\1", re.sub(r"\d*\.\d{10}\d+", mround, body))
    # Realiza o envio da mensagem para a sala desejada
    try:
        message = api.messages.create(dest, text=msg)
        # print(message.text)
        sys.exit(0)
    except ApiError as e:
        print(e)
        sys.exit(1)
