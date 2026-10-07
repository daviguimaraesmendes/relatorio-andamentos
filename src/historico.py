"""Retrato mensal da carteira: a série histórica que alimenta "ao longo do tempo" nos dashboards (WS-11).

A cada atualização concluída grava-se um retrato (CONTRATOS §9) em
`projetos/<slug>/data/historico/AAAA-MM-DD.json`; na migração, vários relatórios antigos (um por mês) viram a
série de uma vez.

    gravar_retrato(fichas, data_base, destino=None) -> Path     # grava AAAA-MM-DD.json
    carregar(projeto=None) -> Serie                              # retratos em ordem de data (lista + .avisos)
    reconstruir(relatorios_lidos) -> Serie                       # de vários RelatorioLido (leitores/)
    retrato(fichas, data_base) -> dict                           # o dict, sem gravar

Formato (contrato §9 + dois campos ADITIVOS, descritos em docs/fase2/RFC-retrato-cliente.md):

    {"versao": 1, "data_base": "AAAA-MM-DD",
     "totais": {"processos", "ativos", "encerrados", "valor_causa", "valor_estimado", "valor_economizado",
                "valor_economizado_confiavel"},
     "por_processo": [{"numero", "cliente", "situacao", "momento_atual", "valor_causa", "valor_estimado",
                       "resultado", "probabilidade"}]}

Regras dos totais (dinheiro em texto "1234.56"):
  - processos/ativos/encerrados: uma ficha = um processo (vinculados não contam à parte); ativo/encerrado vem de
    qualidade.encerrado (ativo, situação ou momento). Linha-marcador e número repetido não entram;
  - valor_causa, valor_estimado, valor_economizado: soma do que está LANÇADO (o mesmo que um SUM da planilha);
    processo sem valor lançado não entra na soma;
  - valor_economizado_confiavel: o indicador recomendado (quadros.py): só encerrado, sem ressalva (acordo sem valor,
    acordo de terceiro, exclusão da lide, cliente autor) e com desfecho pecuniário definido.
  - campo vazio vira "" no `por_processo`.

REPRODUTÍVEL: o mesmo estado gera o MESMO arquivo, byte a byte (processos ordenados por número, nenhuma hora
gravada, JSON com a mesma formatação do resto do projeto), então regravar não cria diferença.
"""
import re
from decimal import Decimal
from pathlib import Path

import comum
import ficha
import qualidade

VERSAO = 1
_ARQUIVO = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


class Serie(list):
    """Lista de retratos em ordem de data-base, com `.avisos` (Aviso do contrato dos leitores)."""
    avisos = None

    def __init__(self, itens=(), avisos=None):
        super().__init__(itens)
        self.avisos = list(avisos or [])


def _aviso(nivel, codigo, onde, mensagem):
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": []}


def pasta(projeto=None):
    """Pasta dos retratos. `projeto`: None (relatório ativo), slug de projeto, pasta do projeto (tem projeto.json),
    pasta `historico` ou qualquer pasta que contenha os .json."""
    if projeto is None:
        return Path(comum.DATA) / "historico"
    p = Path(projeto)
    if isinstance(projeto, str) and not p.is_absolute() and (comum.PROJETOS_DIR / projeto).is_dir():
        p = comum.PROJETOS_DIR / projeto
    if (p / "projeto.json").exists():
        return p / "data" / "historico"
    if p.name != "historico" and (p / "data" / "historico").is_dir():
        return p / "data" / "historico"
    return p


def _dinheiro_texto(valor):
    return f"{valor:.2f}"


def _fichas_do_retrato(fichas):
    """Fichas v2 sem linha-marcador e sem número repetido (a primeira vale), ordenadas pelo número."""
    vistas = {}
    for f in (ficha.de_carteira_v1(x) for x in (fichas or [])):
        if not qualidade.e_marcador(f):
            vistas.setdefault(f.get("numero", ""), f)
    return [vistas[n] for n in sorted(vistas)]


def _texto(valor):
    return "" if valor in (None, "") else str(valor)


def retrato(fichas, data_base):
    """Dict do retrato mensal (ver o cabeçalho). `data_base` em ISO ou DD/MM/AAAA."""
    base = ficha.parse_data(data_base)
    if base is None:
        raise ValueError(f"Data-base inválida: {data_base!r}")
    por_processo, soma = [], {"valor_causa": Decimal(0), "valor_estimado": Decimal(0), "valor_economizado": Decimal(0),
                              "confiavel": Decimal(0)}
    ativos = encerrados = 0
    for f in _fichas_do_retrato(fichas):
        acabou = qualidade.encerrado(f)
        ativos, encerrados = ativos + (not acabou), encerrados + acabou
        situacao = ficha.obter(f, "situacao") or ("Encerrado" if acabou else "Ativo")
        por_processo.append({"numero": f["numero"], "cliente": _texto(ficha.obter(f, "cliente")), "situacao": situacao,
                             "momento_atual": _texto(ficha.obter(f, "momento_atual")),
                             "valor_causa": _texto(ficha.obter(f, "valor_causa")),
                             "valor_estimado": _texto(ficha.obter(f, "valor_estimado")),
                             "resultado": _texto(ficha.obter(f, "resultado")),
                             "probabilidade": _texto(ficha.obter(f, "probabilidade"))})
        for campo, chave in (("valor_causa", "valor_causa"), ("valor_estimado", "valor_estimado"),
                             ("valor_economizado", "valor_economizado")):
            valor = ficha.dinheiro(ficha.obter(f, campo))
            if valor is not None:
                soma[chave] += valor
        economizado = ficha.dinheiro(ficha.obter(f, "valor_economizado"))
        if (economizado is not None and acabou and not qualidade.ressalvas_de_economia(f)
                and qualidade.desfecho_pecuniario_definido(f)):
            soma["confiavel"] += economizado
    return {"versao": VERSAO, "data_base": base,
            "totais": {"processos": len(por_processo), "ativos": ativos, "encerrados": encerrados,
                       "valor_causa": _dinheiro_texto(soma["valor_causa"]),
                       "valor_estimado": _dinheiro_texto(soma["valor_estimado"]),
                       "valor_economizado": _dinheiro_texto(soma["valor_economizado"]),
                       "valor_economizado_confiavel": _dinheiro_texto(soma["confiavel"])},
            "por_processo": por_processo}


