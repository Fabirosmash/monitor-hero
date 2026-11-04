#!/usr/bin/env python3
"""
Monitor do item [100.000] Moeda Hero Points (id 40111) no Hero Saga.

Envia alerta no Telegram quando:
  - Venda Por = RMT  e  Valor < 45
  - Venda Por = Zeny (qualquer valor)

Cada oferta é avisada uma única vez enquanto estiver à venda (sem spam a cada
5 minutos). Se a oferta sumir e voltar, avisa de novo.

Dependências:  pip install requests beautifulsoup4
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ===================== CONFIGURAÇÃO =====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "COLE_AQUI_O_TOKEN_DO_BOT")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "COLE_AQUI_SEU_CHAT_ID")

ITEM_URL = "https://rpgherosaga.com/?module=item&action=view&id=40111"
LIMITE_RMT = 45  # alerta quando valor RMT for MENOR que isso

STATE_FILE = Path(__file__).with_name("monitor_hero_state.json")
# ========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


def enviar_telegram(texto: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    r.raise_for_status()


def numero(texto: str):
    """'45 RMT' -> 45 ; '1.500.000 z' -> 1500000"""
    digitos = re.sub(r"[^\d]", "", texto)
    return int(digitos) if digitos else None


def buscar_ofertas():
    r = requests.get(ITEM_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Acha a tabela cujo cabeçalho contém "Venda Por"
    tabela = None
    for t in soup.find_all("table"):
        if "venda por" in t.get_text(" ", strip=True).lower():
            tabela = t
            break
    if tabela is None:
        return None  # estrutura mudou ou nenhuma loja aberta

    linhas = tabela.find_all("tr")
    cab = [c.get_text(" ", strip=True).lower() for c in linhas[0].find_all(["th", "td"])]
    try:
        i_loja = cab.index("loja")
        i_valor = cab.index("valor")
        i_qtd = cab.index("qtd")
        i_venda = cab.index("venda por")
    except ValueError:
        return None

    ofertas = []
    for tr in linhas[1:]:
        cels = tr.find_all("td")
        if len(cels) <= max(i_loja, i_valor, i_qtd, i_venda):
            continue
        link = cels[i_loja].find("a")
        ofertas.append(
            {
                "loja": cels[i_loja].get_text(" ", strip=True),
                "link": link["href"] if link and link.has_attr("href") else ITEM_URL,
                "valor_txt": cels[i_valor].get_text(" ", strip=True),
                "valor": numero(cels[i_valor].get_text()),
                "qtd": cels[i_qtd].get_text(" ", strip=True),
                "venda_por": cels[i_venda].get_text(" ", strip=True),
            }
        )
    return ofertas


def interessa(o) -> bool:
    venda = o["venda_por"].strip().lower()
    if venda == "zeny":
        return True
    if venda == "rmt" and o["valor"] is not None and o["valor"] < LIMITE_RMT:
        return True
    return False


def carregar_estado():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"avisados": [], "erro_estrutura": False}


def salvar_estado(estado):
    STATE_FILE.write_text(json.dumps(estado, ensure_ascii=False, indent=2))


def main():
    estado = carregar_estado()
    ofertas = buscar_ofertas()

    if ofertas is None:
        # Avisa uma vez se a tabela não for encontrada
        if not estado.get("erro_estrutura"):
            enviar_telegram(
                "⚠️ Monitor Hero Points: não encontrei a tabela de lojas na página. "
                "Pode ser que não haja lojas abertas ou o site mudou.\n" + ITEM_URL
            )
            estado["erro_estrutura"] = True
            salvar_estado(estado)
        print("Tabela não encontrada.")
        return
    estado["erro_estrutura"] = False

    boas = [o for o in ofertas if interessa(o)]
    chaves_atuais = {f'{o["link"]}|{o["valor_txt"]}|{o["venda_por"]}' for o in boas}
    ja_avisados = set(estado.get("avisados", []))

    novas = [
        o for o in boas
        if f'{o["link"]}|{o["valor_txt"]}|{o["venda_por"]}' not in ja_avisados
    ]

    if novas:
        partes = ["🔔 <b>[100.000] Moeda Hero Points</b>\n"]
        for o in novas:
            tag = "💰 ZENY" if o["venda_por"].lower() == "zeny" else "📉 RMT barato"
            partes.append(
                f'{tag}: <b>{o["valor_txt"]}</b> (qtd {o["qtd"]})\n'
                f'Loja: <a href="{o["link"]}">{o["loja"]}</a>\n'
            )
        partes.append(ITEM_URL)
        enviar_telegram("\n".join(partes))
        print(f"Alerta enviado: {len(novas)} oferta(s).")
    else:
        print(f"Nada novo. {len(ofertas)} oferta(s) na página.")

    # guarda só as que ainda estão à venda (se sumir e voltar, avisa de novo)
    estado["avisados"] = sorted(chaves_atuais)
    salvar_estado(estado)


if __name__ == "__main__":
    if "--teste" in sys.argv:
        enviar_telegram("✅ Monitor Hero Points configurado!")
        print("Mensagem de teste enviada.")
    else:
        try:
            main()
        except Exception as e:
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)
