"""Leitura de planilhas e tabelas (.xlsx, .csv) para os leitores `xlsx_b`, `tabela_livre` e `lista` (WS-2).

Três peças:

1. `Grade`: uma aba ou um CSV como lista de linhas (valores já "crus"), com a marca de quais células são
   fórmula e de qual é o formato de cada célula. `carregar_xlsx` e `carregar_csv` produzem grades; erro de
   arquivo (corrompido, protegido, ilegível) volta como aviso `arquivo_ilegivel`, nunca como exceção.

2. Mapeador de cabeçalhos: `propor_mapeamento` casa cada coluna com um campo da ficha (`ficha.CAMPOS`) por
   semelhança do cabeçalho (sem acento, caixa ou pontuação; abreviações; sinônimos; palavras a mais) e devolve
   a CONFIANÇA. Casamento ambíguo (dois campos quase empatados) ou repetido (duas colunas para o mesmo
   campo) não é aplicado: vira aviso e a coluna vai para `colunas_sem_destino`. Também reconhece, pelo
   conteúdo, a coluna de números CNJ quando o cabeçalho não ajuda. Destinos especiais além dos campos da
   ficha: `numero`, `andamentos` (histórico em texto), `tribunal` (deduzido do número, ignorado) e `ativo`.

3. `extrair_processos`: percorre as linhas de uma grade e devolve `ProcessoLido`. Ignora linhas-marcador e
   totais (e as lista, em um aviso `linhas_ignoradas`); recusa e lista número com dígito errado; usa o valor
   em cache das células de fórmula e avisa (`formula_sem_valor`) quando não há; nada se perde em silêncio.

Limites conhecidos: só lê cabeçalho de uma linha; células mescladas contam só na célula de cima/esquerda;
`.xls` antigo e `.ods` não são lidos (o detector avisa para salvar como `.xlsx`).
"""
import csv
import functools
import io
import math
import re
import warnings
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

import ficha

from . import base

LIMIAR_AUTO = 0.7        # a partir daqui o mapeamento é aplicado sem confirmação
LIMIAR_MIN = 0.5         # abaixo disso nem é proposto
MAX_LINHAS_CABECALHO = 40
LIMITE_BYTES = 300 * 1024 * 1024

ESPECIAIS = {"numero": "Número do processo", "andamentos": "Andamentos (histórico em texto)",
             "tribunal": "Tribunal (deduzido do número; ignorado)", "ativo": "Ativo (calculado; ignorado)"}
DERIVADOS = ("ativo", "valor_economizado", "taxa_resolucao_dias")   # colunas que costumam ser fórmula

# Colunas do modelo B (CONTRATOS/WORKSTREAMS "fatos estruturais"); usadas para reconhecer o próprio modelo B.
CABECALHOS_B = ("Número do Processo", "Autor(es)", "Réu(s)", "Vara", "Município", "Tribunal", "Data do Ajuizamento",
                "Área do Direito", "Matéria Principal", "Objeto", "Valor da Causa", "Andamentos", "Situação", "Ativo",
                "Valor Arbitrado em Juízo", "Probabilidade", "Valor Estimado", "Valor da Execução", "Custas Processuais",
                "Depósitos Recursais", "Garantias Processuais", "Resultado", "Valor Economizado",
                "Data do trânsito em julgado", "Taxa de resolução (em dias)", "Houve recurso da empresa?",
                "Percentual de êxito", "Reclamante terceirizado?", "Outra(s) Parte(s)")

