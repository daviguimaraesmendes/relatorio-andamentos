"""Relatório mensal em planilha: parte da planilha do mês anterior (o modelo
que o escritório já usa) e acrescenta, na coluna "Andamentos" da aba
"Processos", o que foi aprovado na revisão, no mesmo estilo:

    "... Em 01/10/2026, o juiz proferiu decisão, determinando ... "
    "... Até 03/10/2026 sem andamentos."   (processo sem novidade aprovada)

A gravação é cirúrgica: só as células "Andamentos" mudam; gráficos, tabelas
dinâmicas, imagens, fórmulas e as outras abas são copiados byte a byte.
(Bibliotecas comuns de Excel apagam gráficos e tabelas dinâmicas ao salvar.)

Este módulo é o "módulo de texto" do relatório em planilha (Fase 1, mantido na Fase 2):
as REGRAS do texto de andamentos (só acrescenta, fecho "Até DD/MM/AAAA sem atualizações.",
não repetir andamento que já consta) e o fluxo simples da Fase 1 (`gerar`, usado pela tela
"Planilha do mês"). A escrita de células, linhas novas, colunas e o modelo padrão (Fase 2)
ficam em `escritores/xlsx_b.py`, que usa `montar_texto` daqui. A coluna "Andamentos" e a
de número são achadas pelo cabeçalho; planilhas sem cabeçalho caem nas colunas A e P da
Fase 1.

Uso:
    python planilha.py MODELO.xlsx DESTINO.xlsx [--sem-linha-vazia]
"""
import datetime
import os
import re
import sys
import unicodedata
from pathlib import Path

from comum import carteira, eventos, salvar_eventos
from escritores import xlsx_b

ABA = "Processos"
COL_NUMERO, COL_ANDAMENTOS = "A", "P"      # planilhas da Fase 1 sem cabeçalho reconhecível
CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
FECHO = re.compile(r"\s*Até\s+\d{2}/\d{2}/\d{4},?\s+sem\s+(atualizações|atualização|andamentos?)\.?\s*$", re.I)
_DATA = re.compile(r"\d{2}/\d{2}/\d{4}")


def frase_planilha(ev):
    """'Em 01/10/2026, o juiz proferiu decisão, dizendo que...' (estilo do relatório mensal)."""
    import relatorio
    frase, extras = relatorio.linha(ev)
    data = relatorio._data_evento(ev).strftime("%d/%m/%Y")
    primeira = frase.split()[0]
    corpo = frase if (len(primeira) > 1 and primeira.isupper()) else frase[0].lower() + frase[1:]  # mantém siglas
    if ev.get("grau") and ev["grau"] != "1º grau":
        corpo = f"no {ev['grau']}, {corpo}"
    texto = f"Em {data} {corpo}"  # estilo da planilha: sem vírgula após a data
    for x in extras:
        texto += f" {x}."
    return texto


# ---------------------------------------------------------------- regras do texto de andamentos

