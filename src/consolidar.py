"""Consolidação das fichas: vinculados, duplicatas, grafias de nomes e migração da Fase 1.

Quando relatórios de várias origens (um .docx, duas abas de um .xlsx, uma lista de números) viram fichas, o mesmo
processo costuma aparecer mais de uma vez, com números escritos de jeitos diferentes, grafias diferentes do mesmo
nome e rótulos soltos. Este módulo arruma o que dá para arrumar SEM adivinhar, e AVISA o resto.

Uso
    fichas, avisos = consolidar.consolidar(fichas)               # devolve cópias; a lista recebida não é alterada
    grupos = consolidar.sugerir_grafias(fichas)                  # grafias parecidas, para o usuário confirmar
    fichas, avisos = consolidar.aplicar_grafias(fichas, [{"canonico": "Sítio X Ltda", "variantes": ["SITIO X"]}])
    consolidar.campos_humanos_perdidos(antes, depois)            # [] = nenhum campo "humano" se perdeu
    consolidar.migrar_projeto("meu-relatorio")                   # carteira.json da Fase 1 -> fichas v2, em lote

O que consolidar() faz, nesta ordem
    1. Número CNJ: padroniza a máscara (0000000-00.0000.0.00.0000); número sem formato CNJ ou com dígito
       verificador errado NÃO é corrigido nem descartado: vira aviso `numero_invalido` (nível erro).
    2. Duplicata EXATA (mesmo número, mesmo com formatação diferente) é fundida numa ficha só. Por campo vence
       a origem de maior prioridade (humano > coletado > migrado > derivado > sugerido); em empate, o mais recente
       (`em`). O valor que perdeu NÃO some: fica em ficha["consolidacao"]["conflitos"]. Avisos:
       `duplicata_exata_fundida`, `campo_divergente`, `linha_de_base_divergente`.
    3. Vinculados: uma ficha cujo `vinculados` cita o número de OUTRA ficha da lista ("mesmo número em dois
       lugares": reajuizamento, mesma ação remetida por incompetência, agravo, apenso, recurso) passa a ser UMA linha:
       a ficha citada é absorvida pela principal (entra em `vinculados` com o tipo declarado, junto com os vinculados
       dela) e o retrato completo da absorvida fica em ficha["consolidacao"]["absorvidas"]. Só vínculo DECLARADO
       é aplicado; o que for só provável vira sugestão. Avisos: `vinculo_absorvido`, `materia_dois_rotulos`
       (a mesma matéria escrita de dois jeitos nas duas linhas), `vinculado_em_dois_principais`.
    4. Rótulos de vocabulário (área, situação, fase, resultado, probabilidade, polo, momento atual, matéria
       principal) são levados ao valor canônico quando há UM candidato; o texto original fica em
       ficha["consolidacao"]["originais"]. Sem candidato: `rotulo_fora_do_vocabulario`, com sugestões, e o
       valor fica como está. O qualificador do momento "(HONORÁRIOS SUSPENSOS)" é preservado.
    5. Sugestões (nada é alterado): `duplicata_provavel` (mesmo cliente, mesmas partes e mesma data de
       ajuizamento com números diferentes), `vinculo_provavel` (classe "Agravo"/"Apenso"... com as mesmas partes de
       outra linha) e `grafias_do_mesmo_nome` (Sitio/Sítio, com e sem Ltda, caixa; candidatos[0] é a grafia
       sugerida). Nomes só são unificados por aplicar_grafias(), com a confirmação de quem usa.

Garantias
    - Nunca se perde campo `humano`: ou continua no campo, ou fica registrado em ficha["consolidacao"]
      (campos_humanos_perdidos() confere).
    - Idempotente: consolidar(consolidar(x)[0])[0] == consolidar(x)[0]. Só as SUGESTÕES se repetem nos avisos.
    - Origem e carimbo de hora (`em`) dos campos são preservados; nada é regravado com a hora de agora.
    - Aviso = {"nivel", "codigo", "onde", "mensagem", "candidatos"} (CONTRATOS, seção 4) mais, quando o aviso
      trata de processos, "numeros": [...] (todos os números envolvidos).

Falsos positivos conhecidos
    - duplicata_provavel e vinculo_provavel dependem de cliente, partes e data preenchidos; linhas com essas
      informações genéricas (ex.: "Diversos") podem ser acusadas à toa. Por isso só sugerem.
    - grafias_do_mesmo_nome trata "Empresa X Ltda" e "Empresa X S.A." como a mesma grafia (o sufixo societário é
      ignorado), o que pode juntar empresas de fato diferentes: por isso só sugere.
    - O padrão "um número vinculado citado por dois principais" mantém o vínculo no primeiro e só avisa.

Migração da Fase 1 (migrar_projeto): itens de projetos/<slug>/carteira.json sem "v": 2 viram fichas v2 por
ficha.de_carteira_v1 (campos planos continuam; cada um ganha origem "migrado"). Antes de gravar, o arquivo original
é copiado para carteira.fase1.json (uma vez). Rodar de novo não muda nada.
"""
import copy
import re
import shutil
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import carteira as cart
import comum
import ficha as fch
import taxonomia

