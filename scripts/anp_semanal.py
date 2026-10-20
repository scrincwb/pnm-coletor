#!/usr/bin/env python3
"""Baixa o resumo semanal mais recente da ANP e imprime JSON com precos.
Sem argumentos de municipio: extrai TODOS os municipios da planilha.
Uso: anp_semanal.py [--uf PR] [--arquivo local.xlsx] [--saida-dir DIR] "Curitiba" "Foz do Iguacu" ...
Falha (exit 1, mensagem no stderr) se o formato da planilha mudar."""
import argparse, io, json, re, sys, unicodedata, datetime, os
import requests, openpyxl

PAGINA = "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas"
UA = {"User-Agent": "Mozilla/5.0"}
PRODUTOS = {"GASOLINA COMUM": "gasolina", "ETANOL HIDRATADO": "etanol", "OLEO DIESEL S10": "diesel_s10"}
UFS = {"ACRE":"AC","ALAGOAS":"AL","AMAPA":"AP","AMAZONAS":"AM","BAHIA":"BA","CEARA":"CE","DISTRITO FEDERAL":"DF",
 "ESPIRITO SANTO":"ES","GOIAS":"GO","MARANHAO":"MA","MATO GROSSO":"MT","MATO GROSSO DO SUL":"MS","MINAS GERAIS":"MG",
 "PARA":"PA","PARAIBA":"PB","PARANA":"PR","PERNAMBUCO":"PE","PIAUI":"PI","RIO DE JANEIRO":"RJ","RIO GRANDE DO NORTE":"RN",
 "RIO GRANDE DO SUL":"RS","RONDONIA":"RO","RORAIMA":"RR","SANTA CATARINA":"SC","SAO PAULO":"SP","SERGIPE":"SE","TOCANTINS":"TO"}

def die(msg):
    print("ERRO: " + msg, file=sys.stderr); sys.exit(1)

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()

def achar_link():
    r = requests.get(PAGINA, headers=UA, timeout=60)
    if r.status_code != 200: die(f"pagina da ANP devolveu HTTP {r.status_code}: {PAGINA}")
    achados = []
    for h in re.findall(r'href="([^"]+\.xlsx)"', r.text, flags=re.I):
        nome = h.rsplit("/", 1)[-1].lower()
        if "resumo" not in nome or "lpc" not in nome: continue
        d = re.findall(r"(\d{4}-\d{2}-\d{2})", nome)
        if len(d) >= 2: achados.append((d[0], d[1], h))
    if not achados: die("nenhum link resumo_semanal_lpc_*.xlsx com datas encontrado na pagina (layout mudou?)")
    achados.sort()
    return achados[-1][2], achados[-1][0], achados[-1][1]

def achar_cab(ws, obrigatorias):
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=30, values_only=True), 1):
        cols = [norm(c) for c in row]
        if all(c in cols for c in obrigatorias):
            return i, {c: cols.index(c) for c in cols if c}
    die(f"aba {ws.title}: cabecalho com colunas {obrigatorias} nao encontrado nas 30 primeiras linhas")

