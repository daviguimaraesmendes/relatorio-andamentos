"""Qualidade da base e "o que mudou neste ciclo" (WS-11).

Duas peças independentes do mesmo assunto: a base de processos está confiável para ir ao cliente? e o que mudou
desde o último relatório?

1) VERIFICADOR  `verificar(fichas, perfil=None, *, hoje=None) -> [Achado]`

    Achado = {"codigo": str estável, "gravidade": "erro|atencao|info", "numeros": [..], "mensagem": str,
              "sugestao": str}

    `erro`: o indicador ou a entrega sai errado se nada for feito; `atencao`: quase sempre é defeito, vale
    conferir; `info`: ressalva que o leitor do relatório precisa conhecer. Cada código aparece em CODIGOS (a
    lista fechada, com a gravidade padrão). Os achados saem em ordem estável (gravidade, código, número).
    `resumir(achados)` conta por código e `como_texto(achados)` monta o "relatório de qualidade da base".

    O que se procura (cada item é um código):
      linha_marcador, numero_invalido, numero_duplicado, vinculado_invalido, vinculado_duplicado,
      vinculado_com_ficha_propria, vinculo_tipo_invalido, mesma_acao_contada_duas_vezes, possivel_acao_repetida,
      rotulo_fora_do_vocabulario, rotulo_parecido, rotulos_parecidos_na_base, grafias_diferentes_da_parte,
      acordo_sem_valor, ressalva_acordo_terceiro, ressalva_exclusao_lide, ressalva_cliente_autor,
      economia_inflada, economia_inconsistente, encerrado_sem_resultado, resultado_x_situacao, ativo_x_momento,
      fase_x_momento, probabilidade_x_resultado, campo_obrigatorio_ausente, data_incoerente, data_invalida,
      valor_invalido, valor_causa_vazio_ou_zero, ficha_invalida.
    Vai além de `tests/ficticio.detectar_defeitos` (que cobre só: duplicado, matéria com dois rótulos, acordo sem
    valor, encerrado sem resultado, ativo em conflito, DV errado, grafias do cliente).

    CONVENÇÃO DAS RESSALVAS DE ECONOMIA (o relatório não tem campo próprio para elas): três situações inflam o
    indicador de economia e precisam estar marcadas na ficha.
      - acordo pago por terceiro e exclusão da lide: escreva o marcador, entre colchetes, no campo `observacoes`
        (ou em `outras_partes`):  [acordo pago por terceiro]   [exclusão da lide]
        (também vale a forma curta [acordo-terceiro] / [exclusao-da-lide]; maiúscula e acento não importam).
      - cliente autor: não precisa marcar, vem de `polo_cliente == "ativo"`.
      - acordo sem valor lançado: vem de `resultado == "Acordo"` sem `valor_acordo`.
    `ressalvas_de_economia(ficha) -> [codigo]` devolve as que se aplicam (usado por quadros.py, historico.py e
    pelo julgamento.py, para os três usarem a mesma regra).

    FALSOS POSITIVOS CONHECIDOS (o verificador aponta, quem decide é a pessoa):
      - o marcador de ressalva é lido por texto: "não houve exclusão da lide" também dispara; escreva só o marcador;
      - `possivel_acao_repetida` junta fichas com as mesmas partes, mesmo valor da causa e mesma matéria; ações
        realmente distintas (várias cobranças iguais contra o mesmo devedor) caem aqui;
      - `grafias_diferentes_da_parte` só junta nomes que diferem em acento, caixa, pontuação, espaço ou sufixo
        societário (Ltda, S.A., ME...). Erro de letra ("Sitio" x "Sítio" entra; "Silva" x "Silvia" não) NÃO é
        pego de propósito: nome parecido de pessoas diferentes é comum;
      - `rotulos_parecidos_na_base` usa semelhança de texto (nunca para textos com número); duas matérias
        diferentes e muito parecidas podem ser juntadas;
      - `rotulo_fora_do_vocabulario` para matéria é só `info`: fora de trabalhista a matéria é texto livre; para
        o momento atual aceita o qualificador entre parênteses ("... (HONORÁRIOS SUSPENSOS)");
      - `resultado_x_situacao` não vale para decisão que anula a sentença (processo volta à fase de conhecimento
        com o resultado antigo ainda lançado);
      - `probabilidade_x_resultado` segue a regra de julgamento sem inversão por polo (Procedente/Parcial =
        Provável; Improcedente = Remota). Relatórios antigos que olhavam pelo lado do cliente autor aparecem aqui
        como `info`; é calibração, não erro;
      - `linha_marcador` reconhece zeros, noves e "X" no lugar do número e palavras como total/modelo/preencher;
        cliente com nome "Total" e sem número CNJ também; um cliente que se chame assim de verdade seria pego.

2) O QUE MUDOU  `o_que_mudou(estado_antes, estado_depois, *, max_itens=8) -> dict`

    Compara dois estados do relatório e devolve o resumo por processo, por cliente e geral, com um texto de uma
    página pronto para e-mail ao cliente. `estado_*` pode ser: um EstadoRelatorio (`{"fichas", "eventos",
    "data_base", ...}`), uma lista de fichas, ou um retrato mensal (`historico`); `estado_antes=None` trata tudo
    como novo. Com retrato só se comparam os campos que o retrato tem. O texto só usa eventos APROVADOS (ou já
    relatados) da janela entre as datas-base e campos de julgamento que NÃO estejam apenas `sugerido`; nunca
    promete resultado (fecha com aviso de que é informativo).

    {"data_antes", "data_depois", "totais": {"antes", "depois"},
     "por_processo": [{"numero", "cliente", "tipo": "novo|encerrado|reativado|alterado|sem_mudanca|removido",
                       "mudancas": [{"campo", "rotulo", "antes", "depois", "origem"}], "eventos": [...],
                       "texto"}],
     "por_cliente": {cliente: {"novos", "encerrados", "reativados", "removidos", "mudancas_de_momento",
                               "decisoes", "audiencias_e_prazos", "valores", "sem_mudanca", "totais", "texto"}},
     "texto": str, "avisos": [Aviso]}
"""
import datetime
import difflib
import re
from collections import Counter, defaultdict

import carteira as cart
import comum
import ficha
import taxonomia

GRAVIDADES = ("erro", "atencao", "info")

