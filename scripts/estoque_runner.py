#!/usr/bin/env python3
"""
Conferência de estoque feita PELO GITHUB (não pelo servidor).

Por quê: várias lojas bloqueiam o IP do servidor (Roma parou de responder,
Mega deu 429, Madrid Center/Cellshop/Matrix 403) e o servidor corta qualquer
pedido em 120 s. Aqui o runner do GitHub abre as páginas, no ritmo de cada
loja, e o servidor só decide e grava.

Fluxo: GET  api/coletor.php?acao=estoque_pendentes   → lojas, regra e ofertas
       POST api/coletor.php?acao=estoque_resultado   → {loja, canario_ok, itens:[{id, r}]}
r = true (à venda) / false (esgotado ou página 404/410) / null (não deu para saber).

As regras vêm do servidor (includes/produtos.php: ESTOQUE_POR_PAGINA e a
genérica schema.org) — mesma lógica de estoqueLerPagina().
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = os.environ["COLETOR_API_URL"]
TOKEN = os.environ["COLETOR_TOKEN"]
UA_API = os.environ.get("UA_NAV", "Mozilla/5.0")
UA_ROBO = "Mozilla/5.0 (compatible; ParaguaiNaMaoBot/1.0; +https://www.paraguainamao.com)"
UA_NAV = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
LOJAS_JUNTAS = 8          # lojas diferentes conferidas ao mesmo tempo
TEMPO_MAX = int(os.environ.get("ESTOQUE_MINUTOS", "45")) * 60
INICIO = time.time()

GEN_FORA = re.compile(r'schema\.org[\\/]*(?:OutOfStock|SoldOut|Discontinued)|"availability"\s*:\s*"(?:OutOfStock|SoldOut|Discontinued)"', re.I)
GEN_TEM = re.compile(r'schema\.org[\\/]*(?:InStock|LimitedAvailability|OnlineOnly|InStoreOnly|PreOrder|BackOrder)|"availability"\s*:\s*"(?:InStock|LimitedAvailability)"', re.I)


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def api(params, corpo=None):
    url = API + "?" + params
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, headers={
        "Authorization": "Bearer " + TOKEN, "User-Agent": UA_API,
        "Content-Type": "application/json", "Accept": "application/json"})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=150) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # servidor ocupado: tenta de novo
            if tentativa == 2:
                raise
            log(f"  API falhou ({type(e).__name__}), tentando de novo")
            time.sleep(10)


def compilar(regra):
    c = lambda lst: [re.compile(x["p"], re.I if x.get("i") else 0) for x in lst]
    return {"generico": regra.get("generico"), "em_estoque": c(regra.get("em_estoque", [])),
            "esgotado": c(regra.get("esgotado", [])), "sem_sinal": regra.get("sem_sinal"),
            "paralelo": max(1, min(6, int(regra.get("paralelo") or 3)))}


def baixar(url):
    """(código HTTP, html). 403/429/503 tenta de novo com cara de navegador, com calma."""
    cod, html = 0, ""
    for ua, espera in ((UA_ROBO, 0), (UA_NAV, 3)):
        if espera:
            time.sleep(espera)
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml",
                                                   "Accept-Language": "es-PY,es;q=0.9,pt-BR;q=0.8"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                cod, html = r.status, r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            cod, html = e.code, ""
        except Exception:
            cod, html = 0, ""
        if cod not in (403, 429, 503):
            break
    return cod, html


def ler(cod, html, regra):
    if cod in (404, 410):
        return False                      # página sumiu = não vende mais
    if cod != 200 or len(html) < 2000:
        return None
    if regra["generico"]:
        if GEN_FORA.search(html) and not GEN_TEM.search(html):
            return False
        return True                       # "sem sinal" — o servidor não põe de volta
    if regra["em_estoque"]:
        if any(p.search(html) for p in regra["em_estoque"]):
            return True
        if any(p.search(html) for p in regra["esgotado"]):
            return False
        return regra["sem_sinal"]
    return not any(p.search(html) for p in regra["esgotado"])


def conferir_loja(slug, dados):
    regra = compilar(dados["regra"])
    par = regra["paralelo"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        canario_ok = any(r is True for r in ex.map(lambda u: ler(*baixar(u), regra), dados.get("canarios") or []))
    itens, resultado, codigos = dados["itens"], [], {}
    parou = None
    with ThreadPoolExecutor(max_workers=par) as ex:
        for i in range(0, len(itens), par * 4):
            if time.time() - INICIO > TEMPO_MAX:
                parou = "tempo"
                break
            bloco = itens[i:i + par * 4]
            paginas = list(ex.map(lambda it: baixar(it["url"]), bloco))
            res = []
            for it, (cod, html) in zip(bloco, paginas):
                codigos[str(cod)] = codigos.get(str(cod), 0) + 1
                res.append({"id": it["id"], "r": ler(cod, html, regra)})
            resultado += res
            # A loja começou a recusar (70%+ do bloco sem resposta): para, para não ser bloqueado.
            if sum(1 for x in res if x["r"] is None) >= 0.7 * len(res) and len(res) >= 6:
                parou = "loja_recusando"
                break
            time.sleep(0.5)
    resumo = []
    for i in range(0, len(resultado), 500):
        resumo.append(api("acao=estoque_resultado", {"loja": slug, "canario_ok": canario_ok, "itens": resultado[i:i + 500]}))
    tiradas = sum(r.get("tiradas_do_ar", 0) for r in resumo)
    erros = [r.get("erro") for r in resumo if not r.get("ok")]
    log(f"{slug}: {len(resultado)} conferidas, {tiradas} tiradas do ar, canário {'ok' if canario_ok else 'NÃO'}"
        f", códigos {codigos}" + (f", parou: {parou}" if parou else "") + (f", ERRO {erros}" if erros else ""))
    return slug, len(resultado), tiradas, codigos, parou, erros


def main():
    qtd = os.environ.get("ESTOQUE_QTD", "1500")
    qtd_outras = os.environ.get("ESTOQUE_QTD_OUTRAS", "300")
    pend = api(f"acao=estoque_pendentes&qtd={qtd}&qtd_outras={qtd_outras}")
    lojas = pend.get("lojas") or {}
    log(f"{len(lojas)} lojas, {sum(len(d['itens']) for d in lojas.values())} ofertas para conferir")
    # Lojas com mais ofertas primeiro (terminam por último)
    ordem = sorted(lojas.items(), key=lambda kv: -len(kv[1]["itens"]))
    with ThreadPoolExecutor(max_workers=LOJAS_JUNTAS) as ex:
        resultados = list(ex.map(lambda kv: conferir_loja(*kv), ordem))
    total = sum(r[1] for r in resultados)
    tiradas = sum(r[2] for r in resultados)
    log(f"FIM: {total} conferidas, {tiradas} tiradas do ar, {round((time.time() - INICIO) / 60)} min")
    recusando = [r[0] for r in resultados if r[4] == "loja_recusando"]
    if recusando:
        log("Lojas que recusaram o GitHub também: " + ", ".join(recusando))
    return 0


if __name__ == "__main__":
    sys.exit(main())