def extrair(ws, nome_aba, col_local, municipios_norm, uf_alvo):
    obrig = ["DATA INICIAL","DATA FINAL",col_local,"PRODUTO","NUMERO DE POSTOS PESQUISADOS","UNIDADE DE MEDIDA","PRECO MEDIO REVENDA"]
    if nome_aba == "MUNICIPIOS": obrig.append("ESTADO")
    if nome_aba == "BRASIL": municipios_norm = set()
    li, idx = achar_cab(ws, obrig)
    out, datas = [], set()
    for row in ws.iter_rows(min_row=li + 1, values_only=True):
        if not row or row[idx["DATA INICIAL"]] is None: continue
        prod = PRODUTOS.get(norm(row[idx["PRODUTO"]]))
        if not prod: continue
        unid = norm(row[idx["UNIDADE DE MEDIDA"]])
        if unid != "R$/L": die(f"unidade inesperada '{row[idx['UNIDADE DE MEDIDA']]}' para {prod} (esperado R$/l)")
        preco = row[idx["PRECO MEDIO REVENDA"]]
        if not isinstance(preco, (int, float)) or not (0.5 < preco < 30):
            die(f"preco invalido {preco!r} em {row[idx[col_local]]} / {prod}")
        local = norm(row[idx[col_local]])
        di, df = row[idx["DATA INICIAL"]], row[idx["DATA FINAL"]]
        datas.add((di, df))
        n = row[idx["NUMERO DE POSTOS PESQUISADOS"]]
        if nome_aba == "MUNICIPIOS":
            uf_nome = norm(row[idx["ESTADO"]]); uf = UFS.get(uf_nome)
            if uf is None: die(f"estado desconhecido '{uf_nome}'")
            if (not municipios_norm or local in municipios_norm) and (not uf_alvo or uf == uf_alvo):
                out.append({"abrangencia":"municipio","uf":uf,"municipio":local,"produto":prod,"preco_medio":preco,"n_postos":n})
        elif nome_aba == "BRASIL":
            if local != "BRASIL": continue
            out.append({"abrangencia":"brasil","uf":"BR","municipio":None,"produto":prod,"preco_medio":preco,"n_postos":n})
        else:
            uf = UFS.get(local)
            if uf is None: die(f"estado desconhecido '{local}' na aba ESTADOS")
            out.append({"abrangencia":"estado","uf":uf,"municipio":None,"produto":prod,"preco_medio":preco,"n_postos":n})
    return out, datas

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("municipios", nargs="*")
    ap.add_argument("--uf", default=None, help="filtra municipios por UF (padrao: todas)")
    ap.add_argument("--arquivo", help="usar xlsx local em vez de baixar")
    ap.add_argument("--saida-dir", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--enviar", metavar="URL", help="POST do JSON para o site (chave no ambiente: ROTINA_CHAVE, cabecalho X-Chave)")
    a = ap.parse_args()
    if a.arquivo:
        data = open(a.arquivo, "rb").read(); url = None; nome = os.path.basename(a.arquivo)
    else:
        url, _, _ = achar_link()
        nome = url.rsplit("/", 1)[-1]
        r = requests.get(url, headers=UA, timeout=180)
        if r.status_code != 200: die(f"download falhou HTTP {r.status_code}: {url}")
        data = r.content
        try: open(os.path.join(a.saida_dir, nome), "wb").write(data)
        except OSError: pass
    try: wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e: die(f"nao consegui abrir o xlsx: {e}")
    abas = {norm(n): n for n in wb.sheetnames}
    for need in ("MUNICIPIOS", "ESTADOS"):
        if need not in abas: die(f"aba {need} nao encontrada; abas: {wb.sheetnames}")
    mn = {norm(m) for m in a.municipios}
    pm, d1 = extrair(wb[abas["MUNICIPIOS"]], "MUNICIPIOS", "MUNICIPIO", mn, (a.uf or '').upper())
    pe, d2 = extrair(wb[abas["ESTADOS"]], "ESTADOS", "ESTADOS", mn, (a.uf or '').upper())
    if "BRASIL" not in abas: die(f"aba BRASIL nao encontrada; abas: {wb.sheetnames}")
    pb, d3 = extrair(wb[abas["BRASIL"]], "BRASIL", "BRASIL", set(), "")
    faltam = set(PRODUTOS.values()) - {p["produto"] for p in pb}
    if faltam: die(f"aba BRASIL sem media nacional de: {sorted(faltam)}")
    datas = d1 | d2 | d3
    if len(datas) != 1: die(f"datas de semana inconsistentes na planilha: {datas}")
    di, df = next(iter(datas))
    if not (isinstance(di, datetime.datetime) and isinstance(df, datetime.datetime)): die(f"datas invalidas: {di!r} {df!r}")
    if not pe or len(pe) < 27 * 3 * 0.8: die(f"poucas linhas de estado ({len(pe)}); formato mudou?")
    if mn:
        achados = {p["municipio"] for p in pm}
        for m in sorted(mn - achados): print(f"AVISO: municipio ausente na amostra da ANP: {m}", file=sys.stderr)
    saida = {"semana_inicio": di.date().isoformat(), "semana_fim": df.date().isoformat(),
        "arquivo": nome, "fonte_url": url, "precos": pb + pm + pe}
    if a.enviar:
        chave = os.environ.get("ROTINA_CHAVE")
        if not chave: die("defina ROTINA_CHAVE no ambiente para usar --enviar")
        # Repo publico: o log mostra so o codigo HTTP e o resumo, nunca a resposta inteira.
        r = requests.post(a.enviar, data=json.dumps(saida, ensure_ascii=False).encode("utf-8"),
            # UA "curl/...": o Imunify360 do servidor responde "Bot Verification" (HTTP 200, HTML) a UA de
            # navegador vindo de datacenter (20/10/2026). Por isso tambem se exige resposta JSON.
            headers={"X-Chave": chave, "Content-Type": "application/json", "User-Agent": "curl/8.5.0 (pnm-coletor; +https://www.paraguainamao.com)"}, timeout=120)
        json_ok = r.headers.get("Content-Type", "").startswith("application/json")
        print(f"HTTP {r.status_code} {'JSON' if json_ok else 'NAO-JSON (bloqueio/firewall?)'} - {len(saida['precos'])} precos, semana {saida['semana_inicio']} a {saida['semana_fim']}")
        if r.status_code != 200 or not json_ok: sys.exit(1)
    else:
        print(json.dumps(saida, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
