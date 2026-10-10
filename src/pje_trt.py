"""Leitura dos autos pelo PJe do advogado (login do PDPJ), no lugar da Consulta Processual pública (que pede captcha).

Caminho (ver docs/pje-trt-login-proprio.md): login no PDPJ (pdpj.py, uma tentativa) -> para cada processo da
carteira: número -> processo no Acervo Geral do advogado -> linha do tempo dos autos -> PDF de cada documento novo.
Todas as chamadas saem de DENTRO da página do PJe (`fetch` no navegador do programa, com a sessão), como o próprio
PJe faz; só leitura: nenhuma escrita, nenhuma ciência de expediente, nenhum protocolo.

Mesmo contrato do `trt.coletar_processo` (mesmos eventos, mesmo estado em `estado[numero]["trt"]["1"]`, mesma pasta de
documentos), então relatórios já iniciados pela consulta pública seguem sem duplicar nada. Só o 1º grau é lido por
aqui; havendo indício de recurso, sai o aviso `grau_nao_lido` (conferir o 2º grau à mão).

Sem credenciais do PDPJ, com trava de login ou se o login falhar, `sessao_da_rodada` devolve None e a coleta continua
pela consulta pública, como antes. O login nunca é repetido na mesma rodada: nem se a sessão cair, nem se o navegador
for fechado e reaberto no meio dela (a sessão antiga morre com o navegador; o resto da rodada vai pela consulta pública).
"""
import base64
import datetime
import json
import re
import time
from urllib.parse import quote

import acesso
import comum
from comum import slug

API = "/pje-comum-api/api"
GRAU = "1"

LIMITE_PDF = 60 * 1024 * 1024          # documentos maiores que isto não são trazidos (memória do navegador e do programa)

_JS = """async ([url, binario, LIMITE]) => {
  const r = await fetch(url, {method: 'GET', credentials: 'include'});
  const tipo = r.headers.get('content-type') || '';
  if (!binario) return {status: r.status, tipo, texto: await r.text()};
  if (Number(r.headers.get('content-length') || 0) > LIMITE) return {status: r.status, tipo, grande: true};
  const b = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return {status: r.status, tipo, b64: btoa(s)};
}"""


class SessaoExpirada(RuntimeError):
    """O PJe recusou a sessão (401/403): é preciso entrar de novo (e isso é uma nova tentativa de login)."""


class SemAcesso(RuntimeError):
    """O PJe negou (403) UM documento (sigiloso, ou sem permissão desta conta). Não é sessão vencida: a leitura do resto
    segue e o documento fica para a próxima rodada (até desistir)."""


class NaoNoAcervo(LookupError):
    """O processo não está no Acervo Geral do advogado logado: a coleta usa a consulta pública para ele."""


def trt_do_numero(numero):
    m = re.search(r"\d{7}-\d{2}\.\d{4}\.5\.(\d{2})\.\d{4}", numero or "")
    return int(m.group(1)) if m else None


# --- a sessão no PJe ----------------------------------------------------------

