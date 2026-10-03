"""Justiça do Trabalho: consulta processual do PJe de cada TRT
(https://pje.trtN.jus.br/consultaprocessual/).

A ordem importa: primeiro o login no jus.br (coletor.logar), depois a consulta.
Logado, o PJe do TRT mostra os autos completos e deixa baixar documentos; sem
login, pede captcha e não libera os autos. Se ainda assim aparecer captcha, a
janela vem para a tela e quem estiver no computador resolve; depois ela volta
a minimizar.

Esta primeira versão é de EXPLORAÇÃO: grava as telas e as respostas internas
do portal para que a leitura automática seja escrita sobre o formato real.

    python trt.py --explorar NUMERO
"""
import datetime
import json
import re
import sys
import time
from pathlib import Path

import comum
import janela
from comum import slug

CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.(\d)\.(\d{2})\.\d{4}")
MARCAS_CAPTCHA = re.compile(r"captcha|caracteres da imagem|digite os caracteres|n[aã]o sou um rob[oô]|hcaptcha|recaptcha", re.I)
CHAVES_SENSIVEIS = re.compile(r"token|senha|password|secret|authorization|cookie|cpf|email", re.I)


def host_trt(numero):
    """'1234569-95.2026.5.07.0001' -> 'pje.trt7.jus.br' (segmento 5 = Justiça do Trabalho)."""
    m = CNJ.search(numero)
    if not m or m.group(1) != "5":
        raise ValueError(f"{numero} não é da Justiça do Trabalho.")
    return f"pje.trt{int(m.group(2))}.jus.br"