# código: (gravidade padrão, o que significa)
CODIGOS = {
    "linha_marcador": ("atencao", "linha deixada na base só para marcar lugar (total, modelo, número em branco)"),
    "numero_invalido": ("erro", "número CNJ com dígito verificador errado ou fora do padrão"),
    "numero_duplicado": ("erro", "mesmo número em mais de uma ficha"),
    "vinculado_invalido": ("erro", "processo vinculado com número inválido ou igual ao principal"),
    "vinculado_duplicado": ("atencao", "mesmo processo vinculado repetido ou ligado a duas fichas"),
    "vinculado_com_ficha_propria": ("atencao", "processo vinculado que também é uma ficha: seria contado duas vezes"),
    "vinculo_tipo_invalido": ("info", "tipo de vínculo fora do vocabulário"),
    "mesma_acao_contada_duas_vezes": ("erro", "reajuizamento/mesma ação com duas fichas: entra duas vezes nos totais"),
    "possivel_acao_repetida": ("atencao", "fichas com as mesmas partes, valor e matéria: pode ser a mesma ação"),
    "rotulo_fora_do_vocabulario": ("atencao", "rótulo que não existe no vocabulário do campo"),
    "rotulo_parecido": ("atencao", "rótulo escrito de outro jeito que o vocabulário reconhece"),
    "rotulos_parecidos_na_base": ("atencao", "o mesmo rótulo escrito de jeitos diferentes na base"),
    "grafias_diferentes_da_parte": ("atencao", "a mesma parte escrita de jeitos diferentes"),
    "acordo_sem_valor": ("atencao", "acordo sem valor lançado"),
    "ressalva_acordo_terceiro": ("info", "acordo pago por terceiro: fora do indicador de economia"),
    "ressalva_exclusao_lide": ("info", "exclusão da lide: fora do indicador de economia"),
    "ressalva_cliente_autor": ("info", "cliente autor: economia não se aplica"),
    "economia_inflada": ("atencao", "economia lançada em processo que deveria ficar fora do indicador"),
    "economia_inconsistente": ("atencao", "economia diferente de valor da causa menos valor estimado"),
    "encerrado_sem_resultado": ("atencao", "processo encerrado sem resultado"),
    "resultado_x_situacao": ("atencao", "resultado e situação/momento em conflito"),
    "ativo_x_momento": ("atencao", "'ativo' em conflito com o momento atual ou a situação"),
    "fase_x_momento": ("info", "fase em conflito com o momento atual"),
    "probabilidade_x_resultado": ("info", "probabilidade em desacordo com o resultado"),
    "campo_obrigatorio_ausente": ("atencao", "campo que o perfil exige está vazio"),
    "data_incoerente": ("atencao", "datas que não combinam entre si ou no futuro"),
    "data_invalida": ("erro", "data que não é uma data"),
    "valor_invalido": ("erro", "valor monetário que não é número"),
    "valor_causa_vazio_ou_zero": ("atencao", "valor da causa vazio, zero ou negativo"),
    "ficha_invalida": ("erro", "campo ou origem que a ficha não conhece"),
}

# O que cada entrega exige da ficha (além da base). `colunas_ativas` do perfil, quando existir, filtra isto.
OBRIGATORIOS_BASE = ("cliente", "polo_cliente", "momento_atual")
OBRIGATORIOS_POR_ENTREGA = {
    "docx_a": ("assunto", "autores", "reus", "data_ajuizamento", "vara", "area", "materia_principal"),
    "xlsx_b": ("autores", "reus", "vara", "municipio", "data_ajuizamento", "materia_principal", "situacao"),
    "dashboard": ("situacao", "area", "materia_principal", "data_ajuizamento"),
}

RESSALVAS = {"acordo_sem_valor": "acordo sem valor lançado", "acordo_terceiro": "acordo pago por terceiro",
             "exclusao_lide": "exclusão da lide", "cliente_autor": "cliente é autor"}
_RE_TERCEIRO = re.compile(r"acordo[ -]terceiro|pago (por|pelo|pela) (um |uma )?terceir|terceiro pag|"
                          r"pagamento (por|de) terceir")
_RE_EXCLUSAO = re.compile(r"exclusao[ -]da[ -]lide|excluid[oa] da lide|exclusao (do|da) (polo|cliente|empresa|reclamada)")

RESULTADOS_DE_MERITO = ("Procedente", "Parcialmente procedente", "Improcedente")
RESULTADOS_QUE_ENCERRAM = ("Acordo", "Extinto sem resolução de mérito", "Arquivado / desistência")
# momentos em que ainda não há sentença: resultado de mérito aqui é conflito
PRE_SENTENCA = frozenset(m for m, (cat, _) in taxonomia.MOMENTO_ATUAL.items() if cat == "conhecimento"
                         and m not in ("AGUARDANDO PARCELAMENTO DAS CUSTAS", "AGUARDANDO MANIFESTAÇÃO DE TERCEIROS",
                                       "AGUARDANDO SUBSTITUIÇÃO PROCESSUAL"))
FASE_DO_MOMENTO = {"conhecimento": "Conhecimento", "recurso": "Recurso", "execução": "Execução"}
SUFIXOS_SOCIETARIOS = frozenset(("ltda", "sa", "eireli", "me", "epp"))
PARTES = ("cliente", "autores", "reus", "parte_contraria", "outras_partes")
CAMPOS_LIVRES = ("materia_principal", "assunto", "classe", "municipio", "vara")
_STOP = frozenset(("a", "o", "as", "os", "da", "de", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos", "por",
                   "para", "com"))
_MARCADOR_NUMERO = re.compile(r"^[\s0xX9\-._/]*$")
_MARCADOR_PALAVRAS = re.compile(r"\b(total|subtotal|exemplo|modelo|preencher|marcador|linha|xxx+)\b")
_MARCADOR_CLIENTE = frozenset(("total", "subtotal", "totais", "exemplo", "modelo", "preencher", "marcador"))
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


# ---------------------------------------------------------------- utilidades

def _norm(texto):
    return comum.normalizar(str(texto or ""))


def _chave_frouxa(texto):
    """Sem acento, caixa, pontuação nem artigos/preposições: 'Reversão da justa causa.' == 'Reversão Justa Causa'."""
    n = re.sub(r"[^a-z0-9]+", " ", _norm(texto))
    return " ".join(t for t in n.split() if t not in _STOP)


def _chave_parte(nome):
    """Chave de um nome de parte: sem acento/pontuação e sem sufixo societário no fim (Ltda, S.A., ME...)."""
    t = re.sub(r"[^a-z0-9]+", " ", _norm(nome)).split()
    while t:
        if t[-2:] == ["s", "a"]:
            t = t[:-2]
        elif t[-1] in SUFIXOS_SOCIETARIOS:
            t = t[:-1]
        else:
            break
    return " ".join(t)


def _dinheiro(f, campo):
    return ficha.dinheiro(ficha.obter(f, campo))


def _num(f):
    return f.get("numero", "")


def _base_do_momento(momento):
    return _PAREN.sub("", str(momento or "")).strip()


def _achado(codigo, numeros, mensagem, sugestao="", gravidade=None):
    return {"codigo": codigo, "gravidade": gravidade or CODIGOS[codigo][0], "numeros": list(numeros),
            "mensagem": mensagem, "sugestao": sugestao}


def _fichas_v2(fichas):
    return [ficha.de_carteira_v1(f) for f in (fichas or [])]


def _hoje(hoje):
    if hoje is None:
        return datetime.date.today()
    return hoje if isinstance(hoje, datetime.date) else (ficha.data(hoje) or datetime.date.today())


# ---------------------------------------------------------------- situação do processo (regras comuns)

