"""Assistente dos fluxos: a tela "O que você quer fazer?" e os fluxos Importar, Elaborar relatório
inicial e Atualizar, mais o acompanhamento da coleta em tempo real (rotas sob /fluxo).

Telas e rotas (todas com token nos formulários; tudo local; sem JavaScript externo):

    /fluxo                       quatro botões: Importar, Elaborar inicial, Atualizar, Migrar de modelo
                                 (a revisão continua em /; "Migrar de modelo" vive em painel/migracao.py)
    /fluxo/importar              envio de vários arquivos (arrastar e soltar no campo)
    /fluxo/importar/conferir     CONFERÊNCIA DA MIGRAÇÃO: o que foi lido, números inválidos, duplicados,
                                 vinculados, clientes com grafias diferentes, campos sem destino
    /fluxo/importar/confirmar    cria o relatório (projeto), as fichas e as linhas de base
    /fluxo/inicial               perfil de entrega, profundidade, modo de coleta, filtro por cliente
    /fluxo/atualizar             envio do .docx e/ou .xlsx mais recente + conferência contra a carteira
    /fluxo/confirmar             modo imediato: estimativa de duração e confirmação antes de começar
    /fluxo/progresso             andamento em tempo real; pausar, retomar, parar com segurança
    /fluxo/progresso.json        o mesmo, para quem quiser consultar por programa

Como as peças se encaixam (contratos em docs/fase2/CONTRATOS.md):

  - leitura:       `leitores.detectar/ler` (§4) -> fichas v2 + linha de base (`fichas_do_relatorio`);
                   `consolidar.consolidar` agrupa vinculados, acusa duplicatas e SUGERE grafias; nada
                   é fundido sem a pessoa escolher na conferência (a escolha vale ao confirmar);
  - fila e coleta: `fila.Fila(slug)` (§6): `enfileirar`, `resumo`, `pausar`, `retomar`,
                   `parar_com_seguranca`, `fila.rodar_fila(fila, coletor, ao_progresso)` e o coletor.
                   O coletor vem de `FABRICA_DE_COLETOR` (padrão: `fila.ColetorReal()`, que exige o
                   acesso configurado; nos testes, o coletor simulado). A coleta roda numa thread, uma
                   por vez (também não roda junto com uma tarefa da tela Atualizar, que usa o
                   mesmo certificado);
  - o que a coleta grava: só a CAPA nas fichas (origem "coletado"; nunca polo nem parte contrária,
                   que o tribunal não informa). Ganchos extras (movimentos em eventos, síntese, revisão)
                   entram em `AO_COLETAR`: o WS-14 (fluxos.py) liga o resto;
  - entregas:      depois da revisão, a tela /entregas gera os arquivos (painel/entregas.py).

Modos: contínuo (janela de horário, retoma sozinho enquanto o painel estiver aberto) e imediato
(mostra `Fila.resumo()["estimativa_s"]` e exige confirmação). Cancelar na confirmação não coleta
nada: os processos ficam na fila e podem ser iniciados depois em /fluxo/progresso.

Módulos de outros workstreams (leitores, consolidar, fila) são importados na hora do uso; se não
existirem, a tela explica em português em vez de quebrar.
"""
import datetime
import html
import json
import re
import shutil
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from flask import abort, jsonify, make_response, request

import comum
import ficha
import taxonomia
from painel import entregas as ent
from painel import lacunas_tela
from painel import perfil as per
from painel.base import _ir, _msg, _tarefa_rodando, ajuda
from painel.entregas import ESTILO_FLUXO, Indisponivel, modulo

EXTENSOES = (".docx", ".xlsx", ".csv", ".txt", ".md")
EXTENSOES_ATUALIZAR = (".docx", ".xlsx")
ROTULO_FORMATO = {"docx_a": "Relatório em texto (modelo A)", "xlsx_b": "Planilha (modelo B)",
                  "lista": "Lista de números de processo", "tabela_livre": "Planilha ou tabela fora do modelo"}
ROTULO_DA_EXECUCAO = {"parado": "nada em andamento", "rodando": "coletando", "aguardando": "aguardando a janela de horário",
                      "pausada": "em pausa", "parando": "parando (terminando o processo atual)", "parada": "parada",
                      "concluida": "concluída", "erro": "interrompida por erro"}
# agrupamento dos avisos dos leitores/consolidar na conferência: primeira categoria cujo trecho aparece no `codigo`
CATEGORIAS = [("invalidos", "Números com dígito verificador errado (não foram importados)", ("invalido", "dv_", "digito")),
              ("duplicados", "Números repetidos ou processos duplicados", ("duplic",)),
              ("vinculados", "Processos ligados entre si (recurso, agravo, apenso, mesma ação)", ("vincul", "mesma_acao", "reajuiz")),
              ("grafias", "Nomes escritos de mais de um jeito (confirme qual usar)", ("grafia", "nome_parecido", "cliente_sem_padrao", "nome_")),
              ("ambiguos", "Informações para conferir", ("ambig", "vocabulario", "data_invalida", "formula", "campo_", "rotulo"))]
OUTROS = ("outros", "Outros avisos", ())
AJUDA_DA_CATEGORIA = {
    "invalidos": "O número do processo tem o dígito verificador errado (provável erro de digitação). Esses processos NÃO foram importados. "
                 "Corrija o número no arquivo e envie de novo, ou cadastre-o depois em Clientes e processos.",
    "duplicados": "O mesmo processo apareceu mais de uma vez. O programa guarda uma só ficha por processo; confira se não é número diferente por engano.",
    "vinculados": "Processos que parecem ser o mesmo caso (recurso, agravo, apenso). No relatório, cada conjunto vira uma só linha. "
                  "Confira se os vínculos estão certos; se algum estiver errado, corrija no arquivo e envie de novo.",
    "grafias": "O mesmo cliente ou parte escrito de jeitos diferentes. O programa só junta se você escolher; veja \"Qual nome usar?\" abaixo.",
    "ambiguos": "Pontos em que o programa não teve certeza do que o arquivo queria dizer. Nada impede de continuar, mas vale conferir.",
    "outros": "Outros avisos da leitura, em ordem de gravidade. \"Erro\" pede correção; \"atenção\" pede uma olhada; \"info\" é só informação.",
}
CAMPOS_COM_NOME = ("cliente", "autores", "reus", "parte_contraria", "outras_partes")
INTERVALO_DA_JANELA_S = 30      # de quanto em quanto tempo o modo contínuo olha se a janela abriu
DIAS_DE_GUARDA_DOS_LOTES = 3

FABRICA_DE_COLETOR = None       # f() -> Coletor; None = padrão (fila.ColetorReal). Testes e o WS-14 trocam.
AO_COLETAR = []                 # ganchos g(slug, processo, resultado), chamados a cada processo coletado
AO_CONCLUIR = []                # ganchos g(slug), chamados quando a rodada de coleta termina (processar e sintetizar)

_e = html.escape
_TRAVA = threading.Lock()

# ================================================================ guia de passos (onde estou, o que falta)

ESTILO_ASSISTENTE = """<style>
.trilha{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:6px 0 4px;padding:0;counter-reset:passo}
.trilha li{counter-increment:passo;display:flex;align-items:center;gap:6px;font-size:13px;color:var(--suave);border:1px solid var(--linha);
  border-radius:999px;padding:4px 12px 4px 5px;background:var(--cartao,var(--fundo))}
.trilha li::before{content:counter(passo);display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;
  border-radius:50%;background:var(--linha);color:var(--tinta);font-weight:600;font-size:12px}
.trilha li.feito::before{content:"\\2713";background:var(--teal,var(--acento));color:var(--cartao,#fff)}
.trilha li.atual{border-color:var(--teal,var(--acento));color:var(--tinta);font-weight:600}
.trilha li.atual::before{background:var(--teal,var(--acento));color:var(--cartao,#fff)}
.onde{margin:2px 0 12px;font-size:14px;color:var(--suave)}
.agora{border:1px solid var(--linha);border-left:4px solid var(--teal,var(--acento));border-radius:8px;padding:10px 14px;margin:12px 0;
  background:var(--cartao,var(--fundo))}
.agora p{margin:6px 0 0}
.botao-embrulho{position:relative;display:flex}.botao-embrulho .botao-grande{flex:1}
.botao-embrulho>.ajuda{position:absolute;top:10px;right:10px;margin:0}
.opcao{margin:6px 0}
.vazio{color:var(--suave)}
.modos{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin:12px 0}
.modo{display:block;border:2px solid var(--linha);border-radius:14px;padding:14px 16px;background:var(--cartao,var(--fundo));cursor:pointer}
.modo:has(input:checked){border-color:var(--teal,var(--acento))}
.modo b{font-size:17px}.modo .dica{display:block;margin-top:4px}
table.quadro th:first-child,table.quadro td:first-child{white-space:nowrap;font-weight:600;width:1%}
details.avancado{margin:12px 0}details.avancado summary{cursor:pointer;font-weight:600}
</style>"""

# Cada fluxo é uma lista de passos (rótulo, endereço opcional do passo, para o "próximo" virar link).
FLUXOS = {
    "importar": [("Enviar os arquivos", "/fluxo/importar"), ("Conferir o que foi lido", None), ("Relatório criado", None)],
    "inicial": [("Escolher as opções", "/fluxo/inicial"), ("Coleta nos tribunais", "/fluxo/progresso"),
                ("Revisar os resumos", "/"), ("Gerar as entregas", "/entregas")],
    "atualizar": [("Enviar o relatório anterior", "/fluxo/atualizar"), ("Conferir com a carteira", None),
                  ("Coleta nos tribunais", "/fluxo/progresso"), ("Revisar os resumos", "/"), ("Gerar as entregas", "/entregas")],
    # as telas de confirmação e de andamento servem aos dois fluxos de coleta (inicial e atualizar)
    "coleta": [("Preparar a coleta", None), ("Confirmar o início (modo imediato)", "/fluxo/confirmar"),
               ("Coleta nos tribunais", "/fluxo/progresso"), ("Revisar os resumos", "/"), ("Gerar as entregas", "/entregas")],
}
AJUDA_DA_TRILHA = ("Cada fluxo é uma sequência de passos. O passo marcado é o que você está fazendo agora; os com ✓ já ficaram para trás. "
                   "Dá para voltar ao início do Assistente a qualquer momento sem perder o que já foi gravado.")


def trilha(fluxo, atual):
    """Faixa de passos do fluxo (1 = primeiro) e a frase "você está no passo X de N; o próximo é Y"."""
    passos = FLUXOS[fluxo]
    itens = []
    for i, (rotulo, _) in enumerate(passos, 1):
        classe = "feito" if i < atual else "atual" if i == atual else ""
        marca = " aria-current='step'" if i == atual else ""
        itens.append(f"<li class='{classe}'{marca}>{_e(rotulo)}</li>")
    onde = f"Você está no passo <b>{atual} de {len(passos)}</b>: {_e(passos[atual - 1][0])}."
    if atual < len(passos):
        proximo, destino = passos[atual]
        nome = f"<a href='{destino}'>{_e(proximo)}</a>" if destino else _e(proximo)
        onde += f" Depois vem: {nome}."
    else:
        onde += " É o último passo."
    return (f"<ol class='trilha' aria-label='Passos do fluxo'>{''.join(itens)}</ol>"
            f"<p class='onde'>{onde}{ajuda(AJUDA_DA_TRILHA)}</p>")


def agora(*partes, ajuda_texto=None):
    """Caixa "O que fazer agora" no alto da tela: texto curto (HTML já pronto) dizendo a próxima ação."""
    cabeca = "<b>O que fazer agora</b>" + (ajuda(ajuda_texto) if ajuda_texto else "")
    return f"<div class='agora'>{cabeca}" + "".join(f"<p>{p}</p>" for p in partes) + "</div>"
EXEC = {"thread": None, "slug": None, "fila": None, "estado": "parado", "pedido": None, "resumo": None,
        "erro": None, "inicio": None, "modo": "continuo", "log": deque(maxlen=300)}
_ESPERA = threading.Event()


# ================================================================ avisos

def _aviso(nivel, codigo, onde, mensagem, candidatos=None):
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": candidatos or []}


def _aviso_ok(a, arquivo=None):
    """Garante o formato de Aviso (CONTRATOS §4) mesmo se um módulo devolver algo incompleto."""
    a = a if isinstance(a, dict) else {"mensagem": str(a)}
    onde = a.get("onde", "")
    return {"nivel": a.get("nivel", "atencao"), "codigo": a.get("codigo", "aviso"),
            "onde": f"{arquivo}: {onde}" if arquivo and onde else (arquivo or onde),
            "mensagem": str(a.get("mensagem", "")), "candidatos": list(a.get("candidatos") or [])}


def categoria_do_aviso(aviso):
    codigo = str(aviso.get("codigo", "")).lower()
    for chave, titulo, trechos in CATEGORIAS:
        if any(t in codigo for t in trechos):
            return chave
    return OUTROS[0]


# ================================================================ envio e lotes

def pasta_dos_lotes():
    return comum.PROJETOS_DIR / ".importacoes"      # fora de qualquer relatório: pode não haver relatório ainda


def novo_lote():
    base = pasta_dos_lotes()
    base.mkdir(parents=True, exist_ok=True)
    limite = time.time() - DIAS_DE_GUARDA_DOS_LOTES * 86400
    for antiga in base.iterdir():                    # arrumação: envios abandonados somem depois de alguns dias
        try:
            if antiga.is_dir() and antiga.stat().st_mtime < limite:
                shutil.rmtree(antiga, ignore_errors=True)
        except OSError:
            pass
    lote = uuid.uuid4().hex[:12]
    (base / lote).mkdir()
    return lote, base / lote


def pasta_do_lote(lote):
    if not re.fullmatch(r"[0-9a-f]{12}", lote or ""):
        abort(404)
    pasta = pasta_dos_lotes() / lote
    if not pasta.is_dir():
        abort(404)
    return pasta


def ler_lote(pasta, nome):
    return comum.load_json(pasta / nome, None)


def gravar_lote(pasta, nome, dados):
    (pasta / nome).write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def salvar_envios(arquivos, pasta, extensoes=EXTENSOES):
    """Guarda os arquivos enviados (cada um na sua subpasta, com nome limpo). Devolve (aceitos, rejeitados)."""
    aceitos, rejeitados = [], []
    for i, arq in enumerate(arquivos):
        nome = re.split(r"[\\/]", arq.filename or "")[-1].strip()
        if not nome:
            continue                                  # campo de arquivo sem escolha
        ext = Path(nome).suffix.lower()
        if ext not in extensoes:
            rejeitados.append({"nome": nome, "motivo": f"Tipo de arquivo não aceito ({ext or 'sem extensão'}). "
                                                      f"Envie arquivos {', '.join(extensoes)}."})
            continue
        destino = pasta / f"{i:02d}" / (ent.nome_de_arquivo(Path(nome).stem, "arquivo") + ext)
        destino.parent.mkdir(parents=True, exist_ok=True)
        arq.save(destino)
        if destino.stat().st_size == 0:
            destino.unlink()
            rejeitados.append({"nome": nome, "motivo": "O arquivo está vazio."})
            continue
        aceitos.append({"nome": nome, "caminho": str(destino)})
    return aceitos, rejeitados


