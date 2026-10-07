"""Fluxos ponta a ponta da Fase 2 (WS-14): liga os módulos da Onda 1 nos quatro fluxos do PLANO §3.

    import fluxos
    fluxos.migrar(["relatorio.docx", "carteira.xlsx"], confirmar=True)           # Importar relatórios existentes
    fluxos.converter("outra-planilha.xlsx", "xlsx_b", mapeamento={...})          # Migrar de modelo
    fluxos.inicial("meu-relatorio", profundidade="padrao", modo="imediato", entregas=["docx_a", "xlsx_b", "dashboard"])
    fluxos.atualizar("meu-relatorio", ["relatorio-setembro.docx"], data_base="2026-10-31")
    fluxos.entregar("meu-relatorio", ["docx_a", "xlsx_b", "dashboard"], data_base="2026-10-31")

    python3 src/fluxos.py migrar|converter|inicial|atualizar|entregar ... --projeto SLUG      (ver --help)

Cada função devolve um dict {"ok", "resumo" (texto em português simples), "avisos" (CONTRATOS §0), "arquivos", ...mais
chaves de cada fluxo} e aceita `ao_progresso(dict)` (etapa, mensagem e, na coleta, o resumo da fila). Erro esperado
vira aviso com `codigo` estável; só erro de programação levanta exceção. Os módulos dos outros workstreams são
importados na hora do uso (um defeito ou ausência vira aviso, não derruba o resto).

Etapas e quem faz cada uma
    leitura        leitores.ler -> fichas (origem do leitor) -> consolidar.consolidar (vinculados e duplicatas;
                   grafias de nome só como SUGESTÃO no relatório de ambiguidades)
    coleta         fila.Fila + fila.rodar_fila com o Coletor (real ou ColetorSimulado). Em cada resultado
                   (`processar_resultado`, chamado por `ao_resultado`, então só vira `coletado` o que foi gravado):
                   capa.aplicar na ficha e movimentos/documentos como EVENTOS `coletado`
    processamento  extrair.rodar (texto dos documentos) e, por evento: movimento -> regra (resumir.processar_movimento),
                   documento -> resumo pelo provedor de IA do perfil (`ia.provedor`, consentimento por cliente);
                   tudo entra como `rascunho` (decisão 1). `motor` e `profundidade` ficam gravados no evento
    síntese        sintese.momento_atual / ultimo_andamento por ficha (regra -> origem `coletado`; IA -> `sugerido`)
    revisão        o fluxo PÁRA aqui (eventos `rascunho`): a pessoa aprova na tela Revisar ou na revisão em lote
                   (triagem). Rodar o mesmo fluxo de novo, com tudo aprovado, segue para a entrega
    entrega        `entregar`: julgamento.sugerir/aplicar (só com eventos aprovados, só `sugerido`), narrativa,
                   escritores docx_a/xlsx_b/dashboard, qualidade.verificar, qualidade.o_que_mudou e
                   historico.gravar_retrato; tudo numa subpasta de saida/ (a do relatório ou a do perfil)

Decisões de integração (ONDA-2.md) e como ficaram
    1. Eventos seguem `coletado -> extraido -> rascunho -> aprovado -> relatado`. Evento novo entra como rascunho;
       o que já foi aprovado ou relatado nunca volta a rascunho (idempotência por `id`).
    2. Os escritores devolvem `textos_gravados`, `campos_gravados` e `valores_gravados`; o fluxo os guarda na ficha:
       `ultimo_texto_gravado` {data_base, texto, arquivo, campos, por_entrega: {docx_a|xlsx_b: {...}}} e
       `ultimos_valores_gravados` {campo: valor}. Como o texto do .docx e o da planilha têm formatos diferentes,
       cada escritor recebe a ficha com o registro DA SUA entrega (`por_entrega`); as chaves de cima espelham a
       última entrega gravada neste ciclo. Sem isso a detecção de edição manual fica cega no 2º ciclo.
    3. Momento atual por regra entra como `coletado` (a regra lê o que o tribunal mostra e cita a evidência; só assim
       ele substitui o valor `migrado` do relatório antigo); por IA entra como `sugerido`. O qualificador é separado
       por `ficha.definir`. `ativo`, `situacao` e `fase` saem do momento (taxonomia.momento_ativo / categoria).
    4. Avisos `ignorados`, `numero_repetido`, `numero_em_dois_lugares`, `andamento_ja_presente`,
       `edicao_manual_sobrescrita` aparecem em `resultado["avisos"]` e na lista "conferir manualmente" (gravada em
       data/ultimo_ciclo.json, que a tela Entregas mostra). Nenhum derruba o fluxo.
    5. Campos de julgamento: só `sugerido`, só depois da revisão, e `humano` nunca é tocado.
    6. IA: `ia.provedor(perfil, cliente)`: sem consentimento, só local. `FABRICA_DE_PROVEDOR` troca o provedor (testes).
    7. Pastas e perfil.json conforme CONTRATOS §7 (painel/perfil.py e painel/entregas.py).
    8. Retomável: a fila persiste; `data/fluxo.json` guarda o ciclo aberto (data-base, números, fase) e as últimas
       entregas. Interromper em qualquer ponto e rodar de novo não recoleta o que já está `coletado` nem duplica
       evento (id estável) nem andamento (os escritores só acrescentam e conferem o que já consta).
    9. O arquivo enviado vira o molde da próxima entrega; o original nunca é sobrescrito. Sem arquivo enviado, o
       molde é a última entrega do programa; sem ela, o modelo padrão.

Chaves aditivas da ficha usadas aqui: `ultimo_texto_gravado` (+ `campos`, `por_entrega`), `ultimos_valores_gravados`,
`precisa_relatorio_inicial` ("novo, precisa de relatório inicial") e `ultima_coleta`. Estão descritas no cabeçalho
de `ficha.py`.

Limites: tudo foi exercitado com dados fictícios, o ColetorSimulado, provedores de IA falsos e LibreOffice; o
`ColetorReal`, o Word, o Excel, o Google e a IA real não foram exercitados aqui (piloto M5).
"""
import contextlib
import copy
import datetime
import hashlib
import importlib
import io
import re
import shutil
import sys
import threading
import unicodedata
from pathlib import Path

if not __package__ and str(Path(__file__).resolve().parent) not in sys.path:   # executado como script
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import carteira as cart  # noqa: E402
import comum  # noqa: E402
import ficha  # noqa: E402
import taxonomia  # noqa: E402

FABRICA_DE_PROVEDOR = None      # f(perfil, cliente) -> provedor de IA; None = ia.provedor(perfil, cliente, projeto=slug)
ENTREGAS = ("docx_a", "xlsx_b", "dashboard")
PROFUNDIDADES = ("rapido", "padrao", "completo")
EVENTOS_ABERTOS = ("coletado", "extraido", "sem_arquivo")
CODIGOS_PARA_CONFERIR = ("ignorados", "numero_repetido", "numero_em_dois_lugares", "andamento_ja_presente",
                         "edicao_manual_sobrescrita", "edicao_manual", "possivel_duplicata_manual",
                         "andamentos_editados_a_mao", "texto_editado_a_mao", "processo_sumiu_do_arquivo",
                         "processo_novo_no_arquivo", "texto_acima_do_limite", "valor_divergente", "campo_divergente")

_TRAVA = threading.RLock()


# ================================================================ pequenos auxiliares

def _aviso(nivel, codigo, onde, mensagem, candidatos=None):
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": list(candidatos or [])}


def _aviso_ok(a, arquivo=None):
    """Garante o formato de Aviso (CONTRATOS §4) mesmo se um módulo devolver algo incompleto."""
    a = a if isinstance(a, dict) else {"mensagem": str(a)}
    onde = str(a.get("onde", ""))
    return {"nivel": a.get("nivel", "atencao"), "codigo": a.get("codigo", "aviso"),
            "onde": f"{arquivo}: {onde}" if arquivo and onde else (arquivo or onde),
            "mensagem": str(a.get("mensagem", "")), "candidatos": list(a.get("candidatos") or []),
            **({"numeros": a["numeros"]} if a.get("numeros") else {})}


def _mod(nome):
    """Importa um módulo na hora do uso (módulos de outros workstreams; testes podem trocá-los em sys.modules)."""
    return importlib.import_module(nome)


def _hoje():
    return datetime.date.today().isoformat()


def _agora_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _progresso(ao_progresso, etapa, mensagem, **extra):
    if ao_progresso:
        try:
            ao_progresso({"etapa": etapa, "mensagem": mensagem, **extra})
        except Exception:  # noqa: BLE001 - quem acompanha não pode derrubar o fluxo
            pass


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", texto).strip()


def _resultado(ok, resumo, avisos=(), arquivos=(), **extra):
    return {"ok": ok, "resumo": resumo, "avisos": list(avisos), "arquivos": list(arquivos), **extra}


def _data_br(iso):
    return ficha.data_br(iso) if iso else ""


@contextlib.contextmanager
def _em(projeto=None):
    """Aponta `comum` para o relatório pedido (slug) pelo tempo do bloco e devolve o slug. Sem `projeto`, vale o ativo."""
    slug = projeto or comum.PROJETO
    if not slug:
        raise ValueError("Não há relatório ativo: informe o projeto.")
    anterior = comum.PROJETO
    if anterior != slug:
        comum.usar_projeto(slug)
    try:
        yield slug
    finally:
        if anterior and anterior != slug:
            with contextlib.suppress(ValueError):
                comum.usar_projeto(anterior)


def _perfil_mod():
    return _mod("painel.perfil")


def _perfil(slug):
    return _perfil_mod().carregar(slug)


def _arquivo_de_estado():
    return Path(comum.DATA) / "fluxo.json"


def _estado():
    """Estado do fluxo do relatório ativo: ciclo aberto e últimas entregas (data/fluxo.json)."""
    try:
        dados = comum.load_json(_arquivo_de_estado(), {})
    except ValueError:
        dados = {}
    return dados if isinstance(dados, dict) else {}


def _salvar_estado(dados):
    comum.save_json(_arquivo_de_estado(), dados)


def _provedor(perfil, cliente, slug, cache=None):
    """Provedor de IA para o cliente (cache por cliente dentro de uma etapa). Sem consentimento, `ia.provedor`
    devolve o local; a fábrica de testes pode trocar."""
    chave = comum.normalizar(cliente or "")
    if cache is not None and chave in cache:
        return cache[chave]
    if FABRICA_DE_PROVEDOR is not None:
        prov = FABRICA_DE_PROVEDOR(perfil, cliente)
    else:
        prov = _mod("ia").provedor(perfil, cliente, projeto=slug)
    if cache is not None:
        cache[chave] = prov
    return prov


