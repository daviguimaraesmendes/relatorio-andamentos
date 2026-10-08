"""Diagnóstico ANONIMIZADO de uma rodada de coleta: lê (só lê) a pasta data/ de um relatório e escreve contagens.

    python diagnostico_rodada.py --projeto <slug> [--saida arquivo.md]

Lê logs/*.log, fila.json, estado_coleta.json, eventos.json, fluxo.json, diagnosticos/ (só os NOMES dos arquivos) e a
carteira. Não altera nada, não usa rede e não imprime número de processo, nome de parte ou texto de autos: números CNJ
viram "<proc>", dígitos viram "#", sequências de MAIÚSCULAS com 2 palavras ou mais viram "<NOME>". Mesmo assim, LEIA o
resultado antes de mostrá-lo a alguém: a máscara é heurística.

O que responde (as perguntas da análise da primeira rodada real):
  1. totais (processos, físicos, eletrônicos, coletados, manuais, erros) e taxa de sucesso só sobre os eletrônicos;
  2. erros por tipo e por tribunal;
  3. captchas pedidos por TRT e em que momento (primeiro processo do TRT, ao trocar de TRT ou depois);
  4. login do jus.br: falhas, mensagens e passo (o texto vem dos logs, sem dado pessoal);
  5. tempo por processo (da fila) e por etapa (linhas "tempo:" que o beta 3 passou a gravar);
  6. graus lidos (1º, 2º) e processos com indício de recurso sem o 2º grau lido;
  7. andamentos sem tradução em movimentos.json (só o texto genérico, mascarado);
  8. clientes e avisos do ciclo (ambiguidades da migração).
"""
import collections
import os
import re
import statistics
import sys
from pathlib import Path

if "--projeto" in sys.argv:  # antes de importar comum: define o relatório
    os.environ["RELATORIO_PROJETO"] = sys.argv[sys.argv.index("--projeto") + 1]

import comum  # noqa: E402

CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.(\d)\.(\d{2})\.\d{4}")
NOME_EM_MAIUSCULAS = re.compile(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}(?:\s+(?:(?:DE|DA|DO|DAS|DOS|E)\s+)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,})+\b")
INDICIO_RECURSO = re.compile(r"remessa|remetid|recurso ordin|distribu[ií]d\w*.*(relator|turma|gabinete)|ac[oó]rd[aã]o", re.I)


def mascarar(texto, limite=140):
    """Tira do texto o que identifica processo, parte ou valor."""
    texto = CNJ.sub("<proc>", str(texto))
    texto = NOME_EM_MAIUSCULAS.sub("<NOME>", texto)
    texto = re.sub(r"R\$\s*[\d.,]+", "R$ #", texto)
    texto = re.sub(r"(?<![\w#])/(?:[\w.-]+/)*[\w.-]+", "<caminho>", texto)       # caminhos de pasta (não mexe em datas)
    texto = re.sub(r"\d", "#", texto)
    return " ".join(texto.split())[:limite]


def tribunal_de(texto):
    """'jus.br' ou 'TRT 7' conforme o número CNJ que aparece no texto (None se não houver)."""
    m = CNJ.search(texto or "")
    if not m:
        return None
    return f"TRT {int(m.group(2))}" if m.group(1) == "5" else "jus.br"


def _pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "-"


def _tabela(linhas, cabecalho):
    saida = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    saida += ["| " + " | ".join(str(c) for c in linha) + " |" for linha in linhas]
    return "\n".join(saida)


# ---------------------------------------------------------------------------------------------- leitura