def ler_arquivos(aceitos, rejeitados):
    """Detecta o formato e lê cada arquivo. Arquivo ilegível vai para `rejeitados` (nunca derruba a tela).
    Devolve [{"nome", "caminho", "formato", "rel"}]. Levanta Indisponivel se o leitor não existir."""
    leitores = modulo("leitores", "O leitor de relatórios")
    lidos = []
    for a in aceitos:
        caminho = Path(a["caminho"])
        try:
            formato = leitores.detectar(caminho)
        except Exception as erro:  # noqa: BLE001
            rejeitados.append({"nome": a["nome"], "motivo": f"Não consegui abrir o arquivo ({erro})."})
            continue
        if formato not in ROTULO_FORMATO:
            rejeitados.append({"nome": a["nome"], "motivo": "Não reconheci o formato deste arquivo. Confira se ele abre "
                                                           "normalmente e se é um relatório, uma planilha ou uma lista de processos."})
            continue
        try:
            rel = leitores.ler(caminho, formato)
        except Exception as erro:  # noqa: BLE001
            rejeitados.append({"nome": a["nome"], "motivo": f"Não consegui ler o arquivo ({erro}). Ele pode estar corrompido."})
            continue
        lidos.append({"nome": a["nome"], "caminho": a["caminho"], "formato": formato, "rel": rel})
    return lidos


def montar_lote_de_atualizacao(lidos, rejeitados):
    """Compara o que foi lido com a carteira: (fichas lidas, avisos, dados do lote). `novos` estão no arquivo e não na carteira;
    `sumiram` estão na carteira e não no arquivo; `data_base` é a maior dos arquivos."""
    fichas_lidas, avisos, resumos = tratar_leituras(lidos) if lidos else ([], [], [])
    carteira = ficha.carregar(todas=True)
    conhecidos = {n for f in carteira for n in ficha.todos_os_numeros(f)}
    no_arquivo = {n for f in fichas_lidas for n in ficha.todos_os_numeros(f)}
    novos = [f["numero"] for f in fichas_lidas if f["numero"] not in conhecidos]
    sumiram = [f["numero"] for f in carteira if f.get("ativo", True) and lidos
               and not (set(ficha.todos_os_numeros(f)) & no_arquivo)]
    bases = [r["data_base"] for r in resumos if r["data_base"]]
    return fichas_lidas, avisos, {"tipo": "atualizar", "arquivos": resumos, "rejeitados": rejeitados, "novos": novos,
                                  "sumiram": sumiram, "data_base": max(bases) if bases else None, "sem_arquivo": not lidos}


def bloco_de_planilha_fora_do_modelo(resumos, lote):
    """Aviso e atalhos quando um arquivo é planilha FORA do modelo: só as colunas reconhecidas com segurança foram lidas.
    O resto se confere e corrige em /fluxo/mapear, e o arquivo pode ser convertido para os modelos novos."""
    livres = [r for r in resumos if r.get("formato") == "tabela_livre"]
    if not livres:
        return ""
    linhas = []
    for r in livres:
        nao_lidas = [c for c in r.get("sem_destino", []) if c.get("coluna")]
        linhas.append(f"<li><b>{_e(r['nome'])}</b>: {len(nao_lidas)} coluna(s) não lida(s) ou com baixa confiança"
                      + (": " + _e("; ".join(sorted({str(c['coluna']).strip() for c in nao_lidas})[:8])) if nao_lidas else "") + ".</li>")
    return ("<div class='alerta'><b>Planilha fora do modelo do programa.</b> Só leio sem perguntar as colunas que reconheço com segurança "
            "(número do processo e poucas mais). Confira o mapeamento: é ele que decide se partes, valores, resumo e histórico "
            "entram no relatório.<ul>" + "".join(linhas) + "</ul>"
            f"<a href='/fluxo/mapear?lote={_e(lote)}'><b>Conferir e corrigir o mapeamento das colunas</b></a>"
            + ajuda("Mostra, coluna por coluna, para qual campo da ficha cada coluna da sua planilha foi. Você corrige o que estiver "
                    "errado antes de continuar. Nada é gravado só por abrir essa tela.")
            + f" · <a href='/fluxo/migrar?lote={_e(lote)}'>Converter este relatório para os modelos novos (texto, planilha e painel)</a>"
            + ajuda("Gera cópias do seu relatório nos modelos do programa. O arquivo original não é alterado.") + "</div>")


def resumo_da_leitura(lido):
    rel = lido["rel"]
    return {"nome": lido["nome"], "caminho": lido["caminho"], "formato": lido["formato"],
            "processos": len(rel.get("processos", [])), "data_base": rel.get("data_base"), "cliente": rel.get("cliente"),
            "sem_destino": rel.get("colunas_sem_destino", []), "avisos": rel.get("avisos", []),
            "mapeamento": rel.get("mapeamento", [])}


# ================================================================ do relatório lido para fichas

def _origem_valida(origem):
    return origem if origem in ("migrado", "humano", "derivado") else "migrado"


def fichas_do_relatorio(rel, nome_arquivo=None):
    """RelatorioLido -> (fichas v2, avisos). Campos entram com a origem que o leitor deu (migrado ou
    humano); o histórico em texto vira `linha_de_base`; processo só de lista fica sem linha de base."""
    fichas, avisos, momentos_deduzidos = [], [], 0
    derivados_de_contingencia = {}
    for p in rel.get("processos", []):
        numero = p.get("numero")
        if not numero:
            continue
        f = ficha.nova_ficha(numero)
        for campo, c in (p.get("campos") or {}).items():
            valor = c.get("valor") if isinstance(c, dict) else c
            if valor in (None, ""):
                continue
            origem = _origem_valida(c.get("origem") if isinstance(c, dict) else None)
            if campo not in ficha.CAMPOS or not ficha.definir(f, campo, valor, origem, forcar=True):
                rotulo = ficha.CAMPOS[campo][0] if campo in ficha.CAMPOS else campo
                avisos.append(_aviso("atencao", "campo_recusado", f"processo {numero}",
                                     f"{rotulo}: o valor {valor!r} não entrou na ficha (fora do padrão ou campo desconhecido)."))
        if not ficha.obter(f, "cliente") and rel.get("cliente"):
            ficha.definir(f, "cliente", rel["cliente"], "migrado")
        for nome_derivado in ficha.derivar_contingencia(f["campos"]):
            derivados_de_contingencia[nome_derivado] = derivados_de_contingencia.get(nome_derivado, 0) + 1
        for v in p.get("vinculados") or []:
            if v.get("numero"):
                ficha.vincular(f, v["numero"], v.get("tipo") or "mesma_acao")
        texto = p.get("andamentos_texto") or ""
        if texto or (rel.get("formato") in ("docx_a", "xlsx_b") and rel.get("data_base")):
            f["linha_de_base"] = {"data_base": rel.get("data_base"), "andamentos_texto": texto,
                                  "arquivo": nome_arquivo or rel.get("arquivo"), "ultimo_andamento": p.get("ultimo_andamento")}
        if not ficha.obter(f, "momento_atual") and p.get("andamentos"):
            # relatório sem coluna de momento atual (ex.: planilha de contingências): deduz do histórico pelas regras
            movs = [{"data": a.get("data"), "texto": a.get("texto") or "", "grau": None} for a in p["andamentos"]]
            deduzido, evidencia = taxonomia.momento_por_regras(movs)
            if deduzido and ficha.definir(f, "momento_atual", deduzido, "derivado", evidencia=evidencia):
                momentos_deduzidos += 1
        momento, situacao = ficha.obter(f, "momento_atual"), ficha.obter(f, "situacao")
        ativo = taxonomia.momento_ativo(momento) if momento else None
        if ativo is not None:
            f["ativo"] = ativo
        elif situacao == "Encerrado":
            f["ativo"] = False
        elif p.get("ativo") is False:
            f["ativo"] = False       # o leitor viu o processo numa aba de arquivados/encerrados (ou na coluna Ativo = Não)
        ficha.derivar_situacao(f)
        fichas.append(f)
    if derivados_de_contingencia.get("deposito_judicial"):
        avisos.append(_aviso("info", "contingencia_derivada", nome_arquivo or "arquivo",
                             f"{derivados_de_contingencia['deposito_judicial']} processo(s) tinham o valor do depósito mas não o Sim/Não: "
                             "marquei \"Depósito judicial realizado = Sim\" (origem \"derivado\")."))
    if derivados_de_contingencia.get("percentual_provisao"):
        avisos.append(_aviso("info", "contingencia_derivada", nome_arquivo or "arquivo",
                             f"{derivados_de_contingencia['percentual_provisao']} processo(s) tinham provisão e passivo mas não o percentual: "
                             "calculei provisão ÷ passivo potencial (origem \"derivado\")."))
    if momentos_deduzidos:
        avisos.append(_aviso("info", "momento_deduzido", nome_arquivo or "arquivo",
                             f"{momentos_deduzidos} processo(s) não tinham o momento atual no arquivo: deduzi pelas regras a partir do último "
                             "andamento do histórico (origem \"derivado\"). Confira na revisão dos campos."))
    return fichas, avisos


def juntar_fichas(grupos):
    """[(data_base ISO ou None, fichas)] -> (fichas sem repetição por número, avisos). Quando o mesmo número
    aparece em mais de um arquivo, vale o do arquivo de data-base mais recente."""
    por_numero, repetidos = {}, 0
    for _, fichas in sorted(grupos, key=lambda g: g[0] or ""):
        for f in fichas:
            repetidos += f["numero"] in por_numero
            por_numero[f["numero"]] = f
    avisos = []
    if repetidos:
        avisos.append(_aviso("info", "processo_em_varios_arquivos", "arquivos",
                             f"{repetidos} processo(s) apareceram em mais de um arquivo; valeu o do arquivo mais recente."))
    return list(por_numero.values()), avisos


def consolidar_fichas(fichas):
    """Passa as fichas pelo consolidar (WS-1). Sem o módulo, segue sem consolidar e avisa."""
    try:
        mod = modulo("consolidar", "A consolidação (agrupar vinculados, achar duplicatas)")
    except Indisponivel as erro:
        return fichas, [_aviso("info", "consolidar_indisponivel", "consolidação", str(erro))]
    try:
        novas, avisos = mod.consolidar(fichas)
    except Exception as erro:  # noqa: BLE001
        return fichas, [_aviso("atencao", "consolidar_falhou", "consolidação",
                               f"Não consegui conferir duplicados e vinculados ({erro}). Confira à mão.")]
    return novas, [_aviso_ok(a) for a in avisos]


def tratar_leituras(lidos):
    """Lê -> fichas -> consolida. Devolve (fichas consolidadas, avisos, resumos por arquivo)."""
    grupos, avisos, resumos = [], [], []
    for l in lidos:
        fichas, av = fichas_do_relatorio(l["rel"], l["nome"])
        grupos.append((l["rel"].get("data_base"), fichas))
        avisos += [_aviso_ok(a, l["nome"]) for a in l["rel"].get("avisos", [])] + [_aviso_ok(a, l["nome"]) for a in av]
        resumos.append(resumo_da_leitura(l))
    fichas, av = juntar_fichas(grupos)
    fichas, av2 = consolidar_fichas(fichas)
    return fichas, avisos + av + av2, resumos


# ================================================================ conferência da migração

def _nomes_de_cliente(fichas):
    contagem = {}
    for f in fichas:
        nome = ficha.obter(f, "cliente") or ""
        contagem[nome] = contagem.get(nome, 0) + 1
    return contagem


def _tabela_de_avisos(itens):
    linhas = "".join(f"<tr><td class='nivel-{_e(a['nivel'])}'>{_e(a['nivel'])}</td><td>{_e(a['onde'])}</td>"
                     f"<td>{_e(a['mensagem'])}"
                     + (f"<br><span class='dica'>Candidatos: {_e(' | '.join(map(str, a['candidatos'])))}</span>" if a["candidatos"] else "")
                     + "</td></tr>" for _, a in itens)
    return f"<table class='t'><tr><th>Nível</th><th>Onde</th><th>O que houve</th></tr>{linhas}</table>"


def bloco_de_clientes(fichas, nome_sugerido):
    """Identificação dos clientes em lote: candidatos tirados das partes (marque quem é cliente) e um cliente padrão
    para o que sobrar. Só aparece se algum processo ainda estiver sem cliente."""
    sem_cliente = sum(1 for f in fichas if not ficha.obter(f, "cliente"))
    if not sem_cliente:
        return ""
    import clientes as cli
    cands = cli.candidatos(fichas)
    auto = cli.escolher_automatico(cands)
    linhas = []
    for i, c in enumerate(cands):
        marcado = "checked" if (auto is c or (auto is None and not linhas and c["cobertura"] >= 0.4)) else ""
        tipo = "várias empresas com esse nome" if c["tipo"] == "grupo" else "empresa"
        linhas.append(f"<tr><td><input type='checkbox' name='cli' value='{i}' {marcado}></td><td>{_e(c['nome'])}"
                      f"<br><span class='dica'>{tipo}</span></td><td>{c['processos']} ({round(100 * c['cobertura'])}%)</td>"
                      f"<td>{c['autor']}</td><td>{c['reu']}</td></tr>")
    tabela = ("<table class='t'><tr><th>Cliente?</th><th>Parte mais frequente</th><th>Processos</th><th>Como autor</th><th>Como réu</th></tr>"
              + "".join(linhas) + "</table>") if linhas else "<p class='dica'>Não achei uma parte que se repita nos processos.</p>"
    return (f"<h3>Quem é o cliente? ({sem_cliente} processo(s) sem cliente)"
            + ajuda("Os arquivos não diziam quem é o cliente. O programa olhou as partes que mais se repetem. Marque as que são seus clientes: "
                    "ele preenche cliente, polo e parte contrária em todos os processos em que ela aparece. "
                    "Isto só vale quando você confirmar no fim da página, e dá para corrigir depois em Clientes e processos.") + "</h3>"
            "<p class='dica'>Marque quem é cliente: o programa define, de uma vez, o cliente, o polo (autor ou réu) e a parte contrária "
            "em todos os processos em que a parte aparece. Nada de preencher processo por processo.</p>" + tabela +
            "<p><label>Cliente padrão para os processos que ficarem sem cliente (deixe em branco para não aplicar)"
            + ajuda("Se ainda sobrar processo sem cliente depois das marcações acima, este nome é usado nele. Use quando o relatório inteiro "
                    "é de um só cliente. Em branco, os processos sobrantes continuam sem cliente.") +
            f"<br><input type='text' name='cliente_padrao' size='50' value='{_e(nome_sugerido)}' placeholder='Ex.: Cliente Exemplo Ltda'></label></p>")


