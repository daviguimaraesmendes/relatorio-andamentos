"""Coletor: entra no jus.br com o certificado do advogado e, para cada processo
da carteira, lê os autos digitais do PDPJ:

  - aba Movimentos: todos os andamentos, publicados ou não. Os novos viram
    eventos, com print da lista;
  - aba Documentos: cada documento novo é aberto no visualizador, ganha print
    e tem o teor baixado pelo botão de download do próprio visualizador. Se o
    download falhar, o teor sai do print por OCR.

Só lê, tira print e baixa. Nenhum clique de protocolo, assinatura ou
peticionamento. Captcha ou tela desconhecida param a rodada e pedem ação humana.

Primeira vez que um processo é visto: o que já está nos autos vira linha de
base, sem evento; o relatório começa dali. --historico N traz também os N
documentos e andamentos mais recentes.

Depois da primeira busca, a URL dos autos fica guardada e as rodadas seguintes
abrem o processo direto, sem passar pela tela de busca.

Uso:
    python coletor.py                       # rodada normal
    python coletor.py --historico 3         # + 3 itens mais recentes na 1ª vez
    python coletor.py --desde 29/09/2026    # 1ª vez: tudo o que veio depois do último relatório
    python coletor.py --processo NUMERO     # só um processo
    python coletor.py --explorar NUMERO     # salva diagnóstico da tela dos autos (para ajustar seletores)
"""
import datetime
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

import comum
from comum import RAIZ, carteira, config, eventos, load_json, salvar_eventos, save_json, slug
from traduzir import separar_nome_documento
import janela

# Login (certificado + TOTP) embutido: ver acesso.py. Segredos no cofre do sistema.
import acesso

LOGIN_MARKER = "Sair do portal"
LOGIN_TIMEOUT_S = 300
URL_CONSULTA = "https://portaldeservicos.pdpj.jus.br/consulta"
TEXTOS_FECHAR_POPUP = ["Pular", "Não, obrigado", "Agora não", "Fechar", "Dispensar", "Entendi"]

# Seletores da tela de autos digitais do PDPJ (levantados da página real,
# 12/08 e 03/10/2026). As duas abas usam os mesmos blocos ".movimento"
# agrupados por data; por isso a leitura se restringe à aba ativa.
SEL_ABA = ".mat-tab-label"
SEL_ABA_ATIVA = ".mat-tab-body-active"
SEL_DOCUMENTO = "a.documento-nome"
SEL_MOVIMENTO = ".movimento"
SEL_MOV_DATA = ".data"
SEL_MOV_TEXTO = ".timeline .texto"
SEL_VISUALIZADOR_DADOS = ".dados-documento"
SEL_BOTAO_DOWNLOAD = ".botao-download"
SEL_CONTEUDO_HTML = ".conteudo"