# ================================================================ leitura -> fichas

def _origem_valida(origem):
    return origem if origem in ("migrado", "humano") else "migrado"


def fichas_do_relatorio(rel, nome_arquivo=None):
    """RelatorioLido -> (fichas v2, avisos). Os campos entram com a origem que o leitor deu (migrado ou humano); o
    histórico em texto vira `linha_de_base`; processo que veio só como número fica sem linha de base."""
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


def _juntar(grupos):
    """[(data_base ISO ou None, fichas)] -> (fichas sem repetição por número, avisos). Vale o arquivo de data-base
    mais recente quando o mesmo número aparece em mais de um."""
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


def _consolidar(fichas):
    try:
        novas, avisos = _mod("consolidar").consolidar(fichas)
    except ImportError as erro:
        return fichas, [_aviso("info", "consolidar_indisponivel", "consolidação", f"A consolidação não está disponível ({erro}).")]
    except Exception as erro:  # noqa: BLE001
        return fichas, [_aviso("atencao", "consolidar_falhou", "consolidação",
                               f"Não consegui conferir duplicados e vinculados ({erro}). Confira à mão.")]
    return novas, [_aviso_ok(a) for a in avisos]


def _mesclar(atuais, novas):
    """Acrescenta `novas` a `atuais` (lista, alterada no lugar): ficha nova entra; ficha existente só recebe o que a
    prioridade das origens permitir e a linha de base, se não tinha. Devolve (adicionadas, atualizadas, números novos)."""
    por_numero = {f["numero"]: f for f in atuais}
    adicionadas = atualizadas = 0
    numeros_novos = []
    for n in novas:
        existente = por_numero.get(n["numero"])
        if existente is None:
            atuais.append(n)
            por_numero[n["numero"]] = n
            adicionadas += 1
            numeros_novos.append(n["numero"])
            continue
        mudou = False
        for campo, c in n.get("campos", {}).items():
            mudou |= ficha.definir(existente, campo, c["valor"], c["origem"])
        for v in n.get("vinculados", []):
            if all(x["numero"] != v["numero"] for x in existente.get("vinculados", [])):
                ficha.vincular(existente, v["numero"], v["tipo"])
                mudou = True
        if n.get("linha_de_base") and not existente.get("linha_de_base"):
            existente["linha_de_base"] = n["linha_de_base"]
            mudou = True
        atualizadas += mudou
    return adicionadas, atualizadas, numeros_novos


def _registrar_clientes(fichas):
    dados = comum.load_json(comum.CLIENTES_FILE, {"clientes": []})
    lista = dados.setdefault("clientes", [])
    existentes = {comum.normalizar(c["nome"]) for c in lista}
    for nome in sorted({ficha.obter(f, "cliente") or "" for f in fichas}):
        if nome and comum.normalizar(nome) not in existentes:
            lista.append({"nome": nome, "variacoes": [], "contato": "", "responsavel": ""})
            existentes.add(comum.normalizar(nome))
    comum.save_json(comum.CLIENTES_FILE, dados)


def _copiar_para_entrada(caminho):
    """Copia o arquivo enviado para entrada/ (nome com a data); se o mesmo conteúdo já está lá, reaproveita."""
    ent = _mod("painel.entregas")
    caminho = Path(caminho)
    destino_base = ent.pasta_entrada()
    conteudo = hashlib.sha256(caminho.read_bytes()).hexdigest()
    for existente in destino_base.glob(f"*{ent.nome_de_arquivo(caminho.stem, 'arquivo')}*{caminho.suffix.lower()}"):
        if existente.is_file() and hashlib.sha256(existente.read_bytes()).hexdigest() == conteudo:
            return existente
    destino = destino_base / f"{_hoje()} - {ent.nome_de_arquivo(caminho.stem, 'arquivo')}{caminho.suffix.lower()}"
    n = 2
    while destino.exists():
        destino = destino.with_name(f"{destino.stem.rsplit(' (', 1)[0]} ({n}){destino.suffix}")
        n += 1
    shutil.copy2(caminho, destino)
    return destino


def _grupos_de_aviso(avisos):
    grupos = {}
    for a in avisos:
        grupos.setdefault(a["codigo"], []).append(a)
    return grupos


# ================================================================ 1. migrar (importar relatórios existentes)

def migrar(arquivos, projeto=None, *, confirmar=True, cliente_padrao=None, nome=None, mapeamento=None, ao_progresso=None):
    """Importa relatórios existentes (.docx modelo A, .xlsx modelo B, listas de números, tabelas livres).

    Lê cada arquivo, reconhece o formato, junta e consolida (vinculados e duplicatas; grafias de nome só como
    sugestão), e, com `confirmar=True`, cria ou atualiza o relatório (`projeto`: slug existente; None = cria um
    novo, chamado `nome` ou o cliente do arquivo), grava as fichas, a linha de base (histórico lido, que nunca é
    recoletado), os retratos mensais (vários meses do mesmo .xlsx reconstroem a série) e marca "novo, precisa de
    relatório inicial" nos processos que vieram só como número. Com `confirmar=False` só devolve o relatório de
    conferência, sem gravar nada.

    Devolve {"ok", "resumo", "avisos", "arquivos", "projeto", "processos", "clientes", "data_base", "ambiguidades"
    ({codigo: [avisos]}), "colunas_sem_destino", "grafias" (sugestões), "novos_sem_relatorio", "serie" (datas-base
    reconstruídas), "rejeitados", "confirmado"}."""
    leitores = _mod("leitores")
    avisos, lidos, rejeitados = [], [], []
    arquivos = [Path(a) for a in arquivos]
    for i, caminho in enumerate(arquivos, 1):
        _progresso(ao_progresso, "leitura", f"Lendo {caminho.name} ({i} de {len(arquivos)})")
        rel = leitores.ler(caminho, mapeamento=mapeamento) if mapeamento is not None else leitores.ler(caminho)
        erros = [a for a in rel.get("avisos", []) if a.get("nivel") == "erro" and not rel.get("processos")]
        if not rel.get("processos"):
            rejeitados.append({"arquivo": caminho.name, "motivo": (erros[0]["mensagem"] if erros else "nenhum processo reconhecido")})
            avisos += [_aviso_ok(a, caminho.name) for a in rel.get("avisos", [])]
            continue
        fichas, av = fichas_do_relatorio(rel, caminho.name)
        lidos.append({"caminho": caminho, "rel": rel, "fichas": fichas})
        avisos += [_aviso_ok(a, caminho.name) for a in rel.get("avisos", [])] + [_aviso_ok(a, caminho.name) for a in av]
    if not lidos:
        return _resultado(False, "Não consegui ler nenhum dos arquivos. " + " ".join(f"{r['arquivo']}: {r['motivo']}" for r in rejeitados),
                          avisos, projeto=projeto, processos=0, clientes=[], rejeitados=rejeitados, confirmado=False,
                          ambiguidades={}, colunas_sem_destino=[], grafias=[], novos_sem_relatorio=[], serie=[])
    fichas, av = _juntar([(l["rel"].get("data_base"), l["fichas"]) for l in lidos])
    avisos += av
    fichas, av = _consolidar(fichas)
    avisos += av
    if cliente_padrao:
        for f in fichas:
            if not ficha.obter(f, "cliente"):
                ficha.definir(f, "cliente", cliente_padrao, "migrado")
    sem_destino = []
    for l in lidos:
        for c in l["rel"].get("colunas_sem_destino", []):
            sem_destino.append({**c, "arquivo": l["caminho"].name})
    try:
        grafias = _mod("consolidar").sugerir_grafias(fichas)
    except Exception:  # noqa: BLE001
        grafias = []
    # a série mensal vem dos relatórios que têm data-base (um retrato por data)
    com_data = [l["rel"] for l in lidos if l["rel"].get("data_base") and l["rel"].get("formato") in ("docx_a", "xlsx_b", "tabela_livre")]
    serie = []
    if com_data:
        try:
            serie = list(_mod("historico").reconstruir(com_data))
            avisos += [_aviso_ok(a) for a in getattr(serie, "avisos", [])]
        except Exception as erro:  # noqa: BLE001
            avisos.append(_aviso("atencao", "serie_historica_falhou", "histórico", f"Não consegui reconstruir a série mensal ({erro})."))
    bases = sorted({l["rel"]["data_base"] for l in lidos if l["rel"].get("data_base")})
    clientes = sorted({ficha.obter(f, "cliente") or "" for f in fichas} - {""})
    novos = [f["numero"] for f in fichas if not f.get("linha_de_base")]
    ambiguidades = {k: v for k, v in _grupos_de_aviso(avisos).items() if k not in ("processo_em_varios_arquivos",)}
    resumo = (f"{len(fichas)} processo(s), {len(clientes)} cliente(s), data-base "
              f"{_data_br(bases[-1]) if bases else 'não informada'}; {len(novos)} sem relatório anterior; "
              f"{len(avisos)} aviso(s) para conferir.")
    saida = dict(processos=len(fichas), clientes=clientes, data_base=bases[-1] if bases else None,
                 ambiguidades=ambiguidades, colunas_sem_destino=sem_destino, grafias=grafias,
                 novos_sem_relatorio=novos, serie=[r["data_base"] for r in serie], rejeitados=rejeitados, confirmado=False,
                 projeto=projeto, fichas=fichas)
    if not confirmar:
        return _resultado(True, "Conferência (nada foi gravado): " + resumo, avisos, [], **saida)
    with _TRAVA:
        if projeto is None:
            base_nome = nome or cliente_padrao or next((l["rel"].get("cliente") for l in lidos if l["rel"].get("cliente")), None) \
                or "Relatório importado"
            projeto = comum.criar_projeto(base_nome)
        with _em(projeto) as slug:
            existentes = ficha.carregar(todas=True)
            adicionadas, atualizadas, _ = _mesclar(existentes, fichas)
            for f in existentes:
                if f["numero"] in novos and not f.get("linha_de_base"):
                    f["precisa_relatorio_inicial"] = True
            ficha.salvar(existentes)
            _registrar_clientes(existentes)
            copias = []
            for l in lidos:
                with contextlib.suppress(OSError):
                    copias.append(str(_copiar_para_entrada(l["caminho"])))
            perfil_mod = _perfil_mod()
            perfil = perfil_mod.carregar(slug)
            formatos = {l["rel"]["formato"] for l in lidos}
            entregas = [e for e, fmt in (("docx_a", "docx_a"), ("xlsx_b", "xlsx_b")) if fmt in formatos]
            if "xlsx_b" in formatos:
                entregas.append("dashboard")
                perfil["molde_planilha"] = "cliente"
            if entregas:
                perfil["entregas"] = entregas
            perfil_mod.salvar(perfil, slug)
            proj = comum.projeto()
            if bases:
                proj["ultimo_relatorio"] = max(bases[-1], proj.get("ultimo_relatorio") or "")
            comum.salvar_projeto(proj)
            gravados = []
            hist = _mod("historico")
            for r in serie:
                comum.save_json(hist.pasta(slug) / f"{r['data_base']}.json", r)
                gravados.append(r["data_base"])
            saida.update(projeto=slug, confirmado=True, adicionadas=adicionadas, atualizadas=atualizadas,
                         copias_em_entrada=copias, retratos_gravados=gravados)
            saida.pop("fichas", None)
    return _resultado(True, f"Relatório '{slug}' criado ou atualizado: " + resumo, avisos, copias, **saida)