def momento_ativo(f):
    """True/False se o momento atual (sem o qualificador entre parênteses) conta como ativo; None se desconhecido."""
    return taxonomia.momento_ativo(_base_do_momento(ficha.obter(f, "momento_atual")).upper())


def encerrado(f):
    """O processo está encerrado? Qualquer sinal conta: 'ativo' falso, situação Encerrado ou momento encerrado."""
    return (not f.get("ativo", True)) or ficha.obter(f, "situacao") == "Encerrado" or momento_ativo(f) is False


def e_marcador(f):
    """Linha deixada na base só para marcar lugar (ver a seção de falsos positivos do cabeçalho)."""
    numero = _num(f).strip()
    if _MARCADOR_NUMERO.match(numero):   # vazio, só zeros, noves ou X: número que nenhum processo tem
        return bool(numero) or not f.get("campos")   # vazio com dados é número que faltou, não marcador
    if not cart.numeros_no_texto(numero)[0]:
        return bool(_MARCADOR_PALAVRAS.search(_norm(numero))
                    or _norm(ficha.obter(f, "cliente")).strip(" .") in _MARCADOR_CLIENTE)
    return False


def ressalvas_de_economia(f):
    """Códigos das ressalvas que tiram o processo do indicador de economia (convenção no cabeçalho do módulo)."""
    achadas = []
    if ficha.obter(f, "resultado") == "Acordo" and not ficha.obter(f, "valor_acordo"):
        achadas.append("acordo_sem_valor")
    texto = _norm(f"{ficha.obter(f, 'observacoes') or ''} {ficha.obter(f, 'outras_partes') or ''}")
    if _RE_TERCEIRO.search(texto):
        achadas.append("acordo_terceiro")
    if _RE_EXCLUSAO.search(texto):
        achadas.append("exclusao_lide")
    if ficha.obter(f, "polo_cliente") == "ativo":
        achadas.append("cliente_autor")
    return achadas


def desfecho_pecuniario_definido(f):
    """O fim do processo tem valor definido? Acordo com valor, condenação com valor arbitrado ou improcedência
    (valor zero). Extinção sem mérito, arquivamento/desistência e incompetência NÃO definem valor."""
    resultado = ficha.obter(f, "resultado")
    if resultado == "Acordo":
        return bool(ficha.dinheiro(ficha.obter(f, "valor_acordo")))
    if resultado in ("Procedente", "Parcialmente procedente"):
        return _dinheiro(f, "valor_arbitrado") is not None
    return resultado == "Improcedente"


# ---------------------------------------------------------------- verificador

def verificar(fichas, perfil=None, *, hoje=None):
    """Lista de Achado sobre a base inteira. `perfil` (CONTRATOS §7) define os campos obrigatórios; `hoje`
    (date ou ISO) só serve para achar datas no futuro (padrão: hoje de verdade)."""
    hoje = _hoje(hoje)
    achados, reais = [], []
    for f in _fichas_v2(fichas):
        if e_marcador(f):
            achados.append(_achado(
                "linha_marcador", [_num(f)], f"A linha {_num(f) or '(sem número)'!r} parece marcador, não processo.",
                "Apague a linha da base (ela entra nas contagens e nos indicadores)."))
        else:
            reais.append(f)
    achados += _numeros_e_vinculos(reais)
    achados += _acao_repetida(reais)
    achados += _rotulos(reais)
    achados += _grafias_das_partes(reais)
    achados += _ressalvas_agrupadas(reais)
    for f in reais:
        achados += _da_ficha(f, perfil, hoje)
    ordem = {g: i for i, g in enumerate(GRAVIDADES)}
    return sorted(achados, key=lambda a: (ordem[a["gravidade"]], a["codigo"], a["numeros"][:1], a["mensagem"]))


def resumir(achados):
    """{"total", "por_gravidade": {g: n}, "por_codigo": {codigo: {"gravidade", "quantidade", "processos"}}};
    "processos" é a quantidade de números distintos afetados."""
    por_codigo = {}
    for a in achados:
        r = por_codigo.setdefault(a["codigo"], {"gravidade": a["gravidade"], "quantidade": 0, "_numeros": set()})
        r["quantidade"] += 1
        r["_numeros"].update(a["numeros"])
    for r in por_codigo.values():
        r["processos"] = len(r.pop("_numeros"))
    return {"total": len(achados), "por_gravidade": dict(Counter(a["gravidade"] for a in achados)),
            "por_codigo": dict(sorted(por_codigo.items()))}


def como_texto(achados, limite=6):
    """Relatório de qualidade da base em texto simples (vai para a pasta saida/): do mais grave ao menos grave."""
    if not achados:
        return "Qualidade da base: nenhum problema encontrado.\n"
    r = resumir(achados)
    nomes = {"erro": "ERROS (corrigir antes de entregar)", "atencao": "PARA CONFERIR", "info": "RESSALVAS (informativo)"}
    linhas = [f"Qualidade da base: {r['total']} achado(s).", ""]
    for g in GRAVIDADES:
        do_nivel = [a for a in achados if a["gravidade"] == g]
        if not do_nivel:
            continue
        linhas.append(f"{nomes[g]}: {len(do_nivel)}")
        for a in do_nivel:
            quem = ", ".join(a["numeros"][:limite]) + (f" e mais {len(a['numeros']) - limite}" if len(a["numeros"]) > limite else "")
            linhas.append(f"  - {a['mensagem']}" + (f" [{quem}]" if quem else ""))
            if a["sugestao"]:
                linhas.append(f"    Sugestão: {a['sugestao']}")
        linhas.append("")
    return "\n".join(linhas)


# --- números e vínculos