MESES = {m: i for i, m in enumerate(["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                                     "setembro", "outubro", "novembro", "dezembro"], start=1)}
MESES["marco"] = 3


def agora():
    return datetime.datetime.now().isoformat(timespec="seconds")


def carimbo():
    return f"{datetime.datetime.now():%Y%m%d-%H%M%S}"


def pausa(intervalo):
    time.sleep(random.uniform(*intervalo))


def data_por_extenso(texto):
    """'6 de agosto de 2026' -> '06/08/2026'."""
    m = re.search(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", texto.lower())
    if not m or m.group(2) not in MESES:
        return None
    return f"{int(m.group(1)):02d}/{MESES[m.group(2)]:02d}/{m.group(3)}"


def salvar_diagnostico(page, motivo):
    comum.DIAG_DIR.mkdir(parents=True, exist_ok=True)
    base = comum.DIAG_DIR / f"{motivo}_{carimbo()}"
    for sufixo, gravar in ((".png", lambda p: janela.print_da_pagina(page, p, pagina_inteira=True)),
                           (".html", lambda p: p.write_text(page.content(), encoding="utf-8")),
                           (".txt", lambda p: p.write_text(page.inner_text("body"), encoding="utf-8"))):
        try:
            gravar(base.with_suffix(sufixo))
        except Exception:
            pass
    print(f"  diagnóstico salvo em {base}.*")
    return base


def _texto(page):
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def fechar_menu_lateral(page):
    """O menu lateral do portal, aberto, cobre as abas e a busca."""
    try:
        if page.locator(".mat-drawer.mat-drawer-opened").count():
            fundo = page.locator(".mat-drawer-backdrop.mat-drawer-shown")
            if fundo.count():
                fundo.first.click(timeout=2000)
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(600)
    except Exception:
        pass


def fechar_popups(page, tentativas=4):
    """Fecha avisos (navegação guiada etc.). Procura os botões SÓ dentro de
    diálogos e com o nome EXATO: o botão do menu se chama "Abrir/fechar menu
    de navegação", e uma busca solta por "Fechar" abria o menu por cima da
    página."""
    for _ in range(tentativas):
        fechou = False
        dialogos = page.locator("mat-dialog-container, .cdk-overlay-container [role=dialog]")
        for texto in TEXTOS_FECHAR_POPUP:
            try:
                b = dialogos.get_by_role("button", name=texto, exact=True)
                if b.count() and b.first.is_visible():
                    b.first.click(timeout=2000)
                    fechou = True
            except Exception:
                pass
        fechar_menu_lateral(page)
        if not fechou:
            page.wait_for_timeout(1000)


# --- login ---

class LoginFalhou(RuntimeError):
    """O login no jus.br não concluiu. Não adianta tentar o próximo processo: a coleta para e pede uma pessoa."""


def _diagnostico_do_login(page, tentativa, mensagem=None):
    """Grava tela e motivo da falha do login em diagnosticos/ (sem senha, sem código, sem dado pessoal)."""
    base = salvar_diagnostico(page, f"login_jusbr_t{tentativa}")
    motivo = dict(acesso.ULTIMO)
    if mensagem and not motivo:
        motivo = {"passo": "goto", "mensagem": mensagem}
    motivo.update(tentativa=tentativa, plataforma=sys.platform, quando=agora())
    try:
        comum.save_json(base.with_suffix(".json"), motivo)
    except OSError:
        pass
    return motivo


def _orientacao_do_login():
    """O que a pessoa deve fazer, em uma frase, conforme o passo que falhou."""
    ultimo = acesso.ULTIMO
    oque = ultimo.get("o_que_fazer") or "Termine o login no jus.br na janela que apareceu."
    if ultimo.get("pje_office_aberto") is False and ultimo.get("passo") in ("dialogo", "preencher"):
        oque += " (O PJe Office não parece estar aberto.)"
    return f"{ultimo.get('mensagem') or 'O login automático não concluiu.'} {oque}".strip()


def logar(context):
    """Login no jus.br. Automático com os segredos do painel (Acesso); se não concluir, a janela aparece
    (em tela cheia) e a pessoa termina o login, com faixa vermelha no painel e aviso repetido a cada 60 s.
    É o único caminho de login: a aba Atualizar, a fila (ColetorReal), a conferência e a exploração passam por aqui.
    Falha → diagnóstico em diagnosticos/ (tela, texto e motivo) e `LoginFalhou`."""
    import atencao
    atencao.limpar("login")
    acesso.ULTIMO.clear()
    page = janela.nova_pagina(context)
    for tentativa in (1, 2):
        try:
            page.goto("https://www.jus.br", timeout=45000, wait_until="load")
            page.wait_for_timeout(2000)
            if LOGIN_MARKER in _texto(page) or acesso.login_automatico(page):
                break
            print(f"Login automático não concluiu (tentativa {tentativa} de 2): "
                  f"{acesso.ULTIMO.get('mensagem') or 'motivo desconhecido'}", flush=True)
            _diagnostico_do_login(page, tentativa)
        except Exception as e:
            print(f"Login automático falhou ({e}).", flush=True)
            acesso.registrar_falha("goto", f"{type(e).__name__}: {e}")
            try:
                _diagnostico_do_login(page, tentativa)
            except Exception:
                pass
    inicio = time.time()
    lembrete = atencao.Lembrete("Precisa de você: login no jus.br")
    avisou = False
    while LOGIN_MARKER not in _texto(page):
        if time.time() - inicio > LOGIN_TIMEOUT_S:
            orientacao = _orientacao_do_login()
            atencao.pedir("login", f"Login não concluído. {orientacao} Depois clique em Retomar.")
            raise LoginFalhou(f"Login no jus.br não concluído a tempo. {orientacao}")
        if not avisou:
            atencao.chamar(page, "login", _orientacao_do_login())
            print("Termine o login no jus.br na janela que apareceu.", flush=True)
            avisou = True
        lembrete.tick()
        page.wait_for_timeout(1500)
    atencao.limpar("login")
    page.close()
    print("Login concluído.", flush=True)


# --- abrir os autos ---

def _autos_carregados(page, numero):
    try:
        page.locator(SEL_ABA, has_text="Movimentos").first.wait_for(state="visible", timeout=20000)
        # diálogo "Você está na navegação guiada" cobre a tela e esconde a página
        fechar_popups(page, tentativas=2)
        return numero in _texto(page)
    except Exception:
        return False


def chave_tramitacao(url):
    """1º grau e recurso têm o mesmo número; o que os separa na URL dos autos
    é a data de distribuição de cada tramitação."""
    m = re.search(r"dataDistribuicao=(\d+)", url or "")
    return m.group(1) if m else "principal"


def grau(rotulo):
    m = re.search(r"\((\d)º Grau\)", rotulo or "")
    return f"{m.group(1)}º grau" if m else None


ERROS_TRANSITORIOS = ("Internal Server Error", "Erro inesperado ao manusear pedido de autenticação", "Bad Gateway",
                      "Service Unavailable", "Gateway Time-out")


def erro_transitorio_do_portal(page):
    """O portal jus.br às vezes devolve uma página de erro que passa sozinha (visto em 08/10/2026: "Internal Server
    Error" ao abrir os autos e "Erro inesperado ao manusear pedido de autenticação" na busca). Vale esperar e tentar de
    novo, em vez de desistir do processo."""
    texto = _texto(page)
    return any(e.lower() in texto.lower() for e in ERROS_TRANSITORIOS)


def _abrir_url(context, numero, url, tentativas=2):
    for tentativa in range(1, tentativas + 1):
        autos = janela.nova_pagina(context)
        transitorio = False
        try:
            autos.goto(url, timeout=30000, wait_until="domcontentloaded")
            fechar_popups(autos, tentativas=2)
            if _autos_carregados(autos, numero):
                return autos
            transitorio = erro_transitorio_do_portal(autos)
        except Exception:
            pass
        autos.close()
        if not transitorio or tentativa == tentativas:
            break
        print("  O portal devolveu um erro passageiro ao abrir os autos; tentando de novo em instantes.", flush=True)
        time.sleep(6 * tentativa)
    return None


def _data_distribuicao(valor):
    """'2014-03-10T09:08:23' (ou variações) -> '20140310090823'."""
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})[T ]?(\d{2}):?(\d{2}):?(\d{2})", str(valor))
    return "".join(m.groups()) if m else None


def tramitacoes_da_resposta(respostas, numero):
    """[(dataDistribuicao para a URL, órgão julgador)] de cada tramitação, a
    partir do JSON da busca do portal (formato visto em 03/10/2026):
        {"content": [{"numeroProcesso": ..., "tramitacoes": [
            {"dataHoraAjuizamento": "2014-03-10T16:39:08", "orgaoJulgador": {"nome": ...}, ...}]}]}
    A URL usa a data de AJUIZAMENTO da tramitação (é o que a tabela da busca
    chama de "dataDistribuicao"); a data da última redistribuição abre outra coisa."""
    digitos = re.sub(r"\D", "", numero)
    achados = []
    for resp in respostas:
        for proc in (resp.get("content") or []) if isinstance(resp, dict) else []:
            if re.sub(r"\D", "", str(proc.get("numeroProcesso", ""))) != digitos:
                continue
            for t in proc.get("tramitacoes") or []:
                data = _data_distribuicao(t.get("dataHoraAjuizamento", ""))
                orgao = (t.get("orgaoJulgador") or {}).get("nome", "")
                classes = " ".join(c.get("descricao", "") for c in t.get("classe") or [] if isinstance(c, dict))
                segundo = re.search(r"C[AÂ]MARA|TURMA|GADES|GABINETE|DESEMBARG|SE[CÇ][AÃ]O|PLENO|[ÓO]RG[AÃ]O ESPECIAL", orgao, re.I) \
                    or re.search(r"apela|agravo|recurso|remessa necess", classes, re.I)
                rotulo = f"{orgao} ({'2' if segundo else '1'}º Grau)"
                if data and data not in [d for d, _ in achados]:
                    achados.append((data, rotulo))
    return achados


def _buscar(context, numero, respostas=None):
    """Página de consulta com o resultado da busca, ou None. Tenta duas vezes:
    logo depois do login a busca às vezes sai antes de a página estar pronta.
    Se 'respostas' vier (lista), guarda nela o JSON que o portal recebe."""
    digitos = re.sub(r"\D", "", numero)

    def ouvir(resp):
        # só a resposta da busca deste processo; nunca as de login (token, CPF, e-mail)
        if respostas is None or "json" not in resp.headers.get("content-type", ""):
            return
        try:
            corpo = resp.json()
        except Exception:
            return
        texto = json.dumps(corpo, ensure_ascii=False)
        if digitos in re.sub(r"\D", "", texto) and "access_token" not in texto:
            respostas.append(corpo)

    context.on("response", ouvir)
    try:
        return _buscar_tentativas(context, numero)
    finally:
        context.remove_listener("response", ouvir)


def _buscar_tentativas(context, numero):
    for tentativa in (1, 2, 3):
        consulta = janela.nova_pagina(context)
        transitorio = False
        try:
            try:
                consulta.goto(URL_CONSULTA, timeout=30000, wait_until="domcontentloaded")
            except Exception:
                consulta.wait_for_timeout(5000)
            consulta.wait_for_timeout(3000 * tentativa)
            if erro_transitorio_do_portal(consulta):
                transitorio = True
                raise RuntimeError("o portal devolveu uma página de erro passageira")
            fechar_popups(consulta)
            campo = consulta.get_by_placeholder("0000000-00.0000.0.00.0000")
            campo.wait_for(state="visible", timeout=30000)
            campo.fill(numero)
            # Enter no campo dispensa o botão "Buscar", que costuma ficar coberto
            # pelo menu lateral (falha recorrente no PJe Monitor)
            campo.press("Enter")
            linhas = consulta.locator("mat-row, tr").filter(has_text=numero)
            try:
                linhas.first.wait_for(state="visible", timeout=15000)
            except Exception:
                fechar_popups(consulta, tentativas=1)
                consulta.get_by_role("button", name="Buscar", exact=True).click(timeout=10000, force=True)
                linhas.first.wait_for(state="visible", timeout=20000)
            return consulta
        except Exception:
            salvar_diagnostico(consulta, f"busca_falhou_{slug(numero)}_t{tentativa}")
            consulta.close()
            if transitorio and tentativa < 3:
                time.sleep(8 * tentativa)  # o erro de autenticação/servidor do portal costuma passar em segundos
    return None


def em_tribunal_superior(texto):
    """"STJ" ou "STF" quando a tabela da busca mostra o órgão julgador de um tribunal superior (a tramitação atual
    está lá e o jus.br não abre estes autos; visto em 08/10/2026 num Recurso Especial), senão None."""
    m = re.search(r"\b(STJ|STF)\s*-\s*[A-ZÀ-Ú]", texto or "")
    return m.group(1) if m else None


def abrir_tramitacoes(context, numero, salvas=None):
    """Abre os autos de cada tramitação do processo (1º grau, recurso...).
    Volta [(pagina, url, rotulo)]. Usa as URLs guardadas; sem elas, a busca."""
    salvas = salvas or {}
    if salvas:
        abertas = []
        for chave, t in salvas.items():
            pg = _abrir_url(context, numero, t["url_autos"])
            if pg is None:
                for p, _, _ in abertas:
                    p.close()
                abertas = None
                print("  URL guardada não abriu os autos; usando a busca.")
                break
            abertas.append((pg, t["url_autos"], t.get("rotulo", "")))
        if abertas:
            return abertas

    respostas = []
    consulta = _buscar(context, numero, respostas)
    if consulta is None:
        raise RuntimeError("Processo não encontrado na consulta do jus.br (conferir manualmente).")
    consulta.wait_for_timeout(2500)
    total = max(consulta.locator("mat-row, tr").filter(has_text=numero).count(), consulta.locator("mat-row").count())
    achadas = tramitacoes_da_resposta(respostas, numero)
    if not achadas:
        comum.DIAG_DIR.mkdir(parents=True, exist_ok=True)
        (comum.DIAG_DIR / f"respostas_busca_{slug(numero)}_{carimbo()}.json").write_text(
            json.dumps(respostas, ensure_ascii=False, indent=1)[:2_000_000], encoding="utf-8")
    if achadas:
        # abre cada tramitação (1º grau, recurso) pela URL, montada com a data
        # de distribuição que veio na resposta do portal; a contagem de linhas
        # na tela não é confiável (já veio 1 com 2 linhas na página)
        abertas = []
        for i, (data, rot) in enumerate(achadas):
            url = f"{URL_CONSULTA}/autosdigitais?processo={numero}&dataDistribuicao={data}"
            pg = _abrir_url(context, numero, url)
            if pg is not None:
                # rótulo da linha da tabela com a mesma data de ajuizamento (traz "(2º Grau)")
                abertas.append((pg, url, rot))
        if abertas:
            consulta.close()
            return abertas
        print(f"  {len(achadas)} tramitação(ões) na resposta do portal, mas a URL não abriu. Tentando o clique.")
    else:
        print(f"  Resposta do portal sem data de distribuição (salva em diagnósticos). Tentando o clique.")
    abertas = []
    superior = em_tribunal_superior(_texto(consulta))
    try:
        for i in range(total):
            if i > 0:  # cada tramitação a partir de uma busca nova (o clique pode trocar a página)
                consulta.close()
                consulta = _buscar(context, numero)
                if consulta is None:
                    break
            linha = consulta.locator("mat-row, tr").filter(has_text=numero).nth(i)
            rotulo = " ".join(linha.inner_text().split())
            # clicar fora da 1ª célula: o botão "Detalhar" dela intercepta o clique
            celulas = linha.locator("mat-cell, td")
            alvo = celulas.nth(min(2, celulas.count() - 1)) if celulas.count() else linha
            try:
                with context.expect_page(timeout=30000) as nova:
                    consulta.once("dialog", lambda d: d.accept())
                    alvo.click(timeout=10000)
                autos = nova.value
            except Exception:
                if "autosdigitais" in consulta.url:  # abriu na mesma aba
                    autos, consulta = consulta, None
                else:
                    salvar_diagnostico(consulta, f"tramitacao_nao_abriu_{slug(numero)}_{i + 1}")
                    continue
            janela.minimizar(autos)  # o portal abre os autos em outra janela
            autos.wait_for_load_state("domcontentloaded", timeout=20000)
            if not _autos_carregados(autos, numero):
                salvar_diagnostico(autos, f"autos_nao_carregaram_{slug(numero)}_{i + 1}")
                autos.close()
                continue
            abertas.append((autos, autos.url, rotulo))
            if consulta is None:
                consulta = _buscar(context, numero) if i + 1 < total else None
                if consulta is None and i + 1 < total:
                    break
        if not abertas:
            if superior:
                raise RuntimeError(f"Processo no {superior} (tribunal superior): o jus.br não abre estes autos. "
                                   "Conferir manualmente no portal do tribunal.")
            raise RuntimeError("Nenhuma tramitação abriu (diagnóstico salvo).")
        return abertas
    finally:
        if consulta is not None:
            consulta.close()


def abrir_autos(context, numero, url_salva=None):
    """Compatibilidade: primeira tramitação (usada pelo --explorar)."""
    salvas = {"x": {"url_autos": url_salva}} if url_salva else None
    abertas = abrir_tramitacoes(context, numero, salvas)
    for pg, _, _ in abertas[1:]:
        pg.close()
    return abertas[0][0], abertas[0][1]


def abrir_aba(autos, nome):
    fechar_popups(autos, tentativas=1)
    fechar_menu_lateral(autos)
    autos.locator(SEL_ABA, has_text=nome).first.click(timeout=10000)
    autos.wait_for_timeout(1500)


def _grupos_da_aba_ativa(autos):
    """Blocos por data só da aba aberta (sem a estrutura de abas, a página toda)."""
    base = autos.locator(SEL_ABA_ATIVA)
    return (base.first if base.count() else autos).locator(SEL_MOVIMENTO)


# --- leitura dos autos (funções separadas para teste com HTML salvo) ---

def ler_movimentos(autos):
    """[(chave, data dd/mm/aaaa, texto)] do mais recente para o mais antigo.
    A tela não mostra hora: a chave junta data, texto e a ordem do item
    repetido no mesmo dia."""
    itens, repeticoes = [], {}
    grupos = _grupos_da_aba_ativa(autos)
    for i in range(grupos.count()):
        grupo = grupos.nth(i)
        data = data_por_extenso(grupo.locator(SEL_MOV_DATA).first.inner_text()) if grupo.locator(SEL_MOV_DATA).count() else None
        textos = grupo.locator(SEL_MOV_TEXTO)
        for j in range(textos.count()):
            texto = " ".join(textos.nth(j).inner_text().split())
            n = repeticoes[(data, texto)] = repeticoes.get((data, texto), 0) + 1
            itens.append((f"{data}|{texto}|{n}", data, texto))
    return itens


def listar_documentos(autos):
    """[(nome, link, data dd/mm/aaaa)] do mais recente para o mais antigo."""
    docs = []
    grupos = _grupos_da_aba_ativa(autos)
    for i in range(grupos.count()):
        grupo = grupos.nth(i)
        data = data_por_extenso(grupo.locator(SEL_MOV_DATA).first.inner_text()) if grupo.locator(SEL_MOV_DATA).count() else None
        links = grupo.locator(SEL_DOCUMENTO)
        for j in range(links.count()):
            docs.append((" ".join(links.nth(j).inner_text().split()), links.nth(j), data))
    return docs


def print_elemento(page, seletor, destino):
    return janela.print_da_pagina(page, destino, seletor)


def abrir_documento(autos, link, nome, destino_sem_ext):
    """Seleciona o documento, tira print do visualizador e tenta obter o teor:
    1) botão de download do visualizador; 2) PDF carregado pelo visualizador
    (resposta de rede); 3) texto do documento HTML exibido na tela.
    Volta (arquivo ou None, print)."""
    context = autos.context
    info = separar_nome_documento(nome)
    capturadas = []

    def ouvir(resp):
        tipo = resp.headers.get("content-type", "")
        if "application/pdf" in tipo or "octet-stream" in tipo:
            capturadas.append(resp)

    context.on("response", ouvir)
    paginas_antes = set(context.pages)
    destino_sem_ext.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.click()
        try:
            autos.locator(SEL_VISUALIZADOR_DADOS).filter(has_not_text="Nenhum documento selecionado").first.wait_for(timeout=15000)
        except Exception:
            pass
        autos.wait_for_timeout(2500)
        foto = janela.print_da_pagina(autos, destino_sem_ext.with_name(destino_sem_ext.name + "-print.png"))

        try:
            with autos.expect_download(timeout=15000) as dl:
                autos.locator(SEL_BOTAO_DOWNLOAD).first.click(timeout=5000)
            d = dl.value
            caminho = destino_sem_ext.with_suffix(Path(d.suggested_filename).suffix or ".pdf")
            d.save_as(caminho)
            return caminho, foto
        except Exception:
            pass
        for resp in reversed(capturadas):
            try:
                corpo = resp.body()
            except Exception:
                continue
            if corpo[:4] == b"%PDF":
                caminho = destino_sem_ext.with_suffix(".pdf")
                caminho.write_bytes(corpo)
                return caminho, foto
        if info["ext"] in ("html", "htm", None):
            conteudo = autos.locator(SEL_CONTEUDO_HTML)
            if conteudo.count() and len(conteudo.first.inner_text().strip()) > 50:
                caminho = destino_sem_ext.with_suffix(".html")
                caminho.write_text(conteudo.first.inner_html(), encoding="utf-8")
                return caminho, foto
        return None, foto
    finally:
        context.remove_listener("response", ouvir)
        for pg in set(context.pages) - paginas_antes:
            pg.close()


# --- rodada ---

def _evento_base(proc, tipo_evento, chave, titulo):
    return {
        "id": f"{proc['numero']}:{hashlib.sha1(chave.encode()).hexdigest()[:12]}",
        "tipo_evento": tipo_evento,
        "numero": proc["numero"],
        "cliente": proc.get("cliente"),
        "apelido": proc.get("apelido") or proc.get("cliente"),
        "titulo": titulo,
        "detectado_em": agora(),
        "status": "coletado",
    }


def _depois(data_txt, desde):
    if not desde or not data_txt:
        return False
    d, m, a = (int(x) for x in data_txt.split("/"))
    return datetime.date(a, m, d) > desde


def _tramitacoes_salvas(reg):
    """Estado por tramitação; converte o formato antigo (uma só por processo)."""
    if "tramitacoes" in reg:
        return reg["tramitacoes"]
    if reg.get("url_autos"):
        return {chave_tramitacao(reg["url_autos"]): {k: reg[k] for k in ("url_autos", "movimentos", "documentos") if k in reg}}
    return {}


def coletar_processo(context, proc, estado, lista, historico, cota, desde=None, relato=None):
    numero = proc["numero"]
    if re.search(r"\d{7}-\d{2}\.\d{4}\.5\.", numero):  # Justiça do Trabalho: consulta do próprio TRT
        import trt
        return trt.coletar_processo(context, proc, estado, lista, historico, cota, desde, relato)
    reg_proc = estado.get(numero, {})
    salvas = _tramitacoes_salvas(reg_proc)
    # a cada 7 dias refaz a busca: é como se descobre um recurso (tramitação nova)
    ultima_busca = reg_proc.get("ultima_busca", "")
    busca_recente = ultima_busca >= (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    usar = {k: v for k, v in salvas.items() if v.get("url_autos")} if busca_recente else {}
    t_busca = time.time()
    tramitacoes = abrir_tramitacoes(context, numero, usar)
    print(f"  tempo: busca {time.time() - t_busca:.1f} s", flush=True)      # lido por diagnostico_rodada.py
    t_leitura = time.time()
    if not usar:
        ultima_busca = datetime.date.today().isoformat()
    varias = len(tramitacoes) > 1
    novas_salvas = dict(salvas)
    baixados = 0
    ja_lidas = []  # listas de andamentos das tramitações já lidas nesta rodada
    for autos, url, rotulo in tramitacoes:
        chave_t = chave_tramitacao(url)
        reg = salvas.get(chave_t)
        try:
            n, reg_novo = _coletar_tramitacao(autos, proc, reg, rotulo if varias else "", lista, historico,
                                              cota - baixados, desde, chave_t, ja_lidas)
            baixados += n
            reg_novo.update(url_autos=url, rotulo=rotulo)
            novas_salvas[chave_t] = reg_novo
        finally:
            autos.close()
    estado[numero] = {"tramitacoes": novas_salvas, "ultima_coleta": agora(), "ultima_busca": ultima_busca}
    print(f"  tempo: leitura {time.time() - t_leitura:.1f} s", flush=True)
    return baixados


def _coletar_tramitacao(autos, proc, reg, rotulo, lista, historico, cota, desde, chave_t, ja_lidas=None):
    numero = proc["numero"]
    primeira_vez = reg is None
    reg = reg or {}
    nivel = grau(rotulo)
    if rotulo:
        print(f"  tramitação: {nivel or rotulo[-60:]}")
    pasta_prints = comum.PRINTS_DIR / slug(proc.get("cliente") or "sem-cliente") / slug(numero)
    ids = {e["id"] for e in lista}
    baixados = 0
    # 1. Movimentos
    abrir_aba(autos, "Movimentos")
    movimentos = ler_movimentos(autos)
    mov_conhecidos = set(reg.get("movimentos", []))
    assinatura = [m[0] for m in movimentos]
    if ja_lidas is not None:
        if assinatura and assinatura in ja_lidas:
            # alguns tribunais mostram os mesmos autos nas duas tramitações: não duplica eventos
            print(f"  movimentos: {len(movimentos)} na tela, iguais aos de outra tramitação (sem eventos repetidos)")
            return 0, {"movimentos": sorted(set(assinatura) | mov_conhecidos),
                       "documentos": sorted(set(reg.get("documentos", [])) | {d[0] for d in (abrir_aba(autos, "Documentos") or listar_documentos(autos))})}
        ja_lidas.append(assinatura)
    if primeira_vez:
        # 1ª vez: só o que veio depois do último relatório (--desde) ou os N mais recentes (--historico)
        novos_mov = [m for m in movimentos if _depois(m[1], desde)] if desde else movimentos[:historico]
    else:
        novos_mov = [m for m in movimentos if m[0] not in mov_conhecidos]
    if novos_mov:
        foto = print_elemento(autos, ".movimentos", pasta_prints / f"{carimbo()}-movimentos.png")
        vistos_hoje = set()
        for chave, data, texto in novos_mov:
            if (data, texto) in vistos_hoje:
                continue  # o mesmo andamento listado uma vez por destinatário
            vistos_hoje.add((data, texto))
            ev = _evento_base(proc, "movimento", f"mov|{chave_t}|{chave}", texto)
            if ev["id"] not in ids:
                ev.update(data=data, chave=chave, print=str(foto), grau=nivel)
                lista.append(ev)
                ids.add(ev["id"])
    print(f"  movimentos: {len(movimentos)} na tela, {len(novos_mov)} novo(s)")

    # 2. Documentos
    abrir_aba(autos, "Documentos")
    documentos = listar_documentos(autos)
    doc_conhecidos = set(reg.get("documentos", []))
    if primeira_vez:
        novos_doc = [d for d in documentos if _depois(d[2], desde)] if desde else documentos[:historico]
    else:
        novos_doc = [d for d in documentos if d[0] not in doc_conhecidos]
    for nome, link, data_doc in novos_doc[:max(cota, 0)]:
        info = separar_nome_documento(nome)
        ev = _evento_base(proc, "documento", f"doc|{info['id'] or nome}", nome)
        if ev["id"] in ids:
            continue
        arquivo, foto = abrir_documento(autos, link, nome, pasta_prints / slug(nome)[:80])
        if arquivo:
            destino = comum.DOCS_DIR / slug(proc.get("cliente") or "sem-cliente") / slug(numero) / arquivo.name
            destino.parent.mkdir(parents=True, exist_ok=True)
            arquivo.replace(destino)
            arquivo = destino
            baixados += 1
        ev.update(tipo=info["tipo"], descricao=info["descricao"], doc_id=info["id"], data=data_doc, grau=nivel,
                  arquivo=str(arquivo) if arquivo else None, print=str(foto))
        lista.append(ev)
        ids.add(ev["id"])
        doc_conhecidos.add(nome)
        print(f"  documento {'baixado' if arquivo else 'só com print'}: {nome}")
        pausa(config()["coleta"]["pausa_entre_documentos_s"])
    print(f"  documentos: {len(documentos)} na tela, {len(novos_doc)} novo(s)")
    if primeira_vez or len(novos_doc) <= cota:
        doc_conhecidos.update(d[0] for d in documentos)  # o que passou da cota fica para a próxima rodada
    return baixados, {"movimentos": sorted({m[0] for m in movimentos} | mov_conhecidos),
                      "documentos": sorted(doc_conhecidos)}


def rodar(numeros=None, historico=0, desde=None):
    from playwright.sync_api import sync_playwright

    cart = carteira()
    alvo = [cart[n] for n in (numeros or cart)]
    if not alvo:
        print("Carteira vazia: importe a lista de processos (carteira.py importar).")
        return
    estado = load_json(comum.ESTADO_FILE, {})
    lista = eventos()
    cota = config()["coleta"]["max_documentos_por_rodada"]
    with sync_playwright() as p:
        browser, context = janela.abrir_navegador(p)
        logar(context)
        for proc in alvo:
            print(f"{proc['numero']} ({proc.get('cliente', '')})")
            try:
                cota -= coletar_processo(context, proc, estado, lista, historico, max(cota, 0), desde)
            except Exception as e:
                print(f"  falhou: {e}")
            save_json(comum.ESTADO_FILE, estado)
            salvar_eventos(lista)
            pausa(config()["coleta"]["pausa_entre_processos_s"])
        browser.close()


def explorar(numero):
    """Para ajustar o coletor: salva as duas abas dos autos e o que acontece ao
    abrir o documento mais recente (print, rede e frames)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, context = janela.abrir_navegador(p)
        logar(context)
        autos, url = abrir_autos(context, numero)
        print(f"URL dos autos: {url}")
        abrir_aba(autos, "Movimentos")
        salvar_diagnostico(autos, f"explorar_movimentos_{slug(numero)}")
        for chave, data, texto in ler_movimentos(autos)[:10]:
            print("  mov:", data, texto)
        abrir_aba(autos, "Documentos")
        base = salvar_diagnostico(autos, f"explorar_documentos_{slug(numero)}")
        docs = listar_documentos(autos)
        print(f"{len(docs)} documento(s). Primeiros:", *[f"  {d}  {n}" for n, _, d in docs[:10]], sep="\n")
        if docs:
            respostas = []
            context.on("response", lambda r: respostas.append(f"{r.status} {r.headers.get('content-type', '')} {r.url}"))
            arquivo, foto = abrir_documento(autos, docs[0][1], docs[0][0], comum.DIAG_DIR / f"explorar_doc_{carimbo()}")
            print(f"Documento: {arquivo or 'NÃO baixado'} | print: {foto}")
            salvar_diagnostico(autos, f"explorar_documento_aberto_{slug(numero)}")
            Path(f"{base}_rede.txt").write_text("\n".join(respostas + ["", "FRAMES:"] +
                                                          [f.url for pg in context.pages for f in pg.frames]), encoding="utf-8")
        input("Diagnóstico salvo. Aperte Enter para fechar o navegador...")
        browser.close()


def testar_login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, context = janela.abrir_navegador(p)
        try:
            logar(context)
            print("ACESSO OK: entrou no jus.br com o certificado e o autenticador.", flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:  # só a ajuda, sem rodar nada
        print(__doc__)
        sys.exit(0)
    args = sys.argv[1:]
    if "--testar-login" in args:
        testar_login()
        sys.exit(0)
    if "--explorar" in args:
        explorar(args[args.index("--explorar") + 1])
    else:
        nums = [n.strip() for n in args[args.index("--processo") + 1].split(",")] if "--processo" in args else None
        hist = int(args[args.index("--historico") + 1]) if "--historico" in args else 0
        desde = None
        if "--desde" in args:
            d, m, a = (int(x) for x in args[args.index("--desde") + 1].split("/"))
            desde = datetime.date(a, m, d)
        rodar(nums, hist, desde)