# ================================================================ 2. converter (migrar de modelo)

def converter(arquivo, destino_modelo, mapeamento=None, projeto=None, *, nome=None, data_base=None, estilo_texto=None,
              ao_progresso=None):
    """Converte um relatório que está noutro formato para o modelo A (`docx_a`), o B (`xlsx_b`) ou os dois
    (`destino_modelo`: texto ou lista). Mesmo leitor da importação (`mapeamento` {cabeçalho: campo} corrige a
    sugestão); o escritor parte do MODELO PADRÃO. Coluna sem destino vai para a aba "Campos não migrados" da
    planilha (e para `Campos não migrados.csv` na pasta de saída, que vale também para o texto): nada se perde em
    silêncio. Devolve o resultado de `entregar` mais `campos_nao_migrados`, `projeto` e `migracao`."""
    modelos = [destino_modelo] if isinstance(destino_modelo, str) else list(destino_modelo or [])
    modelos = [m for m in modelos if m in ("docx_a", "xlsx_b")]
    if not modelos:
        return _resultado(False, "Escolha o modelo de destino (docx_a ou xlsx_b).",
                          [_aviso("erro", "modelo_de_destino", "converter", "Escolha o modelo de destino: docx_a ou xlsx_b.")])
    mig = migrar([arquivo], projeto, confirmar=True, nome=nome or f"{Path(arquivo).stem} (convertido)", mapeamento=mapeamento,
                 ao_progresso=ao_progresso)
    if not mig["ok"] or not mig.get("projeto"):
        return {**mig, "campos_nao_migrados": []}
    slug = mig["projeto"]
    with _em(slug):
        perfil_mod = _perfil_mod()
        perfil = perfil_mod.carregar(slug)
        perfil["entregas"] = modelos
        perfil["molde_planilha"] = "padrao"
        if estilo_texto in perfil_mod.ESTILOS:
            perfil["estilo_texto"] = estilo_texto
        perfil_mod.salvar(perfil, slug)
    nao_migrados = mig.get("colunas_sem_destino", [])
    saida = entregar(slug, modelos, data_base=data_base or mig.get("data_base"), tipo="conversao",
                     campos_nao_migrados=nao_migrados, moldes={"docx_a": None, "xlsx_b": None}, usar_ultimas=False,
                     ao_progresso=ao_progresso)
    saida["avisos"] = mig["avisos"] + saida["avisos"]
    saida.update(campos_nao_migrados=nao_migrados, projeto=slug, migracao={k: mig[k] for k in ("processos", "clientes", "data_base")})
    if nao_migrados and saida.get("rodada"):
        arquivo_csv = _gravar_campos_nao_migrados(Path(saida["rodada"]), nao_migrados)
        saida["arquivos"].append(arquivo_csv)
        if "docx_a" in modelos:
            saida["avisos"].append(_aviso("info", "campos_nao_migrados_no_texto", "docx_a",
                                          "O relatório em texto não tem lugar para colunas sem destino; elas estão em "
                                          f"'{arquivo_csv.name}' (e na aba 'Campos não migrados' da planilha)."))
    saida["resumo"] = (f"Convertido: {mig['processos']} processo(s) para {', '.join(modelos)}; "
                       f"{len(nao_migrados)} coluna(s) sem destino guardada(s) em 'Campos não migrados'. " + saida["resumo"])
    return saida


def _gravar_campos_nao_migrados(rodada, colunas):
    import csv
    destino = rodada / "Campos não migrados.csv"
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Coluna", "Arquivo de origem", "Amostra de valores"])
        for c in colunas:
            w.writerow([c.get("coluna", ""), c.get("arquivo", ""), " | ".join(str(x) for x in (c.get("amostra") or [])[:5])])
    return destino


# ================================================================ coleta: do resultado ao evento

def _id_do_evento(numero, tipo, chave):
    return f"{numero}:{hashlib.sha1(f'{tipo}|{chave}'.encode()).hexdigest()[:12]}"


def _nome_do_documento(nome):
    """'190123456 - Sentença - Sentença homologatória.pdf' -> (id, tipo, descrição)."""
    partes = [p.strip() for p in Path(str(nome)).stem.split(" - ")]
    if len(partes) >= 3 and partes[0].isdigit():
        return partes[0], partes[1], " - ".join(partes[2:])
    if len(partes) == 2 and partes[0].isdigit():
        return partes[0], partes[1], partes[1]
    return "", partes[0] if partes else "Documento", partes[0] if partes else ""


def _eventos_do_resultado(numero, f_principal, resultado, profundidade, existentes):
    """Eventos novos (formato de comum.py, status `coletado`) para os movimentos e documentos do resultado que ainda
    não estão em `existentes` (por id, chave ou conteúdo). Não altera `existentes`."""
    cliente = ficha.obter(f_principal, "cliente") if f_principal else ""
    apelido = (f_principal or {}).get("apelido") or cliente
    ids = {e["id"] for e in existentes}
    chaves = {(e["numero"], e.get("chave")) for e in existentes if e.get("tipo_evento") == "movimento" and e.get("chave")}
    movs = {(e["numero"], e.get("data"), e.get("titulo")) for e in existentes if e.get("tipo_evento") == "movimento"}
    docs = {(e["numero"], e.get("arquivo")) for e in existentes if e.get("tipo_evento") == "documento" and e.get("arquivo")}
    docs |= {(e["numero"], e.get("titulo"), e.get("data")) for e in existentes if e.get("tipo_evento") == "documento"}
    agora = _agora_iso()
    novos = []
    for m in resultado.get("movimentos") or []:
        data_br = _data_br(m.get("data"))
        chave = m.get("chave") or f"{data_br}|{m.get('texto')}"
        ev_id = _id_do_evento(numero, "mov", chave)
        if ev_id in ids or (numero, chave) in chaves or (numero, data_br, m.get("texto")) in movs:
            continue
        ids.add(ev_id)
        novos.append({"id": ev_id, "tipo_evento": "movimento", "numero": numero, "cliente": cliente, "apelido": apelido,
                      "titulo": m.get("texto") or "", "detectado_em": agora, "status": "coletado", "data": data_br,
                      "chave": chave, "print": None, "grau": m.get("grau"), "profundidade": profundidade})
    for d in resultado.get("documentos") or []:
        data_br = _data_br(d.get("data"))
        ev_id = _id_do_evento(numero, "doc", d.get("nome") or d.get("caminho"))
        if ev_id in ids or (numero, d.get("caminho")) in docs or (numero, d.get("nome"), data_br) in docs:
            continue
        ids.add(ev_id)
        doc_id, tipo, descricao = _nome_do_documento(d.get("nome") or "")
        novos.append({"id": ev_id, "tipo_evento": "documento", "numero": numero, "cliente": cliente, "apelido": apelido,
                      "titulo": d.get("nome") or "", "detectado_em": agora, "status": "coletado",
                      "tipo": d.get("tipo") or tipo, "descricao": descricao, "doc_id": doc_id, "data": data_br,
                      "grau": d.get("grau"), "arquivo": d.get("caminho"), "print": None, "profundidade": profundidade})
    return novos


def processar_resultado(slug, numero, resultado, profundidade=None):
    """Grava no relatório o que a coleta de UM processo trouxe: a capa na ficha (`capa.aplicar`, só no processo
    principal; o tribunal não informa polo nem parte contrária) e os movimentos e documentos como eventos
    `coletado` (sem duplicar o que já existe, inclusive o que o ColetorReal já gravou). Idempotente: chamar duas
    vezes com o mesmo resultado não muda nada. Devolve {"eventos": n, "capa": n}."""
    if not resultado or resultado.get("erro"):
        return {"eventos": 0, "capa": 0}
    with _TRAVA, _em(slug):
        fichas = ficha.carregar(todas=True)
        principal_de = {}
        for f in fichas:
            for n in ficha.todos_os_numeros(f):
                principal_de.setdefault(n, f)
        f_principal = principal_de.get(numero)
        profundidade = profundidade or _estado().get("ciclo", {}).get("profundidade")
        lista = comum.eventos()
        novos = _eventos_do_resultado(numero, f_principal, resultado, profundidade, lista)
        if novos:
            comum.salvar_eventos(lista + novos)       # primeiro os eventos: se cair aqui, a repetição não duplica (id)
        mudou_capa = 0
        if f_principal is not None and f_principal["numero"] == numero:
            if resultado.get("capa"):
                try:
                    mudou_capa = len(_mod("capa").aplicar(f_principal, _mod("capa").de_coleta(resultado)))
                except Exception:  # noqa: BLE001
                    mudou_capa = 0
            f_principal["ultima_coleta"] = {"em": _agora_iso(), "movimentos": len(resultado.get("movimentos") or []),
                                            "documentos": len(resultado.get("documentos") or []), "profundidade": profundidade}
            ficha.salvar(fichas)
        return {"eventos": len(novos), "capa": mudou_capa}


def ao_coletar(slug, processo, resultado):
    """Gancho de `painel.assistente.AO_COLETAR`: grava o resultado de cada processo coletado pela tela."""
    numero = processo if isinstance(processo, str) else processo.get("numero")
    if resultado and not resultado.get("erro"):
        processar_resultado(slug, numero, resultado)


def pos_coleta(slug, ao_progresso=None):
    """Gancho de `painel.assistente.AO_CONCLUIR`: quando a coleta da tela termina, processa os eventos e faz a
    síntese (o resto é a revisão, na tela Revisar)."""
    r1 = processar_eventos(slug, ao_progresso=ao_progresso)
    r2 = sintetizar(slug, ao_progresso=ao_progresso)
    return {"eventos": r1, "sintese": r2}


# ================================================================ processamento dos eventos

