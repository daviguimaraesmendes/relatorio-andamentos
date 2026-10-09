"""Leitura dos autos pelo PJe do advogado (login do PDPJ), no lugar da Consulta Processual pública (que pede captcha).

Caminho (ver docs/pje-trt-login-proprio.md): login no PDPJ (pdpj.py, uma tentativa) -> para cada processo da
carteira: número -> processo no Acervo Geral do advogado -> linha do tempo dos autos -> PDF de cada documento novo.
Todas as chamadas saem de DENTRO da página do PJe (`fetch` no navegador do programa, com a sessão), como o próprio
PJe faz; só leitura: nenhuma escrita, nenhuma ciência de expediente, nenhum protocolo.

Mesmo contrato do `trt.coletar_processo` (mesmos eventos, mesmo estado em `estado[numero]["trt"]["1"]`, mesma pasta de
documentos), então relatórios já iniciados pela consulta pública seguem sem duplicar nada. Só o 1º grau é lido por
aqui; havendo indício de recurso, sai o aviso `grau_nao_lido` (conferir o 2º grau à mão).

Sem credenciais do PDPJ, com trava de login ou se o login falhar, `sessao_da_rodada` devolve None e a coleta continua
pela consulta pública, como antes. O login nunca é repetido na mesma rodada.
"""
import base64
import datetime
import json
import re
import time

import acesso
import comum
from comum import slug

API = "/pje-comum-api/api"
GRAU = "1"

_JS = """async ([url, binario]) => {
  const r = await fetch(url, {credentials: 'include'});
  const tipo = r.headers.get('content-type') || '';
  if (!binario) return {status: r.status, tipo, texto: await r.text()};
  const b = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return {status: r.status, tipo, b64: btoa(s)};
}"""


class SessaoExpirada(RuntimeError):
    """O PJe recusou a sessão (401/403): é preciso entrar de novo (e isso é uma nova tentativa de login)."""


class NaoNoAcervo(LookupError):
    """O processo não está no Acervo Geral do advogado logado: a coleta usa a consulta pública para ele."""


def trt_do_numero(numero):
    m = re.search(r"\d{7}-\d{2}\.\d{4}\.5\.(\d{2})\.\d{4}", numero or "")
    return int(m.group(1)) if m else None


# --- a sessão no PJe ----------------------------------------------------------

class SessaoPje:
    """Uma página do PJe já logada. `chamar` pode ser trocado nos testes: (caminho, binario) -> dict."""

    def __init__(self, page, trt, chamar=None):
        self.page, self.trt = page, trt
        self._chamar = chamar or self._chamar_no_navegador
        self._usuario = None

    def _chamar_no_navegador(self, caminho, binario=False):
        return self.page.evaluate(_JS, [caminho, binario])

    def _get(self, caminho, binario=False):
        r = self._chamar(caminho, binario)
        if r["status"] in (401, 403):
            raise SessaoExpirada(f"O PJe recusou a sessão (HTTP {r['status']}).")
        if r["status"] != 200:
            raise RuntimeError(f"O PJe respondeu HTTP {r['status']} em {caminho.split('?')[0]}.")
        return r

    def id_usuario(self):
        """O `id` do advogado, que vem no access_token (JWT) da sessão: é o que o painel usa na URL."""
        if self._usuario is None:
            for c in self.page.context.cookies():
                if c["name"] == "access_token":
                    carga = c["value"].split(".")[1]
                    carga += "=" * (-len(carga) % 4)
                    self._usuario = int(json.loads(base64.urlsafe_b64decode(carga))["id"])
                    break
            if self._usuario is None:
                raise SessaoExpirada("A sessão do PJe não tem o token do usuário.")
        return self._usuario

    def buscar(self, numero):
        """O processo no Acervo Geral do advogado (dict com `id`, `numeroProcesso`...) ou levanta NaoNoAcervo."""
        r = self._get(f"{API}/paineladvogado/{self.id_usuario()}/processos?numeroProcesso={numero}"
                      "&pagina=1&tamanhoPagina=10&tipoPainelAdvogado=1")
        digitos = re.sub(r"\D", "", numero)
        for p in json.loads(r["texto"]).get("resultado") or []:
            if re.sub(r"\D", "", str(p.get("numeroProcesso", ""))) == digitos:
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
                      "?incluirCapa=false&grau=1&incluirAssinatura=false", binario=True)
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
            docs.append({"id": str(it.get("id")), "unico": it.get("idUnicoDocumento"), "tipo": it.get("tipo") or titulo,
                         "titulo": titulo, "data": data_br(it.get("data")),
                         "publico": not it.get("documentoSigiloso")})
        else:
            movs.append((f"{it.get('data')}|{titulo}", data_br(it.get("data")), titulo))
    return movs, docs