def html_da_conferencia(resumos, rejeitados, fichas, avisos, oculto, lote, nome_sugerido, ha_projeto):
    """A tela de conferência da migração (corpo, sem o cabeçalho)."""
    h = []
    total, clientes = len(fichas), _nomes_de_cliente(fichas)
    bases = sorted({r["data_base"] for r in resumos if r["data_base"]})
    sem_base = sum(1 for f in fichas if not f.get("linha_de_base"))
    ligados = [f for f in fichas if f.get("vinculados")]
    quando = f", data-base {ficha.data_br(bases[-1])}" if bases else ""
    h.append(f"<div class='caixa'><b>Li {total} processo(s) de {len(resumos)} arquivo(s), "
             f"{len([c for c in clientes if c])} cliente(s){quando}.</b>"
             + ajuda("Foi lido aqui, no seu computador, a partir dos arquivos que você enviou. Nada foi gravado ainda: as fichas, o histórico "
                     "e o relatório só são criados quando você clicar em \"Confirmar e criar o relatório\", no fim da página.") + "</div>")
    h.append("<div class='cartoes'>"
             f"<div class='cartao'><b>{total}</b>processos</div>"
             f"<div class='cartao'><b>{len(ligados)}</b>com processos ligados"
             + ajuda("Processos que o programa entendeu que são o mesmo caso (recurso, agravo, apenso). Cada conjunto vira uma só linha no relatório.")
             + "</div>"
             f"<div class='cartao'><b>{sem_base}</b>novos (sem relatório anterior)"
             + ajuda("Processos que vieram só como número, sem histórico escrito. Eles precisam do \"relatório inicial\": o programa busca tudo "
                     "nos tribunais e monta o primeiro texto.") + "</div>"
             f"<div class='cartao'><b>{sum(1 for a in avisos if a['nivel'] == 'erro')}</b>erro(s)"
             + ajuda("Problemas sérios na leitura (por exemplo, número de processo inválido). O que deu erro não é importado; veja a lista abaixo.")
             + "</div>"
             f"<div class='cartao'><b>{sum(1 for a in avisos if a['nivel'] == 'atencao')}</b>ponto(s) de atenção"
             + ajuda("Dúvidas que o programa não resolveu sozinho (nomes parecidos, rótulos fora do padrão). Dê uma olhada nas listas abaixo antes de confirmar.")
             + "</div></div>")
    h.append("<h2>Arquivos" + ajuda("Cada arquivo que você enviou e como o programa o entendeu. Se o formato estiver errado, volte e envie o arquivo certo.") + "</h2>"
             "<table class='t'><tr><th>Arquivo</th><th>Formato</th><th>Processos</th><th>Data-base</th></tr>")
    for r in resumos:
        h.append(f"<tr><td>{_e(r['nome'])}</td><td>{_e(ROTULO_FORMATO.get(r['formato'], r['formato']))}</td>"
                 f"<td>{r['processos']}</td><td>{_e(ficha.data_br(r['data_base']) or '-')}</td></tr>")
    h.append("</table>")
    h.append(bloco_de_planilha_fora_do_modelo(resumos, lote))
    if fichas:
        h.append(lacunas_tela.quadro(fichas, mapeamento=[m for r in resumos for m in r.get("mapeamento", [])],
                                     colunas_sem_destino=[c for r in resumos for c in r.get("sem_destino", [])],
                                     aberto=any(r.get("formato") == "tabela_livre" for r in resumos), incluir_sem_destino=False))
    if rejeitados:
        h.append("<h2>Arquivos que não consegui usar"
                 + ajuda("Estes arquivos foram deixados de lado: nada deles entra no relatório. Corrija o problema (o motivo está ao lado), "
                         "volte e envie de novo.") + "</h2><table class='t'><tr><th>Arquivo</th><th>Motivo</th></tr>"
                 + "".join(f"<tr><td>{_e(r['nome'])}</td><td>{_e(r['motivo'])}</td></tr>" for r in rejeitados) + "</table>")
    if sem_base:
        h.append(f"<p class='dica'>{sem_base} processo(s) vieram só como número, sem relatório anterior: entram marcados como "
                 "<b>novos</b> e precisam do <a href='/fluxo/inicial'>relatório inicial</a>.</p>")
    indexados = list(enumerate(avisos))
    escolhas = []
    for chave, titulo, _ in [*CATEGORIAS, OUTROS]:
        itens = [(i, a) for i, a in indexados if categoria_do_aviso(a) == chave]
        ajuda_cat = ajuda(AJUDA_DA_CATEGORIA[chave])
        if chave == "vinculados" and ligados:
            h.append(f"<h2>{_e(titulo)}{ajuda_cat}</h2><p>{len(ligados)} processo(s) têm processos ligados; no relatório cada conjunto vira uma só linha.</p>"
                     "<table class='t'><tr><th>Principal</th><th>Ligados</th></tr>"
                     + "".join(f"<tr><td>{_e(f['numero'])}</td><td>{_e(', '.join(v['numero'] + ' (' + str(v.get('tipo')) + ')' for v in f['vinculados']))}</td></tr>"
                               for f in ligados[:50])
                     + "</table>" + (f"<p class='dica'>E mais {len(ligados) - 50}.</p>" if len(ligados) > 50 else ""))
            if itens:
                h.append(_tabela_de_avisos(itens))
            continue
        if not itens:
            continue
        h.append(f"<h2>{_e(titulo)} ({len(itens)}){ajuda_cat}</h2>" + _tabela_de_avisos(itens))
        if chave == "grafias":
            for i, a in itens:
                cands = [str(c) for c in a["candidatos"]]
                if len(cands) >= 2:
                    escolhas.append((i, a, cands))
    if escolhas:
        h.append("<h2>Qual nome usar?"
                 + ajuda("Quando a escolha vale: só depois de \"Confirmar e criar o relatório\". Ao escolher um nome, todos os outros jeitos de "
                         "escrever aquele nome, nos processos lidos, são trocados por ele. Se deixar \"manter como está\", nada muda.")
                 + "</h2><p class='dica'>Nada é juntado sem a sua escolha. Se não escolher, os nomes ficam como estão.</p>")
        for i, a, cands in escolhas:
            h.append(f"<div class='caixa'><p>{_e(a['mensagem'])}</p><label><input type='radio' name='grafia_{i}' value='' checked> manter como está</label><br>"
                     + "<br>".join(f"<label><input type='radio' name='grafia_{i}' value='{_e(c)}'> usar <b>{_e(c)}</b> em todos</label>" for c in cands)
                     + "</div>")
    sem_destino = [(r["nome"], c) for r in resumos for c in r["sem_destino"]]
    if sem_destino:
        h.append("<h2>Colunas sem destino"
                 + ajuda("Colunas do seu arquivo que o programa não sabe onde guardar. Elas não entram nas fichas, mas ficam registradas na aba "
                         "\"Campos não migrados\" quando a planilha for gerada, para você não perder a informação.")
                 + "</h2><p><b>Colunas do seu arquivo que ainda não têm destino.</b></p>"
                 "<p class='dica'>Estas colunas do arquivo não têm lugar na ficha. Nada se perde: "
                 "elas aparecem na aba \"Campos não migrados\" quando a planilha for gerada.</p>"
                 "<table class='t'><tr><th>Arquivo</th><th>Coluna</th><th>Exemplos</th></tr>"
                 + "".join(f"<tr><td>{_e(n)}</td><td>{_e(str(c.get('coluna')))}</td><td>{_e(' | '.join(map(str, (c.get('amostra') or [])[:3])))}</td></tr>"
                           for n, c in sem_destino) + "</table>")
    h.append("<h2>Clientes encontrados"
             + ajuda("Quantos processos o programa achou para cada cliente nos arquivos. \"(sem cliente)\" são processos em que o arquivo não "
                     "dizia quem é o cliente; você pode indicá-lo logo abaixo.")
             + "</h2><table class='t'><tr><th>Cliente</th><th>Processos</th></tr>"
             + "".join(f"<tr><td>{_e(n or '(sem cliente)')}</td><td>{q}</td></tr>" for n, q in sorted(clientes.items()))
             + "</table>")
    h.append(f"<form class='caixa' method='post' action='/fluxo/importar/confirmar' onsubmit=\"return confirm('Gravar as fichas de {total} "
             "processo(s) neste computador? O que já está nos relatórios antigos vira o histórico e não será buscado de novo.')\">"
             f"{oculto}<input type='hidden' name='lote' value='{_e(lote)}'>"
             "<h3>Confirmar a importação</h3>"
             "<p><label>Nome do relatório"
             + ajuda("É o nome da aba que aparece no alto da tela. Se você acrescentar a um relatório que já existe, o nome não muda nada. "
                     "O programa sugeriu um com base nos arquivos; troque se quiser.")
             + f"<br><input type='text' name='nome' size='50' value='{_e(nome_sugerido)}' placeholder='Ex.: Grupo Exemplo' required></label></p>")
    h.append(bloco_de_clientes(fichas, nome_sugerido))
    if ha_projeto:
        h.append("<p><label><input type='radio' name='destino' value='novo' checked> criar um relatório novo</label>"
                 + ajuda("Cria uma pasta e uma aba novas só para estes processos. Os outros relatórios não são mexidos.") + "<br>"
                 f"<label><input type='radio' name='destino' value='atual'> acrescentar ao relatório atual ({_e(comum.projeto().get('nome', ''))})</label>"
                 + ajuda("Põe os processos novos dentro do relatório que está aberto. Em processo que já existe, só entra o que faltava; "
                         "o que você já preencheu não é trocado.") + "</p>")
    else:
        h.append("<input type='hidden' name='destino' value='novo'>")
    h.append("<p class='dica'>Ao confirmar, o programa cria as fichas e guarda o histórico lido como linha de base: "
             "o que já está escrito nos relatórios antigos não será coletado de novo.</p>"
             f"<button class='principal' {'disabled' if not total else ''}>Confirmar e criar o relatório</button>"
             + ajuda("Grava as fichas e o histórico lido neste computador e cria (ou completa) o relatório. Não consulta tribunal nenhum e "
                     "não envia nada pela internet. Uma vez confirmado, este envio não pode ser confirmado de novo; para mudar algo, "
                     "corrija depois em Clientes e processos.")
             + " <a href='/fluxo'>Cancelar</a>"
             + ajuda("Abandona esta importação: nada é gravado. Os arquivos enviados ficam numa pasta temporária e são apagados sozinhos em alguns dias.")
             + "</form>")
    return "".join(h)


def identificar_clientes_do_formulario(fichas, form):
    """Aplica a escolha da conferência (caixas `cli` + `cliente_padrao`): cliente, polo e parte contrária em lote.
    Devolve um texto-resumo (ou "" se nada foi pedido). Cliente já definido nunca é trocado."""
    import clientes as cli
    cands = cli.candidatos(fichas)
    marcados = []
    for v in form.getlist("cli"):
        if v.isdigit() and int(v) < len(cands):
            c = cands[int(v)]
            marcados.append({"nome": c["nome"], "variacoes": c["variacoes"]})
    padrao = (form.get("cliente_padrao") or "").strip() or None
    if not marcados and not padrao:
        return ""
    rel = cli.identificar(fichas, cli.especs_do_projeto() + marcados if comum.PROJETO else marcados, padrao=padrao)
    cli.registrar([e for e in marcados if rel["aplicados"].get(e["nome"])] + ([{"nome": padrao, "variacoes": []}] if padrao and rel["padrao"] else []))
    partes = [f"{q} em «{c}»" for c, q in sorted(rel["aplicados"].items())]
    if rel["padrao"]:
        partes.append(f"{rel['padrao']} no cliente padrão «{padrao}»")
    texto = "Clientes definidos em lote: " + "; ".join(partes) + "." if partes else ""
    if rel["ambiguos"]:
        texto += f" {len(rel['ambiguos'])} processo(s) têm o cliente nos dois lados: confira o polo em Clientes e processos."
    if rel["sem_correspondencia"]:
        texto += f" {len(rel['sem_correspondencia'])} processo(s) continuam sem cliente."
    return texto.strip()


def aplicar_grafias(fichas, avisos, form):
    """Aplica as escolhas de grafia da conferência (radio `grafia_<i>`): troca os nomes candidatos pelo escolhido."""
    trocas = 0
    for i, a in enumerate(avisos):
        escolhido = (form.get(f"grafia_{i}") or "").strip()
        cands = {str(c) for c in a.get("candidatos", [])}
        if not escolhido or escolhido not in cands or categoria_do_aviso(a) != "grafias":
            continue
        for f in fichas:
            for campo in CAMPOS_COM_NOME:
                atual = ficha.obter(f, campo)
                if atual in cands and atual != escolhido:
                    ficha.definir(f, campo, escolhido, ficha.origem(f, campo) or "migrado", forcar=True)
                    trocas += 1
    return trocas


# ================================================================ criar / acrescentar relatório

def registrar_clientes(fichas):
    dados = comum.load_json(comum.CLIENTES_FILE, {"clientes": []})
    lista = dados.setdefault("clientes", [])
    existentes = {comum.normalizar(c["nome"]) for c in lista}
    for nome in sorted(_nomes_de_cliente(fichas)):
        if nome and comum.normalizar(nome) not in existentes:
            lista.append({"nome": nome, "variacoes": [], "contato": "", "responsavel": ""})
            existentes.add(comum.normalizar(nome))
    comum.save_json(comum.CLIENTES_FILE, dados)


def copiar_para_entrada(caminho, nome):
    destino = ent.pasta_entrada() / f"{datetime.date.today():%Y-%m-%d} - {ent.nome_de_arquivo(Path(nome).stem, 'arquivo')}{Path(nome).suffix.lower()}"
    n = 2
    while destino.exists():
        destino = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        n += 1
    shutil.copy2(caminho, destino)
    return destino


def mesclar_no_atual(novas):
    """Acrescenta ao relatório ativo: ficha nova entra; ficha existente só recebe o que faltava
    (a prioridade das origens decide) e a linha de base, se não tinha. Devolve (adicionadas, atualizadas)."""
    atuais = ficha.carregar(todas=True)
    por_numero = {f["numero"]: f for f in atuais}
    adicionadas = atualizadas = 0
    for n in novas:
        existente = por_numero.get(n["numero"])
        if existente is None:
            atuais.append(n)
            por_numero[n["numero"]] = n
            adicionadas += 1
            continue
        mudou = False
        for campo, c in n.get("campos", {}).items():
            mudou |= ficha.definir(existente, campo, c["valor"], c["origem"])
        for v in n.get("vinculados", []):
            ficha.vincular(existente, v["numero"], v["tipo"])
        if n.get("linha_de_base") and not existente.get("linha_de_base"):
            existente["linha_de_base"] = n["linha_de_base"]
            mudou = True
        atualizadas += mudou
    ficha.salvar(atuais)
    return adicionadas, atualizadas


def criar_relatorio(nome, fichas, arquivos, resumos):
    """Cria o projeto, grava as fichas e o perfil, copia os arquivos enviados para entrada/ e torna o
    relatório o ativo. Devolve o slug. Guarda no perfil o mapeamento das colunas lidas: é ele que permite à planilha
    (inclusive na atualização leve) preencher a aba "Faltas da migração" com a origem de cada campo."""
    slug = comum.criar_projeto(nome)
    comum.usar_projeto(slug)
    ficha.salvar(fichas)
    registrar_clientes(fichas)
    formatos = {r["formato"] for r in resumos}
    entregas = [e for e, fmt in (("docx_a", "docx_a"), ("xlsx_b", "xlsx_b")) if fmt in formatos]
    if "xlsx_b" in formatos:
        entregas.append("dashboard")
    perfil = per.carregar()
    if entregas:
        perfil["entregas"] = entregas
    mapa = [m for r in resumos for m in (r.get("mapeamento") or [])]
    sem_destino = [c for r in resumos for c in (r.get("sem_destino") or [])]
    if mapa or sem_destino:
        perfil.setdefault("parametros", {})["migracao_lacunas"] = {"mapeamento": mapa, "colunas_sem_destino": sem_destino}
    per.salvar(perfil)
    for a in arquivos:
        copiar_para_entrada(a["caminho"], a["nome"])
    bases = [r["data_base"] for r in resumos if r["data_base"]]
    proj = comum.projeto()
    if bases:
        proj["ultimo_relatorio"] = max(bases)
    comum.salvar_projeto(proj)
    return slug


def _com_cookie(resposta, slug):
    r = make_response(resposta)
    r.set_cookie("projeto", slug, samesite="Strict", max_age=3600 * 24 * 365)
    return r


# ================================================================ fila e coleta