def _contexto_da_ficha(f):
    cliente = ficha.obter(f, "cliente") or ""
    return {"cliente": cliente, "polo": ficha.obter(f, "polo_cliente") or "", "contraria": ficha.obter(f, "parte_contraria") or "",
            "variacoes": cart.variacoes_do_cliente(cliente)}


def _resumir_documento(ev, f, perfil, slug, cache_provedores):
    """Documento extraído -> rascunho. Frase de regra sempre; resumo pelo provedor de IA quando há texto. Sem texto
    legível ou sem resposta da IA, o rascunho vai à revisão com alerta (nunca inventa)."""
    resumir = _mod("resumir")
    traduzir = _mod("traduzir")
    texto = ""
    if ev["status"] != "sem_arquivo" and ev.get("texto_arquivo"):
        with contextlib.suppress(OSError):
            texto = Path(ev["texto_arquivo"]).read_text(encoding="utf-8")
    ctx = _contexto_da_ficha(f) if f else {"cliente": ev.get("cliente") or "", "polo": "", "contraria": "", "variacoes": []}
    quem = traduzir.autoria(texto, ev.get("tipo", ""), ev.get("descricao", ""))
    frase = traduzir.frase_documento(ev.get("tipo", ""), ev.get("descricao", ""), quem, ctx.get("contraria", ""))
    ev.update(autoria=quem, frase=frase, polo_cliente=ctx.get("polo"), motor="regra")
    alertas = ev.setdefault("alertas", [])
    if quem == "outro" and texto:
        alertas.append("Autoria não identificada: confirmar quem apresentou o documento.")
    alertas.extend(a for a in resumir.conferir_contexto(ev, texto, ctx) if a not in alertas)
    if not texto:
        ev.update(conteudo="", status="rascunho")
        alertas.append("Sem resumo automático: o documento não tem texto legível; abrir nos autos e resumir manualmente.")
        return
    try:
        provedor = _provedor(perfil, ctx["cliente"], slug, cache_provedores)
        res, avisos, motor = resumir.resumir_com_provedor(provedor, texto, ev.get("tipo", ""), quem, frase, ctx, ctx["cliente"])
    except Exception as erro:  # noqa: BLE001 - IA fora do ar ou resposta inválida: segue sem resumo
        ev.update(conteudo="", status="rascunho")
        alertas.append(f"Sem resumo automático: a IA não respondeu de forma utilizável ({type(erro).__name__}).")
        return
    ev.update(conteudo=resumir.limpar_conteudo(res["conteudo"]), trecho_origem=(res.get("trecho_origem") or "").strip(),
              prazo=res.get("prazo"), audiencia=res.get("audiencia"), efeito=res.get("efeito"),
              motor=motor or "regra", status="rascunho")
    alertas.extend(a for a in avisos if a not in alertas)


def processar_eventos(slug=None, *, profundidade=None, ao_progresso=None):
    """Eventos `coletado` (movimentos e documentos) -> `rascunho` (ou `descartado`, com o motivo). Idempotente: só
    toca em evento ainda aberto; o que está `rascunho`, `aprovado` ou `relatado` fica como está. Devolve contagens
    {"movimentos", "documentos", "descartados", "sem_texto", "selos": {selo: n}}."""
    resumir = _mod("resumir")
    extrair = _mod("extrair")
    with _TRAVA, _em(slug) as slug:
        perfil = _perfil(slug)
        profundidade = profundidade or _estado().get("ciclo", {}).get("profundidade") or perfil.get("profundidade")
        _progresso(ao_progresso, "processamento", "Lendo o texto dos documentos coletados")
        with contextlib.redirect_stdout(io.StringIO()):
            extrair.rodar()
        lista = comum.eventos()
        fichas = ficha.carregar(todas=True)
        principal_de = {n: f for f in fichas for n in ficha.todos_os_numeros(f)}
        resumir.marcar_repetidos(lista)
        docs_da_rodada = {(e["numero"], e["detectado_em"][:10]) for e in lista if e["tipo_evento"] == "documento"}
        cache, cont = {}, {"movimentos": 0, "documentos": 0, "descartados": 0, "sem_texto": 0, "selos": {}}
        pendentes = [e for e in lista if (e["tipo_evento"] == "movimento" and e["status"] == "coletado")
                     or (e["tipo_evento"] == "documento" and e["status"] in ("extraido", "sem_arquivo"))]
        _progresso(ao_progresso, "processamento", f"Resumindo {len(pendentes)} evento(s)", total=len(pendentes))
        for ev in pendentes:
            if ev["tipo_evento"] == "movimento":
                resumir.processar_movimento(ev, docs_da_rodada)
                ev["motor"], ev["profundidade"] = "regra", ev.get("profundidade") or profundidade
                cont["movimentos"] += 1
            else:
                _resumir_documento(ev, principal_de.get(ev["numero"]), perfil, slug, cache)
                ev["profundidade"] = ev.get("profundidade") or profundidade
                cont["documentos"] += 1
                cont["sem_texto"] += not ev.get("conteudo")
                selo = _mod("ia").selo(ev.get("motor")) if ev.get("motor") not in (None, "regra") else "sem IA"
                cont["selos"][selo] = cont["selos"].get(selo, 0) + 1
            cont["descartados"] += ev["status"] == "descartado"
        # andamentos diferentes que viram a mesma frase no mesmo dia: uma linha só (como o resumir.rodar da Fase 1)
        vistos = set()
        for ev in lista:
            if ev["tipo_evento"] == "movimento" and ev["status"] == "rascunho":
                chave = (ev["numero"], ev.get("data"), ev.get("frase"))
                if chave in vistos:
                    ev.update(status="descartado", motivo="Mesma informação no mesmo dia.")
                    cont["descartados"] += 1
                vistos.add(chave)
        comum.salvar_eventos(lista)
        return cont


# ================================================================ síntese (momento atual e último andamento)

def _eventos_da_ficha(f, lista):
    numeros = set(ficha.todos_os_numeros(f))
    return [e for e in lista if e.get("numero") in numeros]


def aplicar_sintese(f, eventos_da_ficha, provedor=None):
    """Momento atual, `ativo`, situação, fase e último andamento da ficha a partir dos eventos. Devolve
    {"momento": ..., "origem": "regra"|"ia"|None, "alertas": [...]}. Campo `humano` nunca é tocado."""
    sintese = _mod("sintese")
    r = sintese.momento_atual(f, eventos_da_ficha, [], provedor)
    if r.get("momento"):
        origem = "coletado" if r["origem"] == "regra" else "sugerido"
        valor = r["momento"] + (f" ({r['qualificador']})" if r.get("qualificador") else "")
        gravou = ficha.definir(f, "momento_atual", valor, origem, evidencia=r.get("evidencia") or None, forcar=True)
        if gravou and r["origem"] == "regra":
            ativo = taxonomia.momento_ativo(r["momento"])
            if ativo is not None:
                f["ativo"] = ativo
                ficha.definir(f, "situacao", "Ativo" if ativo else "Encerrado", "coletado", forcar=True)
            fase = taxonomia.categoria_do_momento(r["momento"])
            if fase in taxonomia.FASE:
                ficha.definir(f, "fase", fase, "coletado", forcar=True)
    ultimo = sintese.ultimo_andamento(eventos_da_ficha, [])
    if ultimo:
        ficha.definir(f, "ultimo_andamento", ultimo, "coletado", forcar=True)
    return {"momento": r.get("momento"), "origem": r.get("origem"), "alertas": list(r.get("alertas") or [])}


def sintetizar(slug=None, *, numeros=None, ao_progresso=None):
    """`aplicar_sintese` para as fichas com eventos (ou só `numeros`). Devolve {"fichas", "momentos", "sem_momento"}."""
    with _TRAVA, _em(slug) as slug:
        perfil = _perfil(slug)
        fichas = ficha.carregar(todas=True)
        lista = comum.eventos()
        cache, feitas, com_momento = {}, 0, 0
        for f in fichas:
            if numeros is not None and f["numero"] not in numeros:
                continue
            evs = _eventos_da_ficha(f, lista)
            if not evs:
                continue
            r = aplicar_sintese(f, evs, _provedor(perfil, ficha.obter(f, "cliente") or "", slug, cache))
            feitas += 1
            com_momento += bool(r["momento"])
        ficha.salvar(fichas)
        _progresso(ao_progresso, "sintese", f"Momento atual calculado para {com_momento} de {feitas} processo(s)")
        return {"fichas": feitas, "momentos": com_momento, "sem_momento": feitas - com_momento}


# ================================================================ ciclos de coleta (inicial e atualizar)

def desde_do_processo(f, data_base_do_arquivo=None):
    """Data (ISO) a partir da qual coletar: a mais recente entre a data-base do arquivo enviado, o último texto gravado
    pelo programa e a linha de base. Sem nada disso, None (coleta o histórico todo)."""
    candidatas = [data_base_do_arquivo, (f.get("ultimo_texto_gravado") or {}).get("data_base"),
                  (f.get("linha_de_base") or {}).get("data_base") or (f.get("linha_de_base") or {}).get("ultimo_andamento")]
    validas = [ficha.parse_data(c) for c in candidatas if c]
    validas = [v for v in validas if v]
    return max(validas) if validas else None


def _precisa_inicial(f):
    return bool(f.get("precisa_relatorio_inicial") or (not f.get("linha_de_base") and not f.get("ultimo_texto_gravado")))


def _fila(slug, fila, fila_opcoes):
    return fila if fila is not None else _mod("fila").Fila(slug, **(fila_opcoes or {}))


def _coletar(slug, fichas_alvo, *, profundidade, modo, coletor, fila, fila_opcoes, data_base_do_arquivo, ciclo_novo,
             ao_progresso, incluir_vinculados=True):
    """Enfileira e roda a fila; cada resultado é gravado por `processar_resultado`. Devolve o resumo da fila."""
    fila_mod = _mod("fila")
    fila = _fila(slug, fila, fila_opcoes)
    por_desde = {}
    for f in fichas_alvo:
        desde = desde_do_processo(f, data_base_do_arquivo)
        itens = [{"numero": f["numero"], "cliente": ficha.obter(f, "cliente") or ""}]
        if incluir_vinculados:
            itens += [{"numero": v["numero"], "cliente": ficha.obter(f, "cliente") or ""} for v in f.get("vinculados", [])]
        por_desde.setdefault(desde, []).extend(itens)
    numeros = [i["numero"] for itens in por_desde.values() for i in itens]
    if ciclo_novo:
        fila.reabrir(numeros)               # o que ficou para conferência no ciclo anterior ganha nova chance
    for desde, itens in sorted(por_desde.items(), key=lambda kv: kv[0] or ""):
        fila.enfileirar(itens, modo=modo, profundidade=profundidade, desde=desde, recoletar=ciclo_novo)

    def ao_resultado(item, resultado):
        processar_resultado(slug, item["numero"], resultado, profundidade)

    def andamento(resumo):
        _progresso(ao_progresso, "coleta", f"Coletados {resumo.get('coletado', 0)} de {resumo.get('total', 0)}", **resumo)

    fechar = getattr(coletor, "fechar", None)
    try:
        return fila_mod.rodar_fila(fila, coletor, ao_progresso=andamento, ao_resultado=ao_resultado, numeros=numeros), fila
    finally:
        if callable(fechar) and getattr(coletor, "_fluxo_abriu", False):
            fechar()