def _numeros_e_vinculos(fichas):
    achados = []
    contagem = Counter(_num(f) for f in fichas if _num(f))
    duplicados = {n for n, c in contagem.items() if c > 1}
    for numero in sorted(duplicados):
        achados.append(_achado("numero_duplicado", [numero], f"O número {numero} aparece em {contagem[numero]} fichas.",
                               "Mantenha uma ficha só; se são ações diferentes, confira o número."))
    vistas = set()
    for f in fichas:
        numero = _num(f)
        if numero in vistas:
            continue
        vistas.add(numero)
        validos, _ = cart.numeros_no_texto(numero)
        if not validos:
            achados.append(_achado("numero_invalido", [numero], f"Número CNJ inválido (dígito verificador): {numero!r}.",
                                   "Confira o número nos autos e corrija."))
        elif numero.strip() != validos[0][0]:
            achados.append(_achado("numero_invalido", [numero], f"Número fora do padrão com máscara: {numero!r}.",
                                   f"Use {validos[0][0]}.", gravidade="atencao"))
    por_numero = {_num(f): f for f in fichas}
    ligados = defaultdict(set)   # vinculado -> números principais que o citam
    for f in fichas:
        vistos_aqui = set()
        for v in f.get("vinculados", []):
            vn = v.get("numero", "")
            if not cart.numeros_no_texto(vn)[0] or vn == _num(f):
                achados.append(_achado("vinculado_invalido", [_num(f), vn], f"Vinculado {vn!r} inválido na ficha {_num(f)}.",
                                       "Corrija o número ou retire o vínculo."))
                continue
            if vn in vistos_aqui:
                achados.append(_achado("vinculado_duplicado", [_num(f), vn], f"O vinculado {vn} está duas vezes na ficha {_num(f)}.",
                                       "Deixe um só."))
            vistos_aqui.add(vn)
            ligados[vn].add(_num(f))
            if v.get("tipo") not in taxonomia.TIPO_VINCULO:
                achados.append(_achado("vinculo_tipo_invalido", [_num(f), vn],
                                       f"Tipo de vínculo {v.get('tipo')!r} fora do vocabulário ({vn} em {_num(f)}).",
                                       "Use: " + ", ".join(taxonomia.TIPO_VINCULO) + "."))
    for vn, donos in sorted(ligados.items()):
        if len(donos) > 1:
            achados.append(_achado("vinculado_duplicado", [vn, *sorted(donos)],
                                   f"O processo {vn} está vinculado a {len(donos)} fichas diferentes.",
                                   "Um processo vinculado pertence a uma linha só."))
    ja_dito = set()
    for f in fichas:
        for v in f.get("vinculados", []):
            vn = v.get("numero", "")
            outra = por_numero.get(vn)
            if outra is None or vn == _num(f):
                continue
            par = frozenset((_num(f), vn))
            if v.get("tipo") in ("mesma_acao", "reajuizamento"):
                if par not in ja_dito:
                    ja_dito.add(par)
                    achados.append(_achado(
                        "mesma_acao_contada_duas_vezes", [_num(f), vn],
                        f"{_num(f)} e {vn} são a mesma ação ({v.get('tipo')}) mas têm duas fichas: contam em dobro nos totais.",
                        "Deixe uma ficha e registre a outra como processo vinculado."))
            elif par not in ja_dito:
                ja_dito.add(par)
                achados.append(_achado(
                    "vinculado_com_ficha_propria", [_num(f), vn],
                    f"{vn} é vinculado de {_num(f)} ({v.get('tipo')}) e também tem ficha própria: o relatório trata os dois como uma linha.",
                    "Apague a ficha do vinculado."))
    return achados


def _acao_repetida(fichas):
    """Mesmas partes + mesmo valor da causa + mesma matéria, sem vínculo entre as fichas."""
    achados = []
    grupos = defaultdict(set)
    for f in fichas:
        autores, reus = _chave_parte(ficha.obter(f, "autores")), _chave_parte(ficha.obter(f, "reus"))
        causa = _dinheiro(f, "valor_causa")
        tema = _chave_frouxa(ficha.obter(f, "materia_principal") or ficha.obter(f, "assunto"))
        if autores and reus and causa and tema and _num(f):
            grupos[(_chave_parte(ficha.obter(f, "cliente")), autores, reus, str(causa), tema)].add(_num(f))
    ligacao = {frozenset((_num(f), v.get("numero"))) for f in fichas for v in f.get("vinculados", [])}
    for _, numeros in sorted(grupos.items(), key=lambda x: sorted(x[1])):
        if len(numeros) < 2:
            continue
        numeros = sorted(numeros)
        if all(frozenset(p) in ligacao for p in zip(numeros, numeros[1:])):
            continue  # já está dito como vínculo
        achados.append(_achado(
            "possivel_acao_repetida", numeros,
            f"{len(numeros)} fichas com as mesmas partes, o mesmo valor da causa e a mesma matéria: pode ser a mesma ação contada mais de uma vez.",
            "Se for reajuizamento ou duplicidade, deixe uma ficha e vincule a outra."))
    return achados


# --- rótulos

def _momento_conhecido(valor):
    """(ok, canonico_sugerido) para o momento atual, aceitando o qualificador entre parênteses."""
    base = _base_do_momento(valor)
    if base in taxonomia.MOMENTO_ATUAL:
        return True, None
    if base.upper() in taxonomia.MOMENTO_ATUAL:
        return False, base.upper() + valor[len(base):]
    return False, None


def _rotulos(fichas):
    achados = []
    parecido, fora = defaultdict(list), defaultdict(list)
    nao_reconhecidos = defaultdict(lambda: defaultdict(list))   # campo livre -> valor -> números
    for f in fichas:
        for campo, (_, _, _, vocab) in ficha.CAMPOS.items():
            if campo == "materia_principal":
                vocab = "materia"
            valor = ficha.obter(f, campo)
            if campo in CAMPOS_LIVRES and isinstance(valor, str) and valor.strip():
                if vocab is None or taxonomia.normalizar(vocab, valor) is None:
                    nao_reconhecidos[campo][valor.strip()].append(_num(f))
            if not vocab or not isinstance(valor, str) or not valor.strip():
                continue
            if vocab == "momento_atual":
                ok, canonico = _momento_conhecido(valor)
                if ok:
                    continue
            else:
                if valor in taxonomia.VOCABULARIOS[vocab]:
                    continue
                canonico = taxonomia.normalizar(vocab, valor)
            (parecido if canonico else fora)[(campo, valor, canonico)].append(_num(f))
    for (campo, valor, canonico), numeros in sorted(parecido.items()):
        rotulo = ficha.CAMPOS[campo][0]
        achados.append(_achado("rotulo_parecido", numeros, f"{rotulo}: {valor!r} está escrito diferente do vocabulário.",
                               f"Use {canonico!r}."))
    for (campo, valor, _), numeros in sorted(fora.items()):
        rotulo = ficha.CAMPOS[campo][0]
        gravidade = "info" if campo == "materia_principal" else None
        achados.append(_achado("rotulo_fora_do_vocabulario", numeros,
                               f"{rotulo}: {valor!r} não existe no vocabulário.",
                               "Escolha um valor da lista (ou cadastre o novo valor no vocabulário).", gravidade=gravidade))
    for campo in CAMPOS_LIVRES:
        achados += _parecidos_na_base(campo, nao_reconhecidos[campo])
    return achados


def _parecidos_na_base(campo, valores):
    """Agrupa grafias do mesmo texto livre (mesma chave frouxa, ou muito parecidas quando não há número)."""
    nomes = sorted(valores)
    pai = {n: n for n in nomes}

    def raiz(n):
        while pai[n] != n:
            pai[n] = pai[pai[n]]
            n = pai[n]
        return n

    chaves = {n: _chave_frouxa(n) for n in nomes}
    for i, a in enumerate(nomes):
        for b in nomes[i + 1:]:
            ka, kb = chaves[a], chaves[b]
            igual = bool(ka) and ka == kb
            parecido = (not igual and len(ka) >= 8 and len(kb) >= 8 and not re.search(r"\d", ka + kb)
                        and difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.9)
            if igual or parecido:
                pai[raiz(a)] = raiz(b)
    grupos = defaultdict(list)
    for n in nomes:
        grupos[raiz(n)].append(n)
    achados = []
    rotulo = ficha.CAMPOS[campo][0]
    for membros in sorted(grupos.values()):
        if len(membros) < 2:
            continue
        numeros = sorted({num for m in membros for num in valores[m]})
        mais_usado = max(membros, key=lambda m: (len(valores[m]), m))
        achados.append(_achado("rotulos_parecidos_na_base", numeros,
                               f"{rotulo}: grafias diferentes do mesmo texto: " + "; ".join(repr(m) for m in membros) + ".",
                               f"Padronize (por exemplo, todos como {mais_usado!r})."))
    return achados


