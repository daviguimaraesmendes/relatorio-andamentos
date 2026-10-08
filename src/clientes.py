"""Identificação de clientes em lote.

Um relatório importado raramente diz, processo a processo, quem é o cliente: o modelo A só tem o título, o modelo B
(planilha) não tem coluna de cliente e a lista bruta, nem isso. Em vez de pedir o cliente 92 vezes, este módulo:

  1. propõe os clientes a partir das PARTES dos processos importados (`candidatos`): a empresa que aparece em muitos
     processos, com as grafias agrupadas ("Cliente Exemplo Ltda", "CLIENTE EXEMPLO LTDA.") e, quando há várias empresas com a mesma
     marca, um candidato "grupo" ("Cliente Exemplo" cobre "Cliente Exemplo Comércio Ltda" e "Cliente Exemplo
     Distribuidora Ltda");
  2. aplica o cliente escolhido a todos os processos que tenham uma parte correspondente (`identificar`), já deduzindo
     o polo (autor ou réu) e a parte contrária, e usa um cliente padrão para o que sobrar;
  3. permite aplicar um cliente a vários processos de uma vez (`aplicar_em_lote`), para a tela de cadastro.

Nada aqui adivinha em silêncio: o que não casa ou casa dos dois lados volta no relatório (`sem_correspondencia`,
`ambiguos`). Cliente já definido por pessoa (origem "humano") nunca é trocado.

Uso (programa): clientes.candidatos(fichas) -> [candidato]; clientes.identificar(fichas, especs, padrao=...) -> relatório.
`espec` = {"nome": "Cliente Exemplo", "variacoes": ["Cliente Exemplo"]}.
"""
import re
from collections import Counter, defaultdict

import carteira as cart
import comum
import ficha

# palavras que não distinguem uma parte da outra (tipo de pessoa jurídica, ligações); saem da chave de comparação
GENERICAS = {"condominio", "edificio", "residencial", "residence", "empresa", "grupo", "associacao", "sindicato",
             "municipio", "estado", "banco", "cooperativa", "fundacao", "instituto"}
LIGACOES = {"da", "de", "do", "das", "dos", "e", "d", "a", "o"}
SEPARADORES = re.compile(r"\s*(?:;|/|\||,|&|\s+e\s+)\s*", re.I)


def partes(texto):
    """['Nome 1', 'Nome 2'] de um campo de partes ("A, B e C", "A; B")."""
    return [p.strip(" .-") for p in SEPARADORES.split(str(texto or "")) if len(p.strip(" .-")) >= 3]


def nucleo(nome):
    """Palavras que identificam a parte: sem acento, sem sufixo societário (Ltda, S.A....), sem ligações nem termos
    genéricos ("Condomínio", "Edifício"). 'Condomínio do Edifício Blue Ocean' -> ['blue', 'ocean']."""
    palavras = [p for p in cart._sem_sufixo(nome) if p not in LIGACOES]
    sem_genericas = [p for p in palavras if p not in GENERICAS]
    return sem_genericas or palavras


def _casa_nucleo(parte, variacao):
    """A parte é a variação, ou começa por ela (ao menos 2 palavras identificadoras, ou igualdade)."""
    if not parte or not variacao:
        return False
    return parte == variacao or (len(variacao) >= 2 and parte[:len(variacao)] == variacao)


def partes_da_ficha(f):
    return {"autores": partes(ficha.obter(f, "autores")), "reus": partes(ficha.obter(f, "reus"))}


def lado(espec, f):
    """'ativo' (aparece entre os autores), 'passivo' (entre os réus), 'ambos' ou None."""
    variacoes = [nucleo(v) for v in [espec.get("nome"), *(espec.get("variacoes") or [])] if v]
    variacoes = [v for v in variacoes if v]
    encontrou = set()
    for nome_lado, polo in (("autores", "ativo"), ("reus", "passivo")):
        for p in partes_da_ficha(f)[nome_lado]:
            n = nucleo(p)
            if any(_casa_nucleo(n, v) for v in variacoes):
                encontrou.add(polo)
    if not encontrou:
        return None
    return "ambos" if len(encontrou) == 2 else encontrou.pop()


# ---------------------------------------------------------------- sugestão a partir das partes