def _coletor_real():
    """O ColetorReal (exige o acesso configurado e rede); aberto pelo próprio fluxo e fechado no fim."""
    c = _mod("fila").ColetorReal()
    c._fluxo_abriu = True
    return c


def _abrir_ciclo(tipo, data_base, numeros, profundidade, arquivos):
    estado = _estado()
    ciclo = estado.get("ciclo")
    if ciclo and ciclo.get("tipo") == tipo and ciclo.get("id") == data_base and ciclo.get("fase") != "concluido":
        ciclo["numeros"] = sorted(set(ciclo.get("numeros", [])) | set(numeros))
        retomado = True
    else:
        ciclo = {"tipo": tipo, "id": data_base, "fase": "coleta", "numeros": sorted(numeros), "profundidade": profundidade,
                 "arquivos": list(arquivos), "iniciado_em": _agora_iso()}
        retomado = False
    ciclo["profundidade"] = profundidade
    estado["ciclo"] = ciclo
    _salvar_estado(estado)
    return ciclo, retomado


def _fechar_ciclo(fase):
    estado = _estado()
    if estado.get("ciclo"):
        estado["ciclo"]["fase"] = fase
        _salvar_estado(estado)


def _pendentes_de_revisao(slug, numeros=None):
    """Eventos `rascunho` do relatório (opcionalmente só dos processos `numeros`) com a classificação da triagem."""
    lista = comum.eventos()
    rascunhos = [e for e in lista if e.get("status") == "rascunho" and (numeros is None or e.get("numero") in numeros)]
    niveis = {}
    try:
        fichas = ficha.carregar(todas=True)
        triagem = _mod("triagem")
        for item in triagem.classificar_lista(rascunhos, fichas):
            nivel = item.get("nivel") if isinstance(item, dict) else None
            niveis[nivel or "?"] = niveis.get(nivel or "?", 0) + 1
    except Exception:  # noqa: BLE001 - a triagem é só informação
        niveis = {}
    return rascunhos, niveis


def _conferir_manualmente(slug, fila=None, fila_opcoes=None):
    try:
        return _fila(slug, fila, fila_opcoes).conferir_manualmente()
    except Exception:  # noqa: BLE001
        return []


def _guardar_ultimo_ciclo(avisos, conferir, extra=None):
    dados = {"em": _agora_iso(), "avisos": [a for a in avisos if a.get("codigo") in CODIGOS_PARA_CONFERIR or a.get("nivel") == "erro"],
             "conferir_manualmente": conferir, **(extra or {})}
    comum.save_json(Path(comum.DATA) / "ultimo_ciclo.json", dados)


def ultimo_ciclo(slug=None):
    """O que o último ciclo deixou para conferir: {"em", "avisos", "conferir_manualmente"} (ou {})."""
    with _em(slug):
        try:
            return comum.load_json(Path(comum.DATA) / "ultimo_ciclo.json", {}) or {}
        except ValueError:
            return {}


def _rodar_ciclo(tipo, projeto, fichas_alvo_fn, *, profundidade, modo, entregas, coletor, data_base, fila, fila_opcoes,
                 ao_progresso, arquivos_do_ciclo=(), data_base_do_arquivo=None, moldes=None, avisos_previos=(),
                 aguardar_revisao=True, entregar_opcoes=None):
    avisos = list(avisos_previos)
    with _em(projeto) as slug:
        perfil_mod = _perfil_mod()
        perfil = perfil_mod.carregar(slug)
        mudou = False
        for chave, valor in (("profundidade", profundidade), ("modo_coleta", modo), ("entregas", entregas)):
            if valor and perfil.get(chave) != valor:
                perfil[chave], mudou = valor, True
        if mudou:
            perfil_mod.salvar(perfil, slug)
        profundidade, modo = perfil["profundidade"], perfil["modo_coleta"]
        data_base = ficha.parse_data(data_base) or _hoje()
        alvo = fichas_alvo_fn(ficha.carregar(todas=True))
        numeros_alvo = {n for f in alvo for n in ficha.todos_os_numeros(f)}
        if not alvo:
            return _resultado(True, "Nada a coletar: nenhum processo se enquadra neste fluxo.", avisos, [], etapa="nada",
                              processos=0, conferir_manualmente=[], pendentes_de_revisao=0)
        ciclo, retomado = _abrir_ciclo(tipo, data_base, [f["numero"] for f in alvo], profundidade, arquivos_do_ciclo)
        _progresso(ao_progresso, "coleta", f"{'Retomando' if retomado else 'Iniciando'} a coleta de {len(alvo)} processo(s)")
        usar_real = coletor is None
        if usar_real:
            coletor = _coletor_real()
        try:
            resumo_fila, fila_usada = _coletar(slug, alvo, profundidade=profundidade, modo=modo, coletor=coletor, fila=fila,
                                               fila_opcoes=fila_opcoes, data_base_do_arquivo=data_base_do_arquivo,
                                               ciclo_novo=not retomado, ao_progresso=ao_progresso)
        except KeyboardInterrupt:
            return _resultado(False, "Interrompido. Tudo o que já foi coletado está gravado; rode de novo para continuar.",
                              avisos, [], etapa="interrompido", processos=len(alvo), conferir_manualmente=[],
                              pendentes_de_revisao=0, interrompido=True)
        finally:
            if usar_real and getattr(coletor, "fechar", None):
                coletor.fechar()
        if resumo_fila.get("pausada") or resumo_fila.get("parando") or resumo_fila.get("pendente"):
            return _resultado(True, f"Coleta em andamento ou pausada: {resumo_fila.get('coletado', 0)} de {resumo_fila.get('total', 0)} "
                              "coletado(s). Rode de novo para continuar.", avisos, [], etapa="coleta", fila=resumo_fila,
                              processos=len(alvo), conferir_manualmente=[], pendentes_de_revisao=0)
        _progresso(ao_progresso, "processamento", "Processando os eventos coletados")
        cont = processar_eventos(slug, profundidade=profundidade, ao_progresso=ao_progresso)
        sint = sintetizar(slug, numeros={f["numero"] for f in alvo}, ao_progresso=ao_progresso)
        conferir = _conferir_manualmente(slug, fila_usada)
        rascunhos, niveis = _pendentes_de_revisao(slug, numeros_alvo)
        extra = dict(etapa="revisao", fila=resumo_fila, processos=len(alvo), eventos=cont, sintese=sint,
                     conferir_manualmente=conferir, pendentes_de_revisao=len(rascunhos), niveis_de_revisao=niveis,
                     retomado=retomado)
        abertos = [e for e in comum.eventos() if e.get("status") in EVENTOS_ABERTOS and e.get("numero") in numeros_alvo]
        if abertos:
            avisos.append(_aviso("atencao", "evento_nao_processado", "eventos",
                                 f"{len(abertos)} evento(s) coletado(s) não puderam ser processados; ficam para o próximo ciclo."))
        if rascunhos and aguardar_revisao:
            _fechar_ciclo("revisao")
            _guardar_ultimo_ciclo(avisos, conferir)
            return _resultado(True, f"Coleta pronta: {resumo_fila.get('coletado', 0)} processo(s) coletado(s), "
                              f"{len(conferir)} para conferir manualmente. Falta revisar {len(rascunhos)} evento(s) "
                              "(tela Revisar); depois rode este fluxo de novo para gerar os arquivos.", avisos, [], **extra)
        saida = entregar(slug, entregas or perfil["entregas"], data_base=data_base, moldes=moldes, tipo=tipo,
                         ao_progresso=ao_progresso, **(entregar_opcoes or {}))
        _fechar_ciclo("concluido" if saida["ok"] else "revisao")
        saida["avisos"] = avisos + saida["avisos"]
        _guardar_ultimo_ciclo(saida["avisos"], conferir, {"rodada": str(saida.get("rodada") or "")})
        saida.update({k: v for k, v in extra.items() if k not in ("etapa",)}, etapa="entregue" if saida["ok"] else "entrega")
        saida["resumo"] = (f"{resumo_fila.get('coletado', 0)} processo(s) coletado(s), {len(conferir)} para conferir manualmente. "
                           + saida["resumo"])
        return saida


# ================================================================ 3. inicial

def inicial(projeto, *, profundidade=None, modo=None, entregas=None, cliente=None, coletor=None, data_base=None,
            todos=False, fila=None, fila_opcoes=None, ao_progresso=None, incluir_vinculados=True):
    """Relatório inicial: coleta os processos SEM relatório anterior (ou todos, com `todos=True`; `cliente` filtra),
    grava capa, eventos, momento atual e último andamento, e PARA na revisão dos rascunhos. Rodar de novo com tudo
    aprovado gera as entregas (A, B e C conforme `entregas` ou o perfil) e fecha o ciclo. Retomável.

    `coletor`: objeto com `coletar(processo, profundidade, desde)` (ColetorSimulado nos testes); None = ColetorReal
    (exige o acesso configurado). `fila`/`fila_opcoes` trocam a fila (testes: relógio, pausa e janela).
    Devolve o dict padrão mais `etapa` ("nada", "coleta", "revisao", "entregue", "interrompido"), `fila` (resumo),
    `processos`, `eventos`, `sintese`, `conferir_manualmente`, `pendentes_de_revisao`, `niveis_de_revisao`."""
    def alvo(fichas):
        return [f for f in fichas if f.get("ativo", True) and (not cliente or ficha.obter(f, "cliente") == cliente)
                and (todos or _precisa_inicial(f))]
    return _rodar_ciclo("inicial", projeto, alvo, profundidade=profundidade, modo=modo, entregas=entregas, coletor=coletor,
                        data_base=data_base, fila=fila, fila_opcoes=fila_opcoes, ao_progresso=ao_progresso)


# ================================================================ 4. atualizar