# --- a sessão da rodada (login único) ------------------------------------------------

_SESSOES = {}       # (id do contexto, trt) -> SessaoPje | None (None = não deu: usar a consulta pública nesta rodada)
AVISOS = []         # o que impediu o uso do PJe próprio (texto), para o relato da rodada


def credenciais_ok():
    return all(acesso.situacao_pdpj().values())


def sessao_da_rodada(context, numero, abrir_pagina=None, entrar=None):
    """A sessão logada do TRT do processo, ou None. O login é feito UMA vez por TRT e por rodada; falha não se repete."""
    trt = trt_do_numero(numero)
    if trt is None or not credenciais_ok():
        return None
    chave = (id(context), trt)
    if chave in _SESSOES:
        return _SESSOES[chave]
    import pdpj
    _SESSOES[chave] = None                       # marcado ANTES: nenhuma segunda tentativa nesta rodada, aconteça o que acontecer
    try:
        if pdpj.trava():
            raise pdpj.PdpjErro("travado", "Há uma trava de login do PDPJ; libere na tela Acesso e escritório.")
        if abrir_pagina is None:
            import janela
            abrir_pagina = janela.nova_pagina
        page = abrir_pagina(context)
        (entrar or pdpj.entrar)(pdpj.Navegador(page), trt, consulta=False)
        _SESSOES[chave] = SessaoPje(page, trt)
        print(f"PJe do TRT{trt}: login do PDPJ feito; os autos serão lidos pelo PJe do advogado.", flush=True)
    except pdpj.PdpjErro as e:
        AVISOS.append(f"PJe próprio do TRT{trt} indisponível ({e.etapa}): {e.mensagem}")
        print(AVISOS[-1] + " Usando a consulta pública.", flush=True)
    except Exception as e:  # noqa: BLE001 - qualquer imprevisto: sem nova tentativa, a coleta segue pela consulta pública
        AVISOS.append(f"PJe próprio do TRT{trt} indisponível ({type(e).__name__}).")
        print(AVISOS[-1] + " Usando a consulta pública.", flush=True)
    return _SESSOES[chave]


def encerrar_sessao(context, numero):
    """A sessão caiu no meio da rodada: não entra de novo (seria outra tentativa de login); o resto vai pela consulta pública."""
    _SESSOES[(id(context), trt_do_numero(numero))] = None


def zerar_rodada():
    _SESSOES.clear()
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