# destino -> formas conhecidas do cabeçalho (o rótulo de ficha.CAMPOS entra automaticamente)
SINONIMOS = {
    "numero": ("numero do processo", "processo", "numero", "n do processo", "numero processo", "autos", "cnj",
               "numero cnj", "processo cnj", "numero unico", "numero unico do processo", "processos", "n cnj",
               "numero do processo cnj", "processo numero", "n processo"),
    "andamentos": ("andamentos", "andamento", "historico", "historico do processo", "movimentacoes", "movimentacao",
                   "movimentos", "andamentos processuais", "ultimos andamentos", "resumo dos andamentos",
                   "texto de andamentos", "atualizacoes", "relatorio de andamentos"),
    "tribunal": ("tribunal", "orgao", "justica", "tribunal de origem", "tribunal de justica"),
    "ativo": ("ativo", "processo ativo", "esta ativo", "ativo sim nao"),
    "cliente": ("cliente", "nosso cliente", "razao social", "cliente razao social", "nome do cliente", "parte cliente"),
    "apelido": ("apelido", "apelido do processo", "nome do caso", "caso", "referencia interna"),
    "responsavel": ("responsavel", "advogado", "advogado responsavel", "responsavel pelo processo", "adv responsavel",
                    "socio responsavel"),
    "contato": ("contato", "e mail", "email", "whatsapp", "telefone", "contato do cliente"),
    "observacoes": ("observacoes", "observacao", "anotacoes", "comentarios", "notas", "obs"),
    "polo_cliente": ("polo", "polo do cliente", "posicao", "posicao do cliente", "polo processual", "polo cliente"),
    "autores": ("autor es", "autor", "autores", "autora", "requerente", "requerentes", "reclamante", "reclamantes",
                "exequente", "exequentes", "demandante", "polo ativo", "parte autora", "impetrante", "parte ativa"),
    "reus": ("reu s", "reu", "reus", "re", "requerido", "requeridos", "reclamado", "reclamada", "reclamadas",
             "reclamado s", "executado", "executados", "demandado", "polo passivo", "parte re", "parte passiva",
             "impetrado"),
    "parte_contraria": ("parte contraria", "contraria", "adverso", "parte adversa", "contraparte"),
    "outras_partes": ("outra s parte s", "outras partes", "outras partes envolvidas", "litisconsortes", "demais partes"),
    "terceirizado": ("reclamante terceirizado", "terceirizado", "trabalhador terceirizado", "terceirizado s"),
    "vara": ("vara", "juizo", "vara juizo", "orgao julgador", "vara de origem", "unidade", "vara comarca"),
    "municipio": ("municipio", "cidade", "comarca", "foro", "localidade", "municipio da vara"),
    "uf": ("uf", "estado", "unidade federativa"),
    "data_ajuizamento": ("data do ajuizamento", "ajuizamento", "data de ajuizamento", "data de distribuicao",
                         "distribuicao", "data da distribuicao", "distribuido em", "ajuizado em", "data da propositura",
                         "data distribuicao", "data de entrada"),
    "data_citacao": ("data de citacao", "citacao", "data da citacao", "citado em"),
    "classe": ("classe", "classe processual", "tipo de acao", "tipo de processo", "natureza", "natureza da acao",
               "tipo da acao"),
    "assunto": ("assunto", "assuntos", "assunto principal", "assunto do processo"),
    "area": ("area do direito", "area", "area juridica", "ramo do direito", "ramo", "area do processo"),
    "materia_principal": ("materia principal", "materia", "tese", "tese principal", "materia do processo",
                          "causa de pedir"),
    "objeto": ("objeto", "objeto da acao", "pedido", "pedidos", "pedido principal", "resumo do objeto"),
    "valor_causa": ("valor da causa", "valor causa", "valor atribuido a causa", "valor atribuido", "valor da acao",
                    "valor do processo", "valor inicial", "valor da causa atualizado"),
    "momento_atual": ("momento atual", "momento atual do processo", "momento processual", "fase atual",
                      "andamento atual", "posicao atual"),
    "situacao": ("situacao", "status", "situacao do processo", "status do processo", "situacao processual"),
    "fase": ("fase", "fase processual"),
    "ultimo_andamento": ("ultimo andamento", "data do ultimo andamento", "data ultimo andamento", "ultima movimentacao",
                         "data da ultima movimentacao", "ultima atualizacao", "data da ultima atualizacao"),
    "houve_recurso": ("houve recurso da empresa", "houve recurso", "recurso da empresa", "recorreu", "recurso interposto",
                      "recurso"),
    "resultado": ("resultado", "desfecho", "resultado do processo", "resultado final", "decisao final"),
    "probabilidade": ("probabilidade", "probabilidade do resultado", "probabilidade de perda", "risco",
                      "classificacao de risco", "classificacao do risco"),
    "valor_arbitrado": ("valor arbitrado em juizo", "valor arbitrado", "condenacao arbitrada", "valor da condenacao",
                        "condenacao", "valor condenado"),
    "valor_estimado": ("valor estimado", "estimativa", "valor estimado da condenacao"),
    "valor_execucao": ("valor da execucao", "valor execucao", "valor executado", "valor em execucao", "execucao"),
    "valor_acordo": ("valor do acordo", "valor acordo", "valor acordado", "acordo"),
    "valor_economizado": ("valor economizado", "economia", "economia efetiva"),
    "custas": ("custas processuais", "custas", "custas judiciais"),
    "depositos_recursais": ("depositos recursais", "deposito recursal", "depositos", "deposito"),
    "garantias": ("garantias processuais", "garantia", "garantias", "garantia do juizo"),
    "data_transito": ("data do transito em julgado", "transito em julgado", "data de transito", "data do transito",
                      "transito", "data do transito em julgado"),
    "taxa_resolucao_dias": ("taxa de resolucao em dias", "taxa de resolucao dias", "taxa de resolucao",
                            "tempo de resolucao", "dias para resolucao", "prazo de resolucao", "duracao em dias"),
    "percentual_exito": ("percentual de exito", "exito", "taxa de exito", "percentual exito"),
}
_PALAVRAS_FRACAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "para", "ao", "por", "com", "es", "s",
                    "r"}
