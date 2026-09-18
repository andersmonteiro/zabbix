#!/usr/bin/env python3
# Este script utiliza encoding: utf-8
# Este script foi desenvolvido por Gabriel Mocan, disponíveis em contato@mw-solucoes.com ou (84) 992169981
# Todos os direitos reservados - Copyright © 2017-2022 MW Soluções

import sys, re, os
import discord
from asyncio import get_event_loop

################################ PARÂMETROS #################################

dest  = sys.argv[1]                     # ID do chat
token = os.getenv("DISCORD_TOKEN", "")  # Token de acesso

################################# FUNÇÕES ###################################

def mround(match):
    return "{:.2f}".format(float(match.group()))

################################# EXECUCÃO ##################################

client = discord.Client(intents=discord.Intents.default())

@client.event
async def on_ready():
    # print('We have logged in as {0.user}'.format(client))
    channel = client.get_channel(int(dest))
    await channel.send(msg)
    await client.close()
    get_event_loop().stop()

# Monta a mensagem
subj = sys.argv[2] # Assunto da mensagem
body = sys.argv[3] # Corpo da mensagem
msg  = subj + "\n" + re.sub(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", r"\3/\2/\1", re.sub(r"\d*\.\d{10}\d+", mround, body))

# Realiza o envio da mensagem
client.run(token)
sys.exit(0)