def coletar_processo(sessao, proc, estado, lista, historico, cota, desde=None, relato=None):
    import coletor
    import trt
    relato = relato if relato is not None else {}
    relato.setdefault("graus_lidos", [])
    relato.setdefault("graus_falhos", [])
    relato.setdefault("avisos", [])
    numero = proc["numero"]
    achado = sessao.buscar(numero)                                  # NaoNoAcervo sobe para o chamador
    itens = sessao.timeline(achado["id"])
    movs, docs = itens_da_timeline(itens)
    relato["graus_lidos"] = [GRAU]
    reg_proc = estado.get(numero, {}).get("trt", {})
    reg = reg_proc.get(GRAU)
    primeira_vez = reg is None
    reg = reg or {}

    instancia = instancia_do_processo(sessao, achado["id"])
    relato["instancia"] = instancia
    # `outraInstancia: true` confirma. `false` NÃO prova nada: num processo real que já está no TST, o PJe do 1º grau
    # diz `false` (o registro dele para na remessa). Por isso os andamentos valem sempre, além do sinal do PJe.
    motivo = None
    if instancia["outra_instancia"] is True:
        motivo = "o PJe informa que o processo também está em outra instância (2º grau)"
    else:
        motivo = trt.indicio_de_recurso(movs, proc, reg_proc) or _remessa_para_recurso(movs)
    if motivo:
        relato["avisos"].append({"nivel": "atencao", "codigo": "grau_nao_lido", "onde": f"pje/{numero}",
                                 "mensagem": f"O 2º grau não foi lido pelo PJe do advogado ({motivo}). Conferir o recurso à mão."})
        relato["graus_falhos"].append({"grau": "2", "motivo": "leitura do 2º grau ainda não disponível pelo PJe do advogado"})

    ids = {e["id"] for e in lista}
    conhecidos = set(reg.get("movimentos", []))
    if primeira_vez:
        novos = [m for m in movs if coletor._depois(m[1], desde)] if desde else movs[:historico]
    else:
        novos = [m for m in movs if m[0] not in conhecidos]
    for chave, data, texto in novos:
        ev = coletor._evento_base(proc, "movimento", f"trt|{GRAU}|{chave}", texto)
        if ev["id"] not in ids:
            ev.update(data=data, chave=chave, grau=None)
            lista.append(ev)
            ids.add(ev["id"])
    print(f"  andamentos: {len(movs)} nos autos, {len(novos)} novo(s)", flush=True)

    docs_conhecidos = set(reg.get("documentos", []))
    falhas = dict(reg.get("falhas_documentos", {}))
    if primeira_vez:
        novos_docs = [d for d in docs if coletor._depois(d["data"], desde)] if desde else docs[:historico]
    else:
        novos_docs = [d for d in docs if d["id"] not in docs_conhecidos]
    fora_da_selecao = [d["id"] for d in docs if d not in novos_docs]
    baixados = 0
    for d in novos_docs[:max(cota, 0)]:
        nome = f"{d['id']} - {d['tipo']} - {d['titulo']}"
        ev = coletor._evento_base(proc, "documento", f"doc|{d['id']}", nome)
        anterior = next((e for e in lista if e["id"] == ev["id"]), None) if ev["id"] in ids else None
        if anterior is not None and anterior.get("arquivo"):
            docs_conhecidos.add(d["id"])
            continue
        arquivo = None
        try:
            corpo = sessao.pdf(achado["id"], d["id"])
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
        dados_ev = dict(tipo=d["tipo"], descricao=d["titulo"], doc_id=d["id"], data=d["data"], grau=None,
                        arquivo=str(arquivo) if arquivo else None, print=None)
        if anterior is not None:
            anterior.update(dados_ev)
        else:
            ev.update(dados_ev)
            lista.append(ev)
            ids.add(ev["id"])
        print(f"  documento {'baixado' if arquivo else 'sem arquivo'}: {nome}", flush=True)
        coletor.pausa(comum.config()["coleta"]["pausa_entre_documentos_s"])
    print(f"  documentos: {len(docs)} nos autos, {len(novos_docs)} novo(s)", flush=True)
    docs_conhecidos.update(fora_da_selecao)
    novo = dict(reg_proc)
    novo[GRAU] = {"movimentos": sorted({m[0] for m in movs} | conhecidos), "documentos": sorted(docs_conhecidos),
                  "falhas_documentos": falhas}
    estado[numero] = {"trt": novo, "instancia": instancia,
                      "ultima_coleta": datetime.datetime.now().isoformat(timespec="seconds")}
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