_PRIMEIRO = {"n": "numero", "no": "numero", "nr": "numero", "num": "numero", "nro": "numero"}
_ABREV = {"vlr": "valor", "dt": "data", "proc": "processo", "obs": "observacoes", "ult": "ultimo",
          "mun": "municipio", "qtd": "quantidade"}


def _expandir(k):
    """Chave normalizada com abreviações expandidas ('Nº proc.' -> 'numero processo'; 'Vlr causa (R$)' -> 'valor causa')."""
    saida = []
    for i, t in enumerate(k.split()):
        if i == 0 and t in _PRIMEIRO:
            t = _PRIMEIRO[t]
        t = _ABREV.get(t, t)
        if t == "r":
            continue
        saida.append(t)
    return " ".join(saida)


def _tokens(k):
    return {t for t in k.split() if t not in _PALAVRAS_FRACAS}


def _construir_indice():
    indice = {}
    for destino in (*ficha.CAMPOS, *ESPECIAIS):
        formas = {_expandir(base.chave(s)) for s in SINONIMOS.get(destino, ())}
        if destino in ficha.CAMPOS:
            formas.add(_expandir(base.chave(ficha.CAMPOS[destino][0])))
        formas.discard("")
        indice[destino] = [(f, _tokens(f)) for f in sorted(formas)]
    return indice


_INDICE = _construir_indice()
_EXATOS_B = {_expandir(base.chave(c)) for c in CABECALHOS_B}


def _construir_exatos():
    exatos = {}
    for destino, formas in _INDICE.items():
        for forma, _ in formas:
            exatos.setdefault(forma, destino)
            if exatos[forma] != destino:
                exatos[forma] = None          # forma que serve a dois destinos: não é exata
    return {f: d for f, d in exatos.items() if d}


_EXATOS = _construir_exatos()


def destino_exato(rotulo):
    """Campo da ficha (ou destino especial) cujo nome conhecido é IGUAL ao rótulo (sem acento, caixa ou pontuação); None se não houver."""
    return _EXATOS.get(_expandir(base.chave(rotulo)))


def rotulo_do_destino(destino):
    if destino in ESPECIAIS:
        return ESPECIAIS[destino]
    return ficha.CAMPOS[destino][0] if destino in ficha.CAMPOS else destino


def destinos_possiveis():
    """Lista para a tela de mapeamento: [{"campo", "rotulo", "grupo"}] (campos da ficha + destinos especiais)."""
    saida = [{"campo": c, "rotulo": r, "grupo": "especial"} for c, r in ESPECIAIS.items()]
    saida += [{"campo": c, "rotulo": v[0], "grupo": v[1]} for c, v in ficha.CAMPOS.items()]
    return saida


def pontuar_cabecalho(cabecalho):
    """[(confianca, destino)] em ordem decrescente para um texto de cabeçalho (só >= LIMIAR_MIN)."""
    return list(_pontuar(str(cabecalho)))


@functools.lru_cache(maxsize=8192)
def _pontuar(cabecalho):
    h = _expandir(base.chave(cabecalho))
    if not h:
        return ()
    ht = _tokens(h)
    achados = []
    for destino, formas in _INDICE.items():
        melhor = 0.0
        for forma, ft in formas:
            if h == forma:
                melhor = 1.0
                break
            if ht and ft and (ft <= ht or ht <= ft):
                melhor = max(melhor, 0.9 * math.sqrt(min(len(ft), len(ht)) / max(len(ft), len(ht))))
            else:
                sm = SequenceMatcher(None, h, forma)
                if sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8:
                    r = sm.ratio()
                    if r >= 0.82:
                        melhor = max(melhor, r * 0.88)
        if melhor >= LIMIAR_MIN:
            achados.append((round(melhor, 3), destino))
    return tuple(sorted(achados, key=lambda x: (-x[0], x[1])))


def _razao(amostras, teste):
    valores = [v for v in amostras if not base.vazio(v)]
    if not valores:
        return None
    return sum(1 for v in valores if teste(v)) / len(valores)


def _tem_cnj(valor):
    return bool(base.achar_numeros(valor)) if not isinstance(valor, (int, float)) else False


def _data_ok(valor):
    v, problema = base.converter_data(valor)
    return v is not None or problema is None


def _dinheiro_ok(valor):
    v, problema = base.converter_dinheiro(valor)
    return v is not None or problema is None