def _molde_por_cliente(lidos_docx, clientes):
    """{cliente: caminho} para os .docx enviados: o título do documento (cliente) casa com o cliente das fichas;
    com um só cliente na carteira, o único .docx vale para ele."""
    saida = {}
    for l in lidos_docx:
        nome = l["rel"].get("cliente")
        alvo = next((c for c in clientes if nome and comum.normalizar(c) == comum.normalizar(nome)), None)
        if alvo is None and len(clientes) == 1 and len(lidos_docx) == 1:
            alvo = clientes[0]
        if alvo is not None:
            saida[alvo] = l["entrada"]
    return saida


def _texto_gravado(f, entrega):
    """O registro do último texto que o programa gravou nesta entrega (ou o único registro antigo)."""
    u = f.get("ultimo_texto_gravado") or {}
    por = u.get("por_entrega") or {}
    return por.get(entrega) if por else (u or None)


def _ler_enviados(arquivos, fichas, avisos, ao_progresso):
    """Lê os .docx/.xlsx enviados, compara com a carteira e funde na lista de fichas (alterada no lugar). Devolve
    {"docx_a": {...}, "xlsx_b": Path|None, "data_base": ISO|None, "novos": [...], "sumiram": [...]}."""
    leitores = _mod("leitores")
    lidos = []
    for caminho in map(Path, arquivos or []):
        _progresso(ao_progresso, "leitura", f"Lendo {caminho.name}")
        rel = leitores.ler(caminho)
        if rel.get("formato") not in ("docx_a", "xlsx_b") or not rel.get("processos"):
            motivo = next((a["mensagem"] for a in rel.get("avisos", []) if a.get("nivel") == "erro"),
                          "só envie o relatório em texto (.docx) ou a planilha (.xlsx) no formato do programa")
            avisos.append(_aviso("erro", "arquivo_nao_aceito", caminho.name, f"Não usei {caminho.name}: {motivo}."))
            continue
        avisos += [_aviso_ok(a, caminho.name) for a in rel.get("avisos", [])]
        lidos.append({"caminho": caminho, "rel": rel, "entrada": _copiar_para_entrada(caminho)})
    novos_n, sumiram_n = [], []
    por_numero = {n: f for f in fichas for n in ficha.todos_os_numeros(f)}
    for l in lidos:
        rel, nome = l["rel"], l["caminho"].name
        fs, av = fichas_do_relatorio(rel, nome)
        avisos += [_aviso_ok(a, nome) for a in av]
        numeros_no_arquivo = {n for p in rel["processos"] for n in [p["numero"], *[v["numero"] for v in p.get("vinculados", [])]]}
        entrega = rel["formato"]
        for p in rel["processos"]:
            f = por_numero.get(p["numero"])
            texto = _norm(p.get("andamentos_texto"))
            gravado = _texto_gravado(f, entrega) if f is not None else None
            if f is not None and gravado and gravado.get("texto") and texto and _norm(gravado["texto"]) != texto:
                avisos.append(_aviso("info", "texto_editado_a_mao", p["numero"],
                                     f"O texto de andamentos de {p['numero']} em {nome} difere do último que o programa gravou "
                                     "(edição à mão ou outra origem). O programa só acrescenta; nada do que está lá será reescrito."))
        principais = {f["numero"] for f in fichas}
        fs = [f for f in fs if f["numero"] in principais or f["numero"] not in por_numero]    # vinculado não vira linha
        novas = [f for f in fs if f["numero"] not in por_numero]
        for f in novas:
            novos_n.append(f["numero"])
            avisos.append(_aviso("atencao", "processo_novo_no_arquivo", f["numero"],
                                 f"O processo {f['numero']} está em {nome} mas não estava na carteira: entrou agora, com o histórico do arquivo."))
        _mesclar(fichas, fs)
        por_numero.update({n: f for f in fichas for n in ficha.todos_os_numeros(f)})
        escopo = [f for f in fichas if f.get("ativo", True) and (not rel.get("cliente")
                  or comum.normalizar(ficha.obter(f, "cliente") or "") == comum.normalizar(rel["cliente"]))]
        for f in escopo:
            if not (set(ficha.todos_os_numeros(f)) & numeros_no_arquivo) and f["numero"] not in sumiram_n:
                sumiram_n.append(f["numero"])
                avisos.append(_aviso("atencao", "processo_sumiu_do_arquivo", f["numero"],
                                     f"O processo {f['numero']} está na carteira mas não aparece em {nome}. Ele continua sendo "
                                     "acompanhado; se saiu da carteira, marque-o como inativo."))
    bases = [l["rel"].get("data_base") for l in lidos if l["rel"].get("data_base")]
    docx = [l for l in lidos if l["rel"]["formato"] == "docx_a"]
    xlsx = [l for l in lidos if l["rel"]["formato"] == "xlsx_b"]
    return {"lidos": lidos, "docx": docx, "xlsx": xlsx[-1]["entrada"] if xlsx else None,
            "data_base": max(bases) if bases else None, "novos": novos_n, "sumiram": sumiram_n}


def atualizar(projeto, arquivos=None, *, profundidade=None, modo=None, entregas=None, cliente=None, coletor=None,
              data_base=None, fila=None, fila_opcoes=None, ao_progresso=None, incluir_vinculados=True):
    """Atualização mensal. Opcionalmente lê o .docx/.xlsx mais recente (`arquivos`): processo novo entra, processo que
    sumiu e texto alterado à mão viram avisos, campos `humano` do arquivo são preservados. Coleta SÓ o que veio depois
    da data-base de cada processo (`desde`), processa, sintetiza e PARA na revisão. Com tudo aprovado, rodar de novo
    gera VERSÕES NOVAS dos arquivos enviados (o enviado é o molde; o original nunca é sobrescrito) e regenera o outro
    a partir da ficha (partindo da última entrega do programa, se houver). O .html não precisa ser enviado.

    Devolve o mesmo dict de `inicial`, mais `novos` e `sumiram` (números) quando houve arquivo."""
    avisos, moldes, base_arquivo, extra = [], {}, None, {}
    with _TRAVA, _em(projeto) as slug:
        if arquivos:
            fichas = ficha.carregar(todas=True)
            lidos = _ler_enviados(arquivos, fichas, avisos, ao_progresso)
            ficha.salvar(fichas)
            _registrar_clientes(fichas)
            clientes = sorted({ficha.obter(f, "cliente") or "" for f in fichas} - {""})
            if lidos["docx"]:
                moldes["docx_a"] = _molde_por_cliente(lidos["docx"], clientes)
            if lidos["xlsx"]:
                moldes["xlsx_b"] = lidos["xlsx"]
            base_arquivo = lidos["data_base"]
            extra = {"novos": lidos["novos"], "sumiram": lidos["sumiram"]}
            if not (lidos["docx"] or lidos["xlsx"]) and not lidos["lidos"]:
                return _resultado(False, "Nenhum dos arquivos enviados pôde ser usado.", avisos, [], etapa="arquivos", **extra)
    def alvo(fichas):
        return [f for f in fichas if f.get("ativo", True) and (not cliente or ficha.obter(f, "cliente") == cliente)]
    saida = _rodar_ciclo("atualizar", projeto, alvo, profundidade=profundidade, modo=modo, entregas=entregas,
                         coletor=coletor, data_base=data_base, fila=fila, fila_opcoes=fila_opcoes, ao_progresso=ao_progresso,
                         arquivos_do_ciclo=[Path(a).name for a in arquivos or []], data_base_do_arquivo=base_arquivo,
                         moldes=moldes or None, avisos_previos=avisos)
    saida.update(extra)
    if moldes and saida.get("etapa") == "revisao":
        with _em(projeto):                          # guarda os moldes do ciclo para a retomada depois da revisão
            estado = _estado()
            if estado.get("ciclo"):
                estado["ciclo"]["moldes"] = {k: ({c: str(p) for c, p in v.items()} if isinstance(v, dict) else str(v))
                                             for k, v in moldes.items()}
                _salvar_estado(estado)
    return saida


# ================================================================ 5. entregar

def _view(f, entrega):
    """Cópia rasa da ficha em que `ultimo_texto_gravado` é o registro DESTA entrega (ver cabeçalho, decisão 2)."""
    u = f.get("ultimo_texto_gravado")
    if not u:
        return f
    por = u.get("por_entrega") or {}
    if entrega in por:
        registro = dict(por[entrega])
    elif por:
        registro = {}
    else:
        registro = {k: v for k, v in u.items() if k != "por_entrega"}
    v = dict(f)
    v["ultimo_texto_gravado"] = registro
    if entrega == "docx_a":
        v.pop("ultimos_valores_gravados", None)
    return v


def _guardar_gravados(fichas, entrega, res, data_base, nome_arquivo):
    """textos_gravados / campos_gravados / valores_gravados do escritor -> ficha (decisão 2)."""
    por_numero = {f["numero"]: f for f in fichas}
    for numero, texto in (res.get("textos_gravados") or {}).items():
        f = por_numero.get(numero)
        if f is None:
            continue
        registro = {"data_base": data_base, "texto": texto, "arquivo": nome_arquivo}
        campos = (res.get("campos_gravados") or {}).get(numero)
        if campos:
            registro["campos"] = campos
        u = f.get("ultimo_texto_gravado") or {}
        por = dict(u.get("por_entrega") or {})
        if not por and u.get("texto") is not None:       # registro antigo, sem entrega: vira o desta entrega
            por[entrega] = {k: v for k, v in u.items() if k != "por_entrega"}
        por[entrega] = registro
        f["ultimo_texto_gravado"] = {**registro, "por_entrega": por}      # o espelho é a gravação mais recente
    for numero, valores in (res.get("valores_gravados") or {}).items():
        f = por_numero.get(numero)
        if f is not None and valores:
            f["ultimos_valores_gravados"] = {**(f.get("ultimos_valores_gravados") or {}), **valores}


def _como_aprovado(ev):
    return dict(ev, status="aprovado")


def _eventos_para(entrega, fichas, aprovados, relatados, tem_molde):
    """Eventos que o escritor recebe: os aprovados; sem molde (o arquivo nasce agora), também os já relatados, para
    o histórico não se perder. Os escritores só acrescentam e conferem o que já consta."""
    numeros = {n for f in fichas for n in ficha.todos_os_numeros(f)}
    lista = [e for e in aprovados if e.get("numero") in numeros]
    if not tem_molde:
        lista += [_como_aprovado(e) for e in relatados if e.get("numero") in numeros]
    return lista


def _aplicar_julgamento(fichas, aprovados, relatados):
    """Sugestão dos campos de julgamento (`sugerido`), só para processos com evento aprovado/relatado."""
    try:
        julgamento = _mod("julgamento")
    except ImportError:
        return 0
    por_numero = {}
    for e in aprovados + relatados:
        por_numero.setdefault(e.get("numero"), []).append(e)
    gravados = 0
    for f in fichas:
        evs = [e for n in ficha.todos_os_numeros(f) for e in por_numero.get(n, [])]
        if not evs:
            continue
        try:
            gravados += len(julgamento.aplicar(f, julgamento.sugerir(f, evs)))
        except Exception:  # noqa: BLE001 - sugestão é auxiliar; nunca derruba a entrega
            continue
    return gravados