def candidatos(fichas, *, minimo=2, topo=12):
    """Clientes prováveis a partir das partes dos processos. Cada um:
    {"nome", "variacoes", "tipo": "nome"|"grupo", "processos", "autor", "reu", "cobertura"}.
    Ordenados por número de processos; `cobertura` = fração dos processos em que a parte aparece."""
    total = max(1, len(fichas))
    por_chave = defaultdict(lambda: {"grafias": Counter(), "numeros": set(), "autor": set(), "reu": set()})
    for f in fichas:
        for nome_lado, marca in (("autores", "autor"), ("reus", "reu")):
            for p in partes_da_ficha(f)[nome_lado]:
                n = nucleo(p)
                if not n:
                    continue
                d = por_chave[tuple(n)]
                d["grafias"][p] += 1
                d["numeros"].add(f["numero"])
                d[marca].add(f["numero"])
    lista = []
    for chave, d in por_chave.items():
        lista.append({"nome": d["grafias"].most_common(1)[0][0], "variacoes": [g for g, _ in d["grafias"].most_common()],
                      "tipo": "nome", "processos": len(d["numeros"]), "autor": d["autor"], "reu": d["reu"],
                      "numeros": d["numeros"], "chave": chave})
    # grupos: várias empresas com a mesma marca (duas primeiras palavras identificadoras)
    marcas = defaultdict(list)
    for c in lista:
        marcas[c["chave"][:2]].append(c)
    for marca, membros in marcas.items():
        # várias empresas da mesma marca: ao menos duas delas têm mais de um processo (pessoas físicas que só
        # compartilham o primeiro nome não formam grupo, porque cada uma aparece uma vez)
        if len(marca) < 2 or sum(1 for m in membros if m["processos"] >= 2) < 2:
            continue
        numeros = set().union(*(m["numeros"] for m in membros))
        modelo = max(membros, key=lambda m: m["processos"])["nome"]
        nome = _prefixo_original(modelo, len(marca))
        lista.append({"nome": nome, "variacoes": [nome], "tipo": "grupo", "processos": len(numeros),
                      "autor": len(set().union(*(m["autor"] for m in membros))),
                      "reu": len(set().union(*(m["reu"] for m in membros))),
                      "numeros": numeros, "chave": marca})
    # grupo que cobre exatamente o mesmo conjunto de processos de um nome único não acrescenta nada
    vistos, final = set(), []
    for c in sorted(lista, key=lambda c: (-c["processos"], c["tipo"] != "grupo", c["nome"])):
        if c["processos"] < minimo:
            continue
        conjunto = frozenset(c["numeros"])
        if conjunto in vistos and c["tipo"] == "grupo":
            continue
        vistos.add(conjunto)
        c["cobertura"] = round(c["processos"] / total, 3)
        final.append(c)
    for c in final:
        c["autor"], c["reu"] = len(c["autor"]) if not isinstance(c["autor"], int) else c["autor"], \
            len(c["reu"]) if not isinstance(c["reu"], int) else c["reu"]
        c.pop("numeros", None)
        c.pop("chave", None)
    return final[:topo]


def _prefixo_original(nome, n_palavras_identificadoras):
    """Início do nome original que contém as `n` primeiras palavras identificadoras ('Cliente Exemplo Comércio...' -> 'Cliente Exemplo')."""
    palavras, vistos = nome.split(), 0
    fim = len(palavras)
    for i, p in enumerate(palavras):
        chave = comum.normalizar(p).strip(".,;")
        if chave and chave not in LIGACOES and chave not in GENERICAS:
            vistos += 1
        if vistos >= n_palavras_identificadoras:
            fim = i + 1
            break
    return " ".join(palavras[:fim]).strip(" ,.;")


# ---------------------------------------------------------------- aplicação em lote

def especs_do_projeto():
    """Clientes já cadastrados (clientes.json) no formato de `espec`."""
    return [{"nome": c["nome"], "variacoes": c.get("variacoes", [])}
            for c in comum.load_json(comum.CLIENTES_FILE, {"clientes": []}).get("clientes", []) if c.get("nome")]


