import os
import asyncio
from quotexapi.stable_api import Quotex


client = Quotex(email="user@gmail.com", password="pwd")
client.debug_ws_enable = False
check_connect, message = client.connect()
print(check_connect, message)



def asset_parse(asset):
    new_asset = asset[:3] + "/" + asset[3:]
    if "_otc" in asset:
        asset = new_asset.replace("_otc", " (OTC)")
    else:
        asset = new_asset
    return asset


async def login(attempts=5):
    check, reason = await client.connect()
    print("Start your robot")
    attempt = 1
    while attempt <= attempts:
        if not client.check_connect():
            print(f"Tentando reconectar, tentativa {attempt} de {attempts}")
            check, reason = await client.connect()
            if check:
                print("Reconectado com sucesso!!!")
                break
            else:
                print("Erro ao reconectar.")
                attempt += 1
                if os.path.isfile("session.json"):
                    os.remove("session.json")
        elif not check:
            attempt += 1
        else:
            break
        await asyncio.sleep(5)
    return check, reason


async def buy_and_check_win():
    check_connect, message = await login()
    print(check_connect, message)
    if check_connect:
        client.change_account("PRACTICE")
        print("Saldo corrente: ", await client.get_balance())
        amount = 5
        asset = "EURUSD_otc"  # "EURUSD_otc"
        direction = "call"
        duration = 60  # in seconds
        asset_query = asset_parse(asset)
        asset_open = client.check_asset_open(asset_query)
        if asset_open[2]:
            print("OK: Asset está aberto.")
            status, buy_info = await client.buy(amount, asset, direction, duration)
            print(status, buy_info)
            if status:
                print("Aguardando resultado...")
                if await client.check_win(buy_info["id"]):
                    print(f"\nWin!!! \nVencemos moleque!!!\nLucro: R$ {client.get_profit()}")
                else:
                    print(f"\nLoss!!! \nPerdemos moleque!!!\nPrejuízo: R$ {client.get_profit()}")
            else:
                print("Falha na operação!!!")
        else:
            print("ERRO: Asset está fechado.")
        print("Saldo Atual: ", await client.get_balance())
        print("Saindo...")
    client.close()
