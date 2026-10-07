"""Kit de pedidos das petições iniciais (Fase 2, WS-16).

O programa NÃO lê a inicial sozinho: prepara o trabalho para uma IA de maior capacidade (o Claude no
navegador, por exemplo) e RECEBE o resultado, conferindo tudo antes de gravar.

    1. pacote(projeto)            processos com inicial localizada e ainda sem pedidos extraídos
       exportar_pacote(...)       pasta (ou .zip, pacote_zip) com os PDFs e o prompt.md pronto para colar
    2. prompt_pronto()            prompt versionado (modelos/pedidos/prompt.md) com o vocabulário de matérias
                                  atual, o esquema e o exemplo embutidos; a versão vem do cabeçalho do arquivo
    3. validar(texto_colado)      confere o que a IA devolveu: JSON, esquema, matéria no vocabulário, soma dos
                                  pedidos x valor da causa, processo desconhecido/duplicado, valores numéricos
    4. gravar(projeto, dados)     grava data/pedidos.json (por número de processo) e, só se a pessoa pedir na
                                  tela, preenche a ficha (origem "humano", só campos vazios, salvo `sobrescrever`)
    5. linhas_para_planilha / exportar_xlsx   as abas Cadastro, Pedidos, Resumo e Parâmetros por matéria

O prompt está claramente marcado como NÃO VALIDADO com petições reais: foi escrito e testado só com dados
fictícios; a qualidade se confirma no piloto, com as petições reais e a IA que o escritório escolher.

`projeto` aceita: None (relatório ativo do painel), a pasta do projeto (Path) ou o slug (texto).

Formato de data/pedidos.json (um arquivo por relatório):

    {"versao": 1, "atualizado_em": "2026-10-07T10:00:00",
     "processos": {"<numero CNJ>": {"cadastro": {...}, "pedidos": [...], "achados": [...], "resumo": {...},
                                    "recebido_em": "...", "prompt_versao": "1.0.0", "conferido_em": "..."}}}

Decisões de leitura do resultado (documentadas porque o esquema não as impõe):
  - `ok` de validar() só é verdadeiro sem nenhum erro; mas `dados` traz os processos SEM erro (quem tem erro
    fica de fora e é listado), para uma resposta com 4 processos bons e 1 ruim não perder os 4. Erro global
    (JSON ilegível, esquema inválido na raiz) deixa `dados` = None.
  - Vira ERRO (o processo não é aceito): número inválido/desconhecido/vinculado/duplicado, valor que não é
    número, pedido "atribuído" sem valor, valor negativo, processo sem nenhum pedido, estrutura fora do esquema.
    Vira AVISO: matéria fora do vocabulário (entra como "Outros", com sugestões), soma diferente do valor da
    causa, situação do valor incoerente, cadastro incompleto, processo já extraído (será substituído).
  - Soma x valor da causa: entram os pedidos com `entra_nos_totais` e valor; os "encargos embutidos na causa"
    compõem o valor da causa e são somados à parte. Diferença = valor da causa - soma - encargos; acima da
    tolerância (padrão R$ 1,00) vira aviso com os valores. Se o reclamante declarou um critério que não é a
    soma (valor arbitrado, alçada, simbólico), a divergência é só informativa.
  - Matéria fora do vocabulário NUNCA é adivinhada: vira "Outros", guarda `materia_original` e lista as
    mais parecidas em `candidatos` (difflib). Sinônimo conhecido (taxonomia.normalizar) é normalizado.

Sem dependência nova: o JSON Schema é conferido por um verificador mínimo daqui (tipos, obrigatórios,
enum, padrão, mínimos, $ref local), igual ao `jsonschema` nos casos do esquema (teste de equivalência
roda quando a biblioteca existir). Nada de rede.
"""
import difflib
import json
import re
import shutil
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path

import carteira as cart
import comum
import ficha as fch
import taxonomia

PASTA_MODELO = Path(__file__).resolve().parent / "modelos" / "pedidos"
SITUACOES_VALOR = ("atribuído", "sem valor atribuído", "fora do valor da causa", "encargos embutidos na causa")
_SINONIMOS_SITUACAO = {"sem valor": "sem valor atribuído", "valor nao atribuido": "sem valor atribuído",
                       "nao atribuido": "sem valor atribuído", "encargos embutidos": "encargos embutidos na causa",
                       "fora da causa": "fora do valor da causa"}
TOLERANCIA_PADRAO = Decimal("1.00")
LIMITE_TEXTO = 5_000_000            # caracteres colados; acima disso, quase certamente não é a resposta da IA
CADASTRO_OPCIONAL = ("funcao", "categoria_funcao", "municipio", "uf", "vara", "tribunal", "data_ajuizamento",
                     "criterio_valor_causa")
_CRITERIO_NAO_SOMA = ("arbitr", "alcada", "simbol", "estimativ", "nao declar", "sem criterio", "valor fixo")

# Aba de cadastro/pedidos/resumo/parâmetros das planilhas de pedidos (rótulos exatamente como no modelo B).
COLUNAS = {
    "cadastro": ["Processo", "Reclamante", "Função do reclamante", "Categoria da função", "Empresa do grupo (principal)",
                 "Outras empresas do grupo no polo passivo", "Terceiros no polo passivo", "Município", "UF", "Vara",
                 "Tribunal", "Data do ajuizamento", "Situação", "Fase", "Resultado", "Valor da causa",
                 "Condenação arbitrada", "Valor do acordo", "Natureza do acordo", "Probabilidade",
                 "Advogado(a) do reclamante", "Tipo de ação", "Entra nos totais?", "Motivo da exclusão",
                 "Processo relacionado", "Causa geradora"],
    "pedidos": ["Processo", "Tribunal", "Reclamante", "Reclamada(s)", "Matéria", "Pedido (como formulado na inicial)",
                "Valor atribuído", "Valor da causa", "% do valor da causa", "Situação do valor", "Pág. PDF",
                "Entra nos totais?"],
    "resumo": ["Processo", "Valor da causa", "Soma dos pedidos quantificados", "Diferença",
               "Critério do valor da causa", "Nº de pedidos", "Pedidos sem valor", "Matéria de maior peso",
               "Observações / achados", "Fonte dos valores"],
    "parametros": ["Matéria", "Tema", "Classe", "Conta nos rankings", "Pode ser causa geradora"],
}
ABAS_XLSX = {"cadastro": "Cadastro", "pedidos": "Pedidos", "resumo": "Resumo", "parametros": "Parâmetros por matéria"}
FONTE_DOS_VALORES = "Petição inicial (valores atribuídos pelo reclamante), lida por IA e conferida no programa"