class SessaoPje:
    """Uma página do PJe já logada. `chamar` pode ser trocado nos testes: (caminho, binario) -> dict."""

    def __init__(self, page, trt, chamar=None, grau=1):
        self.page, self.trt, self.grau = page, trt, int(grau)
        self._chamar = chamar or self._chamar_no_navegador
        self._usuario = None

    def _chamar_no_navegador(self, caminho, binario=False):
        return self.page.evaluate(_JS, [caminho, binario, LIMITE_PDF])

    def _get(self, caminho, binario=False, documento=False):
        r = self._chamar(caminho, binario)
        if documento and r["status"] == 403:
            raise SemAcesso("O PJe negou o acesso a este documento (HTTP 403).")
        if r["status"] in (401, 403):
            raise SessaoExpirada(f"O PJe recusou a sessão (HTTP {r['status']}).")
        if r["status"] != 200:
            raise RuntimeError(f"O PJe respondeu HTTP {r['status']} em {caminho.split('?')[0]}.")
        if not binario and str(r.get("texto", "")).lstrip()[:1] == "<":     # sessão vencida: o PJe devolve a tela de login com HTTP 200
            raise SessaoExpirada("O PJe devolveu uma página em vez dos dados (sessão vencida).")
        return r

    def id_usuario(self):
        """O `id` do advogado, que vem no access_token (JWT) da sessão: é o que o painel usa na URL."""
        if self._usuario is None:
            for c in self.page.context.cookies():
                if c["name"] == "access_token":
                    try:
                        carga = c["value"].split(".")[1]
                        carga += "=" * (-len(carga) % 4)
                        self._usuario = int(json.loads(base64.urlsafe_b64decode(carga))["id"])
                    except Exception:          # noqa: BLE001 - token ilegível: sem repetir nem citar o conteúdo dele
                        raise SessaoExpirada("O token do usuário na sessão do PJe não pôde ser lido.") from None
                    break
            if self._usuario is None:
                raise SessaoExpirada("A sessão do PJe não tem o token do usuário.")
        return self._usuario

    def buscar(self, numero):
        """O processo no Acervo Geral do advogado (dict com `id`, `numeroProcesso`...) ou levanta NaoNoAcervo."""
        r = self._get(f"{API}/paineladvogado/{self.id_usuario()}/processos?numeroProcesso={quote(numero, safe='')}"
                      "&pagina=1&tamanhoPagina=10&tipoPainelAdvogado=1")
        digitos = re.sub(r"\D", "", numero)
        for p in json.loads(r["texto"]).get("resultado") or []:
            if re.sub(r"\D", "", str(p.get("numeroProcesso", ""))) == digitos and str(p.get("id", "")).isdigit():
                return p
        raise NaoNoAcervo(f"{numero} não está no Acervo Geral do advogado logado.")

    def dados(self, id_processo):
        """Os dados do processo; o que interessa aqui: `instancia` (a deste sistema) e `outraInstancia` (True quando o
        processo também existe em outra instância, isto é, já subiu ao 2º grau)."""
        return json.loads(self._get(f"{API}/processos/id/{id_processo}")["texto"])

    def timeline(self, id_processo):
        r = self._get(f"{API}/processos/id/{id_processo}/timeline?somenteDocumentosAssinados=false"
                      "&buscarMovimentos=true&buscarDocumentos=true")
        return json.loads(r["texto"])

    def pdf(self, id_processo, id_documento):
        """Bytes do documento ou None (não veio PDF)."""
        r = self._get(f"{API}/processos/id/{id_processo}/documentos/id/{id_documento}/conteudo"
                      f"?incluirCapa=false&grau={self.grau}&incluirAssinatura=false", binario=True, documento=True)
        if r.get("grande"):
            raise RuntimeError(f"Documento maior que {LIMITE_PDF // (1024 * 1024)} MB: não trazido.")
        corpo = base64.b64decode(r.get("b64", "")) if r.get("b64") is not None else r.get("corpo", b"")
        return corpo if corpo[:4] == b"%PDF" else None


# --- da linha do tempo para o formato do coletor ---------------------------------