def ler_logs(pasta):
    """Percorre os logs em ordem e junta as contagens. Devolve um dicionário com os achados."""
    r = {"captcha_por_trt": collections.Counter(), "captcha_momento": collections.Counter(), "falhas_por_tipo": collections.Counter(),
         "login": collections.Counter(), "login_mensagens": collections.Counter(), "tempos": collections.defaultdict(list),
         "graus_lidos": collections.Counter(), "graus_nao_lidos": 0, "arquivos": 0, "pje_office": collections.Counter()}
    for arq in sorted(Path(pasta).glob("*.log")):
        r["arquivos"] += 1
        atual, bloco_n, ultimo = None, 0, None      # tribunal do momento, processos vistos seguidos no mesmo tribunal
        for linha in arq.read_text(encoding="utf-8", errors="replace").splitlines():
            m = CNJ.search(linha)
            trib = tribunal_de(linha)
            if m and trib:
                if trib != atual:
                    atual, bloco_n, ultimo = trib, 1, m.group(0)
                elif m.group(0) != ultimo:
                    bloco_n, ultimo = bloco_n + 1, m.group(0)
            if "CAPTCHA na consulta do TRT" in linha:
                numero = re.search(r"TRT (\d+)", linha)
                dono = f"TRT {numero.group(1)}" if numero else (atual or "TRT ?")
                r["captcha_por_trt"][dono] += 1
                r["captcha_momento"]["no 1º processo do bloco do TRT (início ou troca de TRT)" if bloco_n <= 1
                                     else "do 2º processo do bloco em diante"] += 1
            if re.match(r"\s*(falhou|Login automático falhou|Login automático não concluiu|Login no jus\.br não concluído)", linha):
                if linha.strip().startswith("falhou"):
                    r["falhas_por_tipo"][mascarar(linha.split("falhou:", 1)[-1], 90) + f" [{atual or '?'}]"] += 1
                else:
                    r["login"]["falhas"] += 1
                    r["login_mensagens"][mascarar(linha, 160)] += 1
            if "Termine o login no jus.br" in linha:
                r["login"]["pediu_ajuda_manual"] += 1
            if "Login concluído" in linha:
                r["login"]["concluidos"] += 1
            if "diálogo do PJe Office não apareceu" in linha:
                r["pje_office"]["dialogo_nao_apareceu"] += 1
            if "Aguardando o diálogo do PJe Office" in linha:
                r["pje_office"]["aguardou_dialogo"] += 1
            m = re.search(r"tempo:\s*(\w+)\s+([\d.,]+)\s*s", linha)
            if m:
                r["tempos"][m.group(1)].append(float(m.group(2).replace(",", ".")))
            m = re.search(r"tramitação:\s*(\d)º grau", linha)
            if m:
                r["graus_lidos"][m.group(1)] += 1
            if "2º grau NÃO lido" in linha or "NÃO lidos" in linha:
                r["graus_nao_lidos"] += 1
    return r


def ler_fila(data):
    fila = comum.load_json(Path(data) / "fila.json", None) or {}
    itens = list((fila.get("itens") or {}).values())
    c = collections.Counter()
    erros = collections.Counter()
    duracoes = collections.defaultdict(list)
    for i in itens:
        trib = i.get("tribunal") or "?"
        grupo = "TRT" if str(trib).upper().startswith("TRT") else "jus.br (demais)"
        c[i["estado"]] += 1
        codigo = (i.get("erro") or {}).get("codigo")
        if codigo:
            erros[(codigo, trib)] += 1
        if i["estado"] == "coletado" and i.get("duracao_s") is not None:
            duracoes[grupo].append(float(i["duracao_s"]))
            duracoes[str(trib)].append(float(i["duracao_s"]))
    return itens, c, erros, duracoes


def sem_traducao(data):
    textos = collections.Counter()
    for ev in comum.load_json(Path(data) / "eventos.json", []):
        if ev.get("tipo_evento") == "movimento" and any("sem tradução" in a for a in ev.get("alertas") or []):
            textos[mascarar(ev.get("titulo", ""), 100)] += 1
    return textos