# Cadastro da inicial -> campo da ficha (só estes vão para a ficha, e só quando a pessoa pede na tela).
CADASTRO_PARA_FICHA = {"reclamante": "autores", "municipio": "municipio", "uf": "uf", "vara": "vara",
                       "data_ajuizamento": "data_ajuizamento", "valor_causa": "valor_causa",
                       "terceirizado": "terceirizado"}

# Ponto de extensão do envio direto pelo provedor externo (WS-18). Enquanto for None, a tela mostra
# "indisponível". Quando houver provedor cadastrado e consentido, quem integra atribui aqui uma função
# `(projeto, numeros) -> texto` que devolve a resposta da IA (o mesmo texto que a pessoa colaria).
PROVEDOR = None
MENSAGEM_INDISPONIVEL = ("Envio direto pelo provedor indisponível: nenhum provedor externo cadastrado e "
                         "consentido neste relatório. Use o pacote e cole o resultado abaixo.")


# ---------------------------------------------------------------- modelos versionados

def esquema():
    return json.loads((PASTA_MODELO / "esquema.json").read_text(encoding="utf-8"))


def exemplo():
    return json.loads((PASTA_MODELO / "exemplo.json").read_text(encoding="utf-8"))


def _prompt_bruto():
    return (PASTA_MODELO / "prompt.md").read_text(encoding="utf-8")


def prompt_versao():
    """Versão do prompt, lida do cabeçalho de prompt.md (`versao: X.Y.Z`)."""
    m = re.search(r"versao:\s*([0-9][0-9A-Za-z.\-]*)", _prompt_bruto().splitlines()[0])
    return m[1] if m else "desconhecida"


def prompt_validado():
    """False enquanto o cabeçalho disser que o prompt não foi validado com petições reais."""
    return "NÃO VALIDADO" not in _prompt_bruto().splitlines()[0].upper()


def materias():
    """[(matéria, tema)] do vocabulário atual do relatório (taxonomia.MATERIA)."""
    return [(nome, dados[0]) for nome, dados in taxonomia.MATERIA.items()]


def parametros_por_materia():
    """Linhas da aba "Parâmetros por matéria": tema, classe e se conta nos rankings vêm da taxonomia;
    "pode ser causa geradora" não existe na taxonomia, fica vazio para o escritório definir."""
    return [[nome, tema, classe, "Sim" if conta else "Não", None]
            for nome, (tema, classe, conta) in taxonomia.MATERIA.items()]


def prompt_pronto():
    """prompt.md pronto para colar: sem o cabeçalho de controle, com versão, vocabulário de matérias, esquema
    e exemplo embutidos."""
    linhas = _prompt_bruto().splitlines()
    corpo = "\n".join(linhas[1:]).lstrip("\n")
    lista = "\n".join(f"- {nome}  (tema: {tema})" for nome, tema in materias())
    return (corpo.replace("{{VERSAO}}", prompt_versao())
            .replace("{{MATERIAS}}", lista)
            .replace("{{ESQUEMA}}", json.dumps(esquema(), ensure_ascii=False, indent=1))
            .replace("{{EXEMPLO}}", json.dumps(exemplo(), ensure_ascii=False, indent=1)))


# ---------------------------------------------------------------- locais do relatório

def _locais(projeto=None):
    """Onde ficam os dados do relatório: data/, carteira.json, documentos/ e perfil.json."""
    if isinstance(projeto, dict) and "pasta" in projeto:
        projeto = projeto["pasta"]
    if projeto is None:
        return {"data": Path(comum.DATA), "carteira": Path(comum.CARTEIRA_FILE), "docs": Path(comum.DOCS_DIR)}
    pasta = Path(projeto)
    if isinstance(projeto, str) and not pasta.is_dir():
        pasta = Path(comum.PROJETOS_DIR) / projeto
    return {"data": pasta / "data", "carteira": pasta / "carteira.json", "docs": pasta / "data" / "documentos"}


def _fichas(projeto=None):
    """Todas as fichas do relatório (inclusive as encerradas: os pedidos também valem para elas)."""
    return [fch.de_carteira_v1(p) for p in comum.load_json(_locais(projeto)["carteira"], [])]


def arquivo_de_pedidos(projeto=None):
    return _locais(projeto)["data"] / "pedidos.json"


def carregar(projeto=None):
    """Conteúdo de data/pedidos.json (ou o esqueleto vazio)."""
    dados = comum.load_json(arquivo_de_pedidos(projeto), {})
    dados.setdefault("versao", 1)
    dados.setdefault("processos", {})
    return dados


# ---------------------------------------------------------------- pacote por processo

def _so_digitos(texto):
    return re.sub(r"\D", "", str(texto))


def localizar_inicial(numero, projeto=None):
    """PDF da petição inicial do processo, ou None. Ordem: pasta data/iniciais/ (onde a pessoa pode colocar o
    PDF à mão, com o número no nome), documento coletado marcado como "Petição Inicial" e, por último, um PDF
    com "inicial" no nome dentro da pasta de documentos do processo."""
    loc = _locais(projeto)
    digitos = _so_digitos(numero)
    manual = loc["data"] / "iniciais"
    if manual.is_dir():
        for arq in sorted(manual.glob("*.pdf")):
            if digitos and digitos in _so_digitos(arq.name):
                return arq
    candidatos = []
    for ev in comum.load_json(loc["data"] / "eventos.json", []):
        if ev.get("numero") != numero or not ev.get("arquivo"):
            continue
        arq = Path(ev["arquivo"])
        tipo = comum.normalizar(f"{ev.get('tipo') or ''} {ev.get('descricao') or ''}")
        if arq.suffix.lower() == ".pdf" and arq.is_file() and "peticao inicial" in tipo:
            exato = comum.normalizar(ev.get("tipo") or "") == "peticao inicial"
            candidatos.append((0 if exato else 1, ev.get("data") or "", arq))
    if candidatos:
        return sorted(candidatos, key=lambda c: (c[0], str(c[1])))[0][2]
    if loc["docs"].is_dir():
        for arq in sorted(loc["docs"].glob(f"*/{comum.slug(numero)}/*.pdf")):
            if "inicial" in comum.normalizar(arq.name):
                return arq
    return None


def situacao(projeto=None):
    """Um registro por processo da carteira: {numero, cliente, pdf_inicial, ja_extraido, extraido_em, n_pedidos}.
    É o que a tela mostra (com e sem pedidos, com e sem inicial)."""
    extraidos = carregar(projeto)["processos"]
    linhas = []
    for f in _fichas(projeto):
        achado = localizar_inicial(f["numero"], projeto)
        reg = extraidos.get(f["numero"])
        linhas.append({"numero": f["numero"], "cliente": fch.obter(f, "cliente", ""),
                       "pdf_inicial": str(achado) if achado else None, "ja_extraido": bool(reg),
                       "extraido_em": reg.get("recebido_em") if reg else None,
                       "n_pedidos": len(reg["pedidos"]) if reg else 0})
    return linhas