def propor_mapeamento(cabecalhos, amostras=None):
    """Casa colunas e campos. `cabecalhos`: textos (None/'' = coluna sem cabeçalho, ignorada); `amostras`: lista
    (uma por coluna) de valores de exemplo (opcional; melhora a decisão).
    -> [{"indice", "coluna", "campo" | None, "confianca", "candidatos": [campo...], "ambigua": bool,
         "duplicada_de": indice | None, "aplicado": bool}]"""
    amostras = amostras or [[] for _ in cabecalhos]
    registros = []
    for i, cab in enumerate(cabecalhos):
        if base.vazio(cab):
            continue
        cands = pontuar_cabecalho(cab)
        amo = amostras[i] if i < len(amostras) else []
        cnj = _razao(amo, _tem_cnj)
        if cnj is not None and cnj >= 0.5 and not any(d == "numero" and s >= 0.9 for s, d in cands):
            cands = sorted([(s, d) for s, d in cands if d != "numero"] + [(0.9, "numero")], key=lambda x: (-x[0], x[1]))
        ajustados = []
        for s, d in cands:
            if d in ficha.CAMPOS and ficha.CAMPOS[d][2] in ("data", "dinheiro") and len([v for v in amo if not base.vazio(v)]) >= 3:
                r = _razao(amo, _data_ok if ficha.CAMPOS[d][2] == "data" else _dinheiro_ok)
                if r is not None and r < 0.3:
                    s = round(s * 0.5, 3)
            if s >= LIMIAR_MIN:
                ajustados.append((s, d))
        ajustados.sort(key=lambda x: (-x[0], x[1]))
        reg = {"indice": i, "coluna": str(cab).strip(), "campo": None, "confianca": 0.0,
               "candidatos": [d for _, d in ajustados[:3]], "ambigua": False, "duplicada_de": None, "aplicado": False}
        if ajustados:
            melhor_s, melhor_d = ajustados[0]
            reg["campo"], reg["confianca"] = melhor_d, melhor_s
            if len(ajustados) > 1 and melhor_s < 0.97 and melhor_s - ajustados[1][0] < 0.05:
                reg["ambigua"], reg["campo"] = True, None
        registros.append(reg)
    # um campo por coluna: a de maior confiança ganha; a outra vira "duplicada"
    donos = {}
    for reg in sorted((r for r in registros if r["campo"]), key=lambda r: (-r["confianca"], r["indice"])):
        if reg["campo"] in donos:
            reg["duplicada_de"], reg["campo"] = donos[reg["campo"]], None
        else:
            donos[reg["campo"]] = reg["indice"]
    for reg in registros:
        reg["aplicado"] = bool(reg["campo"]) and reg["confianca"] >= LIMIAR_AUTO
    return registros


def aplicar_mapeamento_do_usuario(registros, mapeamento, avisos, onde):
    """Sobrepõe as escolhas do usuário. `mapeamento`: {cabeçalho: campo | None} ou lista de {"coluna","campo"}."""
    if not mapeamento:
        return registros
    if not isinstance(mapeamento, dict):
        mapeamento = {m.get("coluna"): m.get("campo") for m in mapeamento if isinstance(m, dict)}
    escolhas = {base.chave(k): v for k, v in mapeamento.items()}
    validos = set(ficha.CAMPOS) | set(ESPECIAIS)
    for reg in registros:
        k = base.chave(reg["coluna"])
        if k not in escolhas:
            continue
        campo = escolhas[k] or None
        if campo is not None and campo not in validos:
            avisos.append(base.aviso("atencao", "mapeamento_invalido", onde,
                                     f"O destino {campo!r} escolhido para a coluna {reg['coluna']!r} não existe; escolha mantida como automática.", [campo]))
            continue
        reg.update(campo=campo, confianca=1.0 if campo else 0.0, ambigua=False, duplicada_de=None, aplicado=bool(campo),
                   decisao="usuario")
    donos = {}
    for reg in registros:                 # dois destinos iguais escolhidos à mão: vale o primeiro
        if reg["campo"] and reg["aplicado"]:
            if reg["campo"] in donos:
                avisos.append(base.aviso("atencao", "coluna_duplicada", onde,
                                         f"As colunas {donos[reg['campo']]['coluna']!r} e {reg['coluna']!r} foram ligadas ao mesmo campo "
                                         f"({rotulo_do_destino(reg['campo'])}); só a primeira será lida.", [reg["coluna"]]))
                reg.update(campo=None, aplicado=False, duplicada_de=donos[reg["campo"]]["indice"])
            else:
                donos[reg["campo"]] = reg
    return registros


# ---------------------------------------------------------------- grades

class Grade:
    """Uma aba (ou um CSV): `linhas[i][j]` é a célula da linha i+1, coluna j+1."""

    def __init__(self, nome, linhas, formulas=None, formatos=None, epoch=None, oculta=False):
        self.nome = nome
        self.linhas = linhas
        self.formulas = formulas or set()
        self.formatos = formatos or {}
        self.epoch = epoch
        self.oculta = oculta

    def celula(self, i, j):
        if i < 0 or i >= len(self.linhas):
            return None
        linha = self.linhas[i]
        return linha[j] if 0 <= j < len(linha) else None

    def largura(self):
        return max((len(l) for l in self.linhas), default=0)


def _ler_bytes(caminho):
    tam = Path(caminho).stat().st_size
    if tam > LIMITE_BYTES:
        return None, base.aviso("erro", "arquivo_muito_grande", Path(caminho).name,
                                f"O arquivo tem {tam // (1024 * 1024)} MB; acima do limite de leitura ({LIMITE_BYTES // (1024 * 1024)} MB).")
    return Path(caminho).read_bytes(), None