def desde_do_processo(f, data_base_do_arquivo=None):
    """Data (ISO) a partir da qual coletar: a mais recente entre a data-base do arquivo enviado, o último texto
    gravado pelo programa e a linha de base. Sem nada disso, None (coleta o histórico todo)."""
    candidatas = [data_base_do_arquivo,
                  (f.get("ultimo_texto_gravado") or {}).get("data_base"),
                  (f.get("linha_de_base") or {}).get("data_base") or (f.get("linha_de_base") or {}).get("ultimo_andamento")]
    validas = [ficha.parse_data(c) for c in candidatas if c]
    validas = [v for v in validas if v]
    return max(validas) if validas else None


def clientes_da_carteira(fichas):
    return sorted(c for c in _nomes_de_cliente(fichas) if c)


def selecionar_processos(fichas, cliente="", so_novos=False, excluir=()):
    """Fichas ativas (só os números principais) conforme o filtro."""
    return [f for f in fichas if f.get("ativo", True) and (not cliente or ficha.obter(f, "cliente") == cliente)
            and (not so_novos or not f.get("linha_de_base")) and f["numero"] not in excluir]


def _configurar_janela(fila, janela):
    """A janela de horário do modo contínuo é da fila; usa `definir_janela(inicio, fim)` se ela oferecer."""
    definir = getattr(fila, "definir_janela", None)
    if callable(definir):
        definir(janela["inicio"], janela["fim"])


def _coletado_antes_de_hoje(fila, numero, hoje):
    """O processo já foi coletado numa rodada de OUTRO dia? (Sem `Fila.item`, ou sem data, não há como saber: False.)"""
    item_de = getattr(fila, "item", None)
    item = item_de(numero) if callable(item_de) else None
    return bool(item and item.get("estado") == "coletado" and str(item.get("coletado_em") or "")[:10] < hoje)


def enfileirar(selecionadas, perfil_do_relatorio, data_base_do_arquivo=None, historico_todo=False, novo_ciclo=False):
    """Põe os processos na fila (agrupados pela data `desde`). `historico_todo` (montagem completa) ignora a data-base:
    `desde` None, o histórico inteiro. `novo_ciclo` (atualização): o processo que a fila já tem como `coletado` de um dia
    anterior volta para a fila; sem isso a fila o trataria como pronto e a atualização do mês seguinte não buscaria nada.
    O coletado hoje continua pronto (é a mesma rodada). Devolve (fila, quantidade)."""
    grupos = {}
    for f in selecionadas:
        grupos.setdefault(None if historico_todo else desde_do_processo(f, data_base_do_arquivo), []).append(f["numero"])
    fila = ent.abrir_fila()
    if perfil_do_relatorio["modo_coleta"] == "continuo":
        _configurar_janela(fila, perfil_do_relatorio["janela_coleta"])
    hoje = datetime.date.today().isoformat()
    for desde, numeros in sorted(grupos.items(), key=lambda kv: kv[0] or ""):
        pedido = dict(modo=perfil_do_relatorio["modo_coleta"], profundidade=perfil_do_relatorio["profundidade"], prioridade=0, desde=desde)
        fila.enfileirar(numeros, **pedido)
        velhos = [n for n in numeros if novo_ciclo and _coletado_antes_de_hoje(fila, n, hoje)]
        if velhos:
            fila.enfileirar(velhos, recoletar=True, **pedido)
    return fila, sum(len(n) for n in grupos.values())


def duracao_humana(segundos):
    if not segundos or segundos <= 0:
        return "não consegui estimar"
    minutos = max(1, round(segundos / 60))
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f"cerca de {horas} h {resto} min"
    return f"cerca de {horas} h" if horas else f"cerca de {minutos} min"


def gravar_capa(slug, processo, resultado):
    """Gancho padrão: grava a CAPA coletada na ficha (origem "coletado"). Nunca grava polo nem parte
    contrária (o tribunal não os informa) e usa o arquivo do relatório da coleta, não o ativo da tela."""
    if resultado.get("erro") or not resultado.get("capa"):
        return 0
    numero = processo if isinstance(processo, str) else processo.get("numero")
    arquivo = comum.PROJETOS_DIR / slug / "carteira.json"
    with _TRAVA:
        fichas = [ficha.de_carteira_v1(p) for p in comum.load_json(arquivo, [])]
        alvo = next((f for f in fichas if f["numero"] == numero), None)
        if alvo is None:
            return 0
        mudou = sum(ficha.definir(alvo, campo, valor, "coletado", evidencia="capa coletada pela fila")
                    for campo, valor in resultado["capa"].items()
                    if campo in ficha.CAMPOS and campo not in ("polo_cliente", "parte_contraria"))
        if mudou:
            comum.save_json(arquivo, fichas)
        return mudou


AO_COLETAR.append(gravar_capa)


def _ligar_fluxos():
    """WS-14: liga os ganchos de `fluxos.py` (movimentos e documentos como eventos; depois da rodada, extração,
    resumo e síntese). Sem o módulo, a coleta da tela continua gravando só a capa."""
    try:
        import fluxos
    except ImportError:
        return
    AO_COLETAR.append(fluxos.ao_coletar)
    AO_CONCLUIR.append(fluxos.pos_coleta)


_ligar_fluxos()


class _ColetorComGanchos:
    """Embrulha o coletor: depois de cada processo chama os ganchos de AO_COLETAR (erro de gancho só vai ao registro)."""

    def __init__(self, coletor, slug):
        self.coletor, self.slug = coletor, slug

    def coletar(self, processo, profundidade, desde):
        resultado = self.coletor.coletar(processo, profundidade, desde)
        for gancho in list(AO_COLETAR):
            try:
                gancho(self.slug, processo, resultado)
            except Exception as erro:  # noqa: BLE001
                _log(f"gancho {getattr(gancho, '__name__', gancho)} falhou: {erro}")
        return resultado


class _Tee:
    """Copia tudo o que a coleta imprime (login, captcha, andamentos, tempos) para um arquivo em data/logs/: no
    Assistente a coleta roda dentro do painel e o que ela imprimia só aparecia no Terminal."""

    def __init__(self, original, arquivo):
        self._original, self._arquivo = original, arquivo

    def write(self, texto):
        try:
            self._arquivo.write(texto)
            self._arquivo.flush()
        except (OSError, ValueError):
            pass
        return self._original.write(texto)

    def flush(self):
        try:
            self._arquivo.flush()
        except (OSError, ValueError):
            pass
        return self._original.flush()

    def __getattr__(self, nome):
        return getattr(self._original, nome)


