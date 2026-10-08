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
from painel import perfil as per
from painel.base import _ir, _msg, _tarefa_rodando
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
CAMPOS_COM_NOME = ("cliente", "autores", "reus", "parte_contraria", "outras_partes")
INTERVALO_DA_JANELA_S = 30      # de quanto em quanto tempo o modo contínuo olha se a janela abriu
DIAS_DE_GUARDA_DOS_LOTES = 3

FABRICA_DE_COLETOR = None       # f() -> Coletor; None = padrão (fila.ColetorReal). Testes e o WS-14 trocam.
AO_COLETAR = []                 # ganchos g(slug, processo, resultado), chamados a cada processo coletado
AO_CONCLUIR = []                # ganchos g(slug), chamados quando a rodada de coleta termina (processar e sintetizar)

_e = html.escape
_TRAVA = threading.Lock()
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


def resumo_da_leitura(lido):
    rel = lido["rel"]
    return {"nome": lido["nome"], "caminho": lido["caminho"], "formato": lido["formato"],
            "processos": len(rel.get("processos", [])), "data_base": rel.get("data_base"), "cliente": rel.get("cliente"),
            "sem_destino": rel.get("colunas_sem_destino", []), "avisos": rel.get("avisos", [])}


# ================================================================ do relatório lido para fichas

def _origem_valida(origem):
    return origem if origem in ("migrado", "humano") else "migrado"


def fichas_do_relatorio(rel, nome_arquivo=None):
    """RelatorioLido -> (fichas v2, avisos). Campos entram com a origem que o leitor deu (migrado ou
    humano); o histórico em texto vira `linha_de_base`; processo só de lista fica sem linha de base."""
    fichas, avisos = [], []
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
        for v in p.get("vinculados") or []:
            if v.get("numero"):
                ficha.vincular(f, v["numero"], v.get("tipo") or "mesma_acao")
        texto = p.get("andamentos_texto") or ""
        if texto or (rel.get("formato") in ("docx_a", "xlsx_b") and rel.get("data_base")):
            f["linha_de_base"] = {"data_base": rel.get("data_base"), "andamentos_texto": texto,
                                  "arquivo": nome_arquivo or rel.get("arquivo"), "ultimo_andamento": p.get("ultimo_andamento")}
        momento, situacao = ficha.obter(f, "momento_atual"), ficha.obter(f, "situacao")
        ativo = taxonomia.momento_ativo(momento) if momento else None
        if ativo is not None:
            f["ativo"] = ativo
        elif situacao == "Encerrado":
            f["ativo"] = False
        fichas.append(f)
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
    return (f"<h3>Quem é o cliente? ({sem_cliente} processo(s) sem cliente)</h3>"
            "<p class='dica'>Marque quem é cliente: o programa define, de uma vez, o cliente, o polo (autor ou réu) e a parte contrária "
            "em todos os processos em que a parte aparece. Nada de preencher processo por processo.</p>" + tabela +
            "<p><label>Cliente padrão para os processos que ficarem sem cliente (deixe em branco para não aplicar)<br>"
            f"<input type='text' name='cliente_padrao' size='50' value='{_e(nome_sugerido)}'></label></p>")