def carregar_xlsx(caminho, max_linhas=None):
    """Grades de todas as abas de uma planilha. -> (grades, avisos). `max_linhas`: leitura leve (detecção)."""
    with warnings.catch_warnings():        # o openpyxl avisa de extensões que ignora (gráficos, formatação condicional x14...)
        warnings.simplefilter("ignore")
        return _carregar_xlsx(caminho, max_linhas)


def _carregar_xlsx(caminho, max_linhas):
    from openpyxl import load_workbook
    nome = Path(caminho).name
    avisos = []
    wb_v = wb_f = None
    try:
        if Path(caminho).stat().st_size > LIMITE_BYTES:
            raise ValueError("arquivo grande demais")
        wb_v = load_workbook(str(caminho), read_only=True, data_only=True)
        wb_f = load_workbook(str(caminho), read_only=True, data_only=False) if max_linhas is None else None
    except Exception as e:      # noqa: BLE001 -- qualquer falha de abertura é "arquivo ilegível", não erro de programa
        if wb_v is not None:
            wb_v.close()
        return [], [base.aviso("erro", "arquivo_ilegivel", nome,
                               "Não foi possível abrir a planilha (arquivo corrompido, protegido por senha ou "
                               f"não é um .xlsx): {type(e).__name__}.")]
    grades = []
    try:
        for ws in wb_v.worksheets:
            try:
                ws.reset_dimensions()
                linhas, formatos = [], {}
                for i, row in enumerate(ws.iter_rows(max_row=max_linhas)):
                    linhas.append([c.value for c in row])
                    for j, c in enumerate(row):
                        fmt = getattr(c, "number_format", None)
                        if fmt and fmt != "General":
                            formatos[(i, j)] = fmt
                formulas = set()
                if wb_f is not None:
                    wf = wb_f[ws.title]
                    wf.reset_dimensions()
                    for i, row in enumerate(wf.iter_rows()):
                        for j, c in enumerate(row):
                            if getattr(c, "data_type", None) == "f":
                                formulas.add((i, j))
                grades.append(Grade(ws.title, linhas, formulas, formatos, getattr(wb_v, "epoch", None),
                                    getattr(ws, "sheet_state", "visible") != "visible"))
            except Exception as e:      # noqa: BLE001
                avisos.append(base.aviso("erro", "arquivo_ilegivel", f"aba {ws.title!r}",
                                         f"A aba não pôde ser lida: {type(e).__name__}."))
    finally:
        wb_v.close()
        if wb_f is not None:
            wb_f.close()
    return grades, avisos


def decodificar_texto(dados):
    """bytes -> texto (UTF-8 com ou sem BOM; senão Windows-1252, comum em CSV do Excel brasileiro)."""
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


def carregar_csv(caminho):
    """Grade de um .csv (separador `,`, `;`, tabulação ou `|`; UTF-8 ou Windows-1252). -> (grades, avisos)."""
    nome = Path(caminho).name
    dados, erro = _ler_bytes(caminho)
    if erro:
        return [], [erro]
    if b"\x00" in dados[:4096]:
        return [], [base.aviso("erro", "arquivo_ilegivel", nome, "O arquivo parece binário, não um CSV de texto.")]
    texto = decodificar_texto(dados)
    amostra = texto[:8192]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=",;\t|")
    except csv.Error:
        primeira = amostra.splitlines()[0] if amostra.splitlines() else ""
        sep = max(",;\t|", key=primeira.count)

        class dialeto(csv.excel):        # noqa: N801
            delimiter = sep
    try:
        linhas = [[c.strip() for c in l] for l in csv.reader(io.StringIO(texto), dialeto)]
    except csv.Error as e:
        return [], [base.aviso("erro", "arquivo_ilegivel", nome, f"O CSV não pôde ser lido ({e}).")]
    return [Grade(Path(caminho).stem or "csv", linhas)], []


def _linha_tem_cnj(linha):
    return any(isinstance(v, str) and base.achar_numeros(v) for v in linha)


def achar_cabecalho(grade, max_linhas=MAX_LINHAS_CABECALHO):
    """(indice_da_linha, registros_de_mapeamento) do cabeçalho mais provável, ou None. É cabeçalho a linha cujo
    mapeamento inclui a coluna `numero` (pelo nome ou, se nenhum cabeçalho serve, pelo conteúdo da coluna logo
    abaixo) e que não tem número CNJ nas próprias células."""
    melhor = None
    for i, linha in enumerate(grade.linhas[:max_linhas]):
        textos = [v for v in linha if isinstance(v, str) and v.strip()]
        if not textos or _linha_tem_cnj(linha):
            continue
        amostras = [[grade.celula(r, j) for r in range(i + 1, min(i + 31, len(grade.linhas)))] for j in range(len(linha))]
        regs = propor_mapeamento(linha, amostras)
        num = next((r for r in regs if r["campo"] == "numero" and r["aplicado"]), None)
        if num is None:
            continue
        pont = sum(r["confianca"] for r in regs if r["campo"] and r["confianca"] >= LIMIAR_MIN)
        if melhor is None or pont > melhor[0]:
            melhor = (pont, i, regs)
    return (melhor[1], melhor[2]) if melhor else None