def _abrir_log_da_coleta():
    """Abre data/logs/AAAAMMDD-HHMMSS-assistente.log, grava a versão na primeira linha e passa a copiar o que a coleta imprime."""
    import sys
    try:
        logs = Path(comum.DATA) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        arquivo = (logs / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-assistente.log").open("a", encoding="utf-8")
    except OSError:
        return
    arquivo.write(f"Relatório de Andamentos {comum.versao_do_programa() or '?'} (painel {_versao_carregada()}) - coleta iniciada em "
                  f"{datetime.datetime.now():%d/%m/%Y %H:%M:%S}\n")
    arquivo.flush()
    EXEC["log_arquivo"] = arquivo
    EXEC["stdout_original"] = sys.stdout
    sys.stdout = _Tee(sys.stdout, arquivo)


def _fechar_log_da_coleta():
    import sys
    arquivo = EXEC.pop("log_arquivo", None)
    original = EXEC.pop("stdout_original", None)
    if isinstance(sys.stdout, _Tee) and original is not None:
        sys.stdout = original
    if arquivo is not None:
        try:
            arquivo.close()
        except OSError:
            pass


def _versao_carregada():
    from painel import base
    return base.VERSAO_CARREGADA or "?"


def _log(texto):
    linha = f"{datetime.datetime.now():%H:%M:%S} {texto}"
    EXEC["log"].append(linha)
    arquivo = EXEC.get("log_arquivo")
    if arquivo is not None:
        try:
            arquivo.write(linha + "\n")
            arquivo.flush()
        except (OSError, ValueError):
            pass


def _criar_coletor():
    if FABRICA_DE_COLETOR is not None:
        return FABRICA_DE_COLETOR()
    import acesso
    if not all(acesso.situacao().values()):
        raise Indisponivel("Falta configurar o acesso (senha do certificado e código do autenticador). Use \"Acesso e escritório\".")
    return modulo("fila", "A coleta nos tribunais").ColetorReal()


def execucao_rodando():
    t = EXEC["thread"]
    return bool(t and t.is_alive())


def _progresso(resumo):
    EXEC["resumo"] = resumo
    if isinstance(resumo, dict) and resumo.get("evento") == "login":
        EXEC["estado"] = "pausada"       # a fila pausou sozinha: a tela passa a oferecer "Retomar"
        _log(f"PRECISA DE VOCÊ: a coleta parou porque o acesso ao jus.br falhou. {resumo.get('mensagem') or ''} "
             "Resolva e clique em Retomar; o processo volta para a fila sem perder tentativa.")
    if isinstance(resumo, dict):
        _log(f"coletados {resumo.get('coletado', 0)} de {resumo.get('total', 0)}; "
             f"pendentes {resumo.get('pendente', 0)}; erros {resumo.get('erro', 0)}; manuais {resumo.get('manual', 0)}")


def _trabalho(fila_mod, fila, coletor, slug):
    """Corpo da thread de coleta. No modo contínuo, quando `rodar_fila` volta com processos pendentes (fora da
    janela de horário), espera e tenta de novo até acabar, pausar ou parar."""
    try:
        embrulhado = _ColetorComGanchos(coletor, slug)
        while True:
            _ESPERA.clear()
            EXEC["estado"] = "rodando"
            fila_mod.rodar_fila(fila, embrulhado, ao_progresso=_progresso)
            if EXEC["pedido"] in ("pausa", "parada"):
                break
            pendentes = (fila.resumo() or {}).get("pendente", 0)
            if EXEC["modo"] != "continuo" or not pendentes:
                break
            EXEC["estado"] = "aguardando"
            _ESPERA.wait(INTERVALO_DA_JANELA_S)
            if EXEC["pedido"] in ("pausa", "parada"):
                break
        for gancho in list(AO_CONCLUIR):        # o que foi coletado vira rascunho para a revisão, mesmo se parou no meio
            try:
                gancho(slug)
            except Exception as erro:  # noqa: BLE001
                _log(f"gancho {getattr(gancho, '__name__', gancho)} falhou: {erro}")
        EXEC["estado"] = {"pausa": "pausada", "parada": "parada"}.get(EXEC["pedido"], "concluida")
        _log(f"coleta {ROTULO_DA_EXECUCAO[EXEC['estado']]}")
    except Exception as erro:  # noqa: BLE001
        EXEC["estado"], EXEC["erro"] = "erro", str(erro)
        _log(f"erro na coleta: {erro}")
    finally:
        fechar = getattr(coletor, "fechar", None)       # o navegador da coleta não fica aberto depois da rodada
        if callable(fechar):
            try:
                fechar()
            except Exception as erro:  # noqa: BLE001
                _log(f"não consegui fechar o navegador: {erro}")
        _fechar_log_da_coleta()


def iniciar_execucao():
    """Começa (ou continua) a coleta da fila do relatório ativo. Devolve (ok, mensagem)."""
    if execucao_rodando():
        return False, "A coleta já está em andamento."
    if _tarefa_rodando():
        return False, "Há uma tarefa da tela Atualizar em andamento (as duas usam o mesmo acesso). Espere ou interrompa."
    if not comum.PROJETO:
        return False, "Não há relatório aberto. Importe relatórios ou crie um novo relatório para começar."
    try:
        fila_mod = modulo("fila", "A fila de coleta")
        coletor = _criar_coletor()
        fila = ent.abrir_fila()
    except Indisponivel as erro:
        return False, str(erro)
    EXEC["log"].clear()
    EXEC.update(slug=comum.PROJETO, fila=fila, estado="rodando", pedido=None, erro=None, resumo=None,
                inicio=f"{datetime.datetime.now():%H:%M}", modo=per.carregar()["modo_coleta"])
    _abrir_log_da_coleta()
    EXEC["thread"] = threading.Thread(target=_trabalho, args=(fila_mod, fila, coletor, comum.PROJETO), daemon=True)
    EXEC["thread"].start()
    return True, "Coleta iniciada. Acompanhe por aqui; pode fechar a página, mas deixe o programa aberto."


def _fila_da_execucao():
    return EXEC["fila"] if EXEC["slug"] == comum.PROJETO and EXEC["fila"] is not None else ent.abrir_fila()


def situacao_da_execucao():
    """O que a tela de progresso mostra, em dicionário (também serve o .json)."""
    minha = EXEC["slug"] == comum.PROJETO
    s = {"estado": EXEC["estado"] if minha else "parado", "erro": EXEC["erro"] if minha else None,
         "inicio": EXEC["inicio"] if minha else None, "log": list(EXEC["log"]) if minha else [],
         "resumo": None, "aviso": None, "cobertura": None, "taxa": None}
    try:
        s["resumo"] = _fila_da_execucao().resumo()
    except Indisponivel as erro:
        s["aviso"] = str(erro)
    except Exception as erro:  # noqa: BLE001
        s["aviso"] = f"Não consegui ler a fila ({erro})."
    try:
        s["cobertura"] = modulo("fila", "A fila de coleta").cobertura(comum.PROJETO)
    except Exception:  # noqa: BLE001
        s["cobertura"] = None
    try:
        s["taxa"] = modulo("fila", "A fila de coleta").taxa_de_sucesso(comum.PROJETO)
    except Exception:  # noqa: BLE001
        s["taxa"] = None
    return s


def _pedir(acao):
    """Pausar, retomar ou parar com segurança. Devolve a mensagem."""
    try:
        fila = _fila_da_execucao()
    except Indisponivel as erro:
        return str(erro)
    if acao == "pausar":
        fila.pausar()
        EXEC["pedido"], EXEC["estado"] = "pausa", "pausada"
        _ESPERA.set()
        return "Coleta em pausa. O processo atual termina e o resto espera."
    if acao == "parar":
        fila.parar_com_seguranca()
        EXEC["pedido"] = "parada"
        EXEC["estado"] = "parando" if execucao_rodando() else "parada"
        _ESPERA.set()
        return "Parando com segurança: o processo atual termina e tudo fica gravado."
    fila.retomar()
    EXEC["pedido"] = None
    if execucao_rodando():
        EXEC["estado"] = "rodando"
        return "Coleta retomada."
    return iniciar_execucao()[1]


# ================================================================ modos de trabalho: montagem completa x atualização leve

def _fluxos():
    return modulo("fluxos", "Os modos de trabalho")


AJUDA_DOS_MODOS = ("O relatório tem dois modos de trabalho. MONTAGEM COMPLETA: para montar o relatório pela primeira vez (ou quando chega "
                   "um relatório desformatado): traz o histórico todo, todos os documentos, resume tudo com a IA e gera as três entregas. "
                   "ATUALIZAÇÃO LEVE: para os meses seguintes: traz só o que é novo desde a data-base, não refaz resumos nem baixa de novo "
                   "o que já existe. Você pode ajustar cada detalhe em \"Opções avançadas\".")


def _tempo_para(n):
    """Frase de duração para n processos pela média medida da fila (ou o padrão dela); '' se não der para calcular."""
    try:
        return duracao_humana(ent.abrir_fila().estimativa(n)) if n else ""
    except Exception:  # noqa: BLE001 - a estimativa é só um enfeite: nunca derruba a tela
        return ""


def quadro_dos_modos(fichas=None):
    """Quadro simples "Montagem completa x Atualização leve" (o que cada um faz, quanto leva, se usa IA, o que baixa)."""
    ativos = [f for f in (fichas or []) if f.get("ativo", True)]
    sem_rel = [f for f in ativos if not f.get("linha_de_base")]
    n_comp = len(sem_rel) or len(ativos)
    t_comp, t_leve = _tempo_para(n_comp), _tempo_para(len(ativos))
    tempo_comp = ("Mais demorada: lê tudo de cada processo."
                  + (f" Pela média deste computador, para {n_comp} processo(s): {t_comp} ou mais." if t_comp else ""))
    tempo_leve = ("Bem mais rápida: só olha o que mudou."
                  + (f" Pela média deste computador, para {len(ativos)} processo(s): até {t_leve}." if t_leve else ""))
    linhas = [
        ("Para que serve", "Montar o relatório pela primeira vez, ou quando chega um relatório desformatado.",
         "Os ciclos seguintes (por exemplo, todo mês): acrescentar só o que mudou.",
         "Use a montagem completa quando o processo ainda não tem um relatório seu; a atualização leve, quando já tem."),
        ("O que busca nos tribunais", "O histórico todo de cada processo.", "Só o que veio depois da data-base (a data do último relatório).",
         "A data-base é até quando o relatório anterior está em dia. Na leve, tudo o que é mais antigo não é buscado de novo."),
        ("Documentos que baixa", "Todos (leitura completa).", "Só os novos: os principais (leitura padrão) ou nenhum (leitura rápida).",
         "Leitura rápida: capa e movimentações, sem abrir documentos. Padrão: também os principais (inicial, sentenças, acórdãos, decisões). "
         "Completa: todos."),
        ("2º grau e TST", "Lidos sempre que o processo mostra sinal de recurso.", "Lidos sempre que o processo mostra sinal de recurso.",
         "É o próprio leitor do PJe que decide, olhando os andamentos (remessa, recurso, relator, acórdão). Vale nos dois modos."),
        ("Resumos por IA", "Sim: um resumo para cada documento baixado (uma chamada à IA por documento, às vezes duas).",
         "Sim, mas só nos documentos novos: o que já tem resumo não é refeito.",
         "A IA só resume documentos que ainda não têm resumo. Se o relatório usa IA externa, só com o seu consentimento, por cliente; sem ele, "
         "a IA roda neste computador. Dá para desligar em Opções avançadas."),
        ("Consolidação da ficha", "Sim: calcula o momento atual e o último andamento de cada processo.", "Sim, só dos processos que tiveram novidade.",
         "É o passo que deixa a ficha do processo em dia com o que foi coletado."),
        ("Entregas", "As três: texto (Word), planilha e painel.", "As que você já escolheu no Perfil.",
         "Para refazer só a planilha e os painéis sem coletar nada, use o atalho \"Atualizar planilha e painéis agora\"."),
        ("Quanto costuma levar", tempo_comp, tempo_leve,
         "A estimativa vem do tempo médio medido por processo neste computador (ou de um valor padrão, se ainda não houve coleta). A coleta "
         "faz pausas de propósito entre os processos."),
    ]
    corpo = "".join(f"<tr><td>{_e(a)}{ajuda(d)}</td><td>{_e(b)}</td><td>{_e(c)}</td></tr>" for a, b, c, d in linhas)
    return ("<h2>Montagem completa x Atualização leve" + ajuda(AJUDA_DOS_MODOS) + "</h2>"
            "<table class='t quadro'><tr><th></th><th>Montagem completa</th><th>Atualização leve</th></tr>" + corpo + "</table>")


def _radio(nome, valor, rotulo, marcado):
    return f"<label class='opcao'><input type='radio' name='{nome}' value='{_e(valor)}' {'checked' if marcado else ''}> {_e(rotulo)}</label> "


def bloco_de_modos(escolhido, p, *, completo=True):
    """Escolha principal das telas do Assistente: os dois modos (cartões) e, em "Opções avançadas", cada valor do modo.
    Os campos avançados começam em "conforme o modo escolhido" (valor vazio): o servidor usa o do modo, então não depende
    de JavaScript. `completo=False` mostra só os cartões (primeira tela da atualização, antes da conferência)."""
    fluxos = _fluxos()
    todas = ",".join(fluxos.ENTREGAS)
    doperfil = ",".join(p["entregas"])
    ajuda_completa = ("Para montar o relatório pela primeira vez, ou quando chega um relatório desformatado. Busca o histórico todo, "
                      "baixa todos os documentos, resume cada um com a IA, calcula a ficha de cada processo e prepara as três entregas. "
                      "É a mais demorada.")
    ajuda_leve = ("Para os meses seguintes. Busca só o que é novo desde a data-base, baixa só os documentos novos, resume só o que "
                  "ainda não tem resumo e gera as entregas que você escolheu. Bem mais rápida.")
    ajuda_leitura = ("Quanto abrir de cada processo na atualização leve. Padrão baixa os documentos principais novos; Rápida só lê a capa "
                     "e as movimentações (não abre documentos, então não há resumos por IA).")
    cartoes = (
        "<div class='modos'>"
        f"<label class='modo'><input type='radio' name='preset' value='completa' {'checked' if escolhido == 'completa' else ''} "
        f"data-entregas='{_e(todas)}'> <b>Montagem completa</b>{ajuda(ajuda_completa)}"
        "<span class='dica'>Primeira vez, ou relatório desformatado: histórico todo, todos os documentos, resumo por IA e as três entregas.</span></label>"
        f"<label class='modo'><input type='radio' name='preset' value='leve' {'checked' if escolhido == 'leve' else ''} "
        f"data-entregas='{_e(doperfil)}'> <b>Atualização leve</b>{ajuda(ajuda_leve)}"
        "<span class='dica'>Os ciclos seguintes: só o novo desde a data-base, sem refazer resumos nem baixar de novo o que já existe.</span>"
        "<span class='dica'>Leitura: <select name='profundidade_leve' aria-label='Leitura da atualização leve'>"
        "<option value='padrao' selected>Padrão (documentos principais)</option><option value='rapido'>Rápida (só movimentações)</option></select>"
        f"{ajuda(ajuda_leitura)}</span></label>"
        "</div>")
    if not completo:
        return cartoes
    sel = lambda nome, opcoes: (f"<select name='{nome}'>" + "".join(f"<option value='{_e(v)}'>{_e(r)}</option>" for v, r in opcoes) + "</select>")
    conforme = ("", "Conforme o modo escolhido")
    avancado = (
        "<details class='avancado'><summary>Opções avançadas</summary>"
        + ajuda("Cada modo já traz valores prontos. Aqui você muda um deles só para esta coleta. Deixe em \"conforme o modo escolhido\" "
                "para usar o que o modo define.") +
        "<fieldset><legend><b>Profundidade</b>"
        + ajuda("Quanto o programa lê de cada processo. \"Rápido\" só olha a capa e as movimentações. \"Padrão\" também baixa os "
                "documentos principais (inicial, sentenças, acórdãos, decisões). \"Completo\" baixa todos: demora bem mais. "
                "A escolha fica salva no Perfil do relatório.") + "</legend>"
        + _radio("profundidade", "", "Conforme o modo escolhido (completa: Completo; leve: Padrão ou Rápido)", True)
        + "".join(_radio("profundidade", k, v, False) for k, v in per.PROFUNDIDADES.items()) + "</fieldset>"
        "<p><label>Quanto histórico "
        + sel("historico", [conforme, ("todo", "O histórico todo do processo"), ("novo", "Só o novo desde a data-base")])
        + "</label>" + ajuda("\"O histórico todo\" ignora a data-base e traz o processo desde o início (o que já está gravado não é duplicado). "
                             "\"Só o novo\" traz apenas o que veio depois da data-base. Num processo que o programa nunca leu e sem data-base, "
                             "vem tudo de qualquer jeito.") + "</p>"
        "<p><label>Resumos por IA "
        + sel("resumos_ia", [conforme, ("sim", "Sim, nos documentos novos que ainda não têm resumo"), ("nao", "Não: só as frases automáticas")])
        + "</label>" + ajuda("Quando a IA resume o documento. Ligado, ela resume só o que ainda não tem resumo (nunca refaz o que já existe). "
                             "Desligado, a coleta não chama a IA: cada documento fica só com a frase automática e você resume à mão na revisão.")
        + "</p>"
        "<p><label>Consolidar a ficha "
        + sel("sintese", [conforme, ("sim", "Sim: momento atual e último andamento"), ("nao", "Não, deixar a ficha como está")])
        + "</label>" + ajuda("Depois da coleta, calcula o momento atual e o último andamento de cada processo a partir do que foi coletado. "
                             "Desligar deixa a ficha como estava (você pode ajustar à mão em Clientes e processos).") + "</p>"
        "<p class='dica'>2º grau e TST: o programa lê o 2º grau e o TST sempre que o processo mostra sinal de recurso, nos dois modos."
        + ajuda("Quem decide é o leitor do PJe, olhando os andamentos. Não há botão para forçar: forçar leria o 2º grau de processos que "
                "nunca saíram do 1º grau e geraria avisos sem sentido.") + "</p>"
        "</details>")
    script = ("<script>(function(){var f=document.currentScript.closest('form');if(!f)return;"
              "f.querySelectorAll('input[name=preset]').forEach(function(r){r.addEventListener('change',function(){"
              "var l=(r.getAttribute('data-entregas')||'').split(',');"
              "f.querySelectorAll('input[name=entregas]').forEach(function(c){c.checked=l.indexOf(c.value)>=0})})})})();</script>")
    return cartoes + avancado + script


def opcoes_do_formulario(form):
    """(form para o perfil, opções do modo | None, erro | None). Sem o campo `preset`, é o comportamento de sempre (None)."""
    preset = form.get("preset")
    fluxos = _fluxos()
    if preset not in fluxos.PRESETS:
        return form, None, None
    sim_nao = {"sim": True, "nao": False}
    try:
        opcoes = fluxos.opcoes_do_preset(
            preset, profundidade=form.get("profundidade") or (form.get("profundidade_leve") if preset == "leve" else None) or None,
            historico=form.get("historico") or None, resumos_ia=sim_nao.get(form.get("resumos_ia")),
            sintese=sim_nao.get(form.get("sintese")))
    except ValueError as erro:
        return form, None, str(erro)
    novo = form.copy()
    novo["profundidade"] = opcoes["profundidade"]
    if "com_entregas" not in novo and opcoes["entregas"]:          # quem não mandou as caixas recebe as do modo
        novo["com_entregas"] = "1"
        novo.setlist("entregas", opcoes["entregas"])
    return novo, opcoes, None


def html_da_estimativa_de_ia(estimativa):
    """Linha(s) da confirmação: quantos resumos por IA se esperam e onde a IA roda."""
    onde = (f"A IA é externa ({_e(str(estimativa['provedor']))}), autorizada por você; os nomes seguem a regra de pseudonimização do Perfil."
            if estimativa["externa"] else "A IA roda neste computador: nenhum texto sai dele.")
    return (f"<p><b>{_e(estimativa['frase'])}</b>"
            + ajuda("A conta é pelos documentos que já estão no relatório e ainda não têm resumo. Quantos documentos a coleta vai trazer só se "
                    "sabe depois de coletar. Cada documento gera uma chamada à IA (duas, se a primeira resposta vier fora do formato). "
                    "Se a IA não responder, o documento vai para a revisão sem resumo, nunca com um resumo inventado.")
            + (f"<br><span class='dica'>{onde}</span>" if estimativa["ia_ligada"] else "") + "</p>")


# ================================================================ rotas

def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def pagina(ativa, titulo, *partes):
        return "".join([cabecalho(ativa), ESTILO_FLUXO, ESTILO_ASSISTENTE, f"<h1>{titulo}</h1>", _msg(), *partes])

    def sem_relatorio(titulo):
        return pagina("fluxo", titulo,
                      agora("Ainda não há um relatório aberto. Escolha um dos caminhos: "
                            "<a href='/fluxo/importar'>importe os relatórios que você já tem</a> (o mais rápido) "
                            "ou <a href='/novo'>crie um relatório novo</a> e cadastre os processos à mão."),
                      "<p class='vazio'>Esta tela precisa de um relatório para funcionar.</p>")

    def campos_da_coleta(p, com_profundidade=True):
        """Escolhas de profundidade, modo e janela (formulários de inicial e atualizar). Nas telas com os modos de trabalho,
        a profundidade fica em "Opções avançadas" (`com_profundidade=False` aqui)."""
        marca = lambda a, b: "checked" if a == b else ""
        h = []
        if com_profundidade:
            h.append("<fieldset><legend><b>Profundidade</b>"
                     + ajuda("Quanto o programa lê de cada processo. \"Rápido\" só olha a capa e as movimentações. \"Padrão\" também baixa os "
                             "documentos principais (inicial, sentenças, acórdãos, decisões). \"Completo\" baixa todos: demora bem mais. "
                             "A escolha fica salva no Perfil do relatório.") + "</legend>")
            for k, v in per.PROFUNDIDADES.items():
                h.append(f"<div class='opcao'><label><input type='radio' name='profundidade' value='{k}' {marca(p['profundidade'], k)}> {_e(v)}</label></div>")
            h.append("</fieldset>")
        h.append("<fieldset><legend><b>Quando coletar</b>"
                 + ajuda("\"Contínuo\": a coleta só trabalha dentro da janela de horário que você definir (ótimo para a noite) e retoma sozinha "
                         "no dia seguinte, desde que o computador e o painel estejam ligados. \"Imediato\": começa agora, depois de uma "
                         "confirmação que mostra quanto tempo deve levar.") + "</legend>")
        for k, v in per.MODOS.items():
            h.append(f"<div class='opcao'><label><input type='radio' name='modo_coleta' value='{k}' {marca(p['modo_coleta'], k)}> {_e(v)}</label></div>")
        j = p["janela_coleta"]
        h.append(f"<p>Janela do modo contínuo: das <input type='text' name='janela_inicio' size='5' value='{_e(j['inicio'])}' placeholder='20:00'> "
                 f"às <input type='text' name='janela_fim' size='5' value='{_e(j['fim'])}' placeholder='06:00'> (HH:MM)"
                 + ajuda("Horário em que a coleta pode trabalhar no modo contínuo. Pode passar da meia-noite (das 20:00 às 06:00). "
                         "Só vale para o modo contínuo; no imediato é ignorado.") + "</p></fieldset>")
        return "".join(h)

    def seguir_para_a_coleta(perfil_do_relatorio, quantidade, extra=""):
        if quantidade == 0:
            return _ir("/fluxo", (extra + "\n" if extra else "") + "Nenhum processo para coletar com esse filtro. Tire o filtro de cliente ou desmarque \"só os processos sem relatório anterior\" e tente de novo.")
        if perfil_do_relatorio["modo_coleta"] == "imediato":
            return _ir("/fluxo/confirmar", extra)
        ok, msg = iniciar_execucao()
        return _ir("/fluxo/progresso", (extra + "\n" if extra else "") + f"{quantidade} processo(s) na fila. {msg}")

    # ------------------------------------------------------------ início

    @app.get("/fluxo")
    def fluxo_inicio_do_assistente():
        if not comum.PROJETO:
            sugestao = ("Você ainda não tem nenhum relatório. Se já tem relatórios prontos (Word, Excel ou uma lista de números), "
                        "comece por <b>Importar relatórios existentes</b>. Se não, crie um relatório em <a href='/novo'>+ Novo relatório</a>.")
        else:
            fichas = ficha.carregar(todas=True)
            novos = sum(1 for f in fichas if f.get("ativo", True) and not f.get("linha_de_base"))
            if not fichas:
                sugestao = ("O relatório está vazio. Cadastre os processos em <a href='/cadastro'>Clientes e processos</a> "
                            "ou use <b>Importar relatórios existentes</b>.")
            elif novos:
                sugestao = (f"{novos} processo(s) ainda não têm relatório anterior. O próximo passo é <b>Elaborar relatório inicial</b> "
                            "no modo <b>Montagem completa</b>: o programa busca o histórico deles nos tribunais e monta o primeiro texto.")
            else:
                sugestao = ("Seus processos já têm relatório anterior. Para acrescentar o que mudou desde a última vez, use "
                            "<b>Atualizar relatório</b> no modo <b>Atualização leve</b>. Depois, revise os resumos e gere as entregas.")
        h = [agora(sugestao, ajuda_texto="É uma sugestão baseada no estado do seu relatório. Você pode escolher qualquer outro caminho; "
                                         "nada começa sozinho e nenhum botão desta tela consulta tribunal."),
             "<div class='botoes-grandes'>"
             "<div class='botao-embrulho'><a class='botao-grande' href='/fluxo/importar'><b>Importar relatórios existentes</b>"
             "<span class='dica'>Já tenho relatórios prontos (Word, Excel ou uma lista de números) e quero que o programa passe a acompanhá-los.</span></a>"
             + ajuda("Você escolhe os arquivos e o programa mostra o que entendeu antes de gravar qualquer coisa. Tudo é lido neste computador. "
                     "O que já está escrito nos relatórios antigos vira o histórico e não é buscado de novo.") + "</div>"
             "<div class='botao-embrulho'><a class='botao-grande' href='/fluxo/inicial'><b>Elaborar relatório inicial</b>"
             "<span class='dica'>Tenho os processos, mas ainda não tenho relatório. O programa busca tudo e monta o primeiro.</span></a>"
             + ajuda("Escolhe o que entregar e quanto ler de cada processo, e depois coloca os processos na fila de coleta. A coleta entra no "
                     "jus.br e nos TRTs com o seu certificado (só leitura). Só começa depois de você clicar em \"Preparar a coleta\".") + "</div>"
             "<div class='botao-embrulho'><a class='botao-grande' href='/fluxo/atualizar'><b>Atualizar relatório</b>"
             "<span class='dica'>Já tenho o relatório do mês passado e quero acrescentar o que mudou.</span></a>"
             + ajuda("Você envia o último relatório (Word e/ou planilha); o programa confere com a carteira e busca só o que veio depois "
                     "da data-base. O arquivo que você enviou nunca é sobrescrito.") + "</div>"
             "<div class='botao-embrulho'><a class='botao-grande' href='/migracao'><b>Migrar de modelo</b>"
             "<span class='dica'>Meu relatório está num formato diferente e quero passá-lo para os modelos do programa.</span></a>"
             + ajuda("Converte um relatório de outro formato para os modelos do programa (texto, planilha, painel). Trabalha em cópias; "
                     "o original não muda e não se consulta tribunal.") + "</div></div>"]
        h.append("<h2>Dois jeitos de trabalhar" + ajuda(AJUDA_DOS_MODOS) + "</h2><div class='modos'>"
                 "<div class='botao-embrulho'><a class='botao-grande modo-link' href='/fluxo/inicial?modo=completa'><b>Montagem completa</b>"
                 "<span class='dica'>Montar o relatório pela primeira vez, ou quando chega um relatório desformatado: histórico todo, "
                 "todos os documentos, resumo por IA e as três entregas.</span></a>"
                 + ajuda("Abre \"Elaborar relatório inicial\" já no modo Montagem completa. Nada é consultado até você clicar em \"Preparar a coleta\".")
                 + "</div><div class='botao-embrulho'><a class='botao-grande modo-link' href='/fluxo/atualizar?modo=leve'><b>Atualização leve</b>"
                 "<span class='dica'>Os ciclos seguintes: só o novo desde a data-base, sem refazer resumos nem baixar de novo o que já existe.</span></a>"
                 + ajuda("Abre \"Atualizar relatório\" já no modo Atualização leve. Nada é consultado até você clicar em \"Preparar a coleta\".")
                 + "</div></div>")
        h.append(quadro_dos_modos(ficha.carregar(todas=True) if comum.PROJETO else []))
        if comum.PROJETO:
            fichas = ficha.carregar(todas=True)
            novos = sum(1 for f in fichas if not f.get("linha_de_base"))
            h.append(f"<div class='caixa'><b>Relatório atual: {_e(comum.projeto().get('nome', comum.PROJETO))}</b>"
                     f"<p>{len(fichas)} processo(s); {novos} sem relatório anterior (precisam do relatório inicial)."
                     + ajuda("\"Sem relatório anterior\" são processos que o programa ainda não leu nos tribunais nem em relatório antigo. "
                             "Para eles, use \"Elaborar relatório inicial\".") + "</p>"
                     "<p><a href='/fluxo/progresso'>Ver a coleta</a>"
                     + ajuda("Mostra se há coleta em andamento, quantos processos já foram feitos e o que precisa de você.")
                     + " · <a href='/'>Revisar andamentos</a>"
                     + ajuda("Onde você confere cada resumo com o print e o documento e aprova, corrige ou descarta. Só o aprovado entra no relatório.")
                     + " · <a href='/entregas'>Entregas</a>"
                     + ajuda("Gera os arquivos do relatório (Word, planilha, painel) com o que já foi aprovado.")
                     + " · <a href='/perfil'>Perfil</a>"
                     + ajuda("As preferências deste relatório: o que entregar, quanto ler de cada processo e quando coletar.")
                     + "</p></div>")
            h.append(ent.html_do_atalho(oculto, per.carregar(), "/fluxo"))
        else:
            h.append("<p class='vazio'>Quando houver um relatório, aparece aqui o atalho \"Atualizar planilha e painéis agora (sem coletar)\".</p>")
        return pagina("fluxo", "O que você quer fazer?", *h)

    # ------------------------------------------------------------ importar

    @app.get("/fluxo/importar")
    def fluxo_importar():
        return pagina("fluxo", "Importar relatórios existentes",
                      trilha("importar", 1),
                      agora("Escolha os arquivos dos relatórios que o escritório já tem e clique em <b>Ler os arquivos</b>. "
                            "Nada é gravado agora: na próxima tela você confere o que o programa entendeu.",
                            ajuda_texto="Esta etapa só lê os arquivos dentro deste computador. Nenhum tribunal é consultado e nada vai para a internet."),
                      f"<form class='caixa' method='post' action='/fluxo/importar/enviar' enctype='multipart/form-data'>{oculto}"
                      "<p>Arraste os arquivos para a caixa abaixo (ou clique nela para escolher). Pode enviar vários de uma vez: "
                      "relatórios em Word (.docx), planilhas (.xlsx), listas (.csv, .txt)."
                      + ajuda("Aceita Word (.docx), planilhas (.xlsx), listas de números de processo (.csv, .txt) e texto (.md). Os arquivos são "
                              "copiados para uma pasta temporária deste computador e apagados sozinhos depois de alguns dias se você não confirmar. "
                              "Os originais não são alterados.") + "</p>"
                      "<div class='zona'><input type='file' name='arquivos' multiple accept='.docx,.xlsx,.csv,.txt,.md' required "
                      "aria-label='Arquivos para importar'></div>"
                      "<p class='dica'>O programa reconhece o formato e mostra o que leu antes de guardar qualquer coisa. "
                      "Só tem uma lista de números de processo? Também serve.</p>"
                      "<button class='principal'>Ler os arquivos</button>"
                      + ajuda("Envia os arquivos para o painel (que roda neste computador), reconhece o formato e lê os processos. Em seguida abre a "
                              "tela de conferência. Ainda não cria relatório nem ficha: dá para desistir sem consequência.")
                      + "</form>")

    @app.post("/fluxo/importar/enviar")
    def fluxo_importar_enviar():
        token_ok()
        lote, pasta = novo_lote()
        aceitos, rejeitados = salvar_envios(request.files.getlist("arquivos"), pasta)
        if not aceitos and not rejeitados:
            return _ir("/fluxo/importar", "Escolha pelo menos um arquivo.")
        try:
            lidos = ler_arquivos(aceitos, rejeitados)
        except Indisponivel as erro:
            return _ir("/fluxo/importar", str(erro))
        if not lidos:
            motivos = "\n".join(f"{r['nome']}: {r['motivo']}" for r in rejeitados)
            return _ir("/fluxo/importar", "Não consegui usar nenhum dos arquivos.\n" + motivos)
        fichas, avisos, resumos = tratar_leituras(lidos)
        gravar_lote(pasta, "lote.json", {"tipo": "importar", "arquivos": resumos, "rejeitados": rejeitados})
        gravar_lote(pasta, "fichas.json", fichas)
        gravar_lote(pasta, "avisos.json", avisos)
        return _ir(f"/fluxo/importar/conferir?lote={lote}")

    @app.get("/fluxo/importar/conferir")
    def fluxo_importar_conferir():
        pasta = pasta_do_lote(request.args.get("lote", ""))
        dados, fichas, avisos = ler_lote(pasta, "lote.json"), ler_lote(pasta, "fichas.json"), ler_lote(pasta, "avisos.json")
        if dados is None or fichas is None or dados.get("tipo") != "importar":
            abort(404)
        bases = [r["cliente"] for r in dados["arquivos"] if r.get("cliente")]
        sugerido = bases[0] if bases else (clientes_da_carteira(fichas) or ["Relatório importado"])[0]
        corpo = html_da_conferencia(dados["arquivos"], dados["rejeitados"], fichas, avisos, oculto, pasta.name, sugerido, bool(comum.PROJETO))
        return pagina("fluxo", "Conferência da migração", trilha("importar", 2),
                      agora("Leia o resumo, olhe as listas de avisos (números inválidos, nomes parecidos, colunas sem destino) e, no fim da página, "
                            "dê um nome ao relatório e clique em <b>Confirmar e criar o relatório</b>. Se algo estiver errado, "
                            "<a href='/fluxo/importar'>volte e envie os arquivos de novo</a>.",
                            ajuda_texto="Aqui você decide o que entra. Enquanto não confirmar, nada foi gravado: pode fechar a página sem consequência."),
                      corpo)

    @app.post("/fluxo/importar/confirmar")
    def fluxo_importar_confirmar():
        token_ok()
        pasta = pasta_do_lote(request.form.get("lote", ""))
        dados, fichas, avisos = ler_lote(pasta, "lote.json"), ler_lote(pasta, "fichas.json"), ler_lote(pasta, "avisos.json")
        if dados is None or fichas is None or dados.get("tipo") != "importar":
            abort(404)
        if dados.get("confirmado"):
            return _ir("/fluxo", "Este envio já foi confirmado.")
        if not fichas:
            return _ir(f"/fluxo/importar/conferir?lote={pasta.name}", "Não há processos para criar.")
        nome = request.form.get("nome", "").strip()
        if not nome:
            return _ir(f"/fluxo/importar/conferir?lote={pasta.name}", "Dê um nome ao relatório.")
        trocas = aplicar_grafias(fichas, avisos, request.form)
        identificacao = identificar_clientes_do_formulario(fichas, request.form)
        if request.form.get("destino") == "atual" and comum.PROJETO:
            adicionadas, atualizadas = mesclar_no_atual(fichas)
            for a in dados["arquivos"]:
                copiar_para_entrada(a["caminho"], a["nome"])
            registrar_clientes(ficha.carregar(todas=True))
            msg = f"Acrescentei ao relatório atual: {adicionadas} processo(s) novo(s) e {atualizadas} já existente(s) completado(s)."
            slug = comum.PROJETO
        else:
            slug = criar_relatorio(nome, fichas, dados["arquivos"], dados["arquivos"])
            msg = f"Relatório criado: {nome}. {len(fichas)} processo(s) importado(s)."
        if trocas:
            msg += f"\n{trocas} nome(s) padronizado(s) conforme a sua escolha."
        if identificacao:
            msg += "\n" + identificacao
        novos = sum(1 for f in fichas if not f.get("linha_de_base"))
        if novos:
            msg += (f"\n{novos} processo(s) novos, sem relatório anterior: precisam do relatório inicial."
                    "\nPróximo passo: clique em \"Elaborar relatório inicial\".")
        else:
            msg += "\nPróximo passo: clique em \"Atualizar relatório\" para buscar o que mudou desde a data-base."
        dados["confirmado"] = slug
        gravar_lote(pasta, "lote.json", dados)
        return _com_cookie(_ir("/fluxo", msg), slug)

    # ------------------------------------------------------------ elaborar inicial

    @app.get("/fluxo/inicial")
    def fluxo_inicial():
        if not comum.PROJETO:
            return sem_relatorio("Elaborar relatório inicial")
        fichas = ficha.carregar(todas=True)
        p = per.carregar()
        novos = sum(1 for f in fichas if f.get("ativo", True) and not f.get("linha_de_base"))
        if not fichas:
            return pagina("fluxo", "Elaborar relatório inicial",
                          agora("Este relatório ainda não tem processos. <a href='/cadastro'>Cadastre os processos</a> ou "
                                "<a href='/fluxo/importar'>importe seus relatórios</a> primeiro."),
                          "<p class='vazio'>Sem processos, não há o que coletar.</p>")
        modo = "leve" if request.args.get("modo") == "leve" else "completa"
        marcadas = _fluxos().ENTREGAS if modo == "completa" else p["entregas"]
        h = [trilha("inicial", 1),
             agora("Escolha o modo de trabalho (o primeiro serve para montar o relatório pela primeira vez), o que quer receber e como a "
                   "coleta deve trabalhar, e clique em <b>Preparar a coleta</b>. Os valores sugeridos servem para a maioria dos casos.",
                   "Enquanto você está nesta tela, nada é consultado nos tribunais: a coleta só começa depois do clique (no modo imediato, "
                   "ainda há uma tela de confirmação com a estimativa de tempo).",
                   ajuda_texto="O programa lê (só leitura) os processos no jus.br e nos TRTs com o seu certificado, resume os documentos com a IA "
                               "e deixa tudo como rascunho em Revisar. Nada é protocolado, assinado nem enviado."),
             f"<form class='caixa' method='post' action='/fluxo/inicial/preparar' onsubmit=\"return confirm('Gravar estas escolhas no Perfil do "
             "relatório e colocar os processos na fila de coleta? No modo contínuo a coleta já começa a rodar (dentro da janela de horário); "
             "no imediato você ainda confirma na próxima tela.')\">" + oculto,
             f"<p>Relatório: <b>{_e(comum.projeto().get('nome', ''))}</b> · {len(fichas)} processo(s), {novos} sem relatório anterior."
             + ajuda("\"Sem relatório anterior\" são os processos que ainda não foram lidos nos tribunais nem constam de relatório antigo: "
                     "são os que mais precisam deste fluxo.") + "</p>",
             "<input type='hidden' name='com_entregas' value='1'><fieldset><legend><b>O que entregar</b>"
             + ajuda("Os arquivos que o programa vai montar no fim, com o que você aprovar: texto em Word (.docx), planilha (.xlsx) e painel "
                     "com gráficos (.html). Marque pelo menos um. Dá para gerar de novo, depois, na tela Entregas.") + "</legend>"]
        for k, v in per.ENTREGAS.items():
            h.append(f"<div class='opcao'><label><input type='checkbox' name='entregas' value='{k}' {'checked' if k in marcadas else ''}> {_e(v)}</label></div>")
        h.append("</fieldset>")
        i_entregas = next(k for k, x in enumerate(h) if x.startswith("<input type='hidden' name='com_entregas'"))
        h.insert(i_entregas, "<h3>Como trabalhar" + ajuda(AJUDA_DOS_MODOS) + "</h3>" + bloco_de_modos(modo, p))
        h.append(campos_da_coleta(p, com_profundidade=False))
        opcoes = "".join(f"<option value='{_e(c)}'>{_e(c)}</option>" for c in clientes_da_carteira(fichas))
        h.append("<details><summary>Filtros (opcional)"
                 + (": por padrão, só os processos sem relatório anterior" if novos else "") + "</summary>"
                 f"<p><label>Só este cliente <select name='cliente'><option value=''>todos</option>{opcoes}</select></label>"
                 + ajuda("Coleta apenas os processos desse cliente. Útil para testar com um cliente antes de rodar a carteira inteira.") + "</p>"
                 f"<p><label><input type='checkbox' name='so_novos' value='1' {'checked' if novos else ''}> "
                 "só os processos que ainda não têm relatório anterior</label>"
                 + ajuda("Deixa de fora os processos que já constam de um relatório antigo. Desmarque para coletar todos os processos ativos.")
                 + "</p></details>"
                 "<p><button class='principal'>Preparar a coleta</button>"
                 + ajuda("Grava estas escolhas no Perfil do relatório e põe os processos selecionados na fila. No modo contínuo a coleta começa a "
                         "rodar já (entrando no jus.br com o certificado), mas só trabalha dentro da janela de horário. No imediato, você vê a "
                         "estimativa de tempo e confirma antes. Pode pausar ou parar com segurança depois.")
                 + "</p></form>")
        h.append("<details class='avancado'><summary>Ver o quadro Montagem completa x Atualização leve</summary>"
                 + quadro_dos_modos(fichas) + "</details>")
        return pagina("fluxo", "Elaborar relatório inicial", *h)

    @app.post("/fluxo/inicial/preparar")
    def fluxo_inicial_preparar():
        token_ok()
        if not comum.PROJETO:
            return _ir("/fluxo", "Não há relatório aberto. Importe relatórios ou crie um novo relatório para começar.")
        form, opcoes, erro_modo = opcoes_do_formulario(request.form)
        if erro_modo:
            return _ir("/fluxo/inicial", "Corrija antes de continuar:\n" + erro_modo)
        perfil_novo, erros = per.aplicar_formulario(per.carregar(), form, parcial=True)
        if erros:
            return _ir("/fluxo/inicial", "Corrija antes de continuar:\n" + "\n".join(erros))
        per.salvar(perfil_novo)
        _fluxos().guardar_opcoes(opcoes)              # sem modo escolhido: limpa, e tudo corre como sempre
        fichas = ficha.carregar(todas=True)
        selecionadas = selecionar_processos(fichas, request.form.get("cliente", ""), bool(request.form.get("so_novos")))
        try:
            _, quantidade = (enfileirar(selecionadas, perfil_novo, historico_todo=bool(opcoes and opcoes["historico"] == "todo"))
                             if selecionadas else (None, 0))
        except Indisponivel as erro:
            return _ir("/fluxo/inicial", str(erro))
        return seguir_para_a_coleta(perfil_novo, quantidade, f"Modo: {opcoes['nome']}." if opcoes else "")

    # ------------------------------------------------------------ atualizar

    @app.get("/fluxo/atualizar")
    def fluxo_atualizar():
        if not comum.PROJETO:
            return sem_relatorio("Atualizar relatório")
        modo = "completa" if request.args.get("modo") == "completa" else "leve"
        return pagina("fluxo", "Atualizar relatório",
                      trilha("atualizar", 1),
                      agora("Envie o relatório mais recente (o que você mandou ao cliente no mês passado) e clique em <b>Conferir com a carteira</b>. "
                            "Se não tiver o arquivo à mão, clique no mesmo botão sem escolher nada.",
                            "Esta tela só lê o arquivo neste computador. Nada é buscado nos tribunais antes da próxima tela de conferência.",
                            ajuda_texto="Aqui ainda não há coleta. O arquivo serve para o programa saber o que já foi dito ao cliente e a partir de que "
                                        "data buscar o que é novo."),
                      f"<form class='caixa' method='post' action='/fluxo/atualizar/enviar' enctype='multipart/form-data'>{oculto}"
                      "<p>Solte aqui o relatório mais recente: o Word (.docx), a planilha (.xlsx), ou os dois. Basta um; o outro "
                      "é refeito a partir dos dados. O painel (HTML) não precisa ser enviado."
                      + ajuda("O programa lê o arquivo, descobre a data-base (a data do último relatório) e compara com a carteira. O arquivo enviado "
                              "nunca é sobrescrito: no fim saem cópias novas. Tudo fica neste computador.") + "</p>"
                      "<div class='zona'><input type='file' name='arquivos' multiple accept='.docx,.xlsx' aria-label='Relatório mais recente'></div>"
                      "<p class='dica'>Sem arquivo, o programa só coleta o que mudou desde o último relatório de cada processo.</p>"
                      "<h3>Como trabalhar" + ajuda(AJUDA_DOS_MODOS) + "</h3>" + bloco_de_modos(modo, per.carregar(), completo=False) +
                      "<p class='dica'>Na próxima tela você ainda pode ajustar cada detalhe em \"Opções avançadas\".</p>"
                      "<button class='principal'>Conferir com a carteira</button>"
                      + ajuda("Lê o arquivo (se enviado) e mostra uma tela de conferência: quais processos são novos, quais sumiram e qual é a data-base. "
                              "Ainda não busca nada nos tribunais.")
                      + "</form>")

    @app.post("/fluxo/atualizar/enviar")
    def fluxo_atualizar_enviar():
        token_ok()
        if not comum.PROJETO:
            return _ir("/fluxo", "Não há relatório aberto. Importe relatórios ou crie um novo relatório para começar.")
        lote, pasta = novo_lote()
        aceitos, rejeitados = salvar_envios(request.files.getlist("arquivos"), pasta, EXTENSOES_ATUALIZAR)
        lidos = []
        if aceitos:
            try:
                lidos = ler_arquivos(aceitos, rejeitados)
            except Indisponivel as erro:
                return _ir("/fluxo/atualizar", str(erro))
        if (aceitos or rejeitados) and not lidos:
            motivos = "\n".join(f"{r['nome']}: {r['motivo']}" for r in rejeitados)
            return _ir("/fluxo/atualizar", "Não consegui usar o arquivo enviado.\n" + motivos)
        fichas_lidas, avisos, dados_lote = montar_lote_de_atualizacao(lidos, rejeitados)
        if request.form.get("preset") in ("completa", "leve"):
            dados_lote["modo"] = request.form["preset"]
            dados_lote["profundidade_leve"] = request.form.get("profundidade_leve") or "padrao"
        gravar_lote(pasta, "lote.json", dados_lote)
        gravar_lote(pasta, "fichas.json", fichas_lidas)
        gravar_lote(pasta, "avisos.json", avisos)
        return _ir(f"/fluxo/atualizar/conferir?lote={lote}")

    @app.get("/fluxo/atualizar/conferir")
    def fluxo_atualizar_conferir():
        pasta = pasta_do_lote(request.args.get("lote", ""))
        dados, avisos = ler_lote(pasta, "lote.json"), ler_lote(pasta, "avisos.json")
        if dados is None or dados.get("tipo") != "atualizar":
            abort(404)
        fichas = ficha.carregar(todas=True)
        p = per.carregar()
        if dados["sem_arquivo"]:
            acao = ("Sem arquivo enviado, o programa vai buscar o que mudou em cada processo desde o último relatório de cada um. "
                    "Escolha as opções da coleta e clique em <b>Preparar a coleta</b>.")
        else:
            acao = ("Confira a <b>data-base</b>, os processos novos e os que sumiram do arquivo. Depois escolha as opções da coleta e clique em "
                    "<b>Preparar a coleta</b>.")
        h = [trilha("atualizar", 2),
             agora(acao, ajuda_texto="Esta é a última tela antes da coleta. Aqui você ainda pode corrigir a data e decidir o que entra. "
                                     "Nada foi buscado nos tribunais até agora."),
             "<form class='caixa' method='post' action='/fluxo/atualizar/preparar' onsubmit=\"return confirm('Preparar a coleta? Os processos "
             "marcados entram na fila e as escolhas ficam gravadas no Perfil. No modo contínuo a coleta já começa a rodar; no imediato você "
             f"confirma na próxima tela.')\">{oculto}<input type='hidden' name='lote' value='{_e(pasta.name)}'>"]
        if dados["sem_arquivo"]:
            h.append("<p>Sem arquivo enviado: vou coletar o que mudou em cada processo da carteira desde o último relatório.</p>")
        else:
            h.append("<table class='t'><tr><th>Arquivo</th><th>Formato</th><th>Processos</th><th>Data-base</th></tr>"
                     + "".join(f"<tr><td>{_e(r['nome'])}</td><td>{_e(ROTULO_FORMATO.get(r['formato'], r['formato']))}</td><td>{r['processos']}</td>"
                               f"<td>{_e(ficha.data_br(r['data_base']) or '-')}</td></tr>" for r in dados["arquivos"]) + "</table>")
            h.append(bloco_de_planilha_fora_do_modelo(dados["arquivos"], pasta.name))
            data_base = dados.get("data_base")
            h.append("<h2>Data-base do relatório"
                     + ajuda("É a data até a qual o relatório que você enviou está em dia. O programa busca só o que veio DEPOIS dela. "
                             "Se a data estiver errada, corrija: uma data mais antiga que a certa traz andamentos repetidos; uma mais recente "
                             "pode deixar andamentos de fora.") + "</h2>"
                     f"<p><label>Data do último relatório: <input type='text' name='data_base' size='12' placeholder='DD/MM/AAAA' "
                     f"value='{_e(ficha.data_br(data_base) if data_base else '')}'></label></p>"
                     + ("<p class='dica'>O programa vai buscar o que veio <b>depois</b> desta data. Já tinha lido a data no arquivo; corrija se estiver errada.</p>"
                        if data_base else
                        "<div class='alerta'><b>O arquivo não traz a data-base.</b> Informe a data do último relatório (DD/MM/AAAA) para o programa buscar só o que "
                        "veio depois dela. Sem a data, ele lê o <b>histórico completo</b> de cada processo que ainda não tem relatório anterior (mais demorado).</div>"))
            h.append(f"<h2>Processos novos no arquivo ({len(dados['novos'])})"
                     + ajuda("Processos que estão no relatório enviado mas ainda não estão na sua carteira. Se marcar a caixa, eles são cadastrados "
                             "e passam a ser acompanhados. Se desmarcar, ficam de fora desta vez.") + "</h2>")
            if dados["novos"]:
                h.append("<p class='dica'>Estão no arquivo e não estão na carteira.</p><ul>"
                         + "".join(f"<li>{_e(n)}</li>" for n in dados["novos"][:100]) + "</ul>"
                         + "<p><label><input type='checkbox' name='incluir_novos' value='1' checked> incluir na carteira e acompanhar</label></p>")
            else:
                h.append("<p class='vazio'>Nenhum: todos os processos do arquivo já estão na carteira.</p>")
            h.append(f"<h2>Processos da carteira que não aparecem no arquivo ({len(dados['sumiram'])})"
                     + ajuda("Processos que você acompanha, mas que não constam do relatório enviado. Podem ter sido encerrados ou retirados "
                             "de propósito. Se desmarcar a caixa, eles não são buscados nesta coleta (continuam na carteira).") + "</h2>")
            if dados["sumiram"]:
                h.append("<p class='dica'>Podem ter sido encerrados ou retirados do relatório. Confira antes de seguir.</p><ul>"
                         + "".join(f"<li>{_e(n)}</li>" for n in dados["sumiram"][:100]) + "</ul>"
                         + "<p><label><input type='checkbox' name='incluir_sumidos' value='1' checked> continuar acompanhando mesmo assim</label></p>")
            else:
                h.append("<p class='vazio'>Nenhum: tudo que está na carteira aparece no arquivo.</p>")
        if avisos:
            h.append("<h2>Avisos da leitura"
                     + ajuda("Pontos que o programa notou ao ler o arquivo. \"Erro\" pede correção; \"atenção\", uma olhada; \"info\" é só informação. "
                             "Nenhum deles impede de continuar.") + "</h2>" + _tabela_de_avisos(list(enumerate(avisos))))
        escolhido = dados.get("modo") or "leve"
        h.append("<h3>Como trabalhar" + ajuda(AJUDA_DOS_MODOS) + "</h3>" + bloco_de_modos(escolhido, p))
        if dados.get("profundidade_leve") == "rapido":
            h[-1] = h[-1].replace("<option value='padrao' selected>", "<option value='padrao'>").replace(
                "<option value='rapido'>", "<option value='rapido' selected>")
        h.append(campos_da_coleta(p, com_profundidade=False))
        opcoes = "".join(f"<option value='{_e(c)}'>{_e(c)}</option>" for c in clientes_da_carteira(fichas))
        h.append(f"<p><label>Só este cliente <select name='cliente'><option value=''>todos</option>{opcoes}</select></label>"
                 + ajuda("Coleta apenas os processos desse cliente. Em \"todos\", entram todos os processos ativos da carteira.") + "</p>"
                 "<p><button class='principal'>Preparar a coleta</button>"
                 + ajuda("Grava as escolhas no Perfil, cadastra os processos novos marcados e põe os processos na fila. Entra no jus.br e nos TRTs "
                         "(só leitura) com o seu certificado. No modo contínuo a coleta começa a rodar já, dentro da janela de horário; no imediato "
                         "você confirma antes. A cópia do arquivo enviado é guardada na pasta de entrada do relatório.")
                 + " <a href='/fluxo'>Cancelar</a>"
                 + ajuda("Volta ao início do Assistente sem gravar nada: nem a cópia do arquivo, nem as escolhas.") + "</p></form>")
        return pagina("fluxo", "Conferência antes de atualizar", *h)

    @app.post("/fluxo/atualizar/preparar")
    def fluxo_atualizar_preparar():
        token_ok()
        if not comum.PROJETO:
            return _ir("/fluxo", "Não há relatório aberto. Importe relatórios ou crie um novo relatório para começar.")
        pasta = pasta_do_lote(request.form.get("lote", ""))
        dados = ler_lote(pasta, "lote.json")
        if dados is None or dados.get("tipo") != "atualizar":
            abort(404)
        form, opcoes, erro_modo = opcoes_do_formulario(request.form)
        if erro_modo:
            return _ir(f"/fluxo/atualizar/conferir?lote={pasta.name}", "Corrija antes de continuar:\n" + erro_modo)
        perfil_novo, erros = per.aplicar_formulario(per.carregar(), form, parcial=True)
        if erros:
            return _ir(f"/fluxo/atualizar/conferir?lote={pasta.name}", "Corrija antes de continuar:\n" + "\n".join(erros))
        per.salvar(perfil_novo)
        _fluxos().guardar_opcoes(opcoes)              # sem modo escolhido: limpa, e tudo corre como sempre
        carteira = ficha.carregar(todas=True)
        incluidos = 0
        if request.form.get("incluir_novos") and dados["novos"]:
            lidas = {f["numero"]: f for f in (ler_lote(pasta, "fichas.json") or [])}
            existentes = {f["numero"] for f in carteira}
            for numero in dados["novos"]:
                if numero in lidas and numero not in existentes:
                    carteira.append(lidas[numero])
                    incluidos += 1
            ficha.salvar(carteira)
            registrar_clientes(carteira)
        for a in dados["arquivos"]:
            copiar_para_entrada(a["caminho"], a["nome"])
        excluir = set() if request.form.get("incluir_sumidos") or not dados["sumiram"] else set(dados["sumiram"])
        selecionadas = selecionar_processos(carteira, request.form.get("cliente", ""), excluir=excluir)
        digitada = request.form.get("data_base", "").strip()
        data_base = ficha.parse_data(digitada) if digitada else dados.get("data_base")
        if digitada and not data_base:
            return _ir(f"/fluxo/atualizar/conferir?lote={pasta.name}", f"Não entendi a data-base '{digitada}'. Use DD/MM/AAAA.")
        try:
            _, quantidade = (enfileirar(selecionadas, perfil_novo, data_base, historico_todo=bool(opcoes and opcoes["historico"] == "todo"),
                                      novo_ciclo=True)
                             if selecionadas else (None, 0))
        except Indisponivel as erro:
            return _ir("/fluxo/atualizar", str(erro))
        avisos_do_envio = [f"{incluidos} processo(s) novo(s) incluído(s) na carteira." if incluidos else "",
                           f"Modo: {opcoes['nome']}." if opcoes else ""]
        return seguir_para_a_coleta(perfil_novo, quantidade, "\n".join(t for t in avisos_do_envio if t))

    # ------------------------------------------------------------ confirmação (modo imediato) e progresso

    @app.get("/fluxo/confirmar")
    def fluxo_confirmar():
        if not comum.PROJETO:
            return sem_relatorio("Confirmar coleta")
        try:
            resumo = ent.abrir_fila().resumo()
        except Indisponivel as erro:
            return pagina("fluxo", "Confirmar coleta", f"<p>{_e(str(erro))}</p>")
        pendentes = resumo.get("pendente", 0)
        fluxos = _fluxos()
        opc = fluxos.opcoes_da_coleta()
        nome_do_modo = fluxos.PRESETS[opc["preset"]]["nome"] if opc.get("preset") in fluxos.PRESETS else ""
        try:
            estimativa_ia = fluxos.estimar_resumos_ia(comum.PROJETO, per.carregar()["profundidade"], opc)
            linha_ia = html_da_estimativa_de_ia(estimativa_ia)
        except Exception:  # noqa: BLE001 - a estimativa nunca derruba a confirmação
            linha_ia = "<p><b>Resumos por IA: não consegui estimar agora.</b></p>"
        return pagina("fluxo", "Confirmar coleta imediata",
                      trilha("coleta", 2),
                      agora("Veja a estimativa de tempo. Se puder deixar o computador e este programa abertos por esse tempo, clique em "
                            "<b>Confirmar e começar agora</b>. Se não, escolha <b>Agora não</b>: os processos ficam na fila.",
                            ajuda_texto="Esta confirmação existe porque a coleta imediata é demorada. Até você confirmar, nada é buscado nos tribunais."),
                      f"<div class='alerta'><b>Atenção:</b> a coleta imediata começa agora e vai levar {_e(duracao_humana(resumo.get('estimativa_s')))} "
                      f"para {pendentes} processo(s). O programa busca um processo por vez, com pausas, para não sobrecarregar o tribunal."
                      + ajuda("A estimativa usa o tempo médio por processo já medido (ou um valor padrão, se ainda não houve coleta) e pode variar. As pausas entre processos são de propósito: imitam o ritmo "
                              "humano e evitam sobrecarregar o jus.br e os TRTs.") + "</div>"
                      + (f"<p><b>Modo de trabalho:</b> {_e(nome_do_modo)}." + ajuda(AJUDA_DOS_MODOS) + "</p>" if nome_do_modo else "")
                      + linha_ia +
                      "<p>Durante a coleta o programa precisa ficar aberto. O PJe Office também, mas só para processos fora da Justiça do Trabalho (a Justiça do Trabalho entra pelo PDPJ). Você pode pausar ou parar com segurança a qualquer momento.</p>"
                      f"<form method='post' action='/fluxo/comecar'>{oculto}<button class='principal'>Confirmar e começar agora</button>"
                      + ajuda("Abre um navegador (minimizado) e entra no jus.br com o seu certificado e o autenticador. Depois consulta os processos "
                              "da fila, um por vez, só para ler. Um aviso vermelho aparece se precisar de você (captcha do TRT, por exemplo). "
                              "O que for baixado não se desfaz, mas nada entra no relatório sem a sua aprovação.")
                      + " <a href='/fluxo/progresso'>Agora não</a>"
                      + ajuda("Não começa nada. Os processos continuam na fila e você pode iniciar depois, na tela Andamento da coleta.")
                      + "</form>"
                      "<p class='dica'>Se escolher \"Agora não\", os processos ficam na fila; dá para começar depois em Progresso.</p>")

    @app.post("/fluxo/comecar")
    def fluxo_comecar():
        token_ok()
        ok, msg = iniciar_execucao()
        return _ir("/fluxo/progresso", msg)

    @app.get("/fluxo/progresso")
    def fluxo_progresso():
        if not comum.PROJETO:
            return sem_relatorio("Andamento da coleta")
        s = situacao_da_execucao()
        r = s["resumo"] or {}
        total = r.get("total", 0)
        feitos = r.get("coletado", 0) + r.get("erro", 0) + r.get("manual", 0)
        estado = s["estado"]
        pendentes_ou_erros = r.get("pendente", 0) or r.get("erro", 0)
        terminou = estado in ("concluida", "parada") or bool(total and feitos >= total and estado not in ("rodando", "aguardando", "parando"))
        j = per.carregar()["janela_coleta"]
        if estado == "rodando":
            acao = ("A coleta está rodando. Pode deixar esta página aberta ou fechá-la, mas <b>mantenha o programa aberto</b> (e o PJe Office, se houver processos fora da Justiça do Trabalho). "
                    "Se aparecer uma faixa vermelha no alto da tela, a coleta está esperando por você (captcha do TRT ou código do jus.br): "
                    "resolva na janela do navegador que se abriu.")
        elif estado == "aguardando":
            acao = (f"A coleta está esperando a janela de horário ({_e(j['inicio'])} às {_e(j['fim'])}). Deixe o computador e o programa ligados: "
                    "ela retoma sozinha. Para começar já, mude para o modo imediato no <a href='/perfil'>Perfil</a>.")
        elif estado == "pausada":
            acao = ("A coleta está em pausa. Quando quiser continuar, clique em <b>Retomar</b>. Se ela pausou sozinha por falha no acesso, "
                    "confira o registro abaixo e o PJe Office antes de retomar.")
        elif estado == "parando":
            acao = "Aguarde: o processo atual está terminando e tudo está sendo gravado. Esta página se atualiza sozinha."
        elif estado == "erro":
            acao = ("A coleta parou por um erro (veja o aviso abaixo). Confira o acesso em <a href='/acesso'>Acesso e escritório</a> "
                    "(botão Testar acesso) e depois clique em <b>Começar ou continuar a coleta</b>. O que já foi coletado está gravado.")
        elif terminou:
            acao = ("A coleta terminou. O próximo passo é <a href='/'><b>Revisar os resumos</b></a>: confira cada um com o print e o documento e "
                    "aprove, corrija ou descarte. Depois gere as <a href='/entregas'>Entregas</a>.")
        elif pendentes_ou_erros:
            acao = "Há processos na fila e nada está rodando. Clique em <b>Começar ou continuar a coleta</b> quando quiser iniciar."
        else:
            acao = ("Não há coleta em andamento nem processos na fila. Para coletar, use <a href='/fluxo/inicial'>Elaborar relatório inicial</a> "
                    "ou <a href='/fluxo/atualizar'>Atualizar relatório</a>.")
        h = [trilha("coleta", 4 if terminou else 3) if (total or estado != "parado") else "",
             agora(acao, ajuda_texto="A página se atualiza sozinha a cada poucos segundos enquanto a coleta roda. Você pode pausar ou parar "
                                     "com segurança quando quiser: o que já foi coletado fica gravado."),
             f"<div class='caixa'><b>Coleta: {_e(ROTULO_DA_EXECUCAO.get(estado, estado))}</b>"
             + (f" · início {_e(s['inicio'])}" if s["inicio"] else "")
             + ajuda("Coletando: lendo os processos agora. Aguardando a janela: o modo contínuo espera o horário que você definiu. Em pausa: parada "
                     "a seu pedido (ou por falha de acesso), pronta para retomar. Parada: encerrada com segurança. Concluída: acabou a fila.")
             + "</div>"]
        if s["aviso"]:
            h.append(f"<div class='alerta'>{_e(s['aviso'])}</div>")
        if s["erro"]:
            h.append(f"<div class='alerta'>A coleta parou por erro: {_e(s['erro'])}</div>")
        if r:
            h.append(f"<progress max='{max(total, 1)}' value='{feitos}' aria-label='Progresso da coleta'></progress>"
                     f"<p class='dica'>{feitos} de {total} processo(s) tratados. Tempo restante: {_e(duracao_humana(r.get('estimativa_s')))}."
                     + ajuda("\"Tratados\" inclui os coletados, os que deram erro e os que ficaram para conferir à mão. O tempo restante é uma estimativa "
                             "que se ajusta conforme a coleta anda.") + "</p>"
                     "<div class='cartoes'>"
                     + "".join(f"<div class='cartao'><b>{n}</b>{rot}{ajuda(aj)}</div>" for n, rot, aj in
                               ((r.get("pendente", 0), "na fila", "Processos que ainda vão ser lidos."),
                                (r.get("coletando", 0), "coletando", "O processo que está sendo lido neste momento (um por vez)."),
                                (r.get("coletado", 0), "coletados", "Lidos com sucesso. Os resumos já aparecem como rascunho em Revisar."),
                                (r.get("erro", 0), "com erro", "Falharam por problema passageiro (conexão, tempo esgotado). O programa tenta de novo sozinho algumas vezes."),
                                (r.get("manual", 0) - r.get("fisico", 0), "para conferir à mão",
                                 "O programa não conseguiu ler e não vai repetir: captcha não resolvido, segredo de justiça ou processo não encontrado. Confira no tribunal."),
                                (r.get("fisico", 0), "físicos (sem autos eletrônicos)", "Processos em papel: não há o que ler no sistema. Lance à mão.")))
                     + "</div>")
        else:
            h.append("<p class='vazio'>Ainda não há processos na fila. Eles aparecem aqui depois que você preparar uma coleta.</p>")
        taxa = s.get("taxa")
        if taxa and taxa.get("eletronicos"):
            h.append(f"<p class='dica'>Taxa de sucesso (só processos eletrônicos): {taxa['coletados']} de {taxa['eletronicos']} "
                     f"({round(100 * taxa['taxa'])}%). Os {taxa['fisicos']} processo(s) físico(s) ficam de fora da conta: "
                     "o relatório deles segue pelo DJEN e pelo que você lançar à mão.</p>")
        botoes = []
        if estado in ("rodando", "aguardando"):
            botoes += [("pausar", "Pausar"), ("parar", "Parar com segurança")]
        elif estado == "pausada":
            botoes += [("retomar", "Retomar"), ("parar", "Parar com segurança")]
        elif estado == "parando":
            pass
        elif r.get("pendente", 0) or r.get("erro", 0):
            botoes.append(("retomar", "Começar ou continuar a coleta"))
        ajuda_botao = {
            "pausar": "Para de pegar processos novos. O que está sendo lido agora termina e o resto espera. Nada se perde: continue depois com Retomar.",
            "parar": "Termina o processo atual, grava tudo e encerra a coleta (o navegador fecha). Os que faltam continuam na fila: dá para "
                     "continuar depois com \"Começar ou continuar a coleta\".",
            "retomar": "Volta a coletar de onde parou, entrando de novo no jus.br com o seu certificado. Se a pausa foi por falha de acesso, "
                       "resolva isso antes (PJe Office aberto, captcha) para ela não pausar de novo.",
        }
        ajuda_botao_comecar = ("Inicia (ou continua) a coleta dos processos que estão na fila: abre o navegador, entra no jus.br com o seu "
                               "certificado e lê os processos um por vez, só para consultar. Nada entra no relatório sem a sua aprovação.")
        for acao, rotulo in botoes:
            confirmacao = (" onsubmit=\"return confirm('Parar a coleta? O processo atual termina e o resto fica na fila para depois.')\""
                           if acao == "parar" else "")
            texto_ajuda = ajuda_botao_comecar if rotulo.startswith("Começar") else ajuda_botao[acao]
            destaque = "principal" if acao != "parar" else ""
            h.append(f"<form style='display:inline' method='post' action='/fluxo/{acao}'{confirmacao}>{oculto}"
                     f"<button class='{destaque}'>{rotulo}</button>{ajuda(texto_ajuda)}</form> ")
        if s["log"]:
            h.append("<h2>Registro da coleta"
                     + ajuda("As últimas linhas do que a coleta fez, na ordem. Serve para entender o que aconteceu se algo falhar. Não mostra senhas. "
                             "Uma cópia completa fica na pasta data/logs deste relatório.") + "</h2>"
                     "<pre class='log'>" + _e("\n".join(s["log"][-30:])) + "</pre>")
        if s["cobertura"]:
            h.append("<h2>Cobertura por tribunal"
                     + ajuda("Para cada tribunal: quantos processos foram lidos nos autos, quantos só têm as publicações do Diário (DJEN), quantos "
                             "ficaram para você conferir à mão e quantos são físicos. Mostra onde o relatório tem lacunas.") + "</h2>"
                     "<table class='t'><tr><th>Tribunal</th><th>Coletados</th><th>Só publicações (DJEN)</th><th>Conferir à mão</th><th>Físicos</th></tr>"
                     + "".join(f"<tr><td>{_e(str(t))}</td><td>{c.get('coletado', 0)}</td><td>{c.get('so_djen', 0)}</td><td>{c.get('manual', 0)}</td><td>{c.get('fisico', 0)}</td></tr>"
                               for t, c in sorted(s["cobertura"].items())) + "</table>")
        if estado in ("concluida", "parada", "pausada") or (total and feitos >= total):
            h.append("<p><a href='/'>Ir para a revisão</a>"
                     + ajuda("Abre a tela Revisar, onde você confere os resumos que já chegaram e aprova, corrige ou descarta cada um.")
                     + " · <a href='/entregas'>Ver entregas</a>"
                     + ajuda("Gera os arquivos do relatório (Word, planilha, painel) com o que você já aprovou.") + "</p>")
        if terminou:
            h.append(ent.html_do_atalho(oculto, per.carregar(), "/fluxo/progresso"))
        if estado in ("rodando", "aguardando", "parando"):
            h.append("<script>setTimeout(()=>location.reload(),3000);</script>")
        return pagina("fluxo", "Andamento da coleta", *h)

    @app.get("/fluxo/progresso.json")
    def fluxo_progresso_json():
        return jsonify(situacao_da_execucao())

    for acao in ("pausar", "retomar", "parar"):
        def tratar(acao=acao):
            token_ok()
            return _ir("/fluxo/progresso", _pedir(acao))
        app.add_url_rule(f"/fluxo/{acao}", endpoint=f"fluxo_{acao}", view_func=tratar, methods=["POST"])
