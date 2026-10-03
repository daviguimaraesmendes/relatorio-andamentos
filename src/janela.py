"""Janela do navegador do jus.br: nasce no canto mais distante da tela e é
minimizada assim que aparece. Só volta à frente quando precisa de alguém
(login manual, captcha).

A minimização usa o protocolo do próprio Chromium (CDP), página por página,
sem depender do nome do aplicativo no AppleScript. Os parâmetros de
inicialização impedem o Chromium de "dormir" com a janela minimizada, para
que prints e o visualizador de PDF continuem funcionando.
"""
import subprocess
import time

TAMANHO = (1440, 1000)        # tamanho da página (o que sai no print)
JANELA = (480, 320)           # janela física, pequena, para caber no canto
VISIVEL = (24, 24)            # quanto da janela fica dentro da tela no canto
# Concedidas já na abertura: com a janela minimizada ninguém vê os avisos
# nativos do Chrome, e sem "acesso à rede local" o jus.br não alcança o PJe
# Office (o diálogo da senha do certificado nunca abre).
PERMISSOES = ["local-network-access", "notifications"]
SEM_ECONOMIA = [
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]


def tamanho_da_tela():
    """(largura, altura) da área de trabalho somando todos os monitores."""
    import sys
    if sys.platform.startswith("win"):
        try:
            import ctypes
            u = ctypes.windll.user32
            return u.GetSystemMetrics(78), u.GetSystemMetrics(79)  # tela virtual (todos os monitores)
        except Exception:
            return 1440, 900
    try:
        saida = subprocess.run(["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
                               capture_output=True, text=True, timeout=5).stdout
        _, _, largura, altura = (int(x) for x in saida.split(","))
        return largura, altura
    except Exception:
        return 1440, 900


def _janela(page):
    sessao = page.context.new_cdp_session(page)
    return sessao, sessao.send("Browser.getWindowForTarget")["windowId"]


def _canto():
    largura, altura = tamanho_da_tela()
    return largura - VISIVEL[0], altura - VISIVEL[1]


def _aguardar_estado(sessao, janela, estado, limite=2.0):
    """O macOS ignora redimensionar enquanto a janela ainda está saindo do Dock."""
    fim = time.time() + limite
    while time.time() < fim:
        if sessao.send("Browser.getWindowBounds", {"windowId": janela})["bounds"].get("windowState") == estado:
            time.sleep(0.3)
            return
        time.sleep(0.1)


def _para_o_canto(sessao, janela):
    esquerda, topo = _canto()
    sessao.send("Browser.setWindowBounds", {"windowId": janela, "bounds": {"width": JANELA[0], "height": JANELA[1]}})
    sessao.send("Browser.setWindowBounds", {"windowId": janela, "bounds": {"left": esquerda, "top": topo}})


def minimizar(page):
    """Leva a janela para o canto (pequena) e minimiza, confirmando que o
    macOS aceitou. Assim, quando ela sair do Dock para um print, reaparece
    já no canto."""
    try:
        sessao, janela = _janela(page)
        limites = sessao.send("Browser.getWindowBounds", {"windowId": janela})["bounds"]
        if limites.get("windowState") == "normal" and (limites["left"], limites["top"]) != _canto():
            _para_o_canto(sessao, janela)
            time.sleep(0.3)
        for _ in range(2):
            sessao.send("Browser.setWindowBounds", {"windowId": janela, "bounds": {"windowState": "minimized"}})
            _aguardar_estado(sessao, janela, "minimized", limite=1.5)
            if sessao.send("Browser.getWindowBounds", {"windowId": janela})["bounds"].get("windowState") == "minimized":
                break
        sessao.detach()
    except Exception:
        pass  # página fechada no meio do caminho: nada a minimizar


def nova_pagina(context):
    page = context.new_page()
    minimizar(page)
    return page


def mostrar(page):
    """Traz a janela de volta, em posição normal, quando alguém precisa agir."""
    try:
        sessao, janela = _janela(page)
        sessao.send("Browser.setWindowBounds", {"windowId": janela, "bounds": {"windowState": "normal"}})
        sessao.send("Browser.setWindowBounds", {"windowId": janela, "bounds": {"left": 80, "top": 60, "width": 1100, "height": 800}})
        sessao.detach()
        page.bring_to_front()
    except Exception:
        pass


def esconder_no_canto(page):
    """Janela fora do Dock, mas no canto, quase toda fora da tela."""
    sessao, janela = _janela(page)
    sessao.send("Browser.setWindowBounds", {"windowId": janela, "bounds": {"windowState": "normal"}})
    _aguardar_estado(sessao, janela, "normal")
    _para_o_canto(sessao, janela)
    sessao.detach()


def print_da_pagina(page, destino, seletor=None, pagina_inteira=False):
    """Com a janela minimizada o Chromium não desenha e o print trava. Então:
    sai do Dock só no canto, tira o print e minimiza de novo."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        esconder_no_canto(page)
        page.wait_for_timeout(300)
        alvo = page.locator(seletor).first if seletor else None
        if alvo is not None and alvo.count():
            alvo.screenshot(path=str(destino), timeout=15000)
        else:
            page.screenshot(path=str(destino), timeout=15000, full_page=pagina_inteira)
    finally:
        minimizar(page)
    return destino


def abrir_navegador(p):
    """Abre o Chromium no canto inferior direito e devolve (browser, context).
    Cada página nova deve ser aberta por nova_pagina() (ou passar por
    minimizar(), como a dos autos, que o portal abre em outra janela)."""
    esquerda, topo = _canto()
    browser = p.chromium.launch(headless=False, args=[
        f"--window-position={esquerda},{topo}",
        f"--window-size={JANELA[0]},{JANELA[1]}",
        *SEM_ECONOMIA,
    ])
    context = browser.new_context(accept_downloads=True, viewport={"width": TAMANHO[0], "height": TAMANHO[1]},
                                  permissions=PERMISSOES)
    return browser, context