def _narrativas(fichas, aprovados, perfil, slug, data_base):
    """Texto de andamentos por processo (inicial ou incremental) a partir dos eventos aprovados, para conferência."""
    try:
        sintese = _mod("sintese")
    except ImportError:
        return {}
    por_numero = {}
    for e in aprovados:
        por_numero.setdefault(e.get("numero"), []).append(e)
    saida = {}
    for f in fichas:
        evs = [e for n in ficha.todos_os_numeros(f) for e in por_numero.get(n, [])]
        if not evs:
            continue
        try:
            inicial_ = not f.get("linha_de_base") and not f.get("ultimo_texto_gravado")
            saida[f["numero"]] = (sintese.narrativa_inicial(f, evs, perfil.get("profundidade", "padrao"), None) if inicial_
                                  else sintese.narrativa_incremental(f, evs))
        except Exception:  # noqa: BLE001
            continue
    if saida:
        comum.save_json(Path(comum.DATA) / "narrativas" / f"{data_base}.json", saida)
    return saida


def _moldes(perfil, clientes, explicitos, usar_ultimas):
    """{"docx_a": {cliente: Path|None}, "xlsx_b": Path|None}. Ordem: o molde pedido (`explicitos`; `None` = "sem molde"),
    o do ciclo em andamento (arquivos enviados antes da revisão) e, só com `usar_ultimas`, o MAIS RECENTE (pela data
    de modificação) entre a última entrega do programa e o arquivo de entrada/ (o .docx quando há um único cliente;
    a planilha quando o perfil diz que o molde é a do cliente): um arquivo mais novo que a última entrega foi
    enviado depois dela e vale mais; a última entrega vale mais que um arquivo antigo de entrada/, senão o que foi
    entregue e relatado se perderia."""
    ent = _mod("painel.entregas")
    explicitos = explicitos or {}
    estado = _estado()
    guardados = (estado.get("ciclo") or {}).get("moldes") or {}
    ultimas = estado.get("ultimas_entregas", {}) if usar_ultimas else {}

    def existe(p):
        return Path(p) if p and Path(p).is_file() else None

    def do_cliente(fonte, c):
        return existe(fonte.get(c) if isinstance(fonte, dict) else fonte)

    def mais_novo(*candidatos):
        validos = [c for c in candidatos if c]
        return max(validos, key=lambda p: p.stat().st_mtime) if validos else None
    docx = {}
    sem_molde = "docx_a" in explicitos and explicitos["docx_a"] is None
    for c in clientes:
        molde = None
        if not sem_molde:
            molde = do_cliente(explicitos.get("docx_a"), c) or do_cliente(guardados.get("docx_a"), c)
            if molde is None and usar_ultimas:
                molde = mais_novo(do_cliente(ultimas.get("docx_a") or {}, c),
                                  ent.molde_mais_recente(".docx") if len(clientes) == 1 else None)
        docx[c] = molde
    xlsx = None
    if not ("xlsx_b" in explicitos and explicitos["xlsx_b"] is None):
        xlsx = existe(explicitos.get("xlsx_b")) or existe(guardados.get("xlsx_b"))
        if xlsx is None and usar_ultimas:
            xlsx = mais_novo(existe(ultimas.get("xlsx_b")),
                             ent.molde_mais_recente(".xlsx") if perfil.get("molde_planilha") == "cliente" else None)
    return {"docx_a": docx, "xlsx_b": xlsx}


def entregar(projeto=None, entregas=None, *, data_base=None, moldes=None, tipo="entrega", fichas=None,
             parametros_extra=None, campos_nao_migrados=None, dashboard_modo="embutido", recalcular=None,
             usar_ultimas=True, rodada=None, marcar_relatados=True, ao_progresso=None):
    """Gera as entregas pedidas (padrão: as do perfil) numa subpasta nova de saida/ e confere o resultado.

    Ordem: julgamento (sugestões, só com eventos aprovados) -> narrativa -> .docx (um por cliente) -> .xlsx ->
    painel .html (lê a planilha) -> `qualidade.verificar` -> `qualidade.o_que_mudou` (contra o retrato anterior)
    -> `historico.gravar_retrato`. Depois guarda na ficha `ultimo_texto_gravado` e `ultimos_valores_gravados`, marca
    `relatado` os eventos gravados nos arquivos pedidos e lembra as últimas entregas (molde do próximo ciclo).

    `moldes`: {"docx_a": {cliente: Path}|Path, "xlsx_b": Path}; `None` explícito = "sem molde" (modelo padrão).
    `fichas`: gera só de um conjunto (nada é persistido; usado pela tela de migração). `dashboard_modo`:
    "embutido" (abre já preenchido) ou "modelo". `recalcular`: recalcular as fórmulas da planilha com o LibreOffice
    (padrão: se houver `soffice`). Devolve {"ok", "resumo", "avisos", "arquivos", "rodada", "resultados", "qualidade",
    "o_que_mudou", "relatados", "retrato"}."""
    ent = _mod("painel.entregas")
    with _TRAVA, _em(projeto) as slug:
        perfil = _perfil(slug)
        entregas = [e for e in (entregas or perfil["entregas"]) if e in ENTREGAS]
        subconjunto = fichas is not None
        todas = fichas if subconjunto else ficha.carregar(todas=True)
        base_iso = ficha.parse_data(data_base) or _hoje()
        nome_relatorio = comum.projeto().get("nome", slug)
        lista_eventos = comum.eventos()
        aprovados = [e for e in lista_eventos if e.get("status") == "aprovado"]
        relatados = [e for e in lista_eventos if e.get("status") == "relatado"]
        rodada = Path(rodada) if rodada else ent.nova_rodada(tipo)
        saida = {"rodada": rodada, "arquivos": [], "resultados": {}, "avisos": [], "qualidade": None, "o_que_mudou": None,
                 "relatados": 0, "retrato": None}
        avisos = saida["avisos"]
        _progresso(ao_progresso, "entrega", "Calculando as sugestões de julgamento e a narrativa")
        julgados = 0 if subconjunto else _aplicar_julgamento(todas, aprovados, relatados)
        narrativas = {} if subconjunto else _narrativas(todas, aprovados, perfil, slug, base_iso)
        clientes = sorted({ficha.obter(f, "cliente") or "" for f in todas}) or [""]
        usados = _moldes(perfil, clientes, moldes, usar_ultimas)
        extra_parametros = {**(parametros_extra or {})}
        nao_migrados = campos_nao_migrados if campos_nao_migrados is not None else extra_parametros.get("campos_nao_migrados")
        parametros = {**perfil.get("parametros", {}), **extra_parametros}
        historico = _mod("historico")
        try:
            retratos = list(historico.carregar(slug))
        except Exception:  # noqa: BLE001
            retratos = []

        def estado(nome, fs, evs):
            e = {"cliente": nome, "data_base": base_iso, "fichas": fs, "eventos": evs, "perfil": perfil, "parametros": parametros,
                 "historico": [r for r in retratos if r.get("data_base") != base_iso]}
            if nao_migrados:
                e["campos_nao_migrados"] = nao_migrados
            return e

        escritos = {"docx_a": False, "xlsx_b": False}          # ficha -> gravada nos arquivos pedidos
        gravou_numero = {"docx_a": set(), "xlsx_b": set()}
        # 1. texto (um por cliente)
        if "docx_a" in entregas:
            _progresso(ao_progresso, "entrega", "Gravando o relatório em texto (.docx)")
            try:
                escritor = ent.modulo("escritores.docx_a", "O escritor do relatório em texto (.docx)")
                ok_todos = True
                for cliente in clientes:
                    do_cliente = [f for f in todas if (ficha.obter(f, "cliente") or "") == cliente]
                    molde = usados["docx_a"].get(cliente)
                    evs = _eventos_para("docx_a", do_cliente, aprovados, relatados, molde is not None)
                    destino = rodada / f"Relatório - {ent.nome_de_arquivo(cliente or nome_relatorio)}.docx"
                    res = escritor.gravar(molde, estado(cliente or nome_relatorio, [_view(f, "docx_a") for f in do_cliente], evs), destino)
                    saida["resultados"][f"docx_a: {cliente or nome_relatorio}"] = res
                    destino_ok = res.get("destino") and Path(res["destino"]).is_file() and res.get("gravado", True)
                    avisos.extend(res.get("avisos", []))
                    avisos.extend(_avisos_de_ignorados(res, "docx_a"))
                    if destino_ok:
                        saida["arquivos"].append(Path(res["destino"]))
                        if not subconjunto:
                            _guardar_gravados(todas, "docx_a", res, base_iso, Path(res["destino"]).name)
                        gravou_numero["docx_a"] |= {f["numero"] for f in do_cliente}
                        saida.setdefault("moldes_novos", {}).setdefault("docx_a", {})[cliente] = str(res["destino"])
                    else:
                        ok_todos = False
                escritos["docx_a"] = ok_todos
            except ent.Indisponivel as erro:
                avisos.append(_aviso("erro", "escritor_indisponivel", "docx_a", str(erro)))
            except Exception as erro:  # noqa: BLE001 - erro de escritor vira aviso; os demais seguem
                avisos.append(_aviso("erro", "escritor_falhou", "docx_a", f"Não consegui gerar o relatório em texto: {erro}"))
        # 2. planilha
        caminho_planilha = None
        if "xlsx_b" in entregas or "dashboard" in entregas:
            _progresso(ao_progresso, "entrega", "Gravando a planilha (.xlsx)")
            try:
                escritor = ent.modulo("escritores.xlsx_b", "O escritor da planilha (.xlsx)")
                molde = usados["xlsx_b"]
                evs = _eventos_para("xlsx_b", todas, aprovados, relatados, molde is not None)
                destino = rodada / f"Planilha - {ent.nome_de_arquivo(nome_relatorio)}.xlsx"
                opcoes = {}
                if (recalcular if recalcular is not None else bool(shutil.which("soffice"))):
                    opcoes["recalcular_com_soffice"] = True
                res = escritor.gravar(molde, estado(nome_relatorio, [_view(f, "xlsx_b") for f in todas], evs), destino, **opcoes)
                saida["resultados"]["xlsx_b"] = res
                avisos.extend(res.get("avisos", []))
                avisos.extend(_avisos_de_ignorados(res, "xlsx_b"))
                if res.get("destino") and Path(res["destino"]).is_file():
                    caminho_planilha = Path(res["destino"])
                    saida["arquivos"].append(caminho_planilha)
                    if not subconjunto:
                        _guardar_gravados(todas, "xlsx_b", res, base_iso, caminho_planilha.name)
                    gravou_numero["xlsx_b"] = {f["numero"] for f in todas}
                    saida.setdefault("moldes_novos", {})["xlsx_b"] = str(caminho_planilha)
                    escritos["xlsx_b"] = True
            except ent.Indisponivel as erro:
                avisos.append(_aviso("erro", "escritor_indisponivel", "xlsx_b", str(erro)))
            except Exception as erro:  # noqa: BLE001
                avisos.append(_aviso("erro", "escritor_falhou", "xlsx_b", f"Não consegui gerar a planilha: {erro}"))
        # 3. painel (lê a planilha)
        if "dashboard" in entregas:
            if caminho_planilha is None:
                avisos.append(_aviso("erro", "painel_sem_planilha", "dashboard", "O painel precisa da planilha, que não foi gerada."))
            else:
                _progresso(ao_progresso, "entrega", "Gravando o painel (.html)")
                try:
                    escritor = ent.modulo("escritores.dashboard", "O gerador do painel (.html)")
                    destino = rodada / f"Painel - {ent.nome_de_arquivo(nome_relatorio)}.html"
                    opcoes = {"modo": dashboard_modo, "data_base": base_iso, "cliente": nome_relatorio}
                    if dashboard_modo == "embutido":
                        opcoes["historico"] = [r for r in retratos if r.get("data_base") != base_iso]
                    res = escritor.gravar(caminho_planilha, destino, perfil, **opcoes)
                    saida["resultados"]["dashboard"] = res
                    avisos.extend(res.get("avisos", []))
                    if res.get("destino"):
                        saida["arquivos"].append(Path(res["destino"]))
                        saida.setdefault("moldes_novos", {})["dashboard"] = str(res["destino"])
                except ent.Indisponivel as erro:
                    avisos.append(_aviso("erro", "escritor_indisponivel", "dashboard", str(erro)))
                except Exception as erro:  # noqa: BLE001
                    avisos.append(_aviso("erro", "escritor_falhou", "dashboard", f"Não consegui gerar o painel: {erro}"))
        # 4. qualidade e o que mudou
        _progresso(ao_progresso, "entrega", "Conferindo a qualidade da base")
        try:
            qual = ent.modulo("qualidade", "O verificador de qualidade da base")
            achados = qual.verificar(todas, perfil)
            destino = rodada / "qualidade.html"
            destino.write_text(ent.html_da_qualidade(achados, f"Qualidade da base: {nome_relatorio}"), encoding="utf-8")
            saida["arquivos"].append(destino)
            saida["qualidade"] = achados
        except ent.Indisponivel as erro:
            avisos.append(_aviso("info", "qualidade_indisponivel", "qualidade", str(erro)))
        except Exception as erro:  # noqa: BLE001
            avisos.append(_aviso("atencao", "qualidade_falhou", "qualidade", f"Não consegui verificar a qualidade da base: {erro}"))
        if not subconjunto:
            try:
                anteriores = [r for r in retratos if r.get("data_base") < base_iso]
                mudou = _mod("qualidade").o_que_mudou(anteriores[-1] if anteriores else None,
                                                      {"fichas": todas, "eventos": aprovados + relatados, "data_base": base_iso})
                saida["o_que_mudou"] = mudou
                destino = rodada / "O que mudou neste ciclo.txt"
                destino.write_text(_texto_do_que_mudou(mudou), encoding="utf-8")
                saida["arquivos"].append(destino)
            except ImportError:
                pass
            except Exception as erro:  # noqa: BLE001
                avisos.append(_aviso("atencao", "o_que_mudou_falhou", "qualidade", f"Não consegui montar o 'o que mudou': {erro}"))
        # 5. memória do ciclo: eventos relatados, fichas, retrato, últimas entregas
        pedidos_arquivo = [e for e in ("docx_a", "xlsx_b") if e in entregas or (e == "xlsx_b" and "dashboard" in entregas)]
        relatados_agora = 0
        if marcar_relatados and not subconjunto and pedidos_arquivo and all(escritos[e] for e in pedidos_arquivo):
            gravados_em_todos = set.intersection(*[gravou_numero[e] for e in pedidos_arquivo])
            numeros_gravados = {n for f in todas if f["numero"] in gravados_em_todos for n in ficha.todos_os_numeros(f)}
            for ev in lista_eventos:
                if ev.get("status") == "aprovado" and ev.get("numero") in numeros_gravados:
                    ev["status"] = "relatado"
                    ev["relatado_em"] = base_iso
                    relatados_agora += 1
        saida["relatados"] = relatados_agora
        if not subconjunto:
            if relatados_agora:
                comum.salvar_eventos(lista_eventos)
            for f in todas:
                if f.get("ultimo_texto_gravado"):
                    f.pop("precisa_relatorio_inicial", None)
            ficha.salvar(todas)
            try:
                saida["retrato"] = str(historico.gravar_retrato(todas, base_iso))
            except Exception as erro:  # noqa: BLE001
                avisos.append(_aviso("atencao", "retrato_falhou", "histórico", f"Não consegui gravar o retrato do mês: {erro}"))
            if saida.get("moldes_novos"):
                estado_fluxo = _estado()
                ultimas = estado_fluxo.setdefault("ultimas_entregas", {})
                for chave, valor in saida["moldes_novos"].items():
                    if isinstance(valor, dict):
                        ultimas.setdefault(chave, {}).update(valor)
                    else:
                        ultimas[chave] = valor
                ultimas["data_base"] = base_iso
                _salvar_estado(estado_fluxo)
        erros = [a for a in avisos if a.get("nivel") == "erro"]
        saida["ok"] = bool(saida["arquivos"]) and not [a for a in erros if a["codigo"] in ("escritor_falhou", "escritor_indisponivel", "painel_sem_planilha")]
        n_ignorados = sum(len(r.get("ignorados") or []) for r in saida["resultados"].values())
        saida["resumo"] = (f"{len(saida['arquivos'])} arquivo(s) em saida/{rodada.name}; {relatados_agora} evento(s) marcado(s) como "
                           f"relatado(s); {julgados} campo(s) de julgamento sugerido(s); {n_ignorados} andamento(s) já constava(m); "
                           f"{len(erros)} erro(s).")
        saida["julgamento_sugerido"], saida["narrativas"] = julgados, len(narrativas)
        return saida