def cabecalho_exato_b(grade, indice, regs):
    """Quantas colunas do cabeçalho são, literalmente, colunas do modelo B."""
    linha = grade.linhas[indice]
    return sum(1 for v in linha if isinstance(v, str) and _expandir(base.chave(v)) in _EXATOS_B)


def grades_de_processos(grades):
    """[(grade, indice_cabecalho, registros)] das grades que têm cabeçalho com `numero` e ao menos um número CNJ abaixo."""
    saida = []
    for g in grades:
        achado = achar_cabecalho(g)
        if achado is None:
            continue
        i, regs = achado
        num = next(r for r in regs if r["campo"] == "numero" and r["aplicado"])
        if any(base.achar_numeros(g.celula(r, num["indice"])) for r in range(i + 1, len(g.linhas))
               if isinstance(g.celula(r, num["indice"]), str)):
            saida.append((g, i, regs))
    return saida


LISTA_CAMPOS = {"numero", "cliente", "polo_cliente", "parte_contraria", "responsavel", "contato", "observacoes", "apelido",
                "situacao", "tribunal"}


def classificar_grades(grades):
    """'xlsx_b' | 'tabela_livre' | 'lista' | None para as grades de uma planilha ou CSV.
    xlsx_b: cabeçalho com pelo menos 10 colunas do modelo B (ou 6, se a pasta de trabalho tem aba de parâmetros ou de
    indicadores, como o próprio modelo B com poucas colunas ativas); tabela_livre: cabeçalho com `numero` e dois ou mais
    campos que não são de lista; lista: o resto (inclusive sem cabeçalho, desde que haja números CNJ)."""
    com_proc = grades_de_processos(grades)
    do_modelo = any(t in base.chave(g.nome) for g in grades for t in ("param", "indicador"))
    for g, i, regs in com_proc:
        exatas = cabecalho_exato_b(g, i, regs)
        if exatas >= 10 or (exatas >= 6 and do_modelo):
            return "xlsx_b"
    for g, i, regs in com_proc:
        outros = {r["campo"] for r in regs if r["campo"] and r["aplicado"]} - LISTA_CAMPOS
        if len(outros) >= 2 or "andamentos" in outros:
            return "tabela_livre"
    if com_proc:
        return "lista"
    for g in grades:
        if any(_linha_tem_cnj(l) for l in g.linhas):
            return "lista"
    return None


# ---------------------------------------------------------------- extração

def col_letra(j):
    from openpyxl.utils import get_column_letter
    return get_column_letter(j + 1)


_ERROS_EXCEL = {"#N/A", "#N/D", "#VALUE!", "#VALOR!", "#REF!", "#DIV/0!", "#NAME?", "#NOME?", "#NULL!", "#NUM!", "#NÚM!"}
_TOTAL = re.compile(r"^(sub ?)?total|^totais|^soma\b|^media\b")


def _amostra(grade, i0, j, n=3):
    saida = []
    for r in range(i0, len(grade.linhas)):
        v = grade.celula(r, j)
        if not base.vazio(v):
            t = base.limpar_texto(v.isoformat() if hasattr(v, "isoformat") else v)
            saida.append(t[:80])
            if len(saida) == n:
                break
    return saida


def _traduzir(avisos_conv, onde):
    return [base.aviso(n, c, onde, m, cand) for n, c, m, cand in avisos_conv]


