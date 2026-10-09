"""Rodada completa, igual no Mac e no Windows: coleta nos autos (jus.br e TRTs),
extração do texto, resumo pela IA local. É o que o botão Atualizar do painel roda.

    python rodar.py --projeto <pasta> [--desde DD/MM/AAAA] [--historico N] [--processo N1,N2]
                    [--fila [--modo continuo|imediato] [--profundidade rapido|padrao|completo] [--novo-ciclo]]

Com --fila a coleta passa pela fila persistente (fila.py): retomável após queda, com tentativas por tipo de erro,
captcha/segredo indo para "conferir manualmente" e, no modo contínuo, só dentro das janelas de horário. Sem
--fila nada muda (o fluxo da Fase 1 continua igual). Modo padrão: imediato. Quem já foi coletado na fila não é
coletado de novo; ao começar o ciclo seguinte (outro mês), use --novo-ciclo.
"""
import datetime
import os
import subprocess
import sys
import time
import urllib.request

if "--projeto" in sys.argv:  # antes de importar comum: define o relatório ativo
    os.environ["RELATORIO_PROJETO"] = sys.argv[sys.argv.index("--projeto") + 1]

import comum  # noqa: E402


def _arg(nome):
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else None


def ollama_no_ar():
    try:
        urllib.request.urlopen(comum.config().get("ollama_url", "http://127.0.0.1:11434") + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


def coletar_pela_fila(numeros, historico, desde):
    """Coleta usando fila.Fila + fila.ColetorReal. Os eventos e o estado são gravados pelo ColetorReal, como na
    coleta direta. NÃO testável sem certificado e rede: validar no piloto."""
    import fila
    f = fila.Fila(comum.PROJETO)
    f.enfileirar(numeros or list(comum.carteira()), modo=_arg("--modo") or "imediato",
                 profundidade=_arg("--profundidade") or "padrao", desde=desde.isoformat() if desde else None, recoletar="--novo-ciclo" in sys.argv)
    resumo = f.resumo()
    print(f"Fila: {resumo['pendente']} processo(s) a coletar.", flush=True)

    f.retomar()  # uma pausa deixada por falha de login numa rodada anterior não vale para esta

    def andamento(r):
        if r["evento"] in ("coletado", "erro", "manual"):
            print(f"  {r['numero']}: {r['evento']}{' (' + r['codigo'] + ')' if r.get('codigo') else ''}", flush=True)
        elif r["evento"] == "login":  # sem ninguém para retomar a fila (rodada em segundo plano): para com segurança
            print(f"A coleta parou: o acesso ao jus.br falhou. {r.get('mensagem') or ''}", flush=True)
            f.parar_com_seguranca()
    with fila.ColetorReal(historico=historico) as coletor_real:
        resumo = fila.rodar_fila(f, coletor_real, ao_progresso=andamento)
    print(f"Fila: {resumo['coletado']} coletado(s), {resumo['manual']} para conferir manualmente, "
          f"{resumo['erro']} com erro.", flush=True)


def main():
    print(f"Relatório de Andamentos {comum.versao_do_programa() or '?'}", flush=True)
    import coletor
    import extrair
    import ia_local
    import resumir

    desde = _arg("--desde")
    if desde:
        d, m, a = (int(x) for x in desde.split("/"))
        desde = datetime.date(a, m, d)
    numeros = [n.strip() for n in _arg("--processo").split(",")] if _arg("--processo") else None
    try:
        if "--fila" in sys.argv:
            coletar_pela_fila(numeros, int(_arg("--historico") or 0), desde)
        else:
            coletor.rodar(numeros, int(_arg("--historico") or 0), desde)
    except Exception as e:
        print(f"Coleta com falha ({e}); seguindo com o que já foi baixado.", flush=True)
    extrair.rodar()
    # o modelo local só roda durante o resumo: liga aqui e desliga no fim
    servidor = None
    exe = ia_local.ollama_exe()
    if not ollama_no_ar() and exe:
        servidor = subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
    try:
        resumir.rodar()
    finally:
        if servidor:
            servidor.terminate()
    n = sum(e["status"] == "rascunho" for e in comum.eventos())
    print(f"{n} rascunho(s) aguardando revisão. Veja em Revisar, no painel.", flush=True)


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:  # só a ajuda, sem rodar nada
        print(__doc__)
        sys.exit(0)
    main()