def _grafias_das_partes(fichas):
    por_chave = defaultdict(lambda: defaultdict(set))
    for f in fichas:
        for campo in PARTES:
            nome = ficha.obter(f, campo)
            if isinstance(nome, str) and nome.strip():
                chave = _chave_parte(nome)
                if chave:
                    por_chave[chave][nome.strip()].add(_num(f))
    achados = []
    for chave, grafias in sorted(por_chave.items()):
        if len(grafias) < 2:
            continue
        numeros = sorted({n for ns in grafias.values() for n in ns})
        achados.append(_achado("grafias_diferentes_da_parte", numeros,
                               "A mesma parte aparece escrita de jeitos diferentes: " + "; ".join(repr(g) for g in sorted(grafias)) + ".",
                               "Escolha uma grafia e use em todas as fichas (e no cadastro de clientes)."))
    return achados


def _ressalvas_agrupadas(fichas):
    """As três ressalvas informativas viram um achado cada, com todos os números afetados."""
    grupos = {"acordo_terceiro": [], "exclusao_lide": [], "cliente_autor": []}
    for f in fichas:
        r = ressalvas_de_economia(f)
        for chave in grupos:
            if chave in r and (chave != "cliente_autor" or encerrado(f)):
                grupos[chave].append(_num(f))
    textos = {
        "acordo_terceiro": ("ressalva_acordo_terceiro", "acordo pago por terceiro: o cliente não desembolsou, então não conta como economia dele"),
        "exclusao_lide": ("ressalva_exclusao_lide", "exclusão da lide: o cliente saiu do processo sem pagar, então não conta como economia"),
        "cliente_autor": ("ressalva_cliente_autor", "o cliente é autor: 'economia' não se aplica (não há valor que ele deixou de pagar)"),
    }
    return [_achado(codigo, sorted(numeros), f"{len(numeros)} processo(s) com {msg}.",
                    "Esses processos ficam fora do indicador recomendado de economia.")
            for chave, (codigo, msg) in textos.items() if (numeros := grupos[chave])]


# --- ficha a ficha

def _obrigatorios(perfil):
    perfil = perfil or {}
    exigidos = list(OBRIGATORIOS_BASE)
    entregas = perfil.get("entregas") or []
    colunas = set(perfil.get("colunas_ativas") or [])
    for entrega in entregas:
        for campo in OBRIGATORIOS_POR_ENTREGA.get(entrega, ()):
            if (not colunas or campo in colunas) and campo not in exigidos:
                exigidos.append(campo)
    for campo in perfil.get("obrigatorios") or []:
        if campo in ficha.CAMPOS and campo not in exigidos:
            exigidos.append(campo)
    return [c for c in exigidos if c != "valor_causa"]  # valor da causa tem achado próprio