def pacote(projeto=None, incluir_extraidos=False):
    """[{numero, pdf_inicial, ja_extraido}]: processos com inicial localizada e, por padrão, ainda sem
    pedidos extraídos (`incluir_extraidos=True` traz todos os que têm inicial, para refazer)."""
    return [{"numero": s["numero"], "pdf_inicial": s["pdf_inicial"], "ja_extraido": s["ja_extraido"]}
            for s in situacao(projeto) if s["pdf_inicial"] and (incluir_extraidos or not s["ja_extraido"])]


def _itens_do_pacote(projeto, numeros, por_lote, incluir_extraidos):
    escolhidos = pacote(projeto, incluir_extraidos=incluir_extraidos)
    if numeros is not None:
        pedidos = set(numeros)
        escolhidos = [c for c in escolhidos if c["numero"] in pedidos]
    faltando = [n for n in (numeros or []) if n not in {c["numero"] for c in escolhidos}]
    itens = []
    for i, c in enumerate(escolhidos):
        lote = f"lote-{i // por_lote + 1:02d}/" if por_lote and por_lote > 0 else ""
        itens.append((f"{lote}{c['numero']}.pdf", Path(c["pdf_inicial"])))
    lotes = (len(escolhidos) + por_lote - 1) // por_lote if por_lote and por_lote > 0 and escolhidos else (1 if escolhidos else 0)
    return itens, faltando, lotes


def _leia_me(itens, lotes):
    linhas = ["Pacote de petições iniciais para leitura por IA.", "",
              "1. Abra a IA que o escritório autorizou e anexe os PDFs (um lote por vez, se houver pastas lote-NN).",
              "2. Cole o conteúdo de prompt.md na conversa e envie.",
              "3. Copie a resposta inteira (só o JSON) e cole na tela Pedidos do programa.", "",
              "ATENÇÃO: anexar estes PDFs numa IA na internet envia o conteúdo para fora do seu computador.",
              f"Prompt versão {prompt_versao()}" + ("" if prompt_validado() else " (NÃO VALIDADO com petições reais)."), "",
              f"Arquivos ({len(itens)}, em {lotes} lote(s)):"]
    return "\n".join(linhas + [f"- {nome}" for nome, _ in itens]) + "\n"


def exportar_pacote(projeto, destino, numeros=None, por_lote=0, incluir_extraidos=False):
    """Copia os PDFs (nomeados <número>.pdf, em subpastas lote-NN se `por_lote`) e grava prompt.md e LEIA-ME.txt
    em `destino`. Devolve {destino, arquivos, lotes, sem_inicial}; `sem_inicial` são números pedidos que não
    têm inicial localizada (ou que já foram extraídos e `incluir_extraidos` é falso)."""
    destino = Path(destino)
    itens, faltando, lotes = _itens_do_pacote(projeto, numeros, por_lote, incluir_extraidos)
    destino.mkdir(parents=True, exist_ok=True)
    copiados = []
    for nome, origem in itens:
        alvo = destino / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origem, alvo)
        copiados.append(alvo)
    (destino / "prompt.md").write_text(prompt_pronto(), encoding="utf-8")
    (destino / "LEIA-ME.txt").write_text(_leia_me(itens, lotes), encoding="utf-8")
    return {"destino": destino, "arquivos": copiados, "lotes": lotes, "sem_inicial": faltando}


def pacote_zip(projeto=None, numeros=None, por_lote=0, incluir_extraidos=False):
    """O mesmo pacote como .zip, num arquivo temporário já aberto e posicionado no início (apaga ao fechar)."""
    itens, _, lotes = _itens_do_pacote(projeto, numeros, por_lote, incluir_extraidos)
    saida = tempfile.TemporaryFile()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, origem in itens:
            z.write(origem, nome)
        z.writestr("prompt.md", prompt_pronto())
        z.writestr("LEIA-ME.txt", _leia_me(itens, lotes))
    saida.seek(0)
    return saida


# ---------------------------------------------------------------- verificador mínimo de JSON Schema