def data_br(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else None


def itens_da_timeline(itens):
    """(andamentos [(chave, data dd/mm/aaaa, texto)], documentos [dict]) do mais recente ao mais antigo, no mesmo formato
    de `trt.itens_do_processo`. A chave do andamento é `data com hora|texto` (única, como no coletor da consulta)."""
    movs, docs = [], []
    for it in sorted(itens or [], key=lambda x: str(x.get("data") or ""), reverse=True):
        titulo = " ".join((it.get("titulo") or "").split())
        if it.get("documento") in (True, "True"):
            if not str(it.get("id", "")).isdigit():      # sem id não há como pedir o PDF (e o id vai na URL)
                continue
            docs.append({"id": str(it.get("id")), "unico": it.get("idUnicoDocumento"), "tipo": it.get("tipo") or titulo,
                         "titulo": titulo, "data": data_br(it.get("data")),
                         "publico": not it.get("documentoSigiloso"), "cod_instancia": it.get("codigoInstancia")})
        else:
            movs.append((f"{it.get('data')}|{titulo}", data_br(it.get("data")), titulo))
    return movs, docs


# --- a sessão da rodada (login único) ------------------------------------------------

_SESSOES = {}       # (trt, grau) -> (contexto, SessaoPje | None); None = não deu: usar a consulta pública nesta rodada
_TENTADOS = set()   # (trt, grau) em que o login JÁ foi tentado nesta rodada (com ou sem sucesso): nunca uma segunda vez
AVISOS = []         # o que impediu o uso do PJe próprio (texto), para o relato da rodada


def credenciais_ok():
    return all(acesso.situacao_pdpj().values())


_CONTEXTOS_2G = {}   # (id do contexto original, grau) -> contexto isolado do 2º grau / TST (cookies próprios)


def _contexto_para(context, grau):
    """O 1º e o 2º grau NÃO podem dividir os cookies: o login no 2º grau sobrescreve a sessão do 1º e os documentos do 1º
    passam a falhar (visto na coleta real). O 2º grau usa um contexto de navegador próprio, aberto uma vez por rodada."""
    if int(grau) == 1:
        return context
    navegador = getattr(context, "browser", None)
    if navegador is None:
        return context
    chave = (id(context), int(grau))
    if chave not in _CONTEXTOS_2G:
        import janela
        _CONTEXTOS_2G[chave] = navegador.new_context(
            accept_downloads=True, viewport={"width": janela.TAMANHO[0], "height": janela.TAMANHO[1]},
            permissions=janela.PERMISSOES)
    return _CONTEXTOS_2G[chave]


def _avisar(texto):
    AVISOS.append(texto)
    print(texto + " Usando a consulta pública.", flush=True)


def _chave(trt, grau):
    """O TST é um sistema só para todos os TRTs: um login por rodada, qualquer que seja o TRT do processo."""
    return (0, 3) if int(grau) == 3 else (trt, int(grau))


def sessao_da_rodada(context, numero, abrir_pagina=None, entrar=None, grau=1):
    """A sessão logada do TRT (e do `grau`: 1 ou 2, mesma conta) do processo, ou None. O login é feito UMA vez por TRT, por
    grau e por rodada; falha não se repete. A rodada vale por TRT e grau, não por navegador: se o navegador for fechado e
    reaberto no meio dela (outro contexto), a sessão antiga se perdeu e NÃO se entra de novo (seria outro envio de
    credenciais): vai pela consulta pública."""
    trt = trt_do_numero(numero)
    if trt is None or not credenciais_ok():
        return None
    chave = _chave(trt, grau)
    rotulo = "TST" if int(grau) == 3 else f"TRT{trt}" + ("" if int(grau) == 1 else f" ({int(grau)}º grau)")
    if chave in _TENTADOS:
        contexto, sessao = _SESSOES.get(chave, (None, None))
        if sessao is not None and contexto is context:
            return sessao
        if sessao is not None:
            _SESSOES[chave] = (contexto, None)
            _avisar(f"PJe próprio do {rotulo}: o navegador foi reaberto no meio da rodada e o login do PDPJ não é repetido.")
        return None
    _TENTADOS.add(chave)                         # marcado ANTES: nenhuma segunda tentativa nesta rodada, aconteça o que acontecer
    _SESSOES[chave] = (context, None)
    import pdpj
    try:
        if pdpj.trava():
            raise pdpj.PdpjErro("travado", "Há uma trava de login do PDPJ; libere na tela Acesso e escritório.")
        if abrir_pagina is None:
            import janela
            abrir_pagina = janela.nova_pagina
        page = abrir_pagina(_contexto_para(context, grau))
        entrada = entrar or pdpj.entrar
        if int(grau) == 1:
            entrada(pdpj.Navegador(page), trt, consulta=False)
        else:
            entrada(pdpj.Navegador(page), trt, consulta=False, grau=int(grau))
        _SESSOES[chave] = (context, SessaoPje(page, trt, grau=grau))
        print(f"PJe do {rotulo}: login do PDPJ feito; os autos serão lidos pelo PJe do advogado.", flush=True)
    except pdpj.PdpjErro as e:
        _avisar(f"PJe próprio do {rotulo} indisponível ({e.etapa}): {e.mensagem}")
    except Exception as e:  # noqa: BLE001 - qualquer imprevisto: sem nova tentativa, a coleta segue pela consulta pública
        _avisar(f"PJe próprio do {rotulo} indisponível ({type(e).__name__}).")
    return _SESSOES[chave][1]


def encerrar_sessao(context, numero):
    """A sessão caiu no meio da rodada: não entra de novo (seria outra tentativa de login); o resto vai pela consulta pública."""
    trt = trt_do_numero(numero)
    if trt is not None:
        for grau in (1, 2, 3):
            _TENTADOS.add(_chave(trt, grau))
            _SESSOES[_chave(trt, grau)] = (context, None)


def zerar_rodada():
    for ctx in list(_CONTEXTOS_2G.values()):
        try:
            ctx.close()
        except Exception:  # noqa: BLE001 - o navegador pode já ter sido fechado
            pass
    _CONTEXTOS_2G.clear()
    _SESSOES.clear()
    _TENTADOS.clear()
    AVISOS.clear()


# --- a coleta de um processo (mesmo papel e contrato do trt.coletar_processo) -------------

REMESSA = re.compile(r"remetid[oa]s?\s+os\s+autos\s+para\s+[óo]rg[ãa]o\s+jurisdicional\s+competente|"
                     r"remetid[oa]s?\s+os\s+autos\s+.*processar\s+recurso|remessa\s+.*(tst|tribunal\s+superior)", re.I)


def _remessa_para_recurso(movs):
    """Motivo (texto) se algum andamento é a remessa dos autos para julgar recurso, senão None. É o andamento que o PJe do
    1º grau registra ao subir o processo; depois dele a tramitação segue em outro sistema (2º grau/TST)."""
    for _, _, texto in movs:
        if REMESSA.search(texto or ""):
            return f"andamento \"{' '.join(texto.split())[:70]}\""
    return None


def instancia_do_processo(sessao, id_processo):
    """{"atual": 1|2|None, "outra_instancia": True|False|None, "verificado_em"}: de qual instância é o sistema em que o
    processo foi lido e se ele também existe em outra (já subiu ao 2º grau). Vem do próprio PJe, sem ação da pessoa.
    Falha ao ler não derruba a coleta: devolve None nos campos (e o indício pelos andamentos vale)."""
    try:
        d = sessao.dados(id_processo)
        atual = d.get("instancia")
        outra = d.get("outraInstancia")
        return {"atual": atual if isinstance(atual, int) else None, "outra_instancia": outra if isinstance(outra, bool) else None,
                "verificado_em": datetime.datetime.now().isoformat(timespec="seconds")}
    except SessaoExpirada:
        raise
    except Exception:  # noqa: BLE001
        return {"atual": None, "outra_instancia": None, "verificado_em": datetime.datetime.now().isoformat(timespec="seconds")}


def coletar_processo(sessao, proc, estado, lista, historico, cota, desde=None, relato=None, segunda=None, terceira=None):
    """Lê o processo pelo PJe do advogado. `segunda` e `terceira` (opcionais) devolvem a sessão do 2º grau e a do TST
    (login só quando preciso).
    O `relato` do chamador só recebe o resultado quando a leitura TERMINA: se a sessão cair no meio (SessaoExpirada) e a
    coleta seguir pela consulta pública, nada do que o PJe tinha anotado (graus lidos, aviso de 2º grau) sobra para
    confundir o relato da consulta pública."""
    relato = relato if relato is not None else {}
    parcial = {"graus_lidos": [], "graus_falhos": [], "avisos": []}
    baixados = _coletar_processo(sessao, proc, estado, lista, historico, cota, desde, parcial, segunda, terceira)
    for chave, valor in parcial.items():
        if isinstance(valor, list):
            relato[chave] = valor if chave == "graus_lidos" else list(relato.get(chave, [])) + valor
        else:
            relato[chave] = valor
    return baixados


TST = re.compile(r"\bTST\b|tribunal\s+superior\s+do\s+trabalho|recurso\s+de\s+revista", re.I)


def _aviso(relato, numero, mensagem, grau="2"):
    relato["avisos"].append({"nivel": "atencao", "codigo": "grau_nao_lido", "onde": f"pje/{numero}", "mensagem": mensagem})
    relato["graus_falhos"].append({"grau": grau, "motivo": mensagem})


ROTULOS = {"1": "1º grau", "2": "2º grau", "3": "TST"}


def _ler_grau_superior(obter, numero, relato, grau):
    """(sessão, processo achado, andamentos, documentos próprios desse grau, instância) ou None, com o aviso no relato.
    Os documentos dos graus de baixo vêm na mesma linha do tempo, mas já foram lidos nas leituras deles."""
    nome = ROTULOS[str(grau)]
    sess = obter() if obter else None
    if sess is None:
        return None
    try:
        achado = sess.buscar(numero)
    except NaoNoAcervo:
        _aviso(relato, numero, f"O processo não está no acervo do {nome} do advogado logado. Conferir à mão.", grau=str(grau))
        return None
    movs, docs = itens_da_timeline(sess.timeline(achado["id"]))
    docs = [d for d in docs if d.get("cod_instancia") == int(grau)]
    return sess, achado, movs, docs, instancia_do_processo(sess, achado["id"])


def _sobe_ao_tst(movs):
    return any(TST.search(m[2] or "") and re.search(r"remess|remetid|subida|autos", m[2] or "", re.I) for m in movs)


def _coletar_processo(sessao, proc, estado, lista, historico, cota, desde, relato, segunda=None, terceira=None):
    import coletor
    import trt
    numero = proc["numero"]
    achado = sessao.buscar(numero)                                  # NaoNoAcervo sobe para o chamador
    movs, docs = itens_da_timeline(sessao.timeline(achado["id"]))
    reg_proc = estado.get(numero, {}).get("trt", {})

    instancia = instancia_do_processo(sessao, achado["id"])
    relato["instancia"] = instancia
    # `outraInstancia: true` confirma. `false` NÃO prova nada: num processo real que já está no TST, o PJe do 1º grau
    # diz `false` (o registro dele para na remessa). Por isso os andamentos valem sempre, além do sinal do PJe.
    if instancia["outra_instancia"] is True:
        motivo = "o PJe informa que o processo também está em outra instância (2º grau)"
    else:
        motivo = trt.indicio_de_recurso(movs, proc, reg_proc) or _remessa_para_recurso(movs)

    graus = {GRAU: (sessao, achado, movs, docs)}
    if motivo:
        lido = _ler_grau_superior(segunda, numero, relato, 2) if segunda else None
        if lido:
            s2, achado2, movs2, docs2, instancia2 = lido
            graus["2"] = (s2, achado2, movs2, docs2)
            relato["instancia_2g"] = instancia2
            if _sobe_ao_tst(movs2):
                lido3 = _ler_grau_superior(terceira, numero, relato, 3) if terceira else None
                if lido3:
                    s3, achado3, movs3, docs3, instancia3 = lido3
                    graus["3"] = (s3, achado3, movs3, docs3)
                    relato["instancia_tst"] = instancia3
                elif terceira is None or not relato["avisos"]:
                    _aviso(relato, numero, "O processo parece ter subido ao TST e o TST não foi lido (login do TST indisponível). "
                                           "Conferir no TST à mão.", grau="3")
        elif segunda is None:
            _aviso(relato, numero, f"O 2º grau não foi lido pelo PJe do advogado ({motivo}). Conferir o recurso à mão.")
        elif not relato["avisos"]:
            _aviso(relato, numero, f"O 2º grau não foi lido: o login do 2º grau não estava disponível ({motivo}). Conferir o recurso à mão.")
    relato["graus_lidos"] = list(graus)

    ids = {e["id"] for e in lista}
    varios = len(graus) > 1
    baixados, novo = 0, dict(reg_proc)
    for grau, (sess, ach, mv, dc) in graus.items():
        reg = reg_proc.get(grau)
        primeira_vez = reg is None
        reg = reg or {}
        nivel = ROTULOS[grau] if varios or grau != "1" else None
        conhecidos = set(reg.get("movimentos", []))
        if primeira_vez:
            novos = [m for m in mv if coletor._depois(m[1], desde)] if desde else mv[:historico]
        else:
            novos = [m for m in mv if m[0] not in conhecidos]
        for chave, data, texto in novos:
            ev = coletor._evento_base(proc, "movimento", f"trt|{grau}|{chave}", texto)
            if ev["id"] not in ids:
                ev.update(data=data, chave=chave, grau=nivel)
                lista.append(ev)
                ids.add(ev["id"])
        print(f"  {ROTULOS[grau]}: andamentos: {len(mv)} nos autos, {len(novos)} novo(s)", flush=True)

        docs_conhecidos = set(reg.get("documentos", []))
        falhas = dict(reg.get("falhas_documentos", {}))
        if primeira_vez:
            novos_docs = [d for d in dc if coletor._depois(d["data"], desde)] if desde else dc[:historico]
        else:
            novos_docs = [d for d in dc if d["id"] not in docs_conhecidos]
        fora_da_selecao = [d["id"] for d in dc if d not in novos_docs]
        for d in novos_docs[:max(cota - baixados, 0)]:
            nome = f"{d['id']} - {d['tipo']} - {d['titulo']}"
            ev = coletor._evento_base(proc, "documento", f"doc|{d['id']}", nome)
            anterior = next((e for e in lista if e["id"] == ev["id"]), None) if ev["id"] in ids else None
            if anterior is not None and anterior.get("arquivo"):
                docs_conhecidos.add(d["id"])
                continue
            arquivo = None
            try:
                corpo = sess.pdf(ach["id"], d["id"])
                if corpo:
                    arquivo = comum.DOCS_DIR / slug(proc.get("cliente") or "sem-cliente") / slug(numero) / f"{slug(d['id'] + '-' + d['tipo'])}.pdf"
                    arquivo.parent.mkdir(parents=True, exist_ok=True)
                    arquivo.write_bytes(corpo)
            except SessaoExpirada:
                raise
            except Exception as e:  # noqa: BLE001 - o documento fica para a próxima rodada; a coleta do processo segue
                print(f"  documento sem arquivo ({type(e).__name__}): {nome}", flush=True)
            if arquivo:
                baixados += 1
                falhas.pop(d["id"], None)
                docs_conhecidos.add(d["id"])
            else:
                falhas[d["id"]] = falhas.get(d["id"], 0) + 1
                if falhas[d["id"]] >= coletor.DESISTE_DO_DOCUMENTO:
                    docs_conhecidos.add(d["id"])
            dados_ev = dict(tipo=d["tipo"], descricao=d["titulo"], doc_id=d["id"], data=d["data"], grau=nivel,
                            arquivo=str(arquivo) if arquivo else None, print=None)
            if anterior is not None:
                anterior.update(dados_ev)
            else:
                ev.update(dados_ev)
                lista.append(ev)
                ids.add(ev["id"])
            print(f"  documento {'baixado' if arquivo else 'sem arquivo'}: {nome}", flush=True)
            coletor.pausa(comum.config()["coleta"]["pausa_entre_documentos_s"])
        print(f"  {ROTULOS[grau]}: documentos: {len(dc)} nos autos, {len(novos_docs)} novo(s)", flush=True)
        docs_conhecidos.update(fora_da_selecao)
        novo[grau] = {"movimentos": sorted({m[0] for m in mv} | conhecidos), "documentos": sorted(docs_conhecidos),
                      "falhas_documentos": falhas}
    estado[numero] = {"trt": novo, "instancia": instancia, "ultima_coleta": datetime.datetime.now().isoformat(timespec="seconds")}
    return baixados


# --- teste real, só leitura: login + um processo, contando (nada é gravado na carteira nem nos relatórios) ---------

def testar(numero, baixar_um=False):
    import sys
    import pdpj
    from playwright.sync_api import sync_playwright
    import janela
    with sync_playwright() as p:
        browser, context = janela.abrir_navegador(p)
        try:
            sessao = sessao_da_rodada(context, numero, abrir_pagina=lambda c: _pagina_visivel(c))
            if sessao is None:
                print("FALHOU: " + (" ".join(AVISOS) or "login não disponível (credenciais ou trava)."))
                return 1
            achado = sessao.buscar(numero)
            movs, docs = itens_da_timeline(sessao.timeline(achado["id"]))
            print(f"PJe OK: processo encontrado no Acervo Geral; {len(movs)} andamento(s) e {len(docs)} documento(s) nos autos.")
            if baixar_um and docs:
                corpo = sessao.pdf(achado["id"], docs[0]["id"])
                print(f"Documento mais recente: {'PDF de ' + str(len(corpo)) + ' bytes' if corpo else 'não veio PDF'} (não gravado).")
            return 0
        except NaoNoAcervo as e:
            print(f"AVISO: {e}")
            return 1
        finally:
            browser.close()


def _pagina_visivel(context):
    import janela
    page = context.new_page()
    janela.mostrar(page)
    return page


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if "--testar" in a:
        sys.exit(testar(a[a.index("--testar") + 1], baixar_um="--baixar-um" in a))
    print(__doc__)