def _da_ficha(f, perfil, hoje):
    numero = _num(f)
    achados = []

    def novo(codigo, mensagem, sugestao="", gravidade=None):
        achados.append(_achado(codigo, [numero], mensagem, sugestao, gravidade))

    # problemas estruturais que a própria ficha já sabe dizer (o resto do validar é coberto aqui)
    for p in ficha.validar(f):
        if "data inválida" in p:
            novo("data_invalida", p, "Corrija a data (formato DD/MM/AAAA).")
        elif "valor monetário inválido" in p:
            novo("valor_invalido", p, "Digite só números (ex.: 1234,56).")
        elif p.startswith("Campo desconhecido") or "origem inválida" in p:
            novo("ficha_invalida", p, "Arquivo da ficha alterado fora do programa: regrave a ficha.")
    resultado = ficha.obter(f, "resultado")
    momento = ficha.obter(f, "momento_atual")
    situacao = ficha.obter(f, "situacao")
    ativo_flag = f.get("ativo", True)
    m_ativo = momento_ativo(f)
    acabou = encerrado(f)

    # ativo x momento atual / situação
    conflitos = []
    if m_ativo is not None and m_ativo != ativo_flag:
        conflitos.append(f"'ativo' está {'sim' if ativo_flag else 'não'} mas o momento atual é {momento!r}")
    if situacao in ("Ativo", "Encerrado") and (situacao == "Ativo") != ativo_flag:
        conflitos.append(f"'ativo' está {'sim' if ativo_flag else 'não'} mas a situação é {situacao!r}")
    if conflitos:
        novo("ativo_x_momento", "; ".join(conflitos) + ".", "Confira nos autos em que pé o processo está e corrija o campo errado.")

    # resultado x situação
    problemas = []
    if resultado in RESULTADOS_QUE_ENCERRAM and not acabou:
        problemas.append(f"o resultado é {resultado!r} mas o processo consta como ativo")
    if resultado in RESULTADOS_DE_MERITO and momento and _base_do_momento(momento).upper() in PRE_SENTENCA:
        problemas.append(f"há resultado de mérito ({resultado}) mas o momento atual é {momento!r}, anterior à sentença")
    base_momento = _base_do_momento(momento).upper()
    if resultado == "Acordo" and base_momento == "EXTINTO SEM RESOLUÇÃO DE MÉRITO":
        problemas.append("o resultado é Acordo mas o momento atual é extinção sem resolução de mérito")
    if resultado == "Extinto sem resolução de mérito" and base_momento == "ACORDO HOMOLOGADO":
        problemas.append("o resultado é extinção sem mérito mas o momento atual é acordo homologado")
    if resultado in RESULTADOS_DE_MERITO and base_momento in ("ACORDO HOMOLOGADO", "EXTINTO SEM RESOLUÇÃO DE MÉRITO"):
        problemas.append(f"o resultado é {resultado!r} mas o momento atual é {momento!r}")
    if problemas:
        novo("resultado_x_situacao", "Conflito: " + "; ".join(problemas) + ".",
             "Confira a última decisão e acerte o resultado ou o momento atual.")
    if acabou and not resultado:
        novo("encerrado_sem_resultado", "Processo encerrado sem resultado lançado.",
             "Lance o resultado (procedente, improcedente, acordo...): sem ele o processo some dos quadros de desfecho.")

    # fase x momento
    categoria = taxonomia.categoria_do_momento(base_momento)
    fase = ficha.obter(f, "fase")
    if fase and FASE_DO_MOMENTO.get(categoria) and fase != FASE_DO_MOMENTO[categoria]:
        novo("fase_x_momento", f"A fase é {fase!r} mas o momento atual ({momento}) é da fase {FASE_DO_MOMENTO[categoria]!r}.",
             "Acerte a fase ou o momento atual.")

    # probabilidade x resultado
    prob = ficha.obter(f, "probabilidade")
    if prob and ((resultado in ("Procedente", "Parcialmente procedente") and prob == "Remota")
                 or (resultado == "Improcedente" and prob == "Provável")):
        novo("probabilidade_x_resultado",
             f"Probabilidade {prob!r} com resultado {resultado!r}. A probabilidade é a do resultado do processo, sem inverter por polo.",
             "Se o lançamento olhou pelo lado do cliente autor, ajuste ao critério do relatório.")
    elif prob and resultado in ("Acordo", "Extinto sem resolução de mérito"):
        novo("probabilidade_x_resultado", f"Probabilidade {prob!r} em processo encerrado por {resultado.lower()}.",
             "Nesse caso a probabilidade fica vazia.")

    # valores
    causa = _dinheiro(f, "valor_causa")
    if causa is None or causa <= 0:
        novo("valor_causa_vazio_ou_zero", "Valor da causa vazio ou zero." if not causa else "Valor da causa negativo.",
             "Lance o valor da causa (está na petição inicial); sem ele o indicador de exposição fica errado.")
    if resultado == "Acordo" and not ficha.obter(f, "valor_acordo"):
        novo("acordo_sem_valor", "Acordo sem valor lançado.",
             "Lance o valor do acordo; sem ele a economia fica inflada ou indefinida.")
    economizado, estimado = _dinheiro(f, "valor_economizado"), _dinheiro(f, "valor_estimado")
    if economizado is not None and economizado > 0:
        motivos = [RESSALVAS[r] for r in ressalvas_de_economia(f)]
        if not acabou:
            motivos.append("processo ainda ativo")
        if motivos:
            novo("economia_inflada", "Economia lançada em processo que deveria ficar fora do indicador: " + "; ".join(motivos) + ".",
                 "Zere a economia ou deixe o processo de fora do indicador (o quadro de economia já o separa).")
    if causa is not None and estimado is not None and economizado is not None and abs(causa - estimado - economizado) > ficha.dinheiro("0.01"):
        novo("economia_inconsistente",
             f"Economia {ficha.dinheiro_br(economizado)} difere de valor da causa menos valor estimado ({ficha.dinheiro_br(causa - estimado)}).",
             "Confira os três valores.")

    # campos obrigatórios pelo perfil
    faltam = [ficha.CAMPOS[c][0] for c in _obrigatorios(perfil) if ficha.obter(f, c) in (None, "")]
    if faltam:
        novo("campo_obrigatorio_ausente", "Faltam campos que o relatório exige: " + ", ".join(faltam) + ".",
             "Preencha à mão ou rode a coleta de capa.")

    # datas
    d = {c: ficha.data(ficha.obter(f, c)) for c in ("data_ajuizamento", "data_citacao", "ultimo_andamento", "data_transito")}
    incoerentes = []
    if d["data_ajuizamento"] and d["ultimo_andamento"] and d["data_ajuizamento"] > d["ultimo_andamento"]:
        incoerentes.append("ajuizamento depois do último andamento")
    if d["data_citacao"] and d["data_ajuizamento"] and d["data_citacao"] < d["data_ajuizamento"]:
        incoerentes.append("citação antes do ajuizamento")
    if d["data_citacao"] and d["ultimo_andamento"] and d["data_citacao"] > d["ultimo_andamento"]:
        incoerentes.append("citação depois do último andamento")
    if d["data_transito"] and d["data_ajuizamento"] and d["data_transito"] < d["data_ajuizamento"]:
        incoerentes.append("trânsito em julgado antes do ajuizamento")
    for campo, dia in d.items():
        if dia and dia > hoje:
            incoerentes.append(f"{ficha.CAMPOS[campo][0].lower()} no futuro ({ficha.data_br(dia.isoformat())})")
    base = f.get("linha_de_base") or {}
    if ficha.data(base.get("ultimo_andamento")) and ficha.data(base.get("data_base")) \
            and ficha.data(base["ultimo_andamento"]) > ficha.data(base["data_base"]):
        incoerentes.append("último andamento do histórico migrado depois da data-base do relatório antigo")
    if incoerentes:
        novo("data_incoerente", "Datas incoerentes: " + "; ".join(incoerentes) + ".", "Confira as datas nos autos.")
    return achados


# ---------------------------------------------------------------- o que mudou

CAMPOS_DE_VALOR = ("valor_causa", "valor_arbitrado", "valor_estimado", "valor_acordo", "valor_execucao",
                   "valor_economizado")
CAMPOS_COMPARADOS = ("momento_atual", "resultado", "probabilidade", *CAMPOS_DE_VALOR)
VALORES_NO_TEXTO = ("valor_causa", "valor_acordo", "valor_arbitrado", "valor_estimado", "valor_execucao")
TIPOS_DE_DECISAO = ("sentenca", "acordao", "decisao")
AVISO_FINAL = ("Este resumo é informativo: descreve o que aconteceu nos processos neste período e não constitui "
               "promessa nem garantia de resultado. Estamos à disposição para esclarecer qualquer ponto.")


def _instantaneo(estado):
    """Normaliza EstadoRelatorio, lista de fichas ou retrato num dict comparável."""
    if estado is None:
        return {"data_base": None, "processos": {}, "eventos": [], "completo": True}
    if isinstance(estado, (list, tuple)):
        estado = {"fichas": list(estado)}
    eventos = estado.get("eventos") or []
    if "fichas" not in estado and "por_processo" in estado:
        processos = {}
        for linha in estado["por_processo"]:
            situacao = linha.get("situacao") or ""
            momento = linha.get("momento_atual") or ""
            ativo = not (situacao == "Encerrado" or taxonomia.momento_ativo(_base_do_momento(momento).upper()) is False)
            valores = {c: (linha.get(c) or None) for c in ("valor_causa", "valor_estimado")}
            processos[linha["numero"]] = {
                "numero": linha["numero"], "cliente": linha.get("cliente") or "(sem cliente)", "ativo": ativo, "rotulo": linha["numero"],
                "campos": {"momento_atual": momento or None, "resultado": linha.get("resultado") or None,
                           "probabilidade": linha.get("probabilidade") or None, **valores},
                "origens": {}, "disponiveis": {"momento_atual", "resultado", "probabilidade", "valor_causa", "valor_estimado"}}
        return {"data_base": ficha.parse_data(estado.get("data_base")), "processos": processos, "eventos": eventos,
                "completo": False}
    processos = {}
    for f in _fichas_v2(estado.get("fichas")):
        if e_marcador(f) or _num(f) in processos:
            continue
        contraria = ficha.obter(f, "parte_contraria")
        processos[_num(f)] = {
            "numero": _num(f), "cliente": ficha.obter(f, "cliente") or "(sem cliente)", "ativo": not encerrado(f),
            "rotulo": _num(f) + (f" (contra {contraria})" if contraria else ""),
            "campos": {c: ficha.obter(f, c) for c in CAMPOS_COMPARADOS},
            "origens": {c: ficha.origem(f, c) for c in CAMPOS_COMPARADOS}, "disponiveis": set(CAMPOS_COMPARADOS)}
    return {"data_base": ficha.parse_data(estado.get("data_base")), "processos": processos, "eventos": eventos,
            "completo": True}