def gravar_retrato(fichas, data_base, destino=None):
    """Grava o retrato e devolve o caminho do arquivo. `destino`: arquivo .json, pasta (grava AAAA-MM-DD.json
    dentro dela), projeto (ver `pasta`) ou None (relatório ativo). Regravar a mesma data substitui o arquivo."""
    dados = retrato(fichas, data_base)
    if destino is not None and str(destino).endswith(".json"):
        arquivo = Path(destino)
    else:
        arquivo = pasta(destino) / f"{dados['data_base']}.json"
    comum.save_json(arquivo, dados)
    return arquivo


def carregar(projeto=None):
    """Retratos da pasta, do mais antigo ao mais novo. Arquivo ilegível ou fora do formato é pulado com aviso."""
    base = pasta(projeto)
    serie, avisos = [], []
    for arquivo in sorted(base.glob("*.json")) if base.is_dir() else []:
        if not _ARQUIVO.match(arquivo.name):
            continue
        try:
            dados = comum.load_json(arquivo, None)
        except ValueError:
            dados = None
        if not (isinstance(dados, dict) and ficha.parse_data(dados.get("data_base")) and isinstance(dados.get("totais"), dict)
                and isinstance(dados.get("por_processo"), list)):
            avisos.append(_aviso("atencao", "retrato_ilegivel", arquivo.name, "Retrato mensal ilegível ou fora do formato: ignorado."))
            continue
        serie.append(dados)
    return Serie(sorted(serie, key=lambda r: r["data_base"]), avisos)


def _ativo_do_lido(f):
    """`ativo` de uma ficha montada de relatório lido: situação ou momento atual dizem; na dúvida, ativo."""
    return not (ficha.obter(f, "situacao") == "Encerrado" or qualidade.momento_ativo(f) is False)


def _ficha_do_lido(proc, cliente_padrao, onde, avisos):
    f = ficha.nova_ficha(proc.get("numero", ""))
    for nome, dado in (proc.get("campos") or {}).items():
        try:
            ficha.definir(f, nome, dado.get("valor"), dado.get("origem") if dado.get("origem") in ficha.PRIORIDADE else "migrado")
        except KeyError:
            avisos.append(_aviso("atencao", "campo_desconhecido", onde, f"Campo {nome!r} não existe na ficha: ignorado ({proc.get('numero')})."))
    if cliente_padrao:
        ficha.definir(f, "cliente", cliente_padrao, "migrado")
    for v in proc.get("vinculados") or []:
        ficha.vincular(f, v.get("numero", ""), v.get("tipo", ""))
    f["ativo"] = _ativo_do_lido(f)
    return f


def reconstruir(relatorios_lidos):
    """Série mensal a partir de vários RelatorioLido: um retrato por data-base. Relatório sem data-base é pulado com
    aviso; vários relatórios da mesma data (um por cliente, por exemplo) são unidos, e número repetido no mês fica
    com o último e gera aviso. Só confere o que o relatório traz: sem valor lançado, o total não inclui o processo."""
    avisos, por_data = [], {}
    for rel in relatorios_lidos or []:
        onde = rel.get("arquivo") or "relatório"
        base = ficha.parse_data(rel.get("data_base"))
        if base is None:
            avisos.append(_aviso("atencao", "retrato_sem_data_base", onde, "O relatório não tem data-base: fora da série histórica."))
            continue
        mes = por_data.setdefault(base, {})
        for proc in rel.get("processos") or []:
            f = _ficha_do_lido(proc, rel.get("cliente"), onde, avisos)
            if f["numero"] in mes:
                avisos.append(_aviso("atencao", "numero_repetido_no_mes", onde,
                                     f"O processo {f['numero']} aparece mais de uma vez em {ficha.data_br(base)}: vale o último lido."))
            mes[f["numero"]] = f
    return Serie([retrato(list(por_data[d].values()), d) for d in sorted(por_data)], avisos)


def evolucao(serie):
    """Totais mês a mês, no formato que os gráficos "ao longo do tempo" usam: [{"data_base", **totais}]."""
    return [{"data_base": r["data_base"], **r["totais"]} for r in serie]