def graus_do_estado(data, eventos):
    estado = comum.load_json(Path(data) / "estado_coleta.json", {})
    lidos = collections.Counter()
    segundo = set()
    for numero, reg in estado.items():
        trt = reg.get("trt") or {}
        for grau in trt:
            lidos[f"TRT: {grau}º grau"] += 1
        if "2" in trt:
            segundo.add(numero)
        if len(reg.get("tramitacoes") or {}) > 1:
            lidos["jus.br: mais de uma tramitação"] += 1
    com_indicio = {ev["numero"] for ev in eventos if ev.get("tipo_evento") == "movimento" and INDICIO_RECURSO.search(ev.get("titulo", ""))
                   and tribunal_de(ev.get("numero", "")) and tribunal_de(ev["numero"]).startswith("TRT")}
    return lidos, len(com_indicio), len(com_indicio - segundo)


# ---------------------------------------------------------------------------------------------- relatório

def montar():
    data = Path(comum.DATA)
    itens, c, erros, duracoes = ler_fila(data)
    logs = ler_logs(data / "logs")
    eventos = comum.load_json(data / "eventos.json", [])
    out = ["# Diagnóstico da rodada (anonimizado)\n\nGerado por `diagnostico_rodada.py` (o nome do relatório não é impresso). "
           "Nenhum número de processo, parte ou texto de autos. Releia antes de compartilhar.\n"]

    # 1. totais
    total = len(itens)
    fisicos = sum(1 for i in itens if (i.get("erro") or {}).get("codigo") == "fisico")
    nao_enc = sum(1 for i in itens if (i.get("erro") or {}).get("codigo") == "nao_encontrado")
    manual = c["manual"] - fisicos
    eletronicos = c["coletado"] + manual + sum(1 for i in itens if i["estado"] == "erro" and not i.get("proxima_tentativa"))
    out.append("## 1. Totais\n")
    out.append(_tabela([("Processos na fila", total), ("Coletados", c["coletado"]), ("Para conferir à mão (manual)", manual),
                        ("Com erro (ainda tentando)", c["erro"]), ("Pendentes", c["pendente"]), ("Físicos marcados (beta 3)", fisicos),
                        ("'Não encontrado' (nas versões anteriores, inclui os físicos)", nao_enc)], ("Item", "Quantidade")))
    base = eletronicos - (nao_enc if not fisicos else 0)
    out.append(f"\nTaxa de sucesso só sobre eletrônicos: {c['coletado']} de {base} ({_pct(c['coletado'], base)})"
               + ("" if fisicos else "; sem a marca de físico, os 'não encontrado' foram tirados do denominador (hipótese: são os físicos)")
               + ".\n")

    # 2. erros
    out.append("## 2. Erros por tipo e por tribunal\n")
    out.append(_tabela([(k[0], k[1], n) for k, n in sorted(erros.items(), key=lambda x: -x[1])] or [("-", "-", 0)],
                       ("Tipo", "Tribunal", "Processos")))
    if logs["falhas_por_tipo"]:
        out.append("\nMensagens de falha nos logs (mascaradas):\n")
        out.append(_tabela([(m, n) for m, n in logs["falhas_por_tipo"].most_common(25)], ("Mensagem [tribunal]", "Vezes")))
    out.append("")

    # 3. captchas
    out.append("## 3. Captchas do TRT\n")
    if logs["captcha_por_trt"]:
        out.append(_tabela(sorted(logs["captcha_por_trt"].items()), ("TRT", "Captchas pedidos")))
        out.append("\nMomento: " + "; ".join(f"{k}: {v}" for k, v in logs["captcha_momento"].items()) + ".\n")
    else:
        out.append("Nenhum captcha registrado nos logs lidos.\n")
    por_trt = collections.Counter(i["tribunal"] for i in itens if str(i.get("tribunal", "")).upper().startswith("TRT"))
    if por_trt:
        out.append("Processos de TRT na fila: " + ", ".join(f"{t}: {n}" for t, n in sorted(por_trt.items())) + ". "
                   "Compare com os captchas acima: perto de um captcha por processo indica que a consulta é recarregada a cada processo.\n")

    # 4. login
    out.append("## 4. Login do jus.br\n")
    out.append(_tabela([(k, v) for k, v in logs["login"].items()] or [("sem registros", 0)], ("Evento", "Vezes")))
    if logs["pje_office"]:
        out.append("\nPJe Office: " + "; ".join(f"{k}: {v}" for k, v in logs["pje_office"].items()) + ".")
    if logs["login_mensagens"]:
        out.append("\nMensagens (mascaradas):\n")
        out.append(_tabela(logs["login_mensagens"].most_common(15), ("Mensagem", "Vezes")))
    diag = sorted(p.name for p in (data / "diagnosticos").glob("login_*")) if (data / "diagnosticos").exists() else []
    out.append(f"\nArquivos de diagnóstico de login em diagnosticos/: {len(diag)} (tela, texto e motivo; abrir os `.json` para ver o passo que falhou).\n")

    # 5. tempo
    out.append("## 5. Tempo\n")
    linhas = []
    for grupo, valores in sorted(duracoes.items()):
        if valores:
            linhas.append((grupo, len(valores), f"{statistics.mean(valores):.0f} s", f"{statistics.median(valores):.0f} s", f"{max(valores):.0f} s"))
    out.append(_tabela(linhas or [("sem medições", 0, "-", "-", "-")], ("Grupo (processos coletados)", "n", "média", "mediana", "máximo")))
    if logs["tempos"]:
        out.append("\nPor etapa (linhas `tempo:` dos logs do beta 3):\n")
        out.append(_tabela([(e, len(v), f"{statistics.mean(v):.1f} s") for e, v in sorted(logs["tempos"].items())], ("Etapa", "n", "média")))
    else:
        out.append("\nPor etapa: as versões anteriores ao beta 3 não gravavam o tempo por etapa; o beta 3 grava linhas `tempo:` a partir da próxima rodada.")
    out.append("")

    # 6. graus
    lidos, com_indicio, sem_segundo = graus_do_estado(data, eventos)
    out.append("## 6. Graus (1º, 2º, TST)\n")
    out.append(_tabela(sorted(lidos.items()) or [("sem dados", 0)], ("Leitura registrada", "Processos")))
    out.append(f"\nProcessos de TRT com andamento que indica recurso: {com_indicio}; destes, sem o 2º grau lido: {sem_segundo}"
               " (candidatos a falha silenciosa da tentativa do 2º grau, que antes do beta 3 engolia a exceção).\n")
    out.append(f"Avisos `2º grau NÃO lido` nos logs (beta 3): {logs['graus_nao_lidos']}. O TST nunca foi consultado antes do beta 3.\n")

    # 7. sem tradução
    out.append("## 7. Andamentos sem tradução em movimentos.json\n")
    st = sem_traducao(data)
    out.append(_tabela(st.most_common(40) or [("nenhum", 0)], ("Texto (mascarado)", "Vezes")) + "\n")

    # 8. clientes e avisos
    out.append("## 8. Clientes e avisos do ciclo\n")
    carteira = comum.load_json(comum.CARTEIRA_FILE, [])
    sem_cliente = sum(1 for p in carteira if not (p.get("cliente") or (p.get("campos", {}).get("cliente") or {}).get("valor")))
    out.append(f"Processos na carteira: {len(carteira)}; sem cliente informado: {sem_cliente}.\n")
    fluxo = comum.load_json(data / "fluxo.json", {})
    avisos = collections.Counter(a.get("codigo") for a in (fluxo.get("ciclo") or {}).get("avisos", []))
    out.append(_tabela(avisos.most_common() or [("nenhum aviso", 0)], ("Código do aviso", "Vezes")) + "\n")
    return "\n".join(out)


def main():
    texto = montar()
    if "--saida" in sys.argv:
        Path(sys.argv[sys.argv.index("--saida") + 1]).write_text(texto, encoding="utf-8")
        print("Diagnóstico gravado.")
    else:
        print(texto)


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)
    main()