def chave_texto(texto):
    """Texto para comparar: sem acento, sem caixa, sem pontuação (a barra das datas fica)."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9/]+", " ", t).strip()


def _palavras(texto):
    return {p for p in chave_texto(texto).split() if len(p) >= 4 and not _DATA.fullmatch(p)}


def ja_consta(texto, frase, limiar=0.75):
    """O andamento `frase` já está no `texto`?

    Vale se a frase aparece igual (sem contar acento, caixa e pontuação) ou se há, no texto, um trecho
    que começa na MESMA data e repete pelo menos `limiar` (0 a 1) das palavras da frase: é o caso de
    alguém que reescreveu a frase à mão. Heurística, documentada: dois andamentos diferentes do mesmo
    dia com quase as mesmas palavras podem ser confundidos (por isso o aviso `andamento_ja_presente`
    sempre lista o que foi tratado como já presente)."""
    nf = chave_texto(frase)
    if not nf:
        return False
    if nf in chave_texto(texto):
        return True
    palavras = _palavras(frase)
    if not palavras:
        return False
    for data in set(_DATA.findall(frase)):
        for m in re.finditer(re.escape(data), texto or ""):
            trecho = texto[m.start():m.start() + 800]
            proxima = _DATA.search(trecho, len(data))
            if proxima:
                trecho = trecho[:proxima.start()]
            if len(palavras & _palavras(trecho)) / len(palavras) >= limiar:
                return True
    return False


def montar_texto(atual, evs, data_fecho, *, deduplicar=True, fecho_apos_novidade=False, limiar=0.75):
    """Novo texto da coluna Andamentos: o que já estava (menos o fecho antigo) + os andamentos aprovados;
    sem andamento no ciclo, o fecho 'Até DD/MM/AAAA sem atualizações.' renovado com `data_fecho`
    (texto DD/MM/AAAA). Só acrescenta: nunca reescreve o que a pessoa escreveu.

    Volta {"texto", "gravados" (frases acrescentadas), "ignorados" [(evento, frase)] (já constavam; só com
    `deduplicar`), "fecho_antigo" (texto do fecho retirado ou None), "teve_novidade" (há evento aprovado,
    mesmo que já presente: é isso que impede o fecho e torna gravar duas vezes idempotente)}."""
    import relatorio
    atual = (atual or "").rstrip()
    fecho = FECHO.search(atual)
    expressao = fecho.group(1).lower() if fecho else "atualizações"
    corpo = atual[:fecho.start()].rstrip() if fecho else atual
    novas, ignorados = [], []
    for ev in sorted(evs, key=relatorio.ordem):
        frase = frase_planilha(ev)
        # contra o que já estava: igual ou parecido; contra o que entrou neste ciclo: só igual
        if deduplicar and (ja_consta(corpo, frase, limiar) or chave_texto(frase) in chave_texto(" ".join(novas))):
            ignorados.append((ev, frase))
        else:
            novas.append(frase)
    com_fecho = (not evs) or (fecho_apos_novidade and bool(novas))
    texto = " ".join(x for x in (corpo, " ".join(novas)) if x)
    if com_fecho:
        texto = f"{texto} Até {data_fecho} sem {expressao}.".strip()
    return {"texto": texto, "gravados": novas, "ignorados": ignorados,
            "fecho_antigo": fecho.group(0).strip() if fecho else None, "teve_novidade": bool(evs)}


# ---------------------------------------------------------------- fluxo da Fase 1

def _colunas(ed):
    """(coluna do número, coluna de Andamentos): pelo cabeçalho; sem cabeçalho, A e P como na Fase 1."""
    mapa, _ambiguos = xlsx_b.mapear_cabecalhos(ed.cabecalhos)
    num = mapa.get("numero") or xlsx_b.col_indice(COL_NUMERO)
    andamentos = mapa.get("andamentos") or xlsx_b.col_indice(COL_ANDAMENTOS)
    return num, andamentos


def _abrir(caminho, **kw):
    return xlsx_b.Edicao(caminho, ABA, linha_cabecalho=1, exigir_cabecalho=False, **kw)


def _linhas(ed, col_numero):
    linhas = {}
    for n in ed.folha.numeros():
        achado = CNJ.search(str(ed.valor(n, col_numero) or ""))
        if achado:
            linhas[achado.group(0)] = n
    return linhas


def linhas_da_aba(caminho_xlsx):
    """{numero: linha} dos processos na aba Processos."""
    ed = _abrir(caminho_xlsx)
    return _linhas(ed, _colunas(ed)[0])


def gerar(modelo, destino, sem_novidade=True, hoje=None):
    """Volta (processos atualizados, processos sem linha na planilha)."""
    import relatorio
    hoje = hoje or datetime.date.today()
    lista = eventos()
    aprovados = [e for e in lista if e["status"] == "aprovado"]
    acompanhados = set(carteira())
    # só texto em uma coluna que nenhuma fórmula lê: nada de recálculo nem de mexer no cache (como na Fase 1)
    ed = _abrir(modelo, recalcular=False)
    col_numero, col_andamentos = _colunas(ed)
    linhas = _linhas(ed, col_numero)

    por_processo = {}
    for ev in aprovados:
        por_processo.setdefault(ev["numero"], []).append(ev)
    fora = sorted(n for n in por_processo if n not in linhas)
    atualizados, celulas = [], {}
    for numero, linha in sorted(linhas.items(), key=lambda x: -x[1]):
        evs = sorted(por_processo.get(numero, []), key=relatorio.ordem)
        if not evs and not (sem_novidade and numero in acompanhados):
            continue
        atual = ed.valor(linha, col_andamentos) or ""
        # o fecho "Até 29/09/2026 sem atualizações." do relatório anterior sai:
        # ou vira andamento novo, ou é renovado com a data de hoje
        celulas[(linha, col_andamentos)] = montar_texto(str(atual), evs, f"{hoje:%d/%m/%Y}", deduplicar=False)["texto"]
        atualizados.append(numero)
    ed.escrever_celulas(celulas)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.resolve() == Path(modelo).resolve():
        # Fase 1: gerar de novo "em cima" da planilha de hoje (a referência é a própria saída anterior)
        provisorio = destino.with_name(destino.name + ".novo")
        ed.salvar(provisorio)
        os.replace(provisorio, destino)
    else:
        ed.salvar(destino)

    agora = datetime.datetime.now().isoformat(timespec="seconds")
    for ev in aprovados:
        if ev["numero"] in linhas:
            ev.update(status="relatado", relatorio=str(destino), relatado_em=agora)
    salvar_eventos(lista)
    return sorted(atualizados), fora


if __name__ == "__main__":
    a = sys.argv[1:]
    feitos, fora = gerar(a[0], a[1], sem_novidade="--sem-linha-vazia" not in a)
    print(f"{len(feitos)} processo(s) atualizado(s) em {a[1]}")
    if fora:
        print("Aprovados sem linha na planilha (continuam aprovados):", *fora, sep="\n  ")
