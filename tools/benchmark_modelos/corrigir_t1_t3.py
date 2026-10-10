"""Corrige as respostas dos candidatos (T1 a T3) contra os gabaritos. Uso: python corrigir_t1_t3.py [config ...]
Esperados na mesma pasta: t1_input.json, t1_truth.json, t2_truth.json, t3_input.json, t3_truth.json e respostas/<config>/T1.json, T2.json, T3.json."""
import json, sys, os, glob
B = os.path.dirname(os.path.abspath(__file__)) + "/"
def carregar(nome):
    return json.load(open(B + nome, encoding="utf-8"))
t1_in, t1_gab = carregar("t1_input.json"), carregar("t1_truth.json")
t2_gab = carregar("t2_truth.json")
t3_in, t3_gab = carregar("t3_input.json"), carregar("t3_truth.json")
campos_validos = {c["campo"] for c in t1_in["campos_destino"]}
voc = t3_in["vocabularios"]
def tentar(caminho):
    try:
        return json.load(open(caminho, encoding="utf-8")), None
    except FileNotFoundError:
        return None, "arquivo ausente"
    except ValueError as e:
        return None, f"JSON inválido ({str(e)[:40]})"

def corrigir_t1(r):
    certos, erros, inventados, conf_ok, conf_erro = 0, [], 0, [], []
    for cid, g in t1_gab.items():
        resp = (r or {}).get(cid) or {}
        campo = resp.get("campo")
        if campo is not None and campo not in campos_validos: inventados += 1
        ok = campo in g["aceitos"]
        certos += ok
        c = resp.get("confianca")
        if isinstance(c, (int, float)): (conf_ok if ok else conf_erro).append(c)
        if not ok: erros.append((g["cabecalho"][:30], campo, g["aceitos"]))
    return dict(certos=certos, total=len(t1_gab), erros=erros, inventados=inventados,
                conf_ok=sum(conf_ok) / len(conf_ok) if conf_ok else None, conf_erro=sum(conf_erro) / len(conf_erro) if conf_erro else None)

def igual_t2(tipo, got, esp):
    if tipo == "dinheiro":
        if got is None or esp is None: return got is None and esp is None
        try: return abs(float(got) - float(esp)) < 0.005
        except (TypeError, ValueError): return False
    if tipo == "percentual":
        if got is None or esp is None: return got is None and esp is None
        try: return abs(float(got) - float(esp)) < 1e-9
        except (TypeError, ValueError): return False
    if tipo == "probabilidade":
        if not isinstance(got, dict): return False
        n = lambda v: (str(v).strip().rstrip(".").casefold() if v not in (None, "") else None)
        return n(got.get("grau")) == n(esp.get("grau")) and n(got.get("justificativa")) == n(esp.get("justificativa"))
    return got == esp

def corrigir_t2(r):
    por_tipo, erros = {}, []
    for vid, g in t2_gab.items():
        got = (r or {}).get(vid, "<ausente>")
        ok = got != "<ausente>" and igual_t2(g["tipo"], got, g["esperado"])
        a = por_tipo.setdefault(g["tipo"], [0, 0]); a[1] += 1; a[0] += ok
        if not ok: erros.append((vid, g["tipo"], got, g["esperado"]))
    return dict(por_tipo=por_tipo, certos=sum(a[0] for a in por_tipo.values()), total=len(t2_gab), erros=erros)

CAMPOS_T3 = ("momento_atual", "situacao", "fase", "houve_recurso", "resultado", "data_ultimo_andamento")
def corrigir_t3(r):
    por_campo = {c: [0, 0] for c in CAMPOS_T3}; fora_vocab = 0; inventou = 0; erros = []
    for oid, g in t3_gab.items():
        resp = (r or {}).get(oid) or {}
        for c in CAMPOS_T3:
            v = resp.get(c)
            ok = v in g[c]
            if c in voc and v is not None and v not in voc[c]: fora_vocab += 1
            if c in ("momento_atual", "resultado", "situacao", "fase") and v is not None and g[c] == [None]: inventou += 1
            por_campo[c][1] += 1; por_campo[c][0] += ok
            if not ok: erros.append((oid, c, v, g[c]))
    return dict(por_campo=por_campo, certos=sum(a[0] for a in por_campo.values()), total=sum(a[1] for a in por_campo.values()), fora_vocab=fora_vocab, inventou=inventou, erros=erros)

configs = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(B + "respostas/*"))
resumo = []
for cfg in configs:
    d = B + "respostas/" + cfg + "/"
    t1, e1 = tentar(d + "T1.json"); t2, e2 = tentar(d + "T2.json"); t3, e3 = tentar(d + "T3.json")
    a, b, c = corrigir_t1(t1), corrigir_t2(t2), corrigir_t3(t3)
    resumo.append((cfg, a, b, c, (e1, e2, e3)))
print(f"{'config':16} {'T1 colunas':>11} {'T2 valores':>11} {'T3 texto livre':>15} {'total':>8}")
for cfg, a, b, c, ex in resumo:
    tot = a["certos"] + b["certos"] + c["certos"]; den = a["total"] + b["total"] + c["total"]
    print(f"{cfg:16} {a['certos']:>5}/{a['total']:<5} {b['certos']:>5}/{b['total']:<5} {c['certos']:>7}/{c['total']:<7} {100*tot/den:6.1f}%" + (f"  ! {ex}" if any(ex) else ""))
print()
for cfg, a, b, c, ex in resumo:
    print(f"== {cfg}")
    print("  T1 inventou campo:", a["inventados"], "| confiança média acerto/erro:", None if a["conf_ok"] is None else round(a["conf_ok"], 2), "/", None if a["conf_erro"] is None else round(a["conf_erro"], 2))
    for cab, got, esp in a["erros"]: print(f"     T1 erro: {cab!r}: deu {got!r}, aceitos {esp}")
    print("  T2 por tipo:", {k: f"{v[0]}/{v[1]}" for k, v in b["por_tipo"].items()})
    for vid, tipo, got, esp in b["erros"][:8]: print(f"     T2 erro {vid} ({tipo}): deu {got!r}, esperado {esp!r}")
    print("  T3 por campo:", {k: f"{v[0]}/{v[1]}" for k, v in c["por_campo"].items()}, "| fora do vocabulário:", c["fora_vocab"], "| inventou onde não havia:", c["inventou"])
    for oid, campo, got, esp in c["erros"][:10]: print(f"     T3 erro {oid}.{campo}: deu {got!r}, aceitos {esp}")