def _mostrar(campo, valor):
    if valor in (None, ""):
        return "(vazio)"
    return ficha.dinheiro_br(valor) if campo in CAMPOS_DE_VALOR else str(valor)


def _eventos_da_janela(eventos, data_antes, data_depois):
    """Eventos aprovados da janela (antes, depois]. Sem data-base anterior, só os ainda não relatados."""
    saida = []
    for ev in eventos:
        status = ev.get("status")
        if status not in ("aprovado", "relatado") or (data_antes is None and status != "aprovado"):
            continue
        dia = ficha.data(ficha.parse_data(ev.get("data")))
        if dia is None and ev.get("detectado_em"):
            dia = ficha.data(ev["detectado_em"][:10])
        if dia is not None and ((data_antes and dia <= ficha.data(data_antes)) or (data_depois and dia > ficha.data(data_depois))):
            continue
        texto = " ".join(t.strip() for t in (ev.get("frase") or "", ev.get("conteudo") or "") if t and t.strip()) or ev.get("titulo", "")
        tipo = _norm(ev.get("tipo") or "")
        categorias = []
        if tipo in TIPOS_DE_DECISAO:
            categorias.append("decisao")
        if ev.get("audiencia") or ev.get("prazo") or "audiencia" in _norm(texto):
            categorias.append("audiencia_ou_prazo")
        resumo_data = ev.get("audiencia") and f"audiência em {ev['audiencia']}" or ev.get("prazo") and f"prazo: {ev['prazo']}"
        saida.append({"numero": ev.get("numero"), "data": dia.isoformat() if dia else None, "texto": texto,
                      "categorias": categorias, "destaque": resumo_data or texto})
    return sorted(saida, key=lambda e: (e["data"] or "", e["numero"] or "", e["texto"]))


def _comparar(antes, depois):
    """Lista de mudanças de campo entre dois dicts de processo (só campos disponíveis nos dois lados)."""
    mudancas = []
    for campo in CAMPOS_COMPARADOS:
        if campo not in antes["disponiveis"] or campo not in depois["disponiveis"]:
            continue
        a, b = antes["campos"].get(campo), depois["campos"].get(campo)
        if campo in CAMPOS_DE_VALOR:
            a, b = ficha.dinheiro(a), ficha.dinheiro(b)
        if a == b or (not a and not b and campo not in CAMPOS_DE_VALOR):
            continue
        if a is None and b is None:
            continue
        mudancas.append({"campo": campo, "rotulo": ficha.CAMPOS[campo][0], "antes": antes["campos"].get(campo),
                         "depois": depois["campos"].get(campo), "origem": depois["origens"].get(campo)})
    return mudancas


def _so_aprovado(mudanca):
    """Campo de julgamento só sugerido não vai para o cliente."""
    return not (mudanca["campo"] in ficha.CAMPOS_DE_JULGAMENTO and mudanca["origem"] == "sugerido")


def o_que_mudou(estado_antes, estado_depois, *, max_itens=8):
    """Ver o cabeçalho do módulo. `max_itens` limita cada seção do texto ('e mais N')."""
    antes, depois = _instantaneo(estado_antes), _instantaneo(estado_depois)
    avisos = []
    if depois["data_base"] is None:
        avisos.append({"nivel": "atencao", "codigo": "sem_data_base", "onde": "estado_depois",
                       "mensagem": "O estado atual não tem data-base: os eventos não foram filtrados por período.", "candidatos": []})
    if not depois["completo"]:
        avisos.append({"nivel": "atencao", "codigo": "estado_atual_e_retrato", "onde": "estado_depois",
                       "mensagem": "O estado atual é um retrato mensal: só valor da causa, estimado, resultado, momento e probabilidade foram comparados.",
                       "candidatos": []})
    eventos = _eventos_da_janela(depois["eventos"], antes["data_base"], depois["data_base"])
    por_numero_ev = defaultdict(list)
    for ev in eventos:
        por_numero_ev[ev["numero"]].append(ev)

    por_processo = []
    for numero in sorted(set(antes["processos"]) | set(depois["processos"])):
        a, d = antes["processos"].get(numero), depois["processos"].get(numero)
        base = d or a
        item = {"numero": numero, "cliente": base["cliente"], "rotulo": base["rotulo"], "mudancas": [],
                "eventos": por_numero_ev.get(numero, []) if d else []}
        if d is None:
            item["tipo"] = "removido"
        elif a is None:
            item["tipo"] = "novo"
            item["encerrado_ao_entrar"] = not d["ativo"]
        else:
            item["mudancas"] = _comparar(a, d)
            if a["ativo"] and not d["ativo"]:
                item["tipo"] = "encerrado"
            elif not a["ativo"] and d["ativo"]:
                item["tipo"] = "reativado"
            else:
                item["tipo"] = "alterado" if item["mudancas"] or item["eventos"] else "sem_mudanca"
        item["texto"] = _texto_do_processo(item)
        por_processo.append(item)

    por_cliente = {}
    for cliente in sorted({p["cliente"] for p in por_processo}):
        mine = [p for p in por_processo if p["cliente"] == cliente]
        r = {"novos": [], "encerrados": [], "reativados": [], "removidos": [], "mudancas_de_momento": [], "decisoes": [],
             "audiencias_e_prazos": [], "valores": [], "sem_mudanca": 0}
        for p in mine:
            if p["tipo"] == "novo":
                r["novos"].append(p["numero"])
            elif p["tipo"] == "encerrado":
                r["encerrados"].append(p["numero"])
            elif p["tipo"] == "reativado":
                r["reativados"].append(p["numero"])
            elif p["tipo"] == "removido":
                r["removidos"].append(p["numero"])
            elif p["tipo"] == "sem_mudanca":
                r["sem_mudanca"] += 1
            if p["tipo"] in ("removido", "novo"):
                continue
            for m in p["mudancas"]:
                if m["campo"] == "momento_atual":
                    r["mudancas_de_momento"].append({"numero": p["numero"], "antes": m["antes"], "depois": m["depois"]})
                elif (m["campo"] == "resultado" and m["depois"] and _so_aprovado(m)
                      and not any("decisao" in e["categorias"] for e in p["eventos"])):
                    r["decisoes"].append({"numero": p["numero"], "data": None, "texto": f"resultado: {m['depois']}"})
                elif m["campo"] in CAMPOS_DE_VALOR:
                    r["valores"].append({"numero": p["numero"], "campo": m["campo"], "antes": m["antes"], "depois": m["depois"],
                                         "origem": m["origem"]})
            for ev in p["eventos"]:
                if "decisao" in ev["categorias"]:
                    r["decisoes"].append({"numero": p["numero"], "data": ev["data"], "texto": ev["texto"]})
                if "audiencia_ou_prazo" in ev["categorias"]:
                    r["audiencias_e_prazos"].append({"numero": p["numero"], "data": ev["data"], "texto": ev["destaque"]})
        r["totais"] = {"antes": _totais_de(antes, cliente), "depois": _totais_de(depois, cliente)}
        r["texto"] = _texto_do_cliente(cliente, r, antes["data_base"], depois["data_base"], depois, max_itens)
        por_cliente[cliente] = r

    resultado = {"data_antes": antes["data_base"], "data_depois": depois["data_base"],
                 "totais": {"antes": _totais_de(antes), "depois": _totais_de(depois)},
                 "por_processo": por_processo, "por_cliente": por_cliente, "avisos": avisos}
    resultado["texto"] = _texto_geral(resultado, max_itens)
    return resultado