_TIPOS = {"string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
          "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
          "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict), "null": lambda v: v is None}
_NOMES_DOS_TIPOS = {"string": "texto", "boolean": "verdadeiro/falso (true ou false)", "integer": "número inteiro",
                    "number": "número", "array": "lista", "object": "objeto", "null": "vazio (null)"}


def _tipo_json(valor):
    for nome in ("null", "boolean", "string", "array", "object", "integer", "number"):
        if _TIPOS[nome](valor):
            return _NOMES_DOS_TIPOS[nome]
    return type(valor).__name__


def verificar_esquema(valor, sch, raiz=None, caminho=""):
    """Confere `valor` contra o JSON Schema e devolve [(caminho, mensagem)]; vazio = conforme. Cobre o que o
    esquema do kit usa: type (um ou vários), required, properties, items, enum, pattern, minimum, minItems,
    minLength e $ref local ("#/$defs/...")."""
    raiz = raiz or sch
    if "$ref" in sch:
        alvo = raiz
        for parte in sch["$ref"].lstrip("#/").split("/"):
            alvo = alvo[parte]
        return verificar_esquema(valor, alvo, raiz, caminho)
    erros = []
    tipos = sch.get("type")
    if tipos is not None:
        tipos = [tipos] if isinstance(tipos, str) else tipos
        if not any(_TIPOS[t](valor) for t in tipos):
            esperado = " ou ".join(_NOMES_DOS_TIPOS[t] for t in tipos)
            return [(caminho, f"deveria ser {esperado}, mas veio {_tipo_json(valor)}")]
    if "enum" in sch and valor not in sch["enum"]:
        permitidos = ", ".join(repr(x) if x is not None else "null" for x in sch["enum"])
        return [(caminho, f"valor fora da lista permitida ({permitidos})")]
    if isinstance(valor, str):
        if "pattern" in sch and not re.search(sch["pattern"], valor):
            erros.append((caminho, f"formato inesperado: {valor!r}"))
        if len(valor.strip()) < sch.get("minLength", 0):
            erros.append((caminho, "texto vazio"))
    if isinstance(valor, (int, float)) and not isinstance(valor, bool) and "minimum" in sch and valor < sch["minimum"]:
        erros.append((caminho, f"deveria ser no mínimo {sch['minimum']}"))
    if isinstance(valor, dict):
        for nome in sch.get("required", []):
            if nome not in valor:
                erros.append((f"{caminho}.{nome}" if caminho else nome, "campo obrigatório ausente"))
        for nome, sub in sch.get("properties", {}).items():
            if nome in valor:
                erros += verificar_esquema(valor[nome], sub, raiz, f"{caminho}.{nome}" if caminho else nome)
    if isinstance(valor, list):
        if len(valor) < sch.get("minItems", 0):
            erros.append((caminho, f"lista vazia (precisa de pelo menos {sch['minItems']})"))
        if "items" in sch:
            for i, item in enumerate(valor):
                erros += verificar_esquema(item, sch["items"], raiz, f"{caminho}[{i}]")
    return erros


# ---------------------------------------------------------------- leitura do texto colado

def aviso(nivel, codigo, onde, mensagem, candidatos=None):
    """Aviso estruturado (CONTRATOS §4): nivel info|atencao|erro, codigo estável."""
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": candidatos or []}


def extrair_json(texto):
    """(objeto, avisos). Aceita o JSON puro; se a IA o embrulhou em ```json ... ``` ou escreveu texto antes e
    depois, acha o JSON e avisa. Sem JSON legível, objeto None e um erro `json_invalido`."""
    bruto = (texto or "").strip().lstrip("﻿")
    if not bruto:
        return None, [aviso("erro", "json_vazio", "texto colado", "Nada foi colado. Cole a resposta inteira da IA.")]
    try:
        return json.loads(bruto), []
    except json.JSONDecodeError as e:
        primeiro = e
    decodificador = json.JSONDecoder()
    trechos = [m[1] for m in re.finditer(r"```(?:json)?\s*(.*?)```", bruto, re.S | re.I)] + [bruto]
    for trecho in trechos:
        for m in list(re.finditer(r"[{\[]", trecho))[:30]:
            try:
                obj, _ = decodificador.raw_decode(trecho[m.start():])
            except json.JSONDecodeError:
                continue
            # Só vale o que parece a resposta inteira: o objeto com "processos" ou a lista de processos. Um
            # processo solto achado no meio de um texto cortado seria perda silenciosa dos demais.
            inteira = ((isinstance(obj, dict) and "processos" in obj)
                       or (isinstance(obj, list) and obj and all(isinstance(x, dict) and "numero" in x for x in obj)))
            if inteira:
                return obj, [aviso("info", "resposta_com_texto_extra", "texto colado",
                                   "A resposta trazia texto ou formatação além do JSON; só o JSON foi usado. "
                                   "Da próxima vez, peça à IA para responder somente com o JSON.")]
    abertos = bruto.count("{") + bruto.count("[") - bruto.count("}") - bruto.count("]")
    cortado = primeiro.pos >= len(bruto) - 3 or abertos > 0 or not bruto.endswith(("}", "]", "```"))
    dica = (" A resposta parece ter sido cortada no fim: peça à IA para continuar ou envie menos processos por vez."
            if cortado else " Peça à IA para responder somente com o JSON, sem texto antes ou depois.")
    return None, [aviso("erro", "json_invalido", f"linha {primeiro.lineno}, coluna {primeiro.colno}",
                        f"O texto colado não é um JSON válido ({primeiro.msg}).{dica}")]


# ---------------------------------------------------------------- normalizações de campos

def _valor_monetario(bruto):
    """(texto decimal '1234.56' | None, ok). ok=False quando veio algo que não é número."""
    if bruto is None or bruto == "":
        return None, True
    if isinstance(bruto, bool):
        return None, False
    if isinstance(bruto, str) and not re.fullmatch(r"(?i)\s*(r\$)?\s*-?[\d.,\s]+\s*", bruto):
        return None, False  # "a apurar", "entre 1000 e 2000"...: nunca extrair um número de dentro de frase
    parsed = fch.parse_dinheiro(bruto)
    return parsed, parsed is not None


def _texto(valor):
    return re.sub(r"\s+", " ", valor).strip() if isinstance(valor, str) and valor.strip() else None


def _lista(valor):
    return [t for t in (_texto(x) for x in (valor or [])) if t]


def _situacao_valor(texto):
    chave = comum.normalizar(texto or "").strip(" .")
    for canonica in SITUACOES_VALOR:
        if comum.normalizar(canonica) == chave:
            return canonica, False
    if chave in _SINONIMOS_SITUACAO:
        return _SINONIMOS_SITUACAO[chave], True
    return None, False


def _materia(texto):
    """(canônica | None, normalizada_por_sinonimo, candidatos)."""
    t = texto.strip()
    if t in taxonomia.MATERIA:
        return t, False, []
    canonica = taxonomia.normalizar("materia", t)
    if canonica:
        return canonica, True, []
    chaves = {comum.normalizar(n): n for n in taxonomia.MATERIA if n != "Outros"}
    perto = difflib.get_close_matches(comum.normalizar(t), list(chaves), n=3, cutoff=0.4)
    return None, False, [chaves[c] for c in perto]


def _br(valor):
    return fch.dinheiro_br(valor)


def resumo_do_processo(cadastro, pedidos):
    """Linha da aba Resumo: valor da causa, soma dos quantificados, encargos embutidos, diferença
    (causa - soma - encargos), critério, nº de pedidos, pedidos sem valor e matéria de maior peso."""
    D = Decimal
    vc = fch.dinheiro(cadastro.get("valor_causa"))
    soma = sum((D(p["valor_atribuido"]) for p in pedidos if p["entra_nos_totais"] and p["valor_atribuido"] is not None), D(0))
    encargos = sum((D(p["valor_atribuido"]) for p in pedidos
                    if p["situacao_valor"] == "encargos embutidos na causa" and p["valor_atribuido"] is not None), D(0))
    por_materia = {}
    for p in pedidos:
        if p["entra_nos_totais"] and p["valor_atribuido"] is not None:
            por_materia[p["materia"]] = por_materia.get(p["materia"], D(0)) + D(p["valor_atribuido"])
    maior = max(por_materia, key=por_materia.get) if por_materia else None
    return {"valor_causa": f"{vc:.2f}" if vc is not None else None, "soma_pedidos": f"{soma:.2f}",
            "encargos_embutidos": f"{encargos:.2f}",
            "diferenca": f"{vc - soma - encargos:.2f}" if vc is not None else None,
            "criterio_valor_causa": cadastro.get("criterio_valor_causa"), "n_pedidos": len(pedidos),
            "pedidos_sem_valor": sum(1 for p in pedidos if p["valor_atribuido"] is None),
            "materia_maior_peso": maior}


# ---------------------------------------------------------------- validação

def validar(texto_colado, projeto=None, *, carteira=None, tolerancia=TOLERANCIA_PADRAO):
    """Confere a resposta colada e devolve {"ok", "erros", "avisos", "dados", "recusados"}.

    `erros`/`avisos`: listas de Aviso (nivel "erro" nos erros; "atencao"/"info" nos avisos). `dados`:
    {"versao_prompt", "processos": [...]} só com os processos sem erro (None se o erro for global) e já
    normalizados (número com máscara, datas ISO, dinheiro "1234.56", matéria canônica, resumo calculado).
    `recusados`: [{"posicao", "numero"}] dos processos que ficaram de fora. `carteira`: números conhecidos
    (padrão: as fichas do relatório); `tolerancia`: diferença aceita entre a soma e o valor da causa."""
    tolerancia = Decimal(str(tolerancia))
    erros, avisos = [], []
    if len(texto_colado or "") > LIMITE_TEXTO:
        return _resultado([aviso("erro", "texto_grande_demais", "texto colado",
                                 "O texto colado é grande demais para ser a resposta da IA. Cole só o JSON.")], [], None, [])
    bruto, extras = extrair_json(texto_colado)
    avisos += [a for a in extras if a["nivel"] != "erro"]
    erros += [a for a in extras if a["nivel"] == "erro"]
    if bruto is None:
        return _resultado(erros, avisos, None, [])
    if isinstance(bruto, list):
        avisos.append(aviso("info", "lista_sem_raiz", "texto colado",
                            "A resposta veio como lista de processos, sem o objeto \"processos\"; foi aceita assim."))
        bruto = {"processos": bruto}
    elif isinstance(bruto, dict) and "processos" not in bruto and "numero" in bruto:
        avisos.append(aviso("info", "processo_unico_sem_raiz", "texto colado",
                            "A resposta trouxe um processo solto, sem o objeto \"processos\"; foi aceita assim."))
        bruto = {"processos": [bruto]}
    sch = esquema()
    if not isinstance(bruto, dict) or not isinstance(bruto.get("processos"), list) or not bruto["processos"]:
        for caminho, msg in verificar_esquema(bruto, sch) or [("processos", "lista de processos ausente ou vazia")]:
            erros.append(aviso("erro", "esquema_invalido", caminho or "raiz", f"Resposta fora do formato esperado: {msg}."))
        return _resultado(erros, avisos, None, [])
    versao = bruto.get("versao_prompt")
    if isinstance(versao, str) and versao != prompt_versao():
        avisos.append(aviso("info", "versao_do_prompt_diferente", "versao_prompt",
                            f"A resposta diz ter sido gerada pelo prompt {versao}; a versão atual é {prompt_versao()}."))
    for k, p in enumerate(bruto["processos"]):
        _pre_normalizar(p, avisos, k)
    conhecidos, vinculos = _conhecidos(projeto, carteira)
    extraidos = carregar(projeto)["processos"]
    # números de todos os processos (para achar duplicados antes de qualquer outra coisa)
    numeros = []
    for p in bruto["processos"]:
        bruto_num = p.get("numero") if isinstance(p, dict) else None
        validos, _ = cart.numeros_no_texto(str(bruto_num or ""))
        numeros.append(validos[0][0] if validos else None)
    aceitos, recusados = [], []
    materias_vistas = set()
    for k, p in enumerate(bruto["processos"]):
        pos = k + 1
        rotulo = f"processo {pos}" + (f" ({numeros[k]})" if numeros[k] else "")
        erros_p, avisos_p = [], []
        falhas = verificar_esquema(p, sch["$defs"]["processo"], sch, "")
        for caminho, msg in falhas:
            erros_p.append(aviso("erro", "esquema_invalido", f"{rotulo} · {caminho or 'processo'}",
                                 f"{caminho or 'processo'}: {msg}."))
        if not falhas:
            erros_p += _erros_de_numero(p["numero"], numeros[k], numeros, k, rotulo, conhecidos, vinculos)
            dado = _normalizar_processo(p, numeros[k], rotulo, erros_p, avisos_p, materias_vistas, tolerancia)
            if numeros[k] in extraidos and not erros_p:
                avisos_p.append(aviso("atencao", "processo_ja_extraido", rotulo,
                                      f"Este processo já tinha pedidos gravados em "
                                      f"{fch.data_br(extraidos[numeros[k]].get('recebido_em'))}; ao gravar, serão substituídos."))
        avisos += avisos_p
        erros += erros_p
        if erros_p:
            recusados.append({"posicao": pos, "numero": numeros[k] or (str(p.get("numero")) if isinstance(p, dict) else "")})
        else:
            aceitos.append(dado)
    dados = {"versao_prompt": versao if isinstance(versao, str) else None, "processos": aceitos}
    return _resultado(erros, avisos, dados, recusados)


def _resultado(erros, avisos, dados, recusados):
    return {"ok": not erros, "erros": erros, "avisos": avisos, "dados": dados, "recusados": recusados}


def _pre_normalizar(p, avisos, k):
    """Ajustes só de forma, antes do esquema: situação do valor com acento/caixa/sinônimo diferente."""
    if not isinstance(p, dict) or not isinstance(p.get("pedidos"), list):
        return
    for i, ped in enumerate(p["pedidos"]):
        if isinstance(ped, dict) and isinstance(ped.get("situacao_valor"), str):
            canonica, por_sinonimo = _situacao_valor(ped["situacao_valor"])
            if canonica:
                if por_sinonimo:
                    avisos.append(aviso("info", "situacao_valor_normalizada", f"processo {k + 1} · pedido {i + 1}",
                                        f"A situação do valor \"{ped['situacao_valor']}\" foi entendida como \"{canonica}\"."))
                ped["situacao_valor"] = canonica


def _conhecidos(projeto, carteira):
    """({numero conhecido}, {número vinculado: número principal})."""
    if carteira is not None:
        return {n for n in carteira}, {}
    conhecidos, vinculos = set(), {}
    for f in _fichas(projeto):
        conhecidos.add(f["numero"])
        for v in f.get("vinculados", []):
            vinculos[v["numero"]] = f["numero"]
    return conhecidos, vinculos


def _erros_de_numero(bruto, normal, todos, k, rotulo, conhecidos, vinculos):
    if normal is None:
        _, invalidos = cart.numeros_no_texto(str(bruto))
        motivo = (f"o número {invalidos[0]} tem dígito verificador errado (erro de digitação ou da IA)"
                  if invalidos else "não há número CNJ legível nele")
        return [aviso("erro", "numero_invalido", f"processo {k + 1}", f"Número do processo recusado: {motivo}. "
                                                                    f"Valor recebido: {str(bruto)[:60]!r}.")]
    if todos.count(normal) > 1:
        posicoes = ", ".join(str(i + 1) for i, n in enumerate(todos) if n == normal)
        return [aviso("erro", "processo_duplicado", rotulo, f"O processo aparece mais de uma vez no resultado "
                                                          f"(posições {posicoes}); nenhuma das cópias foi aceita. "
                                                          f"Deixe só uma e confira.")]
    if normal in vinculos:
        return [aviso("erro", "processo_vinculado", rotulo, f"Este número é de um processo vinculado; os pedidos "
                                                          f"ficam no processo principal {vinculos[normal]}.",
                      [vinculos[normal]])]
    if normal not in conhecidos:
        return [aviso("erro", "processo_desconhecido", rotulo, "Este processo não está na carteira do relatório. "
                                                              "Confira se o PDF anexado era o do processo certo.")]
    return []


def _normalizar_processo(p, numero, rotulo, erros, avisos, materias_vistas, tolerancia):
    cad = p["cadastro"]
    ccad = {"reclamante": _texto(cad.get("reclamante")), "funcao": _texto(cad.get("funcao")),
            "categoria_funcao": _texto(cad.get("categoria_funcao")),
            "empresa_principal": _texto(cad.get("empresa_principal")),
            "outras_empresas": _lista(cad.get("outras_empresas")), "terceiros": _lista(cad.get("terceiros")),
            "municipio": _texto(cad.get("municipio")), "uf": cad.get("uf"), "vara": _texto(cad.get("vara")),
            "tribunal": _texto(cad.get("tribunal")), "criterio_valor_causa": _texto(cad.get("criterio_valor_causa")),
            "advogado_reclamante": _texto(cad.get("advogado_reclamante")), "tipo_acao": _texto(cad.get("tipo_acao")),
            "terceirizado": cad.get("terceirizado")}
    desconhecidos = sorted(set(cad) - set(esquema()["$defs"]["cadastro"]["properties"]))
    if desconhecidos:
        avisos.append(aviso("atencao", "campo_desconhecido", rotulo,
                            f"Campos do cadastro fora do esquema foram ignorados: {', '.join(desconhecidos)}."))
    if ccad["uf"] and ccad["uf"] not in cart.UFS:
        avisos.append(aviso("atencao", "uf_invalida", f"{rotulo} · cadastro.uf",
                            f"UF desconhecida ({ccad['uf']!r}); o campo ficou vazio."))
        ccad["uf"] = None
    data = fch.parse_data(cad["data_ajuizamento"]) if cad.get("data_ajuizamento") else None
    if cad.get("data_ajuizamento") and not data:
        avisos.append(aviso("atencao", "data_invalida", f"{rotulo} · cadastro.data_ajuizamento",
                            f"Data de ajuizamento inválida ({cad['data_ajuizamento']!r}); o campo ficou vazio."))
    ccad["data_ajuizamento"] = data
    vc, ok = _valor_monetario(cad.get("valor_causa"))
    if not ok or (vc is not None and Decimal(vc) < 0):
        erros.append(aviso("erro", "valor_nao_numerico" if not ok else "valor_negativo", f"{rotulo} · cadastro.valor_causa",
                           f"Valor da causa não é um número válido: {cad.get('valor_causa')!r}."))
    ccad["valor_causa"] = vc
    ausentes = [c for c in CADASTRO_OPCIONAL if ccad.get(c) in (None, "")]
    if ausentes:
        avisos.append(aviso("info", "cadastro_incompleto", rotulo, "Não vieram no cadastro: " + ", ".join(ausentes) + "."))
    pedidos, vistos = [], set()
    for i, ped in enumerate(p["pedidos"]):
        onde = f"{rotulo} · pedido {i + 1}"
        valor, ok = _valor_monetario(ped["valor_atribuido"])
        if not ok:
            erros.append(aviso("erro", "valor_nao_numerico", onde,
                               f"O valor atribuído não é um número: {ped['valor_atribuido']!r}. Se a petição não "
                               f"traz valor, o campo deve ser null e a situação \"sem valor atribuído\"."))
        elif valor is not None and Decimal(valor) < 0:
            erros.append(aviso("erro", "valor_negativo", onde, f"O valor atribuído é negativo ({valor})."))
        situacao_v = ped["situacao_valor"]
        entra = ped["entra_nos_totais"]
        _coerencia(ped, valor, ok, situacao_v, entra, onde, erros, avisos)
        canonica, por_sinonimo, candidatos = _materia(ped["materia"])
        dado = {"materia": canonica, "pedido_como_formulado": _texto(ped["pedido_como_formulado"]),
                "valor_atribuido": valor, "situacao_valor": situacao_v, "pagina_pdf": ped.get("pagina_pdf"),
                "entra_nos_totais": entra}
        if canonica is None:
            dado["materia"], dado["materia_original"] = "Outros", ped["materia"].strip()
            sugestao = _texto(ped.get("materia_sugerida")) or ped["materia"].strip()
            dado["materia_sugerida"] = sugestao
            texto = f"A matéria \"{ped['materia'].strip()}\" não existe no vocabulário; foi lançada como \"Outros\"."
            if candidatos:
                texto += " Mais parecida(s): " + "; ".join(candidatos) + "."
            avisos.append(aviso("atencao", "materia_fora_do_vocabulario", onde, texto, candidatos))
        else:
            if por_sinonimo and (ped["materia"].strip(), canonica) not in materias_vistas:
                materias_vistas.add((ped["materia"].strip(), canonica))
                avisos.append(aviso("info", "materia_normalizada", onde,
                                    f"A matéria \"{ped['materia'].strip()}\" foi entendida como \"{canonica}\"."))
            if canonica == "Outros" and _texto(ped.get("materia_sugerida")):
                dado["materia_sugerida"] = _texto(ped["materia_sugerida"])
                avisos.append(aviso("info", "materia_sugerida", onde,
                                    f"Sugestão de nova matéria: \"{dado['materia_sugerida']}\" (hoje lançada em \"Outros\")."))
        chave = (dado["materia"], comum.normalizar(dado["pedido_como_formulado"] or ""))
        if chave in vistos:
            avisos.append(aviso("atencao", "pedido_duplicado", onde, "Pedido repetido (mesma matéria e mesmo texto): "
                                                                   "confira se não foi lido duas vezes."))
        vistos.add(chave)
        pedidos.append(dado)
    if not pedidos:
        erros.append(aviso("erro", "processo_sem_pedidos", rotulo,
                           "Nenhum pedido foi extraído deste processo. Se a inicial estava ilegível, refaça a leitura."))
    sem_pagina = sum(1 for d in pedidos if d["pagina_pdf"] is None)
    if sem_pagina:
        avisos.append(aviso("info", "pedido_sem_pagina", rotulo, f"{sem_pagina} pedido(s) sem a página do PDF."))
    if pedidos and not erros:
        _conferir_soma(ccad, pedidos, rotulo, avisos, tolerancia)
    achados = []
    for j, a in enumerate(p.get("achados") or []):
        achados.append({"tipo": _texto(a["tipo"]), "descricao": _texto(a["descricao"]), "impacto": _texto(a.get("impacto"))})
    dado_proc = {"numero": numero, "cadastro": ccad, "pedidos": pedidos, "achados": achados}
    if not erros:
        dado_proc["resumo"] = resumo_do_processo(ccad, pedidos)
    return dado_proc


def _coerencia(ped, valor, ok, situacao_v, entra, onde, erros, avisos):
    if not ok:
        return
    if situacao_v == "atribuído":
        if valor is None:
            erros.append(aviso("erro", "valor_ausente", onde, "Pedido com situação \"atribuído\" mas sem valor. "
                                                             "Informe o valor ou use \"sem valor atribuído\"."))
        elif Decimal(valor) == 0:
            avisos.append(aviso("atencao", "valor_zero", onde, "Pedido \"atribuído\" com valor zero: confira."))
        if not entra:
            avisos.append(aviso("info", "entra_nos_totais_incoerente", onde,
                                "Pedido com valor atribuído marcado para NÃO entrar nos totais (pedido alternativo?)."))
        return
    if situacao_v == "sem valor atribuído" and valor is not None:
        avisos.append(aviso("atencao", "situacao_valor_incoerente", onde,
                            f"Diz \"sem valor atribuído\" mas veio valor ({_br(valor)}); o valor foi mantido, confira."))
    elif situacao_v in ("fora do valor da causa", "encargos embutidos na causa") and valor is None:
        avisos.append(aviso("atencao", "situacao_valor_incoerente", onde,
                            f"Situação \"{situacao_v}\" sem valor informado: confira."))
    if entra:
        avisos.append(aviso("atencao", "entra_nos_totais_incoerente", onde,
                            f"Pedido \"{situacao_v}\" marcado para entrar nos totais: só pedidos com valor atribuído "
                            f"entram."))


def _conferir_soma(cad, pedidos, rotulo, avisos, tolerancia):
    resumo = resumo_do_processo(cad, pedidos)
    if resumo["valor_causa"] is None:
        if any(p["valor_atribuido"] is not None for p in pedidos):
            avisos.append(aviso("atencao", "valor_causa_ausente", rotulo,
                                "A petição não trouxe valor da causa; não dá para conferir com a soma dos pedidos."))
        return
    dif = Decimal(resumo["diferenca"])
    if abs(dif) <= tolerancia:
        return
    criterio = comum.normalizar(cad.get("criterio_valor_causa") or "")
    negado = bool(re.search(r"\b(sem|nao)\b[^,.;]{0,20}\bsoma\b", criterio))     # "sem soma dos pedidos"
    nao_soma = negado or (bool(criterio) and "soma" not in criterio and any(c in criterio for c in _CRITERIO_NAO_SOMA))
    encargos = (f" (mais {_br(resumo['encargos_embutidos'])} de encargos embutidos)"
                if Decimal(resumo["encargos_embutidos"]) else "")
    texto = (f"A soma dos pedidos que entram nos totais ({_br(resumo['soma_pedidos'])}){encargos} difere do valor da "
             f"causa ({_br(resumo['valor_causa'])}) em {_br(abs(dif))}"
             + (" a menos" if dif > 0 else " a mais") + ".")
    if nao_soma:
        texto += f" O reclamante declarou outro critério ({cad['criterio_valor_causa']}), então pode ser esperado."
    avisos.append(aviso("info" if nao_soma else "atencao", "soma_diverge_do_valor_da_causa", rotulo, texto))


# ---------------------------------------------------------------- gravação

def conferir_cadastro(projeto, dados):
    """Prévia do que gravar na ficha: [{numero, campo, rotulo, atual, novo, acao}], acao = preencher | divergente |
    igual. É o que a tela mostra antes de a pessoa confirmar a atualização das fichas."""
    por_numero = {f["numero"]: f for f in _fichas(projeto)}
    linhas = []
    for p in (dados or {}).get("processos", []):
        f = por_numero.get(p["numero"])
        if f is None:
            continue
        for campo_cad, campo_ficha in CADASTRO_PARA_FICHA.items():
            novo = _valor_para_ficha(p["cadastro"], campo_cad)
            if novo in (None, ""):
                continue
            atual = fch.obter(f, campo_ficha)
            acao = "preencher" if atual in (None, "") else ("igual" if _igual(campo_ficha, atual, novo) else "divergente")
            linhas.append({"numero": p["numero"], "campo": campo_ficha, "rotulo": fch.CAMPOS[campo_ficha][0],
                           "atual": atual, "novo": novo, "acao": acao})
        empresas = _valor_para_ficha(p["cadastro"], "reus")
        if empresas:
            atual = fch.obter(f, "reus")
            acao = "preencher" if atual in (None, "") else ("igual" if _igual("reus", atual, empresas) else "divergente")
            linhas.append({"numero": p["numero"], "campo": "reus", "rotulo": fch.CAMPOS["reus"][0], "atual": atual,
                           "novo": empresas, "acao": acao})
    return linhas


def _valor_para_ficha(cadastro, campo):
    if campo == "reus":
        nomes = [cadastro.get("empresa_principal"), *cadastro.get("outras_empresas", [])]
        return "; ".join(n for n in nomes if n) or None
    return cadastro.get(campo)


def _igual(campo, atual, novo):
    tipo = fch.CAMPOS[campo][2]
    if tipo == "dinheiro":
        return fch.dinheiro(atual) == fch.dinheiro(novo)
    return comum.normalizar(str(atual)) == comum.normalizar(str(novo))


def gravar(projeto, dados, *, atualizar_fichas=False, sobrescrever=False):
    """Grava os processos de `dados` (o `dados` de validar) em data/pedidos.json, substituindo os do mesmo
    número e mantendo os demais. Devolve {"gravados", "substituidos", "fichas_atualizadas", "divergencias"}.

    Com `atualizar_fichas` (a pessoa confirmou na tela), o cadastro vai para a ficha com origem "humano",
    só nos campos vazios; campo que já tem valor diferente vira "divergencia" e não é tocado, a menos que
    `sobrescrever`. Valor atribuído e matérias ficam só em pedidos.json."""
    if not isinstance(dados, dict) or not isinstance(dados.get("processos"), list):
        raise ValueError("gravar: `dados` precisa ser o resultado de pedidos.validar() (com a lista de processos)")
    agora = fch.agora()
    arquivo = carregar(projeto)
    saida = {"gravados": [], "substituidos": [], "fichas_atualizadas": [], "divergencias": []}
    for p in dados["processos"]:
        numero = p["numero"]
        if numero in arquivo["processos"]:
            saida["substituidos"].append(numero)
        arquivo["processos"][numero] = {"cadastro": p["cadastro"], "pedidos": p["pedidos"], "achados": p["achados"],
                                        "resumo": p.get("resumo") or resumo_do_processo(p["cadastro"], p["pedidos"]),
                                        "recebido_em": agora, "prompt_versao": dados.get("versao_prompt") or prompt_versao(),
                                        "conferido_em": agora}
        saida["gravados"].append(numero)
    arquivo["atualizado_em"] = agora
    comum.save_json(arquivo_de_pedidos(projeto), arquivo)
    if atualizar_fichas and saida["gravados"]:
        _atualizar_fichas(projeto, dados, sobrescrever, saida)
    return saida


def _atualizar_fichas(projeto, dados, sobrescrever, saida):
    caminho = _locais(projeto)["carteira"]
    itens = comum.load_json(caminho, [])
    previa = conferir_cadastro(projeto, dados)
    for i, item in enumerate(itens):
        mine = [l for l in previa if l["numero"] == item.get("numero")]
        if not mine:
            continue
        f = fch.de_carteira_v1(item)
        mudou = False
        for l in mine:
            if l["acao"] == "igual":
                continue
            if l["acao"] == "divergente" and not sobrescrever:
                saida["divergencias"].append({k: l[k] for k in ("numero", "campo", "atual", "novo")})
                continue
            if fch.definir(f, l["campo"], l["novo"], "humano", "petição inicial lida por IA e conferida na tela de pedidos",
                           forcar=sobrescrever):
                saida["fichas_atualizadas"].append({"numero": l["numero"], "campo": l["campo"], "antes": l["atual"],
                                                    "depois": fch.obter(f, l["campo"])})
                mudou = True
        if mudou:
            itens[i] = f
    comum.save_json(caminho, itens)


# ---------------------------------------------------------------- planilha de pedidos

def _num(texto):
    d = fch.dinheiro(texto)
    return float(d) if d is not None else None


def linhas_para_planilha(projeto=None):
    """As quatro abas da planilha de pedidos, prontas para um escritor de .xlsx:
    {aba: {"colunas": [...], "linhas": [[...]]}}. Dinheiro como número; % como fração. Colunas que dependem de
    julgamento (situação, fase, resultado, condenação, acordo, probabilidade) vêm da ficha quando houver."""
    gravados = carregar(projeto)["processos"]
    fichas = {f["numero"]: f for f in _fichas(projeto)}
    cadastro, pedidos, resumo = [], [], []
    for numero, reg in gravados.items():
        c, f = reg["cadastro"], fichas.get(numero, {})
        obter = lambda campo: fch.obter(f, campo) if f else None
        grupo = "; ".join(x for x in c.get("outras_empresas", []))
        cadastro.append([numero, c.get("reclamante"), c.get("funcao"), c.get("categoria_funcao"), c.get("empresa_principal"),
                         grupo or None, "; ".join(c.get("terceiros", [])) or None, c.get("municipio"), c.get("uf"),
                         c.get("vara"), c.get("tribunal") or f.get("tribunal"), fch.data_br(c.get("data_ajuizamento")) or None,
                         obter("situacao"), obter("fase"), obter("resultado"), _num(c.get("valor_causa")),
                         _num(obter("valor_arbitrado")), _num(obter("valor_acordo")), None, obter("probabilidade"),
                         c.get("advogado_reclamante"), c.get("tipo_acao"), None, None, None, None])
        reclamadas = "; ".join(x for x in [c.get("empresa_principal"), *c.get("outras_empresas", [])] if x)
        vc = fch.dinheiro(c.get("valor_causa"))
        for p in reg["pedidos"]:
            v = fch.dinheiro(p["valor_atribuido"])
            pedidos.append([numero, c.get("tribunal") or f.get("tribunal"), c.get("reclamante"), reclamadas or None,
                            p["materia"], p["pedido_como_formulado"], float(v) if v is not None else None,
                            float(vc) if vc is not None else None,
                            float(v / vc) if v is not None and vc else None, p["situacao_valor"], p.get("pagina_pdf"),
                            "Sim" if p["entra_nos_totais"] else "Não"])
        r = reg["resumo"]
        obs = " | ".join(f"{a['descricao']}" for a in reg.get("achados", []))
        if _num(r["encargos_embutidos"]):
            obs = (obs + " | " if obs else "") + f"Diferença já desconta {_br(r['encargos_embutidos'])} de encargos embutidos na causa."
        resumo.append([numero, _num(r["valor_causa"]), _num(r["soma_pedidos"]), _num(r["diferenca"]),
                       r["criterio_valor_causa"], r["n_pedidos"], r["pedidos_sem_valor"], r["materia_maior_peso"],
                       obs or None, FONTE_DOS_VALORES])
    linhas = {"cadastro": cadastro, "pedidos": pedidos, "resumo": resumo, "parametros": parametros_por_materia()}
    return {aba: {"colunas": COLUNAS[aba], "linhas": linhas[aba]} for aba in COLUNAS}


def exportar_xlsx(projeto, destino):
    """Grava uma planilha NOVA com as quatro abas (sem estilo do cliente, sem fórmulas). Provisório: o escritor
    do modelo B (WS-7) é quem deve gravar nas abas da planilha de pedidos já existente do cliente; este não
    abre, nem altera, arquivo nenhum. Recusa sobrescrever um arquivo que já exista."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    destino = Path(destino)
    if destino.exists():
        raise FileExistsError(f"{destino} já existe; escolha outro nome (a planilha original nunca é sobrescrita)")
    wb = Workbook()
    wb.remove(wb.active)
    for aba, bloco in linhas_para_planilha(projeto).items():
        ws = wb.create_sheet(ABAS_XLSX[aba])
        ws.append(bloco["colunas"])
        for celula in ws[1]:
            celula.font = Font(bold=True)
        for linha in bloco["linhas"]:
            ws.append(linha)
        ws.freeze_panes = "A2"
        for coluna, titulo in enumerate(bloco["colunas"], start=1):
            if "%" in titulo:
                for (cel,) in ws.iter_rows(min_row=2, min_col=coluna, max_col=coluna):
                    cel.number_format = "0.0%"
            elif titulo.startswith(("Valor", "Soma", "Diferença", "Condenação")):
                for (cel,) in ws.iter_rows(min_row=2, min_col=coluna, max_col=coluna):
                    cel.number_format = '#,##0.00'
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino


# ---------------------------------------------------------------- provedor externo (ponto de extensão)

def provedor_disponivel():
    """(disponível, mensagem). Só fica disponível quando o WS-18/o coordenador atribuir `pedidos.PROVEDOR`."""
    return (True, "") if callable(PROVEDOR) else (False, MENSAGEM_INDISPONIVEL)


def enviar_pelo_provedor(projeto, numeros):
    """Pede ao provedor externo (se houver) a leitura dos processos e devolve o texto da resposta, que segue o
    mesmo caminho de um resultado colado (validar -> conferir -> gravar). Sem provedor: ValueError com a
    mensagem de indisponibilidade."""
    ok, msg = provedor_disponivel()
    if not ok:
        raise ValueError(msg)
    return PROVEDOR(projeto, list(numeros))