def extrair_processos(grade, indice_cab, registros, cliente_padrao=None, avisos=None):
    """Lê as linhas abaixo do cabeçalho. -> (processos, colunas_sem_destino)
    `registros`: mapeamento (de `propor_mapeamento`, já ajustado). Os avisos vão para a lista `avisos`."""
    avisos = avisos if avisos is not None else []
    nome = grade.nome
    onde_aba = f"aba {nome!r}"
    aplicados = [r for r in registros if r["campo"] and r["aplicado"]]
    por_coluna = {r["indice"]: r["campo"] for r in aplicados}
    col_num = next((j for j, c in por_coluna.items() if c == "numero"), None)
    processos, ignoradas = [], []
    lidas = []             # linhas (índices) que viraram processo
    com_erro = []          # células com valor de erro do Excel
    i0 = indice_cab + 1
    for i in range(i0, len(grade.linhas)):
        linha = grade.linhas[i]
        numero_linha = i + 1
        nao_vazias = [j for j, v in enumerate(linha) if not base.vazio(v)]
        if not nao_vazias:
            continue
        onde_linha = f"{onde_aba}, linha {numero_linha}"
        bruto_num = grade.celula(i, col_num)
        texto_num = "" if base.vazio(bruto_num) else base.limpar_texto(bruto_num)
        primeira = next((base.limpar_texto(linha[j]) for j in nao_vazias), "")
        if not texto_num or not base.achar_numeros(texto_num):
            eh_total = bool(_TOTAL.match(base.chave(texto_num or primeira)))
            if eh_total or len(nao_vazias) <= 2:
                ignoradas.append(f"linha {numero_linha}: {(texto_num or primeira)[:50]}")
            elif not texto_num:
                avisos.append(base.aviso("atencao", "linha_sem_numero", onde_linha,
                                         "A linha tem dados mas a coluna do número do processo está vazia; linha não lida.", []))
            else:
                avisos.append(base.aviso("erro", "numero_invalido", onde_linha,
                                         f"{texto_num[:60]!r} não tem o formato de número de processo (NNNNNNN-DD.AAAA.J.TR.OOOO); linha não lida.", [texto_num[:60]]))
            continue
        principal, vinculados, av_num = base.interpretar_numeros(texto_num, onde_linha)
        avisos.extend(av_num)
        if principal is None:
            continue
        campos, extras = {}, {}
        andamentos_texto, ultimo_texto, fecho, lista_andamentos = "", None, None, []
        for j in nao_vazias:
            destino = por_coluna.get(j)
            if destino is None or destino == "numero":
                continue
            valor = linha[j]
            e_formula = (i, j) in grade.formulas
            if isinstance(valor, str) and valor.strip().upper() in _ERROS_EXCEL:
                com_erro.append(f"{col_letra(j)}{numero_linha}")
                continue
            onde_cel = f"{onde_aba}, célula {col_letra(j)}{numero_linha}"
            if destino == "tribunal":
                continue
            if destino == "ativo":
                v, problema = base.converter_sim_nao(valor)
                if v is not None:
                    extras["ativo"] = v == "Sim"
                continue
            if destino == "andamentos":
                analise = base.analisar_andamentos(valor if isinstance(valor, str) else str(valor))
                andamentos_texto, ultimo_texto, fecho = analise["texto"], analise["ultimo"], analise["fecho"]
                lista_andamentos = [{"data": a["data"], "texto": a["texto"]} for a in analise["andamentos"]]
                avisos.extend(base.aviso(n, c, onde_cel, m) for n, c, m in analise["avisos"])
                continue
            conv = base.converter_campo(destino, valor, grade.formatos.get((i, j)), grade.epoch)
            if destino == "situacao" and conv["valor"] is None and not base.vazio(valor):
                alt = base.converter_campo("momento_atual", valor)
                if alt["valor"] is not None and "momento_atual" not in campos:
                    campos["momento_atual"] = base.montar_campo("momento_atual", alt["valor"], "migrado")
                    avisos.append(base.aviso("info", "situacao_era_momento", onde_cel,
                                             f"A coluna de situação traz {base.limpar_texto(valor)!r}, que é um momento atual; "
                                             "lido como momento atual do processo.", [alt["valor"]]))
                    continue
            avisos.extend(_traduzir(conv["avisos"], onde_cel))
            extras.update(conv["extras"])
            if conv["valor"] is not None:
                campos[destino] = base.montar_campo(destino, conv["valor"], base.origem_do_campo(destino, e_formula))
        lidas.append(i)
        ultimo = ultimo_texto
        if ultimo is None and "ultimo_andamento" in campos:
            ultimo = campos["ultimo_andamento"]["valor"]
        if cliente_padrao and "cliente" not in campos:
            campos["cliente"] = base.montar_campo("cliente", cliente_padrao, "migrado")
        processos.append(base.processo_lido(
            principal, campos, vinculados, andamentos_texto, ultimo,
            f"aba {nome!r}, linha {numero_linha}" if nome else f"linha {numero_linha}",
            ativo=extras.get("ativo"), fecho=fecho, andamentos=lista_andamentos,
            momento_qualificador=extras.get("momento_qualificador")))
    if ignoradas:
        avisos.append(base.aviso("info", "linhas_ignoradas", onde_aba,
                                 f"{len(ignoradas)} linha(s) ignorada(s) por serem marcadores ou totais.", ignoradas[:20]))
    # fórmulas sem valor em cache: só avisa quando NENHUMA célula de fórmula da coluna tem valor guardado (fórmula que
    # devolve "" de vez em quando é normal; arquivo salvo sem cache deixa a coluna toda vazia)
    faltando = {}
    for j in por_coluna:
        formulas_col = [i for i in lidas if (i, j) in grade.formulas]
        vazias = [i for i in formulas_col if base.vazio(grade.celula(i, j))]
        if formulas_col and len(vazias) == len(formulas_col):
            faltando[j] = [f"{col_letra(j)}{i + 1}" for i in vazias]
    for j, celulas in faltando.items():
        destino = por_coluna[j]
        derivada = destino in DERIVADOS
        avisos.append(base.aviso("info" if derivada else "atencao", "formula_sem_valor", f"{onde_aba}, coluna {col_letra(j)}",
                                 f"{len(celulas)} célula(s) de fórmula da coluna {grade.celula(indice_cab, j)!r} não têm valor "
                                 "calculado guardado no arquivo (salvo sem cache); foram lidas como vazias."
                                 + (" É uma coluna calculada: o valor se refaz ao abrir no Excel." if derivada else ""),
                                 celulas[:10]))
    if com_erro:
        avisos.append(base.aviso("atencao", "celula_com_erro", onde_aba,
                                 f"{len(com_erro)} célula(s) com erro do Excel (#N/D, #REF!...) foram lidas como vazias.", com_erro[:10]))
    # colunas que ficaram sem destino
    sem_destino = []
    for r in registros:
        if r["campo"] and r["aplicado"]:
            continue
        if r["campo"] in ESPECIAIS and r["aplicado"]:
            continue
        amostra = _amostra(grade, i0, r["indice"])
        if not amostra:
            continue
        motivo = ("ambigua" if r["ambigua"] else "duplicada" if r["duplicada_de"] is not None else
                  "baixa_confianca" if r["campo"] else "sem_campo_equivalente")
        sem_destino.append({"coluna": r["coluna"], "amostra": amostra, "aba": nome, "motivo": motivo,
                            "candidatos": r["candidatos"]})
        onde = f"{onde_aba}, coluna {col_letra(r['indice'])}"
        if r["ambigua"]:
            avisos.append(base.aviso("atencao", "coluna_ambigua", onde,
                                     f"A coluna {r['coluna']!r} poderia ser {' ou '.join(rotulo_do_destino(c) for c in r['candidatos'][:2])}; "
                                     "não foi lida. Indique o destino na tela de mapeamento.", r["candidatos"]))
        elif r["duplicada_de"] is not None:
            avisos.append(base.aviso("atencao", "coluna_duplicada", onde,
                                     f"A coluna {r['coluna']!r} repete um campo já lido pela coluna {col_letra(r['duplicada_de'])}; só a primeira foi lida.", r["candidatos"]))
        elif r["campo"]:
            avisos.append(base.aviso("atencao", "coluna_baixa_confianca", onde,
                                     f"A coluna {r['coluna']!r} lembra {rotulo_do_destino(r['campo'])} (confiança {r['confianca']:.0%}), "
                                     "mas não foi lida sem confirmação.", [r["campo"]]))
    return processos, sem_destino