CAMPOS_DE_NOME = ("cliente", "autores", "reus", "parte_contraria", "outras_partes")
# campos com vocabulário (a matéria principal não tem vocabulário em ficha.CAMPOS, mas tem em taxonomia)
CAMPOS_COM_VOCABULARIO = {**{n: c[3] for n, c in fch.CAMPOS.items() if c[3]}, "materia_principal": "materia"}
_CLASSE_DE_VINCULO = re.compile(r"agravo|apenso|embargos|incidente|carta precatoria|execucao provisoria|"
                                r"cumprimento provisorio")
_VINCULOS_DECLARADOS_SEM_TIPO = "mesma_acao"


def _aviso(nivel, codigo, onde, mensagem, candidatos=None, numeros=None):
    aviso = {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": list(candidatos or [])}
    if numeros:
        aviso["numeros"] = list(numeros)
    return aviso


# ---------------------------------------------------------------- utilidades

def _tem_valor(campo):
    return bool(campo) and campo.get("valor") not in (None, "")


def _consolidacao(f):
    return f.setdefault("consolidacao", {})


def _anotar(lista, item):
    if item not in lista:
        lista.append(item)


def _espelhar_planos(f):
    """Os campos planos da Fase 1 (cliente, polo_cliente...) espelham campos[nome]."""
    for nome in fch.PLANOS:
        c = f.get("campos", {}).get(nome)
        if _tem_valor(c):
            f[nome] = c["valor"]


def _nome_chave(nome):
    return " ".join(cart._sem_sufixo(nome or ""))


def _chave_do_numero(f):
    return str(f.get("numero") or "").strip()


def _unir_consolidacao(destino, origem):
    """Junta duas anotações de consolidação sem repetir nada."""
    for chave, valor in (origem or {}).items():
        if isinstance(valor, list):
            lista = destino.setdefault(chave, [])
            for item in valor:
                _anotar(lista, item)
        elif isinstance(valor, dict):
            for k, v in valor.items():
                destino.setdefault(chave, {}).setdefault(k, v)
        else:
            destino.setdefault(chave, valor)


# ---------------------------------------------------------------- 1. números

def _normalizar_numero_texto(texto):
    """(numero_mascarado | None, grupos | None)."""
    m = cart.CNJ.search(str(texto or ""))
    if not m:
        return None, None
    return cart.mascara(m.groups()), m.groups()


def _normalizar_numeros(f, avisos):
    bruto = str(f.get("numero") or "")
    mascarado, grupos = _normalizar_numero_texto(bruto)
    if mascarado is None:
        avisos.append(_aviso("erro", "numero_invalido", bruto or "(sem número)",
                             f"O número {bruto!r} não tem o formato de processo (CNJ). Não foi alterado.",
                             numeros=[bruto] if bruto else None))
    else:
        if mascarado != bruto.strip():
            _anotar(_consolidacao(f).setdefault("numeros_originais", []), bruto)
            f["numero"] = mascarado
            avisos.append(_aviso("info", "numero_normalizado", mascarado,
                                 f"O número {bruto!r} foi escrito no padrão {mascarado}.", [bruto, mascarado],
                                 numeros=[mascarado]))
        if not f.get("tribunal"):
            f["tribunal"] = cart.tribunal(grupos)
        if not cart.dv_correto(grupos):
            avisos.append(_aviso("erro", "numero_invalido", mascarado,
                                 f"O dígito verificador do número {mascarado} não confere (provável erro de digitação). "
                                 "O processo foi mantido, mas confira o número.", numeros=[mascarado]))
    vistos, vinculados = {f.get("numero")}, []
    for v in f.get("vinculados", []):
        num, grupos_v = _normalizar_numero_texto(v.get("numero"))
        num = num or str(v.get("numero") or "").strip()
        if not num or num in vistos:
            continue
        vistos.add(num)
        if grupos_v is None or not cart.dv_correto(grupos_v):
            avisos.append(_aviso("atencao", "numero_invalido", num,
                                 f"O número vinculado {num!r} do processo {f.get('numero')} parece inválido.",
                                 numeros=[f.get("numero"), num]))
        vinculados.append({**v, "numero": num})
    f["vinculados"] = vinculados


# ---------------------------------------------------------------- 2. duplicatas exatas

def _vence(atual, novo):
    """True se o campo `novo` deve substituir o `atual` (maior prioridade; em empate, o mais recente)."""
    pa, pn = fch.PRIORIDADE.get(atual.get("origem"), 0), fch.PRIORIDADE.get(novo.get("origem"), 0)
    if pn != pa:
        return pn > pa
    return str(novo.get("em") or "") > str(atual.get("em") or "")


def _fundir_duplicata(base, outra, avisos):
    numero = base["numero"]
    conflitos = _consolidacao(base).setdefault("conflitos", [])
    for nome, novo in outra.get("campos", {}).items():
        if not _tem_valor(novo):
            continue
        atual = base.setdefault("campos", {}).get(nome)
        if not _tem_valor(atual):
            base["campos"][nome] = copy.deepcopy(novo)
            continue
        ganha, perde = (novo, atual) if _vence(atual, novo) else (atual, novo)
        if ganha is novo:
            base["campos"][nome] = copy.deepcopy(novo)
        if atual["valor"] != novo["valor"]:
            _anotar(conflitos, {"campo": nome, "valor_mantido": ganha["valor"], "valor_descartado": perde["valor"],
                                "origem_descartada": perde.get("origem"), "em_descartado": perde.get("em")})
            mesma_forca = atual.get("origem") == novo.get("origem")
            avisos.append(_aviso("atencao" if mesma_forca else "info", "campo_divergente", f"{numero}: {nome}",
                                 f"Duas linhas do processo {numero} divergem em {fch.CAMPOS[nome][0] if nome in fch.CAMPOS else nome}: "
                                 f"ficou {ganha['valor']!r} (origem {ganha.get('origem')}).",
                                 [ganha["valor"], perde["valor"]], numeros=[numero]))
    for v in outra.get("vinculados", []):
        if v["numero"] != numero and all(x["numero"] != v["numero"] for x in base.setdefault("vinculados", [])):
            base["vinculados"].append(copy.deepcopy(v))
    for chave, descartados in (("linha_de_base", "linhas_de_base_descartadas"),
                               ("ultimo_texto_gravado", "textos_gravados_descartados")):
        a, b = base.get(chave), outra.get(chave)
        if not b or a == b:
            continue
        if not a:
            base[chave] = copy.deepcopy(b)
            continue
        if str(b.get("data_base") or "") > str(a.get("data_base") or ""):
            a, b = b, a
            base[chave] = copy.deepcopy(a)
        _anotar(_consolidacao(base).setdefault(descartados, []), copy.deepcopy(b))
        avisos.append(_aviso("atencao", f"{chave}_divergente", numero,
                             f"Duas linhas do processo {numero} trazem {chave.replace('_', ' ')} diferentes; "
                             "ficou a mais recente e a outra foi guardada.", numeros=[numero]))
    if base.get("ativo", True) != outra.get("ativo", True):
        avisos.append(_aviso("atencao", "campo_divergente", f"{numero}: ativo",
                             f"Duas linhas do processo {numero} divergem em 'ativo'; ficou {base.get('ativo', True)}.",
                             [base.get("ativo", True), outra.get("ativo", True)], numeros=[numero]))
    _unir_consolidacao(_consolidacao(base), outra.get("consolidacao"))
    saltar = {"campos", "vinculados", "linha_de_base", "ultimo_texto_gravado", "consolidacao", "numero", "v", "ativo"}
    for chave, valor in outra.items():
        if chave not in saltar and base.get(chave) in (None, "", [], {}):
            base[chave] = copy.deepcopy(valor)
    _espelhar_planos(base)


def _fundir_duplicatas_exatas(fichas, avisos):
    grupos = OrderedDict()
    for i, f in enumerate(fichas):
        chave = _chave_do_numero(f) or f"(sem número {i})"   # linhas sem número nunca se fundem entre si
        grupos.setdefault(chave, []).append(f)
    saida = []
    for chave, grupo in grupos.items():
        base = grupo[0]
        for outra in grupo[1:]:
            _fundir_duplicata(base, outra, avisos)
        if len(grupo) > 1:
            avisos.append(_aviso("info", "duplicata_exata_fundida", chave,
                                 f"O processo {chave} aparecia {len(grupo)} vezes; as linhas foram reunidas numa só.",
                                 numeros=[chave]))
        saida.append(base)
    return saida


# ---------------------------------------------------------------- 3. vinculados

def _arvore_de_vinculos(fichas):
    """pai[j] = (i, tipo): cada ficha citada por outra vira filha da PRIMEIRA que a cita (sem ciclos)."""
    por_numero = {f["numero"]: i for i, f in enumerate(fichas) if f.get("numero")}
    pai = {}

    def ancestrais(i):
        while i in pai:
            i = pai[i][0]
            yield i

    for i, f in enumerate(fichas):
        for v in f.get("vinculados", []):
            j = por_numero.get(v["numero"])
            if j is None or j == i or j in pai or j in ancestrais(i):
                continue
            pai[j] = (i, v.get("tipo") or _VINCULOS_DECLARADOS_SEM_TIPO)
    return pai


def _comparar_materias(principal, absorvida, avisos):
    ra, rb = fch.obter(principal, "materia_principal"), fch.obter(absorvida, "materia_principal")
    if not ra or not rb or ra == rb:
        return
    ca, cb = taxonomia.normalizar("materia", ra), taxonomia.normalizar("materia", rb)
    numeros = [principal["numero"], absorvida["numero"]]
    if ca and ca == cb:
        avisos.append(_aviso("atencao", "materia_dois_rotulos", " e ".join(numeros),
                             f"A mesma matéria aparece escrita de dois jeitos nas duas linhas do mesmo processo: "
                             f"{ra!r} e {rb!r}. Passa a valer {ca!r}.", [ra, rb, ca], numeros=numeros))
    else:
        avisos.append(_aviso("atencao", "materia_divergente", " e ".join(numeros),
                             f"As duas linhas do mesmo processo trazem matérias diferentes: {ra!r} e {rb!r}.",
                             [ra, rb], numeros=numeros))


def _absorver(principal, filha, tipo, avisos):
    cons = _consolidacao(principal)
    retrato = copy.deepcopy({k: v for k, v in filha.items() if k != "consolidacao"})
    _anotar(cons.setdefault("absorvidas", []), {"numero": filha["numero"], "tipo": tipo, "ficha": retrato})
    _unir_consolidacao(cons, {k: v for k, v in (filha.get("consolidacao") or {}).items() if k != "absorvidas"})
    for antiga in (filha.get("consolidacao") or {}).get("absorvidas", []):
        _anotar(cons["absorvidas"], antiga)
    _comparar_materias(principal, filha, avisos)
    vinculados = principal.setdefault("vinculados", [])
    for numero, t in [(filha["numero"], tipo), *[(v["numero"], v.get("tipo")) for v in filha.get("vinculados", [])]]:
        if numero != principal["numero"] and all(v["numero"] != numero for v in vinculados):
            vinculados.append({"numero": numero, "tipo": t or _VINCULOS_DECLARADOS_SEM_TIPO})
    avisos.append(_aviso("info", "vinculo_absorvido", f"{principal['numero']} e {filha['numero']}",
                         f"O processo {filha['numero']} ({tipo}) foi reunido ao {principal['numero']}: no relatório é uma "
                         "linha só, e os dados da linha reunida ficaram guardados.", [tipo],
                         numeros=[principal["numero"], filha["numero"]]))


def _absorver_vinculadas(fichas, avisos):
    pai = _arvore_de_vinculos(fichas)
    # mesmo número citado por mais de um principal: o vínculo fica no primeiro, os outros só são avisados
    citado_por = defaultdict(list)
    for f in fichas:
        for v in f.get("vinculados", []):
            citado_por[v["numero"]].append(f["numero"])
    for numero, donos in citado_por.items():
        if len(set(donos)) > 1:
            avisos.append(_aviso("atencao", "vinculado_em_dois_principais", numero,
                                 f"O processo {numero} é citado como vinculado de mais de um processo: {', '.join(sorted(set(donos)))}. "
                                 "Confira qual é o principal.", sorted(set(donos)), numeros=[numero, *sorted(set(donos))]))
    if not pai:
        return fichas
    raiz = {}

    def raiz_de(i):
        while i in pai:
            i = pai[i][0]
        return i

    for j in pai:
        raiz[j] = raiz_de(j)
    # descendentes na ordem em que aparecem; a raiz recebe todos
    for j in sorted(pai):
        principal, filha = fichas[raiz[j]], fichas[j]
        tipo = pai[j][1]
        _absorver(principal, filha, tipo, avisos)
    return [f for i, f in enumerate(fichas) if i not in pai]


# ---------------------------------------------------------------- 4. rótulos

def _normalizar_rotulos(f, avisos):
    for nome, vocab in CAMPOS_COM_VOCABULARIO.items():
        campo = f.get("campos", {}).get(nome)
        valor = campo.get("valor") if _tem_valor(campo) else None
        if not isinstance(valor, str):
            continue
        if vocab == "momento_atual":
            momento, qualificador = taxonomia.normalizar_momento(valor)
            novo = taxonomia.formatar_momento(momento, qualificador) if momento else None
        else:
            novo = taxonomia.normalizar(vocab, valor)
        rotulo = fch.CAMPOS[nome][0] if nome in fch.CAMPOS else "Matéria principal"
        if novo is None:
            avisos.append(_aviso("atencao", "rotulo_fora_do_vocabulario", f"{f['numero']}: {nome}",
                                 f"{rotulo} '{valor}' não está no vocabulário do relatório (processo {f['numero']}).",
                                 taxonomia.sugerir(vocab, valor), numeros=[f["numero"]]))
        elif novo != valor:
            cons = _consolidacao(f)
            cons.setdefault("originais", {}).setdefault(nome, valor)
            campo["valor"] = novo
            _espelhar_planos(f)
            avisos.append(_aviso("info", "rotulo_normalizado", f"{f['numero']}: {nome}",
                                 f"{rotulo} '{valor}' foi escrito como '{novo}'.", [valor, novo], numeros=[f["numero"]]))


# ---------------------------------------------------------------- 5. sugestões

def _chave_das_partes(f):
    return (_nome_chave(fch.obter(f, "cliente")), _nome_chave(fch.obter(f, "autores")), _nome_chave(fch.obter(f, "reus")))


def _ligadas(a, b):
    return b["numero"] in fch.todos_os_numeros(a) or a["numero"] in fch.todos_os_numeros(b)


def _sugestoes_de_processos(fichas):
    avisos, ja_sugeridos = [], set()
    por_partes = defaultdict(list)
    for f in fichas:
        cliente, autores, reus = _chave_das_partes(f)
        if cliente and (autores or reus):
            por_partes[(cliente, autores, reus)].append(f)
    # vínculo provável: classe de agravo/apenso... com as mesmas partes de uma linha "principal"
    for grupo in por_partes.values():
        candidatas = [f for f in grupo if _CLASSE_DE_VINCULO.search(taxonomia._chave(fch.obter(f, "classe") or ""))]
        principais = [f for f in grupo if f not in candidatas]
        for f in candidatas:
            donos = [p for p in principais if not _ligadas(p, f)]
            if not donos:
                continue
            classe = taxonomia._chave(fch.obter(f, "classe"))
            tipo = "agravo" if "agravo" in classe else ("recurso" if re.search(r"apelacao|recurso", classe) else "apenso")
            numeros = [f["numero"], *[p["numero"] for p in donos]]
            ja_sugeridos.update(numeros)
            avisos.append(_aviso("atencao", "vinculo_provavel", f["numero"],
                                 f"O processo {f['numero']} (classe {fch.obter(f, 'classe')!r}) tem as mesmas partes de "
                                 f"{', '.join(p['numero'] for p in donos)}: pode ser {tipo} dele. Nada foi alterado; "
                                 "confirme para tratá-los como uma linha só.",
                                 [p["numero"] for p in donos] + [tipo], numeros=numeros))
    # duplicata provável: mesmo cliente, mesmas partes e mesma data de ajuizamento, números diferentes
    por_data = defaultdict(list)
    for chave, grupo in por_partes.items():
        for f in grupo:
            data = fch.obter(f, "data_ajuizamento")
            if data:
                por_data[(*chave, data)].append(f)
    for grupo in por_data.values():
        if len(grupo) > 1 and not any(f["numero"] in ja_sugeridos for f in grupo):
            if all(_ligadas(a, b) for a in grupo for b in grupo if a is not b):
                continue
            numeros = [f["numero"] for f in grupo]
            avisos.append(_aviso("atencao", "duplicata_provavel", " e ".join(numeros),
                                 f"Os processos {', '.join(numeros)} têm o mesmo cliente, as mesmas partes e a mesma data de "
                                 "ajuizamento, mas números diferentes: podem ser a mesma ação contada duas vezes. "
                                 "Nada foi alterado; confira.", numeros, numeros=numeros))
    return avisos


def _nomes_do_campo(valor):
    return [n.strip() for n in re.split(r"[;\n]", str(valor or "")) if n.strip()]


def _escolher_grafia(contagem):
    def pontos(nome):
        misto = not (nome.isupper() or nome.islower())
        acento = any(ord(c) > 127 for c in nome)
        sufixo = bool(re.search(r"\b(ltda|s\.? ?a|eireli|epp|me)\b\.?$", nome.lower()))
        return (contagem[nome], misto, acento, sufixo, len(nome))
    return max(sorted(contagem), key=pontos)


def sugerir_grafias(fichas, campos=CAMPOS_DE_NOME):
    """Grupos de grafias parecidas do mesmo nome (acento, caixa, pontuação, com e sem Ltda/S.A.), para o usuário
    confirmar. Nada é alterado. Cada grupo: {"chave", "canonico_sugerido", "variantes" (a sugerida primeiro),
    "ocorrencias": {grafia: quantas vezes}, "campos": [campos onde aparece]}."""
    contagens, onde = defaultdict(Counter), defaultdict(set)
    for f in fichas:
        f = fch.de_carteira_v1(f)
        for campo in campos:
            for nome in _nomes_do_campo(fch.obter(f, campo)):
                chave = _nome_chave(nome)
                if chave:
                    contagens[chave][nome] += 1
                    onde[chave].add(campo)
    grupos = []
    for chave in sorted(contagens):
        contagem = contagens[chave]
        if len(contagem) < 2:
            continue
        canonico = _escolher_grafia(contagem)
        grupos.append({"chave": chave, "canonico_sugerido": canonico,
                       "variantes": [canonico, *sorted(n for n in contagem if n != canonico)],
                       "ocorrencias": dict(contagem), "campos": sorted(onde[chave])})
    return grupos


def _avisos_de_grafias(fichas):
    avisos = []
    for g in sugerir_grafias(fichas):
        partes = "; ".join(f"{n!r} ({g['ocorrencias'][n]}x)" for n in g["variantes"])
        avisos.append(_aviso("atencao", "grafias_do_mesmo_nome", ", ".join(g["campos"]),
                             f"Estes nomes parecem ser o mesmo: {partes}. A grafia sugerida é {g['canonico_sugerido']!r}. "
                             "Nada foi alterado: confirme para unificar.", g["variantes"]))
    return avisos


def _mapa_de_confirmacoes(confirmadas):
    if isinstance(confirmadas, dict):
        return {str(k): str(v) for k, v in confirmadas.items() if str(k) != str(v)}
    mapa = {}
    for grupo in confirmadas or []:
        canonico = grupo.get("canonico") or grupo.get("canonico_sugerido")
        for variante in grupo.get("variantes", []):
            if canonico and variante != canonico:
                mapa[variante] = canonico
    return mapa


def aplicar_grafias(fichas, confirmadas, campos=CAMPOS_DE_NOME):
    """Unifica nomes JÁ CONFIRMADOS pelo usuário. `confirmadas`: {variante: canônico} ou lista de grupos
    {"canonico": ..., "variantes": [...]} (o que sugerir_grafias devolve, depois de o usuário escolher).
    Devolve (cópias das fichas, avisos). O texto original fica em ficha["consolidacao"]["originais"]."""
    mapa = _mapa_de_confirmacoes(confirmadas)
    saida, trocas = [], Counter()
    for f in fichas:
        f = copy.deepcopy(fch.de_carteira_v1(f))
        for campo in campos:
            c = f.get("campos", {}).get(campo)
            if not _tem_valor(c) or not isinstance(c["valor"], str):
                continue
            nomes = _nomes_do_campo(c["valor"])
            novos = [mapa.get(n, n) for n in nomes]
            if novos != nomes:
                _consolidacao(f).setdefault("originais", {}).setdefault(campo, c["valor"])
                for antigo, novo in zip(nomes, novos):
                    if antigo != novo:
                        trocas[(antigo, novo)] += 1
                c["valor"] = "; ".join(novos)
                _espelhar_planos(f)
        saida.append(f)
    avisos = [_aviso("info", "grafia_unificada", novo, f"'{antigo}' passou a ser escrito '{novo}' em {n} lugar(es).",
                     [antigo, novo]) for (antigo, novo), n in sorted(trocas.items())]
    return saida, avisos


# ---------------------------------------------------------------- consolidar

def consolidar(fichas, *, absorver_vinculadas=True):
    """(fichas consolidadas, avisos). Veja o cabeçalho do módulo. A lista recebida não é alterada.
    `absorver_vinculadas=False` só avisa dos vínculos declarados, sem reunir as linhas."""
    avisos = []
    saida = [copy.deepcopy(fch.de_carteira_v1(f)) for f in fichas]
    for f in saida:
        f.setdefault("campos", {})
        f.setdefault("vinculados", [])
        _normalizar_numeros(f, avisos)
    saida = _fundir_duplicatas_exatas(saida, avisos)
    if absorver_vinculadas:
        saida = _absorver_vinculadas(saida, avisos)
    for f in saida:
        _normalizar_rotulos(f, avisos)
    avisos += _sugestoes_de_processos(saida)
    avisos += _avisos_de_grafias(saida)
    return saida, avisos


def _valores_guardados(f):
    """Pares (campo, valor) que a ficha ainda guarda, no campo ou na anotação de consolidação."""
    achados = {(n, c["valor"]) for n, c in f.get("campos", {}).items() if _tem_valor(c)}
    cons = f.get("consolidacao") or {}
    achados |= {(x["campo"], x["valor_descartado"]) for x in cons.get("conflitos", [])}
    achados |= {(n, v) for n, v in (cons.get("originais") or {}).items()}
    for a in cons.get("absorvidas", []):
        achados |= _valores_guardados(a["ficha"])
    return achados


def campos_humanos_perdidos(antes, depois):
    """[(numero, campo, valor)] de campos de origem `humano` em `antes` que não estão mais em lugar nenhum de
    `depois` (nem no campo, nem em consolidacao). Lista vazia = nada se perdeu."""
    guardados = {}
    for f in depois:
        for numero in [f.get("numero"), *[a["numero"] for a in (f.get("consolidacao") or {}).get("absorvidas", [])]]:
            guardados.setdefault(_chave_do_numero({"numero": numero}), set()).update(_valores_guardados(f))
            guardados.setdefault(_normalizar_numero_texto(numero)[0] or numero, set()).update(_valores_guardados(f))
    perdidos = []
    for f in antes:
        f = fch.de_carteira_v1(f)
        numero = _normalizar_numero_texto(f.get("numero"))[0] or f.get("numero")
        tem = guardados.get(numero, set())
        for nome, c in f.get("campos", {}).items():
            if c.get("origem") == "humano" and _tem_valor(c) and (nome, c["valor"]) not in tem:
                perdidos.append((numero, nome, c["valor"]))
    return perdidos


# ---------------------------------------------------------------- migração da Fase 1

def migrar_itens(itens):
    """(fichas v2, avisos, {"migradas": n, "ja_v2": n}). Itens que já são v2 passam sem mudança."""
    novos, avisos, migradas, ja_v2 = [], [], 0, 0
    for item in itens:
        if not isinstance(item, dict):
            avisos.append(_aviso("erro", "item_ilegivel", "carteira.json", "Um item da carteira não tem o formato esperado "
                                 "e foi mantido como está."))
            novos.append(item)
            continue
        if item.get("v") == fch.VERSAO:
            ja_v2 += 1
            novos.append(item)
        else:
            novos.append(fch.de_carteira_v1(item))
            migradas += 1
        numero, grupos = _normalizar_numero_texto(item.get("numero"))
        if grupos is None or not cart.dv_correto(grupos):
            avisos.append(_aviso("atencao", "numero_invalido", str(item.get("numero") or "(sem número)"),
                                 f"O número {item.get('numero')!r} não é um número de processo válido; foi migrado assim mesmo.",
                                 numeros=[item.get("numero")] if item.get("numero") else None))
    return novos, avisos, {"migradas": migradas, "ja_v2": ja_v2}


def migrar_projeto(slug):
    """Converte projetos/<slug>/carteira.json da Fase 1 para fichas v2, em lote e de forma idempotente.

    Devolve {"ok", "slug", "total", "migradas", "ja_v2", "backup", "avisos"}. Antes de gravar pela primeira vez,
    copia o arquivo original para carteira.fase1.json. Projeto inexistente ou carteira ilegível voltam como aviso
    (ok=False), sem exceção e sem tocar em nada. Não altera o relatório ativo (comum.PROJETO)."""
    pasta = Path(comum.PROJETOS_DIR) / slug
    resposta = {"ok": False, "slug": slug, "total": 0, "migradas": 0, "ja_v2": 0, "backup": None, "avisos": []}
    if not (pasta / "projeto.json").exists():
        resposta["avisos"].append(_aviso("erro", "projeto_nao_encontrado", slug, f"Relatório não encontrado: {slug}."))
        return resposta
    arquivo = pasta / "carteira.json"
    try:
        itens = comum.load_json(arquivo, [])
        if not isinstance(itens, list):
            raise ValueError("a carteira deveria ser uma lista")
    except ValueError as erro:
        resposta["avisos"].append(_aviso("erro", "carteira_ilegivel", str(arquivo.name),
                                         f"Não consegui ler a carteira do relatório ({erro}). Nada foi alterado."))
        return resposta
    novos, avisos, contagem = migrar_itens(itens)
    resposta.update(contagem, total=len(novos), avisos=avisos, ok=True)
    if contagem["migradas"]:
        backup = pasta / "carteira.fase1.json"
        if not backup.exists():
            shutil.copy2(arquivo, backup)
        resposta["backup"] = str(backup)
        comum.save_json(arquivo, novos)
    return resposta