def html_da_conferencia(resumos, rejeitados, fichas, avisos, oculto, lote, nome_sugerido, ha_projeto):
    """A tela de conferência da migração (corpo, sem o cabeçalho)."""
    h = []
    total, clientes = len(fichas), _nomes_de_cliente(fichas)
    bases = sorted({r["data_base"] for r in resumos if r["data_base"]})
    sem_base = sum(1 for f in fichas if not f.get("linha_de_base"))
    ligados = [f for f in fichas if f.get("vinculados")]
    quando = f", data-base {ficha.data_br(bases[-1])}" if bases else ""
    h.append(f"<div class='caixa'><b>Li {total} processo(s) de {len(resumos)} arquivo(s), "
             f"{len([c for c in clientes if c])} cliente(s){quando}.</b></div>")
    h.append("<div class='cartoes'>"
             f"<div class='cartao'><b>{total}</b>processos</div>"
             f"<div class='cartao'><b>{len(ligados)}</b>com processos ligados</div>"
             f"<div class='cartao'><b>{sem_base}</b>novos (sem relatório anterior)</div>"
             f"<div class='cartao'><b>{sum(1 for a in avisos if a['nivel'] == 'erro')}</b>erro(s)</div>"
             f"<div class='cartao'><b>{sum(1 for a in avisos if a['nivel'] == 'atencao')}</b>ponto(s) de atenção</div></div>")
    h.append("<h2>Arquivos</h2><table class='t'><tr><th>Arquivo</th><th>Formato</th><th>Processos</th><th>Data-base</th></tr>")
    for r in resumos:
        h.append(f"<tr><td>{_e(r['nome'])}</td><td>{_e(ROTULO_FORMATO.get(r['formato'], r['formato']))}</td>"
                 f"<td>{r['processos']}</td><td>{_e(ficha.data_br(r['data_base']) or '-')}</td></tr>")
    h.append("</table>")
    if rejeitados:
        h.append("<h2>Arquivos que não consegui usar</h2><table class='t'><tr><th>Arquivo</th><th>Motivo</th></tr>"
                 + "".join(f"<tr><td>{_e(r['nome'])}</td><td>{_e(r['motivo'])}</td></tr>" for r in rejeitados) + "</table>")
    if sem_base:
        h.append(f"<p class='dica'>{sem_base} processo(s) vieram só como número, sem relatório anterior: entram marcados como "
                 "<b>novos</b> e precisam do <a href='/fluxo/inicial'>relatório inicial</a>.</p>")
    indexados = list(enumerate(avisos))
    escolhas = []
    for chave, titulo, _ in [*CATEGORIAS, OUTROS]:
        itens = [(i, a) for i, a in indexados if categoria_do_aviso(a) == chave]
        if chave == "vinculados" and ligados:
            h.append(f"<h2>{_e(titulo)}</h2><p>{len(ligados)} processo(s) têm processos ligados; no relatório cada conjunto vira uma só linha.</p>"
                     "<table class='t'><tr><th>Principal</th><th>Ligados</th></tr>"
                     + "".join(f"<tr><td>{_e(f['numero'])}</td><td>{_e(', '.join(v['numero'] + ' (' + str(v.get('tipo')) + ')' for v in f['vinculados']))}</td></tr>"
                               for f in ligados[:50])
                     + "</table>" + (f"<p class='dica'>E mais {len(ligados) - 50}.</p>" if len(ligados) > 50 else ""))
            if itens:
                h.append(_tabela_de_avisos(itens))
            continue
        if not itens:
            continue
        h.append(f"<h2>{_e(titulo)} ({len(itens)})</h2>" + _tabela_de_avisos(itens))
        if chave == "grafias":
            for i, a in itens:
                cands = [str(c) for c in a["candidatos"]]
                if len(cands) >= 2:
                    escolhas.append((i, a, cands))
    if escolhas:
        h.append("<h2>Qual nome usar?</h2><p class='dica'>Nada é juntado sem a sua escolha. Se não escolher, os nomes ficam como estão.</p>")
        for i, a, cands in escolhas:
            h.append(f"<div class='caixa'><p>{_e(a['mensagem'])}</p><label><input type='radio' name='grafia_{i}' value='' checked> manter como está</label><br>"
                     + "<br>".join(f"<label><input type='radio' name='grafia_{i}' value='{_e(c)}'> usar <b>{_e(c)}</b> em todos</label>" for c in cands)
                     + "</div>")
    sem_destino = [(r["nome"], c) for r in resumos for c in r["sem_destino"]]
    if sem_destino:
        h.append("<h2>Colunas sem destino</h2><p class='dica'>Estas colunas do arquivo não têm lugar na ficha. Nada se perde: "
                 "elas aparecem na aba \"Campos não migrados\" quando a planilha for gerada.</p>"
                 "<table class='t'><tr><th>Arquivo</th><th>Coluna</th><th>Exemplos</th></tr>"
                 + "".join(f"<tr><td>{_e(n)}</td><td>{_e(str(c.get('coluna')))}</td><td>{_e(' | '.join(map(str, (c.get('amostra') or [])[:3])))}</td></tr>"
                           for n, c in sem_destino) + "</table>")
    h.append("<h2>Clientes encontrados</h2><table class='t'><tr><th>Cliente</th><th>Processos</th></tr>"
             + "".join(f"<tr><td>{_e(n or '(sem cliente)')}</td><td>{q}</td></tr>" for n, q in sorted(clientes.items()))
             + "</table>")
    h.append(f"<form class='caixa' method='post' action='/fluxo/importar/confirmar'>{oculto}<input type='hidden' name='lote' value='{_e(lote)}'>"
             f"<label>Nome do relatório<br><input type='text' name='nome' size='50' value='{_e(nome_sugerido)}' required></label>")
    h.append(bloco_de_clientes(fichas, nome_sugerido))
    if ha_projeto:
        h.append("<p><label><input type='radio' name='destino' value='novo' checked> criar um relatório novo</label><br>"
                 f"<label><input type='radio' name='destino' value='atual'> acrescentar ao relatório atual ({_e(comum.projeto().get('nome', ''))})</label></p>")
    else:
        h.append("<input type='hidden' name='destino' value='novo'>")
    h.append("<p class='dica'>Ao confirmar, o programa cria as fichas e guarda o histórico lido como linha de base: "
             "o que já está escrito nos relatórios antigos não será coletado de novo.</p>"
             f"<button class='principal' {'disabled' if not total else ''}>Confirmar e criar o relatório</button> "
             "<a href='/fluxo'>Cancelar</a></form>")
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
    relatório o ativo. Devolve o slug."""
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


def enfileirar(selecionadas, perfil_do_relatorio, data_base_do_arquivo=None):
    """Põe os processos na fila (agrupados pela data `desde`). Devolve (fila, quantidade)."""
    grupos = {}
    for f in selecionadas:
        grupos.setdefault(desde_do_processo(f, data_base_do_arquivo), []).append(f["numero"])
    fila = ent.abrir_fila()
    if perfil_do_relatorio["modo_coleta"] == "continuo":
        _configurar_janela(fila, perfil_do_relatorio["janela_coleta"])
    for desde, numeros in sorted(grupos.items(), key=lambda kv: kv[0] or ""):
        fila.enfileirar(numeros, modo=perfil_do_relatorio["modo_coleta"], profundidade=perfil_do_relatorio["profundidade"],
                        prioridade=0, desde=desde)
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


def _log(texto):
    EXEC["log"].append(f"{datetime.datetime.now():%H:%M:%S} {texto}")


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


def iniciar_execucao():
    """Começa (ou continua) a coleta da fila do relatório ativo. Devolve (ok, mensagem)."""
    if execucao_rodando():
        return False, "A coleta já está em andamento."
    if _tarefa_rodando():
        return False, "Há uma tarefa da tela Atualizar em andamento (as duas usam o mesmo acesso). Espere ou interrompa."
    if not comum.PROJETO:
        return False, "Não há relatório ativo."
    try:
        fila_mod = modulo("fila", "A fila de coleta")
        coletor = _criar_coletor()
        fila = ent.abrir_fila()
    except Indisponivel as erro:
        return False, str(erro)
    EXEC["log"].clear()
    EXEC.update(slug=comum.PROJETO, fila=fila, estado="rodando", pedido=None, erro=None, resumo=None,
                inicio=f"{datetime.datetime.now():%H:%M}", modo=per.carregar()["modo_coleta"])
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
         "resumo": None, "aviso": None, "cobertura": None}
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


# ================================================================ rotas

def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def pagina(ativa, titulo, *partes):
        return "".join([cabecalho(ativa), ESTILO_FLUXO, f"<h1>{titulo}</h1>", _msg(), *partes])

    def sem_relatorio(titulo):
        return pagina("fluxo", titulo, "<p>Ainda não há um relatório. <a href='/fluxo/importar'>Importe relatórios existentes</a> "
                                        "ou <a href='/novo'>crie um relatório novo</a>.</p>")

    def campos_da_coleta(p):
        """Escolhas de profundidade, modo e janela (formulários de inicial e atualizar)."""
        marca = lambda a, b: "checked" if a == b else ""
        h = ["<fieldset><legend><b>Profundidade</b></legend>"]
        for k, v in per.PROFUNDIDADES.items():
            h.append(f"<label><input type='radio' name='profundidade' value='{k}' {marca(p['profundidade'], k)}> {_e(v)}</label><br>")
        h.append("</fieldset><fieldset><legend><b>Quando coletar</b></legend>")
        for k, v in per.MODOS.items():
            h.append(f"<label><input type='radio' name='modo_coleta' value='{k}' {marca(p['modo_coleta'], k)}> {_e(v)}</label><br>")
        j = p["janela_coleta"]
        h.append(f"<p>Janela do modo contínuo: das <input type='text' name='janela_inicio' size='5' value='{_e(j['inicio'])}'> "
                 f"às <input type='text' name='janela_fim' size='5' value='{_e(j['fim'])}'> (HH:MM)</p></fieldset>")
        return "".join(h)

    def seguir_para_a_coleta(perfil_do_relatorio, quantidade, extra=""):
        if quantidade == 0:
            return _ir("/fluxo", (extra + "\n" if extra else "") + "Nenhum processo para coletar com esse filtro.")
        if perfil_do_relatorio["modo_coleta"] == "imediato":
            return _ir("/fluxo/confirmar", extra)
        ok, msg = iniciar_execucao()
        return _ir("/fluxo/progresso", (extra + "\n" if extra else "") + f"{quantidade} processo(s) na fila. {msg}")

    # ------------------------------------------------------------ início

    @app.get("/fluxo")
    def fluxo_inicio_do_assistente():
        h = ["<p class='dica'>Escolha o que fazer. Dá para voltar aqui a qualquer momento.</p>",
             "<div class='botoes-grandes'>"
             "<a class='botao-grande' href='/fluxo/importar'><b>Importar relatórios existentes</b>"
             "<span class='dica'>Já tenho relatórios prontos (Word, Excel ou uma lista de números) e quero que o programa passe a acompanhá-los.</span></a>"
             "<a class='botao-grande' href='/fluxo/inicial'><b>Elaborar relatório inicial</b>"
             "<span class='dica'>Tenho os processos, mas ainda não tenho relatório. O programa busca tudo e monta o primeiro.</span></a>"
             "<a class='botao-grande' href='/fluxo/atualizar'><b>Atualizar relatório</b>"
             "<span class='dica'>Já tenho o relatório do mês passado e quero acrescentar o que mudou.</span></a>"
             "<a class='botao-grande' href='/migracao'><b>Migrar de modelo</b>"
             "<span class='dica'>Meu relatório está num formato diferente e quero passá-lo para os modelos do programa.</span></a></div>"]
        if comum.PROJETO:
            fichas = ficha.carregar(todas=True)
            novos = sum(1 for f in fichas if not f.get("linha_de_base"))
            h.append(f"<div class='caixa'><b>Relatório atual: {_e(comum.projeto().get('nome', comum.PROJETO))}</b>"
                     f"<p>{len(fichas)} processo(s); {novos} sem relatório anterior (precisam do relatório inicial).</p>"
                     "<p><a href='/fluxo/progresso'>Ver a coleta</a> · <a href='/'>Revisar andamentos</a> · "
                     "<a href='/entregas'>Entregas</a> · <a href='/perfil'>Perfil</a></p></div>")
        return pagina("fluxo", "O que você quer fazer?", *h)

    # ------------------------------------------------------------ importar

    @app.get("/fluxo/importar")
    def fluxo_importar():
        return pagina("fluxo", "Importar relatórios existentes",
                      f"<form class='caixa' method='post' action='/fluxo/importar/enviar' enctype='multipart/form-data'>{oculto}"
                      "<p>Arraste os arquivos para a caixa abaixo (ou clique nela para escolher). Pode enviar vários de uma vez: "
                      "relatórios em Word (.docx), planilhas (.xlsx), listas (.csv, .txt).</p>"
                      "<div class='zona'><input type='file' name='arquivos' multiple accept='.docx,.xlsx,.csv,.txt,.md' required "
                      "aria-label='Arquivos para importar'></div>"
                      "<p class='dica'>O programa reconhece o formato e mostra o que leu antes de guardar qualquer coisa.</p>"
                      "<button class='principal'>Ler os arquivos</button></form>")

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
        return pagina("fluxo", "Conferência da migração", corpo)

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
            msg += f"\n{novos} processo(s) novos, sem relatório anterior: precisam do relatório inicial."
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
        h = [f"<form class='caixa' method='post' action='/fluxo/inicial/preparar'>{oculto}",
             f"<p>Relatório: <b>{_e(comum.projeto().get('nome', ''))}</b> · {len(fichas)} processo(s), {novos} sem relatório anterior.</p>",
             "<input type='hidden' name='com_entregas' value='1'><fieldset><legend><b>O que entregar</b></legend>"]
        for k, v in per.ENTREGAS.items():
            h.append(f"<label><input type='checkbox' name='entregas' value='{k}' {'checked' if k in p['entregas'] else ''}> {_e(v)}</label><br>")
        h.append("</fieldset>")
        h.append(campos_da_coleta(p))
        opcoes = "".join(f"<option value='{_e(c)}'>{_e(c)}</option>" for c in clientes_da_carteira(fichas))
        h.append(f"<p><label>Só este cliente <select name='cliente'><option value=''>todos</option>{opcoes}</select></label></p>"
                 f"<p><label><input type='checkbox' name='so_novos' value='1' {'checked' if novos else ''}> "
                 "só os processos que ainda não têm relatório anterior</label></p>"
                 "<button class='principal'>Preparar a coleta</button></form>")
        return pagina("fluxo", "Elaborar relatório inicial", *h)

    @app.post("/fluxo/inicial/preparar")
    def fluxo_inicial_preparar():
        token_ok()
        if not comum.PROJETO:
            return _ir("/fluxo", "Não há relatório ativo.")
        perfil_novo, erros = per.aplicar_formulario(per.carregar(), request.form, parcial=True)
        if erros:
            return _ir("/fluxo/inicial", "Corrija antes de continuar:\n" + "\n".join(erros))
        per.salvar(perfil_novo)
        fichas = ficha.carregar(todas=True)
        selecionadas = selecionar_processos(fichas, request.form.get("cliente", ""), bool(request.form.get("so_novos")))
        try:
            _, quantidade = enfileirar(selecionadas, perfil_novo) if selecionadas else (None, 0)
        except Indisponivel as erro:
            return _ir("/fluxo/inicial", str(erro))
        return seguir_para_a_coleta(perfil_novo, quantidade)

    # ------------------------------------------------------------ atualizar

    @app.get("/fluxo/atualizar")
    def fluxo_atualizar():
        if not comum.PROJETO:
            return sem_relatorio("Atualizar relatório")
        return pagina("fluxo", "Atualizar relatório",
                      f"<form class='caixa' method='post' action='/fluxo/atualizar/enviar' enctype='multipart/form-data'>{oculto}"
                      "<p>Solte aqui o relatório mais recente: o Word (.docx), a planilha (.xlsx), ou os dois. Basta um; o outro "
                      "é refeito a partir dos dados. O painel (HTML) não precisa ser enviado.</p>"
                      "<div class='zona'><input type='file' name='arquivos' multiple accept='.docx,.xlsx' aria-label='Relatório mais recente'></div>"
                      "<p class='dica'>Sem arquivo, o programa só coleta o que mudou desde o último relatório de cada processo.</p>"
                      "<button class='principal'>Conferir com a carteira</button></form>")

    @app.post("/fluxo/atualizar/enviar")
    def fluxo_atualizar_enviar():
        token_ok()
        if not comum.PROJETO:
            return _ir("/fluxo", "Não há relatório ativo.")
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
        fichas_lidas, avisos, resumos = tratar_leituras(lidos) if lidos else ([], [], [])
        carteira = ficha.carregar(todas=True)
        conhecidos = {n for f in carteira for n in ficha.todos_os_numeros(f)}
        no_arquivo = {n for f in fichas_lidas for n in ficha.todos_os_numeros(f)}
        novos = [f["numero"] for f in fichas_lidas if f["numero"] not in conhecidos]
        sumiram = [f["numero"] for f in carteira if f.get("ativo", True) and lidos
                   and not (set(ficha.todos_os_numeros(f)) & no_arquivo)]
        bases = [r["data_base"] for r in resumos if r["data_base"]]
        gravar_lote(pasta, "lote.json", {"tipo": "atualizar", "arquivos": resumos, "rejeitados": rejeitados, "novos": novos,
                                         "sumiram": sumiram, "data_base": max(bases) if bases else None, "sem_arquivo": not lidos})
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
        h = [f"<form class='caixa' method='post' action='/fluxo/atualizar/preparar'>{oculto}<input type='hidden' name='lote' value='{_e(pasta.name)}'>"]
        if dados["sem_arquivo"]:
            h.append("<p>Sem arquivo enviado: vou coletar o que mudou em cada processo da carteira desde o último relatório.</p>")
        else:
            h.append("<table class='t'><tr><th>Arquivo</th><th>Formato</th><th>Processos</th><th>Data-base</th></tr>"
                     + "".join(f"<tr><td>{_e(r['nome'])}</td><td>{_e(ROTULO_FORMATO.get(r['formato'], r['formato']))}</td><td>{r['processos']}</td>"
                               f"<td>{_e(ficha.data_br(r['data_base']) or '-')}</td></tr>" for r in dados["arquivos"]) + "</table>")
            h.append(f"<h2>Processos novos no arquivo ({len(dados['novos'])})</h2>")
            if dados["novos"]:
                h.append("<p class='dica'>Estão no arquivo e não estão na carteira.</p><ul>"
                         + "".join(f"<li>{_e(n)}</li>" for n in dados["novos"][:100]) + "</ul>"
                         + "<p><label><input type='checkbox' name='incluir_novos' value='1' checked> incluir na carteira e acompanhar</label></p>")
            else:
                h.append("<p class='dica'>Nenhum: todos os processos do arquivo já estão na carteira.</p>")
            h.append(f"<h2>Processos da carteira que não aparecem no arquivo ({len(dados['sumiram'])})</h2>")
            if dados["sumiram"]:
                h.append("<p class='dica'>Podem ter sido encerrados ou retirados do relatório. Confira antes de seguir.</p><ul>"
                         + "".join(f"<li>{_e(n)}</li>" for n in dados["sumiram"][:100]) + "</ul>"
                         + "<p><label><input type='checkbox' name='incluir_sumidos' value='1' checked> continuar acompanhando mesmo assim</label></p>")
            else:
                h.append("<p class='dica'>Nenhum: tudo que está na carteira aparece no arquivo.</p>")
        if avisos:
            h.append("<h2>Avisos da leitura</h2>" + _tabela_de_avisos(list(enumerate(avisos))))
        h.append(campos_da_coleta(p))
        opcoes = "".join(f"<option value='{_e(c)}'>{_e(c)}</option>" for c in clientes_da_carteira(fichas))
        h.append(f"<p><label>Só este cliente <select name='cliente'><option value=''>todos</option>{opcoes}</select></label></p>"
                 "<button class='principal'>Preparar a coleta</button> <a href='/fluxo'>Cancelar</a></form>")
        return pagina("fluxo", "Conferência antes de atualizar", *h)

    @app.post("/fluxo/atualizar/preparar")
    def fluxo_atualizar_preparar():
        token_ok()
        if not comum.PROJETO:
            return _ir("/fluxo", "Não há relatório ativo.")
        pasta = pasta_do_lote(request.form.get("lote", ""))
        dados = ler_lote(pasta, "lote.json")
        if dados is None or dados.get("tipo") != "atualizar":
            abort(404)
        perfil_novo, erros = per.aplicar_formulario(per.carregar(), request.form, parcial=True)
        if erros:
            return _ir(f"/fluxo/atualizar/conferir?lote={pasta.name}", "Corrija antes de continuar:\n" + "\n".join(erros))
        per.salvar(perfil_novo)
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
        try:
            _, quantidade = enfileirar(selecionadas, perfil_novo, dados.get("data_base")) if selecionadas else (None, 0)
        except Indisponivel as erro:
            return _ir("/fluxo/atualizar", str(erro))
        return seguir_para_a_coleta(perfil_novo, quantidade,
                                    f"{incluidos} processo(s) novo(s) incluído(s) na carteira." if incluidos else "")

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
        return pagina("fluxo", "Confirmar coleta imediata",
                      f"<div class='alerta'><b>Atenção:</b> a coleta imediata começa agora e vai levar {_e(duracao_humana(resumo.get('estimativa_s')))} "
                      f"para {pendentes} processo(s). O programa busca um processo por vez, com pausas, para não sobrecarregar o tribunal.</div>"
                      "<p>Durante a coleta o programa precisa ficar aberto. Você pode pausar ou parar com segurança a qualquer momento.</p>"
                      f"<form method='post' action='/fluxo/comecar'>{oculto}<button class='principal'>Confirmar e começar agora</button> "
                      "<a href='/fluxo/progresso'>Agora não</a></form>"
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
        h = [f"<div class='caixa'><b>Coleta: {_e(ROTULO_DA_EXECUCAO.get(estado, estado))}</b>"
             + (f" · início {_e(s['inicio'])}" if s["inicio"] else "") + "</div>"]
        if s["aviso"]:
            h.append(f"<div class='alerta'>{_e(s['aviso'])}</div>")
        if s["erro"]:
            h.append(f"<div class='alerta'>A coleta parou por erro: {_e(s['erro'])}</div>")
        if r:
            h.append(f"<progress max='{max(total, 1)}' value='{feitos}' aria-label='Progresso da coleta'></progress>"
                     f"<p class='dica'>{feitos} de {total} processo(s) tratados. Tempo restante: {_e(duracao_humana(r.get('estimativa_s')))}.</p>"
                     "<div class='cartoes'>"
                     + "".join(f"<div class='cartao'><b>{r.get(k, 0)}</b>{rot}</div>" for k, rot in
                               (("pendente", "na fila"), ("coletando", "coletando"), ("coletado", "coletados"),
                                ("erro", "com erro"), ("manual", "para conferir à mão")))
                     + "</div>")
        botoes = []
        if estado in ("rodando", "aguardando"):
            botoes += [("pausar", "Pausar"), ("parar", "Parar com segurança")]
        elif estado == "pausada":
            botoes += [("retomar", "Retomar"), ("parar", "Parar com segurança")]
        elif estado == "parando":
            pass
        elif r.get("pendente", 0) or r.get("erro", 0):
            botoes.append(("retomar", "Começar ou continuar a coleta"))
        for acao, rotulo in botoes:
            h.append(f"<form style='display:inline' method='post' action='/fluxo/{acao}'>{oculto}<button class='principal'>{rotulo}</button></form>")
        if s["log"]:
            h.append("<pre class='log'>" + _e("\n".join(s["log"][-30:])) + "</pre>")
        if s["cobertura"]:
            h.append("<h2>Cobertura por tribunal</h2><table class='t'><tr><th>Tribunal</th><th>Coletados</th><th>Só publicações (DJEN)</th><th>Conferir à mão</th></tr>"
                     + "".join(f"<tr><td>{_e(str(t))}</td><td>{c.get('coletado', 0)}</td><td>{c.get('so_djen', 0)}</td><td>{c.get('manual', 0)}</td></tr>"
                               for t, c in sorted(s["cobertura"].items())) + "</table>")
        if estado in ("concluida", "parada", "pausada") or (total and feitos >= total):
            h.append("<p><a href='/'>Ir para a revisão</a> · <a href='/entregas'>Ver entregas</a></p>")
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
