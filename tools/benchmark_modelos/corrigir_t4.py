"""Corrige o T4 (resumo de documentos reais): checagens automáticas de fidelidade e forma + concordância entre modelos."""
import json, os, re, sys, glob, random, collections
import tempfile
_T = tempfile.mkdtemp(prefix="benchmark-")
os.environ.update(RELATORIO_DATA=_T + "/data", RELATORIO_CARTEIRA=_T + "/c.json", RELATORIO_CLIENTES=_T + "/cl.json", RELATORIO_PROJETOS=_T + "/p")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import resumir
B = os.path.dirname(os.path.abspath(__file__)) + "/"
tx = json.load(open(B + "t4_textos_para_corretor.json", encoding="utf-8"))
textos, meta = tx["textos"], tx["meta"]
EFEITOS = {"favoravel", "desfavoravel", "neutro", "incerto"}
norm = lambda s: re.sub(r"\s+", " ", str(s)).lower()
def numeros(txt):
    achados = set(re.findall(r"R\$\s?[\d\.\,]+\d", txt)) | set(re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", txt)) | set(re.findall(r"\b\d{1,3}(?:,\d+)?\s?%", txt))
    return {re.sub(r"\s", "", a).rstrip(".,") for a in achados}
def no_texto(num, texto):
    return num in re.sub(r"\s", "", texto)
GER = re.compile(r"^\W*[A-Za-zÀ-ÿ]+ndo\b", re.I)
configs = sys.argv[1:] or sorted(os.path.basename(p) for p in glob.glob(B + "respostas/*") if os.path.exists(p + "/T4v2.json"))
dados = {}
for c in configs:
    try: dados[c] = json.load(open(B + f"respostas/{c}/T4v2.json", encoding="utf-8"))
    except Exception as e: print(c, "T4 ausente/ inválido:", e); 
linhas = []
for c, resp in dados.items():
    ok = dict(presentes=0, efeito_valido=0, trecho_ok=0, ger=0, tamanho=0, sem_alerta=0, inventados=0, nums_total=0)
    palavras = []
    for did, texto in textos.items():
        r = resp.get(did)
        if not isinstance(r, dict) or not isinstance(r.get("conteudo"), str): continue
        ok["presentes"] += 1
        ok["efeito_valido"] += r.get("efeito") in EFEITOS
        ok["trecho_ok"] += bool(r.get("trecho_origem")) and resumir.trecho_confere(r["trecho_origem"], texto)
        c_limpo = resumir.limpar_conteudo(r["conteudo"])
        ok["ger"] += bool(GER.match(c_limpo))
        n = len(c_limpo.split()); palavras.append(n); ok["tamanho"] += resumir.MINIMO_PALAVRAS * 2 <= n <= resumir.LIMITE_PALAVRAS + 15
        try: ok["sem_alerta"] += not resumir.conferir({k: r.get(k) for k in ("conteudo", "trecho_origem", "prazo", "audiencia", "efeito")}, texto)
        except Exception: pass
        nums = numeros(r["conteudo"]); ok["nums_total"] += len(nums)
        ok["inventados"] += sum(1 for x in nums if not no_texto(x, texto))
    ok["palavras_media"] = round(sum(palavras) / max(len(palavras), 1), 1)
    linhas.append((c, ok))
N = len(textos)
print(f"{'config':14} {'itens':>5} {'efeito ok':>9} {'trecho literal':>14} {'gerúndio':>8} {'tamanho':>7} {'sem alerta':>10} {'nº inventado':>13} {'palavras':>8}")
for c, o in linhas:
    print(f"{c:14} {o['presentes']:>3}/{N:<2} {o['efeito_valido']:>7}/{N:<2} {o['trecho_ok']:>12}/{N:<2} {o['ger']:>6}/{N:<2} {o['tamanho']:>5}/{N:<2} {o['sem_alerta']:>8}/{N:<2} {o['inventados']:>5} de {o['nums_total']:<5} {o['palavras_media']:>7}")
# concordância de efeito entre os modelos
print("\nCONCORDÂNCIA DE 'efeito' (documento a documento)")
ref = "opus-medium" if "opus-medium" in dados else None
for did in textos:
    vals = {c: (dados[c].get(did) or {}).get("efeito") for c in dados}
    cont = collections.Counter(vals.values())
    if len(cont) > 1: print(f"  {did} {meta[did]['tipo'][:28]:28} {vals}")
if ref:
    print(f"\nconcordância com {ref} no 'efeito':", {c: sum(1 for did in textos if (dados[c].get(did) or {}).get('efeito') == (dados[ref].get(did) or {}).get('efeito')) for c in dados if c != ref}, "de", N)
# arquivo lado a lado, modelos embaralhados (revisão às cegas)
random.seed(7)
rot = {c: chr(65 + i) for i, c in enumerate(random.sample(list(dados), len(dados)))}
json.dump(rot, open(B + "legenda_modelos_T4.json", "w"), ensure_ascii=False)
with open(B + "comparacao_t4.md", "w", encoding="utf-8") as f:
    f.write("# T4: resumos lado a lado (modelos embaralhados: A, B, C...)\n\n")
    for did, texto in textos.items():
        f.write(f"## {did} · {meta[did]['tipo']} · {meta[did]['grau']}\n\n*Trecho do documento (início):* {texto[:380].strip()!r}\n\n")
        for c in sorted(dados, key=lambda k: rot[k]):
            r = dados[c].get(did) or {}
            f.write(f"- **{rot[c]}** · efeito `{r.get('efeito')}` · prazo `{r.get('prazo')}` · audiência `{r.get('audiencia')}`: {resumir.limpar_conteudo(r.get('conteudo', ''))}\n")
        f.write("\n")
print("\ncomparação lado a lado:", B + "comparacao_t4.md")
