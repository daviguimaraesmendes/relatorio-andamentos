"""Justiça do Trabalho: consulta processual do PJe de cada TRT
(https://pje.trtN.jus.br/consultaprocessual/).

A ordem importa: primeiro o login no jus.br (coletor.logar), depois a consulta.
Logado, o PJe do TRT mostra os autos completos e deixa baixar documentos; sem
login, pede captcha e não libera os autos. Se ainda assim aparecer captcha, a
janela vem para a tela (em tela cheia), o Mac avisa com notificação e som a
cada 60 s, o painel mostra a faixa vermelha e quem estiver no computador
resolve; depois ela volta a minimizar. Se ninguém resolver em
`coleta.captcha_espera_min` minutos (padrão 10), o processo é adiado: a fila
segue com os demais e volta ao captcha no fim da rodada.

Uma página de consulta por TRT fica aberta durante toda a rodada: o processo
seguinte é pesquisado pelo próprio formulário, sem recarregar a consulta (o
captcha resolvido continua valendo). Documentos e PDFs abrem em outra aba, que
fecha logo depois, sem tocar na página de consulta.

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


CONSULTAS = {}   # (id do contexto, host) -> página de consulta, uma por TRT durante a rodada
CAPTCHAS = {}    # número do TRT -> captchas pedidos nesta rodada
RECARGAS = {}    # número do TRT -> vezes em que a consulta teve de ser recarregada do zero
PADRAO_CAPTCHA_ESPERA_MIN = 10


class CaptchaNaoResolvido(RuntimeError):
    """Ninguém resolveu o captcha no prazo. `adiavel`: a fila pode pular o processo e voltar no fim da rodada."""
    adiavel = True


def numero_do_trt(texto):
    """'pje.trt7.jus.br' (ou a URL da consulta) -> '7'; '?' se não for de TRT."""
    m = re.search(r"trt(\d+)", texto or "")
    return m.group(1) if m else "?"


def espera_do_captcha_s():
    """Quanto esperar por uma pessoa (config coleta.captcha_espera_min, padrão 10 minutos)."""
    try:
        minutos = float(comum.config().get("coleta", {}).get("captcha_espera_min", PADRAO_CAPTCHA_ESPERA_MIN))
    except (TypeError, ValueError):
        minutos = PADRAO_CAPTCHA_ESPERA_MIN
    return max(minutos, 0.05) * 60


def esperar_captcha_humano(page, limite_s=None, tribunal=None):
    """Chama uma pessoa para resolver o captcha (janela em tela cheia, notificação do Mac com som, faixa vermelha
    no painel, lembrete a cada 60 s) e espera até `limite_s` (padrão: coleta.captcha_espera_min). Volta True se
    resolveram, False se o prazo acabou."""
    if not tem_captcha(page):
        return True
    import atencao
    limite_s = espera_do_captcha_s() if limite_s is None else limite_s
    tribunal = tribunal or numero_do_trt(getattr(page, "url", ""))
    CAPTCHAS[tribunal] = CAPTCHAS.get(tribunal, 0) + 1
    atencao.chamar(page, "captcha", f"Captcha do TRT {tribunal} aguardando.", tribunal=tribunal)
    print(f"CAPTCHA na consulta do TRT {tribunal}: resolva na janela que apareceu (espero até {int(limite_s // 60)} min). "
          "A coleta continua sozinha depois.", flush=True)
    lembrete = atencao.Lembrete(f"Captcha do TRT {tribunal}: precisa de você")
    fim = time.time() + limite_s
    while time.time() < fim:
        page.wait_for_timeout(1500)
        if not tem_captcha(page):
            atencao.limpar("captcha", tribunal)
            janela.minimizar(page)
            return True
        lembrete.tick()
    atencao.limpar("captcha", tribunal)
    return False


def resumo_dos_captchas():
    """'captchas pedidos nesta rodada: 3 no TRT 7, 1 no TRT 9 (consulta recarregada 2 vez(es))' ou a frase
    'nenhum' - vai para o log, para comparar uma rodada com a outra."""
    if not CAPTCHAS:
        texto = "captchas pedidos nesta rodada: nenhum"
    else:
        texto = "captchas pedidos nesta rodada: " + ", ".join(f"{n} no TRT {t}" for t, n in sorted(CAPTCHAS.items()))
    if RECARGAS:
        texto += " (consulta recarregada do zero: " + ", ".join(f"{n}x no TRT {t}" for t, n in sorted(RECARGAS.items())) + ")"
    return texto


def zerar_rodada(context=None):
    """Começo de rodada: zera as contagens e fecha as páginas de consulta (de um contexto, ou de todos)."""
    fechar_consultas(context)
    CAPTCHAS.clear()
    RECARGAS.clear()


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

# Quantas rodadas se tenta de novo um documento cujo arquivo não veio antes de desistir (fica só o print).
DESISTE_DO_DOCUMENTO = 3

# Andamentos que indicam recurso (2º grau): só com um desses a coleta tenta ler o 2º grau.
INDICIO_2_GRAU = re.compile(
    r"remessa\s.*(tribunal|2[ºo°]\s*grau|segundo\s+grau)|remetid[oa]s?\s.*(tribunal|2[ºo°]\s*grau|segundo\s+grau)|"
    r"recurso\s+ordin[aá]rio|distribu[ií]d[oa]\s.*(relator|2[ºo°]\s*grau|segundo\s+grau|turma|gabinete)|"
    r"ac[oó]rd[aã]o|recebid[oa]s?\s+os\s+autos\s+do\s+(tribunal|2[ºo°]\s*grau)|subida\s+(dos\s+)?autos", re.I)


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


def indicio_de_recurso(movimentos, proc=None, reg_proc=None):
    """Por que vale tentar o 2º grau (texto curto) ou None. Indícios: já foi lido antes; o DataJud indicou grau 2
    (`proc["indicio_2grau"]`); algum andamento fala em remessa, recurso ordinário, distribuição ao relator, acórdão."""
    if "2" in (reg_proc or {}):
        return "o 2º grau já tinha sido lido em rodada anterior"
    if (proc or {}).get("indicio_2grau"):
        return "o DataJud indica processo no 2º grau"
    for _, _, texto in movimentos:
        if INDICIO_2_GRAU.search(texto or ""):
            return f"andamento \"{' '.join(texto.split())[:70]}\""
    return None


# --- a página de consulta: uma por TRT, durante toda a rodada -------------------------------------------

def pagina_da_consulta(context, host, guardar=None):
    """A página de consulta do TRT desta rodada. A primeira chamada abre a página e entra pelo acesso restrito; as
    seguintes devolvem a MESMA página (o captcha resolvido continua valendo, sem recarregar a consulta)."""
    chave = (id(context), host)
    page = CONSULTAS.get(chave)
    if page is not None:
        try:
            if not page.is_closed():
                return page
        except Exception:
            pass
        CONSULTAS.pop(chave, None)
    page = janela.nova_pagina(context)
    try:
        if not entrar_acesso_restrito(page, host, guardar):
            raise RuntimeError("Acesso restrito do TRT não abriu a consulta.")
    except BaseException:
        try:
            page.close()
        except Exception:
            pass
        raise
    CONSULTAS[chave] = page
    return page


def fechar_consultas(context=None):
    """Fecha as páginas de consulta (de um contexto, ou de todos). Chamado no fim da rodada."""
    for chave in [c for c in CONSULTAS if context is None or c[0] == id(context)]:
        page = CONSULTAS.pop(chave)
        try:
            page.close()
        except Exception:
            pass


_VOLTAR_PARA_A_PESQUISA = re.compile(r"nova\s+(consulta|pesquisa)|^\s*pesquisar\s+outro|^\s*voltar\s*$", re.I)


def _esperar_consulta(page, segundos=6):
    for _ in range(segundos):
        if consulta_pronta(page):
            return True
        page.wait_for_timeout(1000)
    return consulta_pronta(page)


def preparar_busca(page, host):
    """Deixa a consulta com o campo do número à vista SEM recarregar a página, quando possível. Escada:
    1) o campo já está lá; 2) botão ou link de nova consulta; 3) voltar no histórico (a consulta é uma página
    de uma aplicação só, voltar não a recarrega); 4) último recurso: carregar a consulta de novo (conta em
    RECARGAS, e pode pedir captcha outra vez). Devolve como conseguiu."""
    if consulta_pronta(page):
        return "pronta"
    try:
        for rotulo in (page.get_by_role("button", name=_VOLTAR_PARA_A_PESQUISA), page.get_by_role("link", name=_VOLTAR_PARA_A_PESQUISA)):
            if rotulo.count() and rotulo.first.is_visible():
                rotulo.first.click(timeout=3000)
                if _esperar_consulta(page, 4):
                    return "nova consulta"
    except Exception:
        pass
    for _ in range(2):
        try:
            page.go_back(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            break
        if _esperar_consulta(page, 4):
            return "voltar"
    page.goto(f"https://{host}/consultaprocessual/", timeout=45000, wait_until="domcontentloaded")
    t = numero_do_trt(host)
    RECARGAS[t] = RECARGAS.get(t, 0) + 1
    _esperar_consulta(page, 20)
    return "recarregada"


def _chave_do_grau(texto):
    """"1° Grau\nATOrd-..." -> "1"; "2° Grau..." -> "2"; "TST\nAIRR-..." -> "tst"; o resto -> "?"."""
    t = (texto or "").strip().upper()
    if t.startswith("TST"):
        return "tst"
    m = re.match(r"(\d)\s*[°ºO]", t)
    return m.group(1) if m else "?"


def botoes_de_grau(page):
    """Tela de escolha que o PJe mostra quando o número existe em mais de um grau ("2 processos encontrados:
    1° Grau / 2° Grau / TST", um botão `.selecao-processo` por grau). Devolve [(chave, botão)]; lista vazia = a tela
    não está aberta. Visto no TRT 7 e no TRT 22 em 08/10/2026: sem clicar aqui os autos nunca chegavam."""
    try:
        botoes = page.locator("#painel-escolha-processo button.selecao-processo")
        total = botoes.count()
    except Exception:
        return []
    achados = []
    for i in range(total):
        try:
            b = botoes.nth(i)
            if b.is_visible():
                achados.append((_chave_do_grau(b.inner_text()), b))
        except Exception:
            continue
    return achados


def escolher_grau(page, grau, capturas):
    """Clica no botão do grau pedido ("1", "2"). Para o 1º grau, se ele não estiver na lista (processo só no 2º),
    abre o primeiro grau numérico que houver. Registra em `capturas["graus_disponiveis"]` o que a lista oferecia."""
    achados = botoes_de_grau(page)
    if not achados:
        return False
    capturas["graus_disponiveis"] = [c for c, _ in achados]
    alvo = next((b for c, b in achados if c == grau), None)
    if alvo is None and grau == "1":
        alvo = next((b for c, b in achados if c.isdigit()), None)
    if alvo is None:
        raise RuntimeError(f"A consulta do TRT não lista o {grau}º grau (oferece: {', '.join(c for c, _ in achados)}).")
    alvo.click(timeout=5000)
    return True


def _ir_para_grau(page, host, numero, grau, capturas):
    """Abre os autos de um grau na MESMA página: primeiro pela rota da aplicação (sem recarregar), e só se os
    autos não vierem em ~8 s, carregando o endereço."""
    rota = f"/consultaprocessual/detalhe-processo/{numero}/{grau}"
    try:
        page.evaluate("r => { history.pushState({}, '', r); window.dispatchEvent(new PopStateEvent('popstate', {state: {}})); }", rota)
        for _ in range(8):
            if capturas["autos"] is not None or tem_captcha(page):
                return "rota"
            page.wait_for_timeout(1000)
    except Exception:
        pass
    page.goto(f"https://{host}{rota}", timeout=45000, wait_until="domcontentloaded")
    t = numero_do_trt(host)
    RECARGAS[t] = RECARGAS.get(t, 0) + 1
    return "recarregada"


def _abrir_autos_trt(context, page, host, numero, capturas, grau=None):
    """Busca o número pelo formulário da consulta e espera o JSON dos autos chegar. Se o PJe mostrar a tela de escolha
    de grau, clica no grau pedido (`grau`; padrão o 1º). Para o 2º grau, quando a lista já mostrou que ele existe, a
    busca é refeita pelo formulário e o botão do 2º grau é clicado; senão tenta a rota da aplicação.
    Captcha: chama uma pessoa; se ninguém resolver a tempo, levanta CaptchaNaoResolvido."""
    capturas["autos"] = None
    alvo = grau or "1"
    if grau is None or "2" in capturas.get("graus_disponiveis", []):
        preparar_busca(page, host)
        campo = _campo_numero(page)
        if campo is None:
            raise RuntimeError("Campo do número não apareceu na consulta do TRT.")
        buscar_numero(page, campo, numero)
    else:
        _ir_para_grau(page, host, numero, grau, capturas)
    escolhido = False
    fim = time.time() + 40
    while time.time() < fim and capturas["autos"] is None:
        page.wait_for_timeout(1000)
        if tem_captcha(page):
            if not esperar_captcha_humano(page, tribunal=numero_do_trt(host)):
                raise CaptchaNaoResolvido(f"Captcha do TRT {numero_do_trt(host)} não resolvido a tempo "
                                          f"({int(espera_do_captcha_s() // 60)} min).")
            fim = time.time() + 40
        if not escolhido and capturas["autos"] is None and escolher_grau(page, alvo, capturas):
            escolhido = True
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


def coletar_processo(context, proc, estado, lista, historico, cota, desde=None, relato=None):
    """Mesmo papel do coletor.coletar_processo, para a Justiça do Trabalho.

    `relato` (dict opcional) recebe o que o ColetorReal repassa ao fluxo: `graus_lidos`, `graus_falhos` (cada falha
    com o motivo) e `avisos`. O 2º grau só é tentado com indício de recurso; a falha dele nunca é engolida: vira
    aviso `grau_nao_lido`."""
    import coletor  # evita importação circular

    relato = relato if relato is not None else {}
    relato.setdefault("graus_lidos", [])
    relato.setdefault("graus_falhos", [])
    relato.setdefault("avisos", [])
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
    marcas = {"inicio": time.time()}
    try:
        page = pagina_da_consulta(context, host)
        autos = {"1": _abrir_autos_trt(context, page, host, numero, capturas)}
        if autos["1"] is None:
            coletor.salvar_diagnostico(page, f"trt_autos_nao_vieram_{slug(numero)}")
            raise RuntimeError("Os autos não chegaram (diagnóstico salvo).")
        grau_aberto = re.search(r"/detalhe-processo/[^/]+/(\d)", page.url)
        if grau_aberto and grau_aberto.group(1) != "1":
            autos = {grau_aberto.group(1): autos["1"]}
        relato["graus_lidos"] = list(autos)
        if capturas.get("graus_disponiveis"):
            relato["graus_disponiveis"] = list(capturas["graus_disponiveis"])
        reg_proc = estado.get(numero, {}).get("trt", {})
        # recurso no 2º grau: mesma página, outro grau; só com indício de recurso
        if "2" not in autos:
            movs_1g = itens_do_processo(next(iter(autos.values())))[0]
            motivo = indicio_de_recurso(movs_1g, proc, reg_proc)
            if not motivo and "2" in capturas.get("graus_disponiveis", []):
                motivo = "a consulta do TRT lista o 2º grau"
            if motivo:
                try:
                    segundo = _abrir_autos_trt(context, page, host, numero, capturas, grau="2")
                    if segundo is None:
                        raise RuntimeError("os autos do 2º grau não chegaram")
                    if segundo.get("id") != next(iter(autos.values())).get("id"):
                        autos["2"] = segundo
                        relato["graus_lidos"] = list(autos)
                    else:
                        print("  2º grau: a consulta devolveu os mesmos autos do 1º grau (sem tramitação separada).", flush=True)
                except CaptchaNaoResolvido:
                    raise
                except Exception as e:  # noqa: BLE001 - registrada: o 1º grau já lido segue valendo
                    falha = f"{type(e).__name__}: {e}"
                    relato["graus_falhos"].append({"grau": "2", "motivo": falha})
                    relato["avisos"].append({"nivel": "atencao", "codigo": "grau_nao_lido", "onde": f"trt/{numero}",
                                             "mensagem": f"O 2º grau não foi lido ({motivo}; falha: {falha}). "
                                                         "Conferir o recurso à mão."})
                    print(f"  2º grau NÃO lido ({falha}).", flush=True)

        marcas["busca"] = time.time()
        varios = len(autos) > 1
        ids = {e["id"] for e in lista}
        pasta_prints = comum.PRINTS_DIR / slug(proc.get("cliente") or "sem-cliente") / slug(numero)
        baixados, novo_estado = 0, {}
        for grau, dados in autos.items():
            reg = reg_proc.get(grau)
            primeira_vez = reg is None
            reg = reg or {}
            movs, docs = itens_do_processo(dados)
            nivel = f"{grau}º grau" if varios or grau != "1" else None
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
            marcas["andamentos"] = time.time()
            # documentos
            docs_conhecidos = set(reg.get("documentos", []))
            falhas = dict(reg.get("falhas_documentos", {}))        # {id: tentativas sem conseguir o arquivo}
            if primeira_vez:
                novos_docs = [d for d in docs if coletor._depois(d["data"], desde)] if desde else docs[:historico]
            else:
                novos_docs = [d for d in docs if d["id"] not in docs_conhecidos]
            fora_da_selecao = [d["id"] for d in docs if d not in novos_docs]
            for d in novos_docs[:max(cota - baixados, 0)]:
                nome = f"{d['id']} - {d['tipo']} - {d['titulo']}"
                ev = coletor._evento_base(proc, "documento", f"doc|{d['id']}", nome)
                anterior = next((e for e in lista if e["id"] == ev["id"]), None) if ev["id"] in ids else None
                if anterior is not None and anterior.get("arquivo"):
                    docs_conhecidos.add(d["id"])
                    continue
                arquivo, foto = _baixar_documento_trt(context, host, numero, grau, d, capturas, pasta_prints, proc)
                if arquivo:
                    baixados += 1
                    falhas.pop(d["id"], None)
                    docs_conhecidos.add(d["id"])
                else:  # sem o arquivo: tenta de novo nas próximas rodadas (até DESISTE_DO_DOCUMENTO vezes)
                    falhas[d["id"]] = falhas.get(d["id"], 0) + 1
                    if falhas[d["id"]] >= DESISTE_DO_DOCUMENTO:
                        docs_conhecidos.add(d["id"])
                dados_ev = dict(tipo=d["tipo"], descricao=d["titulo"], doc_id=d["id"], data=d["data"], grau=nivel,
                                arquivo=str(arquivo) if arquivo else None, print=str(foto) if foto else None)
                if anterior is not None:
                    anterior.update(dados_ev)
                else:
                    ev.update(dados_ev)
                    lista.append(ev)
                    ids.add(ev["id"])
                print(f"  documento {'baixado' if arquivo else 'só com print'}: {nome}", flush=True)
                coletor.pausa(comum.config()["coleta"]["pausa_entre_documentos_s"])
            print(f"  documentos: {len(docs)} nos autos, {len(novos_docs)} novo(s)", flush=True)
            # fora da seleção da 1ª leitura (antigos demais) = conhecidos; o que passou da cota fica para a próxima rodada
            docs_conhecidos.update(fora_da_selecao)
            novo_estado[grau] = {"movimentos": sorted({m[0] for m in movs} | conhecidos), "documentos": sorted(docs_conhecidos),
                                 "falhas_documentos": falhas}
        for grau_antigo, reg_antigo in reg_proc.items():  # grau lido antes e não relido agora: o registro não se perde
            novo_estado.setdefault(grau_antigo, reg_antigo)
        estado[numero] = {"trt": novo_estado, "ultima_coleta": datetime.datetime.now().isoformat(timespec="seconds")}
        fim = time.time()
        for etapa, t in (("busca", marcas["busca"] - marcas["inicio"]),
                         ("documentos", fim - marcas.get("andamentos", marcas["busca"]))):
            print(f"  tempo: {etapa} {t:.1f} s", flush=True)      # lido por diagnostico_rodada.py
        print(f"  graus lidos: {', '.join(g + 'º' for g in relato['graus_lidos'])}"
              + (f"; NÃO lidos: {', '.join(f['grau'] + 'º' for f in relato['graus_falhos'])}" if relato["graus_falhos"] else ""), flush=True)
        return baixados
    finally:
        context.remove_listener("response", ouvir)


def _baixar_documento_trt(context, host, numero, grau, doc, capturas, pasta_prints, proc):
    """Abre o documento NUMA ABA PRÓPRIA (a página de consulta não é tocada) no visualizador da consulta (âncora
    com o id único), guarda o PDF que o portal entrega, mais o print da tela, e fecha a aba."""
    capturas["pdfs"].pop(doc["id"], None)
    url = f"https://{host}/consultaprocessual/detalhe-processo/{numero}/{grau}"
    aba = janela.nova_pagina(context)
    try:
        aba.goto(url + (f"#{doc['unico']}" if doc.get("unico") else ""), timeout=45000, wait_until="domcontentloaded")
        for _ in range(25):
            if doc["id"] in capturas["pdfs"]:
                break
            aba.wait_for_timeout(1000)
            if tem_captcha(aba) and not esperar_captcha_humano(aba, tribunal=numero_do_trt(host)):
                raise CaptchaNaoResolvido(f"Captcha do TRT {numero_do_trt(host)} não resolvido a tempo ao abrir um documento.")
        foto = None
        try:
            foto = janela.print_da_pagina(aba, pasta_prints / f"{slug(doc['id'] + '-' + doc['tipo'])}-print.png")
        except Exception:
            pass
    finally:
        try:
            aba.close()
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