def _totais_de(instantaneo, cliente=None):
    todos = [p for p in instantaneo["processos"].values() if cliente is None or p["cliente"] == cliente]
    return {"processos": len(todos), "ativos": sum(p["ativo"] for p in todos), "encerrados": sum(not p["ativo"] for p in todos)}


def _lista(itens, max_itens):
    visiveis = itens[:max_itens]
    extra = f" e mais {len(itens) - max_itens}" if len(itens) > max_itens else ""
    return visiveis, extra


def _texto_do_processo(item):
    """Uma linha por processo, para a visão por processo (sem promessa)."""
    tipo = item["tipo"]
    if tipo == "removido":
        return f"{item['rotulo']}: saiu da carteira neste período."
    if tipo == "novo":
        return f"{item['rotulo']}: incluído na carteira" + (" (já encerrado)." if item.get("encerrado_ao_entrar") else ".")
    partes = []
    for m in item["mudancas"]:
        if _so_aprovado(m):
            partes.append(f"{m['rotulo'].lower()}: {_mostrar(m['campo'], m['antes'])} para {_mostrar(m['campo'], m['depois'])}")
    partes += [f"{ficha.data_br(e['data'])} {e['texto']}".strip() for e in item["eventos"]]
    prefixo = {"encerrado": "encerrado neste período", "reativado": "voltou a tramitar"}.get(tipo)
    if prefixo:
        partes.insert(0, prefixo)
    if not partes:
        return f"{item['rotulo']}: sem alterações."
    return f"{item['rotulo']}: " + "; ".join(partes) + "."


def _periodo(antes, depois):
    if antes and depois:
        return f"entre {ficha.data_br(antes)} e {ficha.data_br(depois)}"
    return f"até {ficha.data_br(depois)}" if depois else "no período"


def _texto_do_cliente(cliente, r, antes, depois, instantaneo_depois, max_itens):
    """Texto de uma página para e-mail ao cliente. Só eventos aprovados e campos não apenas sugeridos."""
    rotulo = lambda n: instantaneo_depois["processos"].get(n, {}).get("rotulo", n)
    linhas = [f"Assunto: Andamento dos processos de {cliente}" + (f" ({ficha.data_br(depois)})" if depois else ""), "",
              "Prezados,", "",
              f"Segue o resumo das novidades dos processos de {cliente} {_periodo(antes, depois)}.", ""]
    t = r["totais"]["depois"]
    linhas.append(f"Panorama: {t['processos']} processo(s) acompanhado(s), {t['ativos']} em andamento e {t['encerrados']} encerrado(s).")
    if not any(r[c] for c in ("novos", "encerrados", "reativados", "removidos", "mudancas_de_momento", "decisoes",
                             "audiencias_e_prazos", "valores")):
        linhas += ["", "Não houve novidades nos processos neste período."]

    def secao(titulo, itens, formato):
        if not itens:
            return
        visiveis, extra = _lista(itens, max_itens)
        linhas.extend(["", f"{titulo}:"])
        linhas.extend(f"- {formato(i)}" for i in visiveis)
        if extra:
            linhas.append(f"- {extra.strip()}.")

    secao("Novos processos", r["novos"], rotulo)
    secao("Processos encerrados", r["encerrados"], rotulo)
    secao("Processos que voltaram a tramitar", r["reativados"], rotulo)
    secao("Processos que saíram do acompanhamento", r["removidos"], lambda n: n)
    secao("Mudança no momento do processo", r["mudancas_de_momento"], lambda m: f"{rotulo(m['numero'])}: de {_mostrar('momento_atual', m['antes'])} para {_mostrar('momento_atual', m['depois'])}")
    secao("Decisões", r["decisoes"], lambda d: f"{rotulo(d['numero'])}: {(ficha.data_br(d['data']) + ' ') if d['data'] else ''}{d['texto']}")
    secao("Audiências e prazos", r["audiencias_e_prazos"], lambda d: f"{rotulo(d['numero'])}: {d['texto']}")
    valores = [v for v in r["valores"] if v["campo"] in VALORES_NO_TEXTO and not (v["campo"] in ficha.CAMPOS_DE_JULGAMENTO and v["origem"] == "sugerido")]
    nomes = {"valor_causa": "valor da causa", "valor_acordo": "valor do acordo", "valor_arbitrado": "valor fixado em juízo",
             "valor_estimado": "valor estimado (estimativa, não é garantia)", "valor_execucao": "valor da execução"}
    secao("Valores", valores, lambda v: f"{rotulo(v['numero'])}: {nomes[v['campo']]} de {_mostrar(v['campo'], v['antes'])} para {_mostrar(v['campo'], v['depois'])}")
    if r["sem_mudanca"]:
        linhas += ["", f"{r['sem_mudanca']} processo(s) sem alteração no período."]
    linhas += ["", AVISO_FINAL, "", "Atenciosamente,"]
    return "\n".join(linhas) + "\n"


def _texto_geral(resultado, max_itens):
    t0, t1 = resultado["totais"]["antes"], resultado["totais"]["depois"]
    tipos = Counter(p["tipo"] for p in resultado["por_processo"])
    linhas = [f"O que mudou {_periodo(resultado['data_antes'], resultado['data_depois'])}:",
              f"Processos: {t0['processos']} para {t1['processos']} (ativos {t0['ativos']} para {t1['ativos']}; encerrados {t0['encerrados']} para {t1['encerrados']}).",
              f"Novos: {tipos['novo']}; encerrados no período: {tipos['encerrado']}; reativados: {tipos['reativado']}; "
              f"removidos: {tipos['removido']}; com alterações: {tipos['alterado']}; sem mudança: {tipos['sem_mudanca']}."]
    for cliente, r in resultado["por_cliente"].items():
        linhas.append(f"- {cliente}: {len(r['novos'])} novo(s), {len(r['encerrados'])} encerrado(s), "
                      f"{len(r['mudancas_de_momento'])} mudança(s) de fase, {len(r['decisoes'])} decisão(ões), "
                      f"{len(r['audiencias_e_prazos'])} audiência(s)/prazo(s).")
    return "\n".join(linhas) + "\n"