def _avisos_de_ignorados(res, onde):
    """`ignorados` (andamento que já constava no texto) -> um aviso por escritor, para a lista de conferência."""
    ign = res.get("ignorados") or []
    if not ign:
        return []
    numeros = sorted({i.get("numero") for i in ign if i.get("numero")})
    return [_aviso("info", "andamento_ja_presente", onde,
                   f"{len(ign)} andamento(s) não foram gravados porque já constavam no texto ({len(numeros)} processo(s)).", numeros[:20])]


def _texto_do_que_mudou(mudou):
    linhas = [f"O que mudou neste ciclo ({_data_br(mudou.get('data_antes'))} a {_data_br(mudou.get('data_depois'))})", ""]
    for cliente, dados in sorted((mudou.get("por_cliente") or {}).items()):
        linhas += [f"== {cliente or '(sem cliente)'} ==", dados.get("texto") or "", ""]
    return "\n".join(linhas).strip() + "\n"


# ================================================================ linha de comando

def _imprimir(res):
    print(res["resumo"])
    for a in res.get("avisos", []):
        if a.get("nivel") in ("erro", "atencao"):
            print(f"  [{a['nivel']}] {a['codigo']} ({a['onde']}): {a['mensagem']}")
    for a in res.get("arquivos", []):
        print(f"  arquivo: {a}")


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="fluxos.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="fluxo", required=True)
    m = sub.add_parser("migrar", help="importa relatórios existentes")
    m.add_argument("arquivos", nargs="+")
    m.add_argument("--projeto")
    m.add_argument("--nome")
    m.add_argument("--cliente")
    m.add_argument("--conferir", action="store_true", help="só mostra a conferência, sem gravar")
    c = sub.add_parser("converter", help="converte um relatório para o modelo A ou B")
    c.add_argument("arquivo")
    c.add_argument("--para", default="xlsx_b", choices=["docx_a", "xlsx_b", "ambos"])
    c.add_argument("--projeto")
    for nome, ajuda in (("inicial", "relatório inicial"), ("atualizar", "atualização mensal")):
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("--projeto", required=True)
        s.add_argument("--profundidade", choices=PROFUNDIDADES)
        s.add_argument("--modo", choices=["continuo", "imediato"])
        s.add_argument("--entregas", help="docx_a,xlsx_b,dashboard")
        s.add_argument("--cliente")
        s.add_argument("--data-base", help="AAAA-MM-DD (padrão: hoje)")
        if nome == "inicial":
            s.add_argument("--todos", action="store_true")
        else:
            s.add_argument("arquivos", nargs="*", help=".docx e/ou .xlsx mais recentes")
    e = sub.add_parser("entregar", help="gera os arquivos a partir da ficha e dos eventos aprovados")
    e.add_argument("--projeto", required=True)
    e.add_argument("--entregas")
    e.add_argument("--data-base")
    a = p.parse_args(argv)

    def progresso(d):
        if d.get("mensagem") and d.get("etapa") != "coleta":
            print(f"  {d['mensagem']}", flush=True)
    entregas = a.entregas.split(",") if getattr(a, "entregas", None) else None
    if a.fluxo == "migrar":
        res = migrar(a.arquivos, a.projeto, confirmar=not a.conferir, cliente_padrao=a.cliente, nome=a.nome, ao_progresso=progresso)
    elif a.fluxo == "converter":
        res = converter(a.arquivo, ["docx_a", "xlsx_b"] if a.para == "ambos" else a.para, projeto=a.projeto, ao_progresso=progresso)
    elif a.fluxo == "inicial":
        res = inicial(a.projeto, profundidade=a.profundidade, modo=a.modo, entregas=entregas, cliente=a.cliente,
                      data_base=a.data_base, todos=a.todos, ao_progresso=progresso)
    elif a.fluxo == "atualizar":
        res = atualizar(a.projeto, a.arquivos or None, profundidade=a.profundidade, modo=a.modo, entregas=entregas,
                        cliente=a.cliente, data_base=a.data_base, ao_progresso=progresso)
    else:
        res = entregar(a.projeto, entregas, data_base=a.data_base, ao_progresso=progresso)
    _imprimir(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
