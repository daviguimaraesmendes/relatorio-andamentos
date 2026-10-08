"""Pedidos de atenção humana durante a coleta: captcha do TRT e login do jus.br.

Quem coleta (trt.py, coletor.py) chama `pedir(...)` quando precisa de alguém na frente do computador e
`limpar(...)` quando o problema passou. O painel lê o mesmo arquivo (`data/atencao.json`) e mostra uma faixa
vermelha fixa em todas as telas, atualizada sozinha; funciona igual com a coleta no próprio painel ou num
processo à parte (aba Atualizar), porque a conversa é por arquivo.

O alerta chama a atenção por quatro vias, nesta ordem de força:
  1. notificação do sistema com som (Mac: osascript; outros sistemas: sinal sonoro do terminal);
  2. o navegador de automação vem para a frente (Mac: osascript);
  3. o navegador é aberto em tela cheia ou maximizado (janela.mostrar);
  4. `Lembrete` repete a notificação e o som a cada 60 s enquanto ninguém resolver.

Nada aqui fala com tribunal. A parte do Mac (osascript) NÃO é testável fora do Mac: os testes usam um
executor falso; quem valida é o usuário, na máquina dele.
"""
import datetime
import os
import subprocess
import sys
import time

import comum

MAC = sys.platform == "darwin"
INTERVALO_LEMBRETE_S = 60
VALIDADE_S = 6 * 3600       # alerta que ninguém limpou (programa fechado à força) some sozinho depois disso
TITULO = "Relatório de Andamentos"


def _arquivo():
    return comum.DATA / "atencao.json"


def _agora():
    return datetime.datetime.now()


def _pid_vivo(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def pedir(tipo, mensagem, tribunal=None, passos=None):
    """Registra que a coleta está esperando uma pessoa. `tipo`: "captcha" ou "login". Devolve o registro."""
    anterior = atual()
    desde = anterior["desde"] if anterior and anterior["tipo"] == tipo and anterior.get("tribunal") == tribunal \
        else _agora().isoformat(timespec="seconds")
    registro = {"tipo": tipo, "mensagem": mensagem, "tribunal": tribunal, "passos": list(passos or []),
                "desde": desde, "pid": os.getpid()}
    try:
        comum.save_json(_arquivo(), registro)
    except OSError:
        pass  # sem pasta para gravar (relatório ainda não criado): o alerta sonoro continua valendo
    return registro


def limpar(tipo=None, tribunal=None):
    """Tira o alerta (só se for do tipo/tribunal indicado, quando indicados)."""
    registro = atual()
    if registro is None:
        return
    if tipo and registro["tipo"] != tipo:
        return
    if tribunal and registro.get("tribunal") != tribunal:
        return
    try:
        _arquivo().unlink()
    except OSError:
        pass


def atual():
    """O pedido de atenção em vigor, ou None. Ignora o que ficou de um programa que não existe mais."""
    try:
        registro = comum.load_json(_arquivo(), None)
    except (OSError, ValueError):
        return None
    if not isinstance(registro, dict) or not registro.get("tipo"):
        return None
    if not _pid_vivo(registro.get("pid")):
        return None
    try:
        idade = (_agora() - datetime.datetime.fromisoformat(registro["desde"])).total_seconds()
    except (KeyError, ValueError):
        idade = 0
    return None if idade > VALIDADE_S else registro


def texto_da_faixa(registro):
    """O que a faixa vermelha do painel diz."""
    if registro["tipo"] == "captcha":
        onde = f" do TRT {registro['tribunal']}" if registro.get("tribunal") else " do TRT"
        return f"Precisa de você: captcha{onde} aguardando. Resolva na janela do navegador que apareceu."
    if registro["tipo"] == "login":
        return f"Precisa de você: login no jus.br. {registro.get('mensagem') or ''}".strip()
    return f"Precisa de você: {registro.get('mensagem') or registro['tipo']}"


# --- vias de aviso (Mac: osascript) -------------------------------------------------------------------------

def _executar(args, timeout=5):
    """Ponto único de chamada ao sistema (os testes trocam por um executor falso)."""
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _aspas(texto):
    return str(texto).replace("\\", "\\\\").replace('"', '\\"')


def notificar(texto, titulo=TITULO):
    """Notificação do sistema com som. No Mac, osascript; nos outros sistemas, sinal sonoro do terminal."""
    if MAC:
        try:
            _executar(["osascript", "-e", f'display notification "{_aspas(texto)}" with title "{_aspas(titulo)}" '
                                          f'sound name "Ping"'])
            # o Mac pode bloquear as notificações do osascript (Ajustes > Notificações > Editor de Script) e então a
            # notificação nem o som aparecem: o bipe do sistema não depende dessa permissão
            _executar(["osascript", "-e", "beep 2"])
            return True
        except Exception:
            return False
    print("\a", end="", flush=True)
    return False


def trazer_navegador_para_frente():
    """Põe o navegador de automação (Chrome for Testing / Chromium) por cima de tudo, Terminal e painel inclusive.
    Nunca o Chrome pessoal da pessoa. Só no Mac."""
    if not MAC:
        return False
    script = ('tell application "System Events"\n'
              '  set alvos to every process whose name is "Google Chrome for Testing" or name is "Chromium"\n'
              '  if (count of alvos) > 0 then set frontmost of item 1 of alvos to true\n'
              'end tell')
    try:
        return _executar(["osascript", "-e", script]).returncode == 0
    except Exception:
        return False


def chamar(page, tipo, mensagem, tribunal=None, passos=None):
    """Registra o pedido e usa todas as vias: faixa do painel, notificação com som, janela em tela cheia e
    navegador na frente. Devolve o registro."""
    import janela
    registro = pedir(tipo, mensagem, tribunal, passos)
    try:
        janela.mostrar(page, maximizar=True)
    except Exception:
        pass
    trazer_navegador_para_frente()
    notificar(texto_da_faixa(registro))
    return registro


class Lembrete:
    """Repete notificação e som a cada `intervalo_s` enquanto a espera dura; chame `tick()` no laço de espera."""

    def __init__(self, texto, intervalo_s=INTERVALO_LEMBRETE_S, relogio=None, notificador=None):
        relogio = relogio or (lambda: time.time())
        self.texto, self.intervalo_s, self.relogio = texto, intervalo_s, relogio
        self.notificador = notificador or notificar
        self.proximo = relogio() + intervalo_s
        self.vezes = 0

    def tick(self):
        if self.relogio() >= self.proximo:
            self.proximo = self.relogio() + self.intervalo_s
            self.vezes += 1
            self.notificador(self.texto)
            return True
        return False