def registrar(especs):
    """Garante o cadastro dos clientes em clientes.json (sem apagar nem duplicar). Devolve os nomes novos."""
    dados = comum.load_json(comum.CLIENTES_FILE, {"clientes": []})
    lista = dados.setdefault("clientes", [])
    existentes = {comum.normalizar(c.get("nome", "")): c for c in lista}
    novos = []
    for e in especs:
        chave = comum.normalizar(e["nome"])
        atual = existentes.get(chave)
        if atual is None:
            atual = {"nome": e["nome"], "variacoes": [], "contato": "", "responsavel": ""}
            lista.append(atual)
            existentes[chave] = atual
            novos.append(e["nome"])
        for v in e.get("variacoes") or []:
            if v and comum.normalizar(v) != chave and v not in atual.setdefault("variacoes", []):
                atual["variacoes"].append(v)
    comum.save_json(comum.CLIENTES_FILE, dados)
    return novos


def identificar(fichas, especs, *, padrao=None, sobrescrever=False, origem="migrado"):
    """Define cliente, polo e parte contrária dos processos pelas partes. `especs` na ordem de preferência.

    - processo sem cliente: o primeiro `espec` que casa vence; polo pelo lado em que o cliente aparece (se aparecer
      nos dois lados, o polo fica em branco e o processo entra em `ambiguos`); parte contrária = partes do outro
      lado, só se o campo estiver vazio;
    - o que ficar sem cliente recebe `padrao`, se houver;
    - `sobrescrever=True` também reavalia processos que já têm cliente de origem não humana;
    - cliente de origem `humano` nunca é trocado.
    Devolve {"aplicados": {cliente: n}, "padrao": n, "sem_correspondencia": [números], "ambiguos": [números]}."""
    rel = {"aplicados": Counter(), "padrao": 0, "sem_correspondencia": [], "ambiguos": []}
    for f in fichas:
        atual = ficha.obter(f, "cliente")
        if atual and (ficha.origem(f, "cliente") == "humano" or not sobrescrever):
            # já tem cliente: não o troca, mas completa polo e parte contrária se ele for um dos clientes dados
            e = next((e for e in especs if comum.normalizar(e["nome"]) == comum.normalizar(atual)), None)
            l = lado(e, f) if e else None
            if l in ("ativo", "passivo"):
                if not ficha.obter(f, "polo_cliente"):
                    ficha.definir(f, "polo_cliente", l, origem)
                outro = partes_da_ficha(f)["reus" if l == "ativo" else "autores"]
                if outro and not ficha.obter(f, "parte_contraria"):
                    ficha.definir(f, "parte_contraria", "; ".join(outro), origem)
            continue
        for e in especs:
            l = lado(e, f)
            if not l:
                continue
            ficha.definir(f, "cliente", e["nome"], origem, forcar=True)
            if l == "ambos":
                rel["ambiguos"].append(f["numero"])
            else:
                if not ficha.obter(f, "polo_cliente"):
                    ficha.definir(f, "polo_cliente", l, origem)
                outro = partes_da_ficha(f)["reus" if l == "ativo" else "autores"]
                if outro and not ficha.obter(f, "parte_contraria"):
                    ficha.definir(f, "parte_contraria", "; ".join(outro), origem)
            rel["aplicados"][e["nome"]] += 1
            break
        else:
            if padrao and not ficha.obter(f, "cliente"):
                ficha.definir(f, "cliente", padrao, origem)
                rel["padrao"] += 1
            elif not ficha.obter(f, "cliente"):
                rel["sem_correspondencia"].append(f["numero"])
    rel["aplicados"] = dict(rel["aplicados"])
    return rel


def aplicar_em_lote(fichas, nome, *, numeros=None, so_sem_cliente=True, origem="humano"):
    """Define o cliente `nome` de vários processos de uma vez (todos, ou só `numeros`). Devolve quantos mudaram.
    Origem padrão "humano": foi uma decisão da pessoa, então vale mais do que a dedução automática."""
    n = 0
    alvo = set(numeros) if numeros is not None else None
    for f in fichas:
        if alvo is not None and f["numero"] not in alvo:
            continue
        atual = ficha.obter(f, "cliente")
        if atual and so_sem_cliente:
            continue
        if atual == nome:
            continue
        if ficha.definir(f, "cliente", nome, origem, forcar=True):
            n += 1
    return n


def escolher_automatico(cands, *, cobertura_minima=0.6):
    """Candidato que dá para escolher sem perguntar: cobre a maior parte dos processos e aparece sempre do mesmo lado.
    Se não houver, None (a tela pergunta com um clique)."""
    for c in cands:
        if c["cobertura"] >= cobertura_minima and (c["autor"] == 0 or c["reu"] == 0 or min(c["autor"], c["reu"]) <= 0.1 * c["processos"]):
            return c
    return None