def registros_publicos(grade, registros, indice_cab=0):
    """Mapeamento no formato exposto em RelatorioLido["mapeamento"]."""
    return [{"aba": grade.nome, "coluna": r["coluna"], "campo": r["campo"], "rotulo_campo": rotulo_do_destino(r["campo"]) if r["campo"] else None,
             "confianca": r["confianca"], "aplicado": r["aplicado"], "candidatos": r["candidatos"],
             "ambigua": r["ambigua"], "amostra": _amostra(grade, indice_cab + 1, r["indice"]), "indice": r["indice"]} for r in registros]


def carregar(caminho):
    """Grades de um .xlsx ou de um CSV, pelo conteúdo (zip = planilha). -> (grades, avisos)"""
    with open(caminho, "rb") as f:
        cabeca = f.read(4)
    if cabeca[:2] == b"PK":
        return carregar_xlsx(caminho)
    return carregar_csv(caminho)


def ler_grades(grades, mapeamento=None, cliente_padrao=None, avisos=None, candidatas=None, lidas_de_outro_modo=()):
    """Processa todas as grades que têm cabeçalho e números. -> (processos, sem_destino, mapeamento_publico, avisos)
    `candidatas`: resultado de `grades_de_processos` se já calculado; `lidas_de_outro_modo`: abas (ids) que o chamador
    leu por outro caminho (parâmetros) e que não merecem o aviso de aba ignorada."""
    avisos = avisos if avisos is not None else []
    processos, sem_destino, publico = [], [], []
    if candidatas is None:
        candidatas = grades_de_processos(grades)
    usadas = {id(g) for g, _, _ in candidatas} | set(lidas_de_outro_modo)
    for g in grades:
        if id(g) not in usadas:
            avisos.append(base.aviso("info", "aba_ignorada", f"aba {g.nome!r}",
                                     "Sem cabeçalho com coluna de número de processo (ou sem números abaixo); aba não lida como lista de processos."))
    for g, i, regs in candidatas:
        regs = aplicar_mapeamento_do_usuario(regs, mapeamento, avisos, f"aba {g.nome!r}")
        publico.extend(registros_publicos(g, regs, i))
        procs, sd = extrair_processos(g, i, regs, cliente_padrao, avisos)
        processos.extend(procs)
        sem_destino.extend(sd)
    return processos, sem_destino, publico, avisos
