"""Quadro "O que falta para a transição" das telas de conferência (Importar) e de Migrar de modelo.

Mostra, por grupo de campos, quantos processos têm cada campo preenchido, de onde ele veio (ou virá) e o que a pessoa
precisa fazer, a partir de `lacunas.lacunas`. Só HTML: nada é gravado, nada vai à rede, e uma falha no cálculo nunca
derruba a tela (volta um aviso curto no lugar do quadro).

    html = quadro(fichas, mapeamento=resumo["mapeamento"], colunas_sem_destino=resumo["sem_destino"])
"""
import html

from painel.base import ajuda

_e = html.escape

AJUDA_DO_QUADRO = ("Compara o que o seu arquivo trouxe com tudo o que os modelos novos (texto, planilha e painel) usam, campo por campo. "
                   "\"Do arquivo\" é o que já veio preenchido; \"buscável nos tribunais\" o programa tenta pegar sozinho ao coletar no PJe/jus.br; "
                   "\"deduzível pelas regras/IA\" ele calcula a partir dos andamentos e das decisões (você confere depois); \"precisa de você\" "
                   "só uma pessoa sabe. Nada aqui altera o arquivo original.")
AJUDA_DA_PORCENTAGEM = ("Quantos processos têm o campo preenchido, entre os que precisam dele. Campos que só valem para parte dos processos "
                        "(por exemplo, pagamento realizado só vale para os encerrados) contam só esses.")
AJUDA_DA_ORIGEM = ("De onde o valor vem hoje (coluna do arquivo) ou de onde o programa pode buscá-lo. Em \"o que fazer\" está o próximo passo "
                   "para o que ainda falta.")


def _porcentagem(valor):
    return "—" if valor is None else f"{round(valor * 100)}%"


def _barra(valor):
    if valor is None:
        return ""
    return f"<progress value='{round(valor * 100)}' max='100' aria-label='{round(valor * 100)}% preenchido'></progress>"


def _tabela_do_grupo(grupo):
    linhas = []
    for c in grupo["campos"]:
        if not c["total"] and not c["preenchidos"]:
            continue
        faltam = c["total"] and c["preenchidos"] < c["total"]
        nota = " <span class='dica'>(opcional)</span>" if c["opcional"] else ""
        confirmar = (f"<br><span class='dica'>{c['a_confirmar']} a confirmar (deduzido pelo programa)</span>"
                     if c["a_confirmar"] else "")
        como = _e(c["completar_por"] or "") if faltam else ""
        linhas.append(
            f"<tr><td>{_e(c['rotulo'])}{nota}</td><td>{c['preenchidos']} de {c['total']}</td>"
            f"<td>{_barra(c['percentual'])} {_porcentagem(c['percentual'])}</td>"
            f"<td>{_e(c['origem'])}{confirmar}</td><td>{como}</td></tr>")
    if not linhas:
        return ""
    return ("<table class='t'><tr><th>Campo</th><th>Preenchidos</th><th>%</th><th>De onde vem</th><th>Para o que falta</th></tr>"
            + "".join(linhas) + "</table>")


def quadro(fonte, mapeamento=None, colunas_sem_destino=None, aberto=True, incluir_sem_destino=True):
    """HTML do quadro. `fonte`: fichas v2 ou RelatorioLido (ver `lacunas.lacunas`). Em falha, devolve um aviso curto."""
    try:
        import lacunas
        lac = lacunas.lacunas(fonte, mapeamento=mapeamento, colunas_sem_destino=colunas_sem_destino)
    except Exception as erro:  # noqa: BLE001 - o quadro é informativo: nunca derruba a tela
        return (f"<div class='caixa'><h2>O que falta para a transição</h2><p class='dica'>Não consegui montar este quadro "
                f"({_e(type(erro).__name__)}). O resto da tela segue valendo.</p></div>")
    return html_do_quadro(lac, aberto=aberto, incluir_sem_destino=incluir_sem_destino)


def html_do_quadro(lac, aberto=True, incluir_sem_destino=True):
    h = ["<div class='caixa' id='o-que-falta'><h2>O que falta para a transição" + ajuda(AJUDA_DO_QUADRO) + "</h2>"]
    r = lac["resumo"]
    if not lac["total_processos"]:
        h.append("<p class='dica'>Nenhum processo lido: não há o que comparar.</p></div>")
        return "".join(h)
    h.append(f"<p><b>{lac['total_processos']} processo(s)</b> ({lac['ativos']} ativo(s), {lac['encerrados']} encerrado(s)). "
             f"Dos campos que os modelos novos usam, <b>{_porcentagem(r['percentual'])}</b> já estão preenchidos: "
             f"{r['campos_completos']} campo(s) completo(s), {r['campos_com_falta']} incompleto(s) e {r['campos_vazios']} vazio(s)."
             + (f" {r['a_confirmar']} valor(es) foram deduzidos pelo programa e esperam a sua conferência." if r["a_confirmar"] else "")
             + "</p>")
    if lac["o_que_falta"]:
        h.append("<h3>O que fazer" + ajuda("A lista do que falta, em ordem: primeiro o que o programa resolve sozinho ao coletar, depois o "
                                           "que ele deduz, por último o que só você pode informar.") + "</h3><ul>"
                 + "".join(f"<li>{_e(m)}</li>" for m in lac["o_que_falta"]) + "</ul>")
    else:
        h.append("<p>Nada de essencial falta: o arquivo traz tudo o que os modelos novos usam.</p>")
    for g in lac["grupos"]:
        tabela = _tabela_do_grupo(g)
        if not tabela:
            continue
        resumo_grupo = (f"{_e(g['rotulo'])} · {_porcentagem(g['percentual'])}"
                        + (f" ({g['preenchidos']} de {g['total']})" if g["total"] else ""))
        h.append(f"<details {'open' if aberto else ''}><summary><b>{resumo_grupo}</b></summary>{tabela}"
                 + ("<ul class='dica'>" + "".join(f"<li>{_e(m)}</li>" for m in g["o_que_falta"]) + "</ul>" if g["o_que_falta"] else "")
                 + "</details>")
    if incluir_sem_destino:
        sem = lac["colunas_sem_destino"]
        h.append(f"<h3>Colunas do seu arquivo que ainda não têm destino ({len(sem)})"
                 + ajuda("Colunas que o programa não soube ligar a nenhum campo. Nada se perde: elas vão para a aba \"Campos não migrados\" da "
                         "planilha. Se alguma é importante, escolha o campo certo na tela de mapeamento.") + "</h3>")
        if sem:
            h.append("<table class='t'><tr><th>Coluna</th><th>Exemplos</th></tr>"
                     + "".join(f"<tr><td>{_e(c['coluna'])}</td><td class='dica'>{_e(' | '.join(map(str, c['amostra'])))}</td></tr>" for c in sem)
                     + "</table>")
        else:
            h.append("<p class='dica'>Todas as colunas do arquivo têm destino.</p>")
    h.append("</div>")
    return "".join(h)
