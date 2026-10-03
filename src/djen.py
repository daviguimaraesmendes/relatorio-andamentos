"""DJEN (API pública do CNJ, sem login), usado em ACRÉSCIMO ao jus.br:

- Descoberta: procura publicações pelo nome dos clientes (clientes.json) e
  lista os processos que ainda NÃO estão na carteira. Nada entra na carteira
  sozinho: homônimo existe, e a inclusão é decisão do advogado.
- Polo e parte contrária dos processos da carteira (carteira.py --completar-djen).

O conteúdo do relatório não vem daqui: vem dos autos no jus.br (coletor.py),
que mostram também andamentos ainda não publicados.

A API aceita 20 requisições por minuto; o cliente respeita o limite.

Uso:
    python djen.py descobrir [--dias 180]
    python djen.py incluir NUMERO [NUMERO ...]     # ou: incluir todos
    python djen.py ignorar NUMERO [NUMERO ...]     # não volta a aparecer na descoberta
"""
import csv
import datetime
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import comum
from comum import load_json, save_json
import carteira as cart

URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
POR_PAGINA = 100


def __getattr__(nome):  # djen.DESCOBERTA_FILE acompanha o relatório ativo
    if nome == "DESCOBERTA_FILE":
        return comum.DATA / "descoberta.json"
    raise AttributeError(nome)


def _descoberta():
    return comum.DATA / "descoberta.json"
_ultima = [0.0]


def _get(params, tentativas=5):
    for t in range(1, tentativas + 1):
        espera = 3.1 - (time.time() - _ultima[0])  # 20/min = uma a cada 3 s
        if espera > 0:
            time.sleep(espera)
        _ultima[0] = time.time()
        req = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "relatorio-clientes/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", 65)))
                continue
            if t == tentativas:
                raise
        except (urllib.error.URLError, TimeoutError):
            if t == tentativas:
                raise
        time.sleep(2 * t)
    raise RuntimeError("DJEN não respondeu.")


def buscar(**filtros):
    itens, pagina = [], 1
    while True:
        dados = _get({**filtros, "pagina": pagina, "itensPorPagina": POR_PAGINA})
        lote = dados.get("items") or []
        itens += lote
        if len(lote) < POR_PAGINA:
            return itens
        pagina += 1


def _janela(dias):
    fim = datetime.date.today()
    return {"dataDisponibilizacaoInicio": (fim - datetime.timedelta(days=dias)).isoformat(),
            "dataDisponibilizacaoFim": fim.isoformat()}


def partes_do_processo(numero):
    """[(nome, 'A'|'P')] dos destinatários de todas as publicações do processo."""
    vistos = set()
    for item in buscar(numeroProcesso=numero):
        for d in item.get("destinatarios") or []:
            vistos.add((d.get("nome", "").strip(), d.get("polo")))
    return sorted(vistos)


# --- 1. descoberta ---

def descobrir(dias=180):
    na_carteira = {p["numero"] for p in load_json(comum.CARTEIRA_FILE, [])}
    anterior = load_json(_descoberta(), {})
    ignorados = set(anterior.get("ignorados", []))
    achados = {}
    for cli in cart.clientes():
        nomes = [cli["nome"], *cli.get("variacoes", [])]
        for nome in nomes:
            print(f"Buscando '{nome}' nos últimos {dias} dias...")
            for item in buscar(nomeParte=nome, **_janela(dias)):
                num = item.get("numeroprocessocommascara")
                dest = item.get("destinatarios") or []
                polos = {d.get("polo") for d in dest if any(cart.nome_bate(v, d.get("nome", "")) for v in nomes)}
                if not num or not polos or num in na_carteira or num in ignorados:
                    continue  # a busca do DJEN é por trecho de nome: só fica o que bate de verdade
                a = achados.setdefault(num, {"numero": num, "tribunal": item.get("siglaTribunal", ""),
                                             "classe": item.get("nomeClasse", ""), "orgao": item.get("nomeOrgao", ""),
                                             "cliente": cli["nome"], "polos_cliente": set(), "outras_partes": set(),
                                             "publicacoes": 0, "ultima": ""})
                a["polos_cliente"] |= polos
                a["outras_partes"] |= {d["nome"] for d in dest if d.get("polo") and d.get("polo") not in polos}
                a["publicacoes"] += 1
                a["ultima"] = max(a["ultima"], item.get("data_disponibilizacao", ""))
    lista = []
    for a in sorted(achados.values(), key=lambda x: x["ultima"], reverse=True):
        polo = {"A": "ativo", "P": "passivo"}.get(next(iter(a["polos_cliente"])), "") if len(a["polos_cliente"]) == 1 else ""
        lista.append({**a, "polo_cliente": polo, "polos_cliente": sorted(a["polos_cliente"]),
                      "outras_partes": "; ".join(sorted(a["outras_partes"]))})
    save_json(_descoberta(), {"gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
                                "dias": dias, "pendentes": lista, "ignorados": sorted(ignorados)})
    destino = comum.DATA / f"descoberta-{datetime.date.today():%Y-%m-%d}.csv"
    with destino.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["numero", "tribunal", "cliente", "polo_cliente", "outras_partes",
                                          "classe", "orgao", "publicacoes", "ultima"], extrasaction="ignore", delimiter=";")
        w.writeheader()
        w.writerows(lista)
    print(f"\n{len(lista)} processo(s) com publicação no DJEN que não estão na carteira:")
    for a in lista:
        print(f"  {a['numero']}  {a['tribunal']:6}  {a['cliente'][:25]:25}  polo {a['polo_cliente'] or '?':8}  "
              f"x {a['outras_partes'][:50]}  (última: {a['ultima']})")
    print(f"\nPlanilha: {destino}\nPara incluir: python djen.py incluir NUMERO ...  |  descartar: python djen.py ignorar NUMERO ...")
    print("Só aparece processo com publicação no período; processo parado não é encontrado por esta busca.")


def incluir(numeros):
    dados = load_json(_descoberta(), {})
    pend = dados.get("pendentes", [])
    escolhidos = pend if numeros == ["todos"] else [p for p in pend if p["numero"] in numeros]
    regs = [{"numero": p["numero"], "tribunal": p["tribunal"], "cliente": p["cliente"],
             "polo_cliente": p["polo_cliente"], "parte_contraria": p["outras_partes"]} for p in escolhidos]
    n = cart.mesclar(regs, "djen")
    dados["pendentes"] = [p for p in pend if p not in escolhidos]
    save_json(_descoberta(), dados)
    print(f"{n} processo(s) incluído(s) na carteira.")


def ignorar(numeros):
    dados = load_json(_descoberta(), {})
    dados["ignorados"] = sorted(set(dados.get("ignorados", [])) | set(numeros))
    dados["pendentes"] = [p for p in dados.get("pendentes", []) if p["numero"] not in numeros]
    save_json(_descoberta(), dados)
    print(f"{len(numeros)} processo(s) ignorado(s) nas próximas descobertas.")


if __name__ == "__main__":
    a = sys.argv[1:]
    dias = int(a[a.index("--dias") + 1]) if "--dias" in a else None
    if a[:1] == ["descobrir"]:
        descobrir(dias or 180)
    elif a[:1] == ["incluir"]:
        incluir(a[1:])
    elif a[:1] == ["ignorar"]:
        ignorar(a[1:])
    else:
        print(__doc__)