def _limpo(obj):
    """Tira do JSON qualquer chave com cara de credencial ou dado pessoal do usuário."""
    if isinstance(obj, dict):
        return {k: ("<removido>" if CHAVES_SENSIVEIS.search(k) else _limpo(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_limpo(v) for v in obj]
    return obj


def tem_captcha(page):
    try:
        if page.locator("img[src*='captcha' i], iframe[src*='captcha' i], [id*='captcha' i], [class*='captcha' i]").count():
            return True
        return bool(MARCAS_CAPTCHA.search(page.inner_text("body")[:5000]))
    except Exception:
        return False


def esperar_captcha_humano(page, limite_s=600):
    """Mostra a janela e espera alguém resolver o captcha (até 10 min)."""
    if not tem_captcha(page):
        return True
    janela.mostrar(page)
    print("CAPTCHA na consulta do TRT: resolva na janela que apareceu. A coleta continua sozinha depois.", flush=True)
    if sys.platform == "darwin":
        try:
            import subprocess
            subprocess.run(["osascript", "-e", 'display notification "Resolva o captcha na janela do TRT" '
                            'with title "Relatório de Andamentos" sound name "Ping"'], timeout=5, check=False)
        except Exception:
            pass
    else:
        print("\a", end="", flush=True)  # sinal sonoro do terminal
    fim = time.time() + limite_s
    while time.time() < fim:
        page.wait_for_timeout(1500)
        if not tem_captcha(page):
            janela.minimizar(page)
            return True
    return False


def _campo_numero(page):
    for sel in ("#nrProcessoInput", "input[placeholder*='processo' i]", "input[id*='processo' i]", "input[name*='processo' i]",
                "input[formcontrolname*='processo' i]", "input[type='text']"):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def consulta_pronta(page):
    """O campo do número na tela da consulta. Obs.: o link 'Acesso restrito'
    continua no menu mesmo logado, então ele NÃO serve para saber se entrou."""
    try:
        return "/consultaprocessual" in page.url and page.locator("#nrProcessoInput").first.is_visible()
    except Exception:
        return False


def entrar_acesso_restrito(page, host, guardar=None):
    """Entra pelo 'Acesso restrito' da consulta processual. Com o login central
    já feito no jus.br, a tela fica em branco até ser recarregada uma vez;
    recarregada, entra sozinho e volta para a consulta (visto em 03/10/2026)."""
    page.goto(f"https://{host}/consultaprocessual/login", timeout=45000, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    page.reload(timeout=45000, wait_until="domcontentloaded")
    for _ in range(30):  # até ~30 s pela consulta pronta
        if consulta_pronta(page):
            break
        page.wait_for_timeout(1000)
    if guardar:
        guardar(page, "0_acesso_restrito")
    pronta = consulta_pronta(page)
    print(f"  Acesso restrito do TRT: {'consulta pronta' if pronta else 'consulta não apareceu'}.", flush=True)
    return pronta


def buscar_numero(page, campo, numero):
    """O campo tem máscara (9999999-99.9999.9.99.9999): colar o número formatado
    embaralha os caracteres ("número de processo inválido"). Digita só os
    dígitos, um a um, e clica em Pesquisar."""
    campo.click()
    campo.fill("")
    campo.press_sequentially(re.sub(r"\D", "", numero), delay=60)
    botao = page.locator("#btnPesquisar")
    if botao.count():
        botao.first.click()
    else:
        campo.press("Enter")


def explorar(numero):
    """Exploração em 4 tempos, com a janela VISÍVEL:
    1) login no jus.br (automático);
    2) a PESSOA clica em "Acesso restrito" e entra no TRT como faria normalmente
       (a ferramenta grava por quais endereços o login passa) e aperta Enter;
    3) a ferramenta busca o processo (captcha, se houver, também à mão);
    4) a PESSOA abre o processo, abre um documento e clica em baixar; Enter.
    Tudo vai para diagnósticos: telas, endereços (sem parâmetros), respostas
    internas sem credenciais e o arquivo baixado."""
    from playwright.sync_api import sync_playwright
    import coletor

    host = host_trt(numero)
    pasta = comum.DIAG_DIR / f"trt_{slug(numero)}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    pasta.mkdir(parents=True, exist_ok=True)
    respostas, chamadas, fase = [], [], ["inicio"]
    digitos = re.sub(r"\D", "", numero)

    def ouvir(resp):
        url = resp.url.split("?")[0]
        tipo = resp.headers.get("content-type", "")
        if re.search(r"\.(js|css|woff2?|png|ico|svg|gif|jpg)$", url):
            return
        chamadas.append(f"[{fase[0]}] {resp.status} {resp.request.method} {tipo[:35]} {url}")
        if host in url and "json" in tipo:
            try:
                corpo = resp.json()
            except Exception:
                return
            respostas.append({"fase": fase[0], "url": url, "corpo": _limpo(corpo)})

    def baixou(download):
        destino = pasta / f"download_{download.suggested_filename}"
        download.save_as(destino)
        print(f"  arquivo baixado e gravado: {destino.name}", flush=True)

    def guardar(page, nome):
        try:
            page.screenshot(path=str(pasta / f"{nome}.png"), full_page=True)
            (pasta / f"{nome}.html").write_text(page.content(), encoding="utf-8")
            (pasta / f"{nome}.txt").write_text(page.inner_text("body"), encoding="utf-8")
            (pasta / f"{nome}_url.txt").write_text(page.url.split("?")[0], encoding="utf-8")
        except Exception:
            pass
        print(f"  tela salva: {nome}", flush=True)

    with sync_playwright() as p:
        browser, context = janela.abrir_navegador(p)
        coletor.logar(context)
        context.on("response", ouvir)
        context.on("download", baixou)
        page = context.new_page()
        janela.mostrar(page)
        page.goto(f"https://{host}/consultaprocessual/", timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        fase[0] = "login_trt"
        if not entrar_acesso_restrito(page, host, guardar):
            print("\n1) A consulta não apareceu sozinha. NA JANELA: clique em 'Acesso restrito', entre no TRT\n"
                  "   (se a tela ficar em branco, recarregue) e, com a consulta na tela, aperte Enter aqui.", flush=True)
            input()
        for i, pg in enumerate(context.pages):
            guardar(pg, f"2_logado_aba{i}")

        fase[0] = "busca"
        page = context.pages[-1]
        if "consultaprocessual" not in page.url:
            page.goto(f"https://{host}/consultaprocessual/", timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        campo = _campo_numero(page)
        if campo is not None:
            buscar_numero(page, campo, numero)
            page.wait_for_timeout(5000)
            guardar(page, "3_depois_da_busca")
            if tem_captcha(page):
                print("   Apareceu captcha mesmo logado: resolva na janela.", flush=True)
                esperar_captcha_humano(page)
                janela.mostrar(page)
                guardar(page, "3b_depois_do_captcha")

        fase[0] = "autos"
        print("\n2) NA JANELA: abra o processo (se ainda não abriu), abra um documento e clique em BAIXAR.\n"
              "   Depois do download, volte aqui e aperte Enter.", flush=True)
        input()
        for i, pg in enumerate(context.pages):
            guardar(pg, f"4_final_aba{i}")
        (pasta / "respostas.json").write_text(json.dumps(respostas, ensure_ascii=False, indent=1)[:5_000_000], encoding="utf-8")
        (pasta / "chamadas.txt").write_text("\n".join(chamadas), encoding="utf-8")
        browser.close()
    print(f"\nDiagnóstico do TRT salvo em: {pasta}")


# --- coleta (rodada normal) ---------------------------------------------------

_HOSTS_LOGADOS = set()  # acesso restrito feito nesta rodada


def data_br(iso):
    """'2026-08-27T11:30:03.31' -> '27/08/2026'."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else None


def itens_do_processo(dados):
    """Do JSON dos autos (pje-consulta-api /processos/<id>) tira:
    andamentos [(chave, data dd/mm/aaaa, texto)] e documentos [dict], do mais recente ao mais antigo.
    A chave do andamento usa a data com hora e fração de segundo do próprio PJe: é única."""
    movs, docs = [], []
    for it in dados.get("itensProcesso") or []:
        if it.get("documento") in (True, "True"):
            docs.append({"id": str(it.get("id")), "unico": it.get("idUnicoDocumento"), "tipo": it.get("tipo") or it.get("titulo"),
                         "titulo": " ".join((it.get("titulo") or "").split()), "data": data_br(it.get("data")),
                         "publico": it.get("publico") in (True, "True")})
        else:
            texto = " ".join((it.get("titulo") or "").split())
            movs.append((f"{it.get('data')}|{texto}", data_br(it.get("data")), texto))
    return movs, docs


def _abrir_autos_trt(context, page, host, numero, capturas, grau=None):
    """Busca (ou abre direto o grau) e espera o JSON dos autos chegar. Captcha: janela para a pessoa."""
    capturas["autos"] = None
    if grau is None:
        page.goto(f"https://{host}/consultaprocessual/", timeout=45000, wait_until="domcontentloaded")
        for _ in range(20):
            if consulta_pronta(page):
                break
            page.wait_for_timeout(1000)
        campo = _campo_numero(page)
        if campo is None:
            raise RuntimeError("Campo do número não apareceu na consulta do TRT.")
        buscar_numero(page, campo, numero)
    else:
        page.goto(f"https://{host}/consultaprocessual/detalhe-processo/{numero}/{grau}", timeout=45000,
                  wait_until="domcontentloaded")
    fim = time.time() + 40
    while time.time() < fim and capturas["autos"] is None:
        page.wait_for_timeout(1000)
        if tem_captcha(page):
            if not esperar_captcha_humano(page):
                raise RuntimeError("Captcha do TRT não resolvido a tempo.")
            fim = time.time() + 40
        texto = ""
        try:
            texto = page.inner_text("body")
        except Exception:
            pass
        if "segredo de justiça" in texto:
            raise RuntimeError("Processo em segredo de justiça: a consulta processual não mostra os autos.")
        if "inválido" in texto and grau is None:
            raise RuntimeError("O TRT não reconheceu o número do processo.")
    return capturas["autos"]


def coletar_processo(context, proc, estado, lista, historico, cota, desde=None):
    """Mesmo papel do coletor.coletar_processo, para a Justiça do Trabalho."""
    import coletor  # evita importação circular

    numero = proc["numero"]
    host = host_trt(numero)
    capturas = {"autos": None, "pdfs": {}}
    digitos = re.sub(r"\D", "", numero)

    def ouvir(resp):
        url = resp.url.split("?")[0]
        if host not in url or "/pje-consulta-api/api/processos/" not in url:
            return
        try:
            if re.search(r"/processos/\d+$", url) and "json" in resp.headers.get("content-type", ""):
                corpo = resp.json()
                if isinstance(corpo, dict) and "itensProcesso" in corpo and digitos in re.sub(r"\D", "", str(corpo.get("numero", ""))):
                    capturas["autos"] = corpo
            m = re.search(r"/documentos/(\d+)$", url)
            if m and "pdf" in resp.headers.get("content-type", ""):
                capturas["pdfs"][m.group(1)] = resp.body()
        except Exception:
            pass

    context.on("response", ouvir)
    page = janela.nova_pagina(context)
    try:
        if host not in _HOSTS_LOGADOS:
            if not entrar_acesso_restrito(page, host):
                raise RuntimeError("Acesso restrito do TRT não abriu a consulta.")
            _HOSTS_LOGADOS.add(host)
        autos = {"1": _abrir_autos_trt(context, page, host, numero, capturas)}
        if autos["1"] is None:
            coletor.salvar_diagnostico(page, f"trt_autos_nao_vieram_{slug(numero)}")
            raise RuntimeError("Os autos não chegaram (diagnóstico salvo).")
        grau_aberto = re.search(r"/detalhe-processo/[^/]+/(\d)", page.url)
        if grau_aberto and grau_aberto.group(1) != "1":
            autos = {grau_aberto.group(1): autos["1"]}
        # recurso no 2º grau: mesma consulta, outro grau na URL
        if "2" not in autos:
            try:
                segundo = _abrir_autos_trt(context, page, host, numero, capturas, grau="2")
                if segundo and segundo.get("id") != next(iter(autos.values())).get("id"):
                    autos["2"] = segundo
            except Exception:
                pass

        reg_proc = estado.get(numero, {}).get("trt", {})
        varios = len(autos) > 1
        ids = {e["id"] for e in lista}
        pasta_prints = comum.PRINTS_DIR / slug(proc.get("cliente") or "sem-cliente") / slug(numero)
        baixados, novo_estado = 0, {}
        for grau, dados in autos.items():
            reg = reg_proc.get(grau)
            primeira_vez = reg is None
            reg = reg or {}
            movs, docs = itens_do_processo(dados)
            nivel = f"{grau}º grau" if varios else None
            if varios:
                print(f"  tramitação: {grau}º grau", flush=True)
            # andamentos
            conhecidos = set(reg.get("movimentos", []))
            if primeira_vez:
                novos = [m for m in movs if coletor._depois(m[1], desde)] if desde else movs[:historico]
            else:
                novos = [m for m in movs if m[0] not in conhecidos]
            for chave, data, texto in novos:
                ev = coletor._evento_base(proc, "movimento", f"trt|{grau}|{chave}", texto)
                if ev["id"] not in ids:
                    ev.update(data=data, chave=chave, grau=nivel)
                    lista.append(ev)
                    ids.add(ev["id"])
            print(f"  andamentos: {len(movs)} nos autos, {len(novos)} novo(s)", flush=True)
            # documentos
            docs_conhecidos = set(reg.get("documentos", []))
            if primeira_vez:
                novos_docs = [d for d in docs if coletor._depois(d["data"], desde)] if desde else docs[:historico]
            else:
                novos_docs = [d for d in docs if d["id"] not in docs_conhecidos]
            for d in novos_docs[:max(cota - baixados, 0)]:
                nome = f"{d['id']} - {d['tipo']} - {d['titulo']}"
                ev = coletor._evento_base(proc, "documento", f"doc|{d['id']}", nome)
                if ev["id"] in ids:
                    continue
                arquivo, foto = _baixar_documento_trt(page, host, numero, grau, d, capturas, pasta_prints, proc)
                if arquivo:
                    baixados += 1
                ev.update(tipo=d["tipo"], descricao=d["titulo"], doc_id=d["id"], data=d["data"], grau=nivel,
                          arquivo=str(arquivo) if arquivo else None, print=str(foto) if foto else None)
                lista.append(ev)
                ids.add(ev["id"])
                docs_conhecidos.add(d["id"])
                print(f"  documento {'baixado' if arquivo else 'só com print'}: {nome}", flush=True)
                coletor.pausa(comum.config()["coleta"]["pausa_entre_documentos_s"])
            print(f"  documentos: {len(docs)} nos autos, {len(novos_docs)} novo(s)", flush=True)
            if primeira_vez or len(novos_docs) <= cota:
                docs_conhecidos.update(d["id"] for d in docs)
            novo_estado[grau] = {"movimentos": sorted({m[0] for m in movs} | conhecidos), "documentos": sorted(docs_conhecidos)}
        estado[numero] = {"trt": novo_estado, "ultima_coleta": datetime.datetime.now().isoformat(timespec="seconds")}
        return baixados
    finally:
        context.remove_listener("response", ouvir)
        page.close()


def _baixar_documento_trt(page, host, numero, grau, doc, capturas, pasta_prints, proc):
    """Abre o documento no visualizador da consulta (âncora com o id único) e
    guarda o PDF que o portal entrega, mais o print da tela."""
    capturas["pdfs"].pop(doc["id"], None)
    url = f"https://{host}/consultaprocessual/detalhe-processo/{numero}/{grau}"
    if page.url.split("#")[0].rstrip("/") == url and doc.get("unico"):
        page.evaluate(f"location.hash = {json.dumps('#' + doc['unico'])}")
    else:
        page.goto(url + (f"#{doc['unico']}" if doc.get("unico") else ""), timeout=45000, wait_until="domcontentloaded")
    for _ in range(25):
        if doc["id"] in capturas["pdfs"]:
            break
        page.wait_for_timeout(1000)
    foto = None
    try:
        foto = janela.print_da_pagina(page, pasta_prints / f"{slug(doc['id'] + '-' + doc['tipo'])}-print.png")
    except Exception:
        pass
    corpo = capturas["pdfs"].get(doc["id"])
    if not corpo or corpo[:4] != b"%PDF":
        return None, foto
    destino = comum.DOCS_DIR / slug(proc.get("cliente") or "sem-cliente") / slug(numero) / f"{slug(doc['id'] + '-' + doc['tipo'])}.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(corpo)
    return destino, foto


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:  # só a ajuda, sem rodar nada
        print(__doc__)
        sys.exit(0)
    a = sys.argv[1:]
    if "--explorar" in a:
        explorar(a[a.index("--explorar") + 1])
    else:
        print(__doc__)
