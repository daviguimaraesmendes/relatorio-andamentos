"""Base de dados sintética dos testes da Fase 2 (sem rede, sem certificado, sem dado de cliente).

    from ficticio import (numero_ficticio, gerar_carteira, gerar_lista_bruta, gerar_historico,
                          criar_projeto_de_teste, projeto_de_teste)

Tudo é gerado em TEMPO DE EXECUÇÃO e é determinístico por `semente`: nenhum número de processo vira
literal no repositório (o `empacotar.sh` recusa). Números seguem o dígito verificador do CNJ e usam
sequenciais a partir de 1234567 (faixa sintética); nomes são claramente fictícios ("Cliente Exemplo 01 Ltda",
"Pessoa Fictícia 0123").

- numero_ficticio(n, ano, j, tr, origem)    número CNJ com DV correto
- gerar_carteira(n, clientes, semente, com_defeitos)   fichas v2 plausíveis, dentro dos vocabulários
- gerar_lista_bruta(destino_dir, fichas, semente)      .txt (e-mail), .csv, .xlsx e .xlsx bagunçado
- gerar_textos_de_andamento / gerar_historico / anexar_linha_de_base  texto corrido coerente com a ficha
- criar_projeto_de_teste / projeto_de_teste            projeto temporário com a carteira gravada
- detectar_defeitos(fichas)                            localiza os defeitos intencionais (referência para o WS-11)
"""
import copy
import datetime
import math
import os
import random
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de qualquer módulo da ferramenta)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import carteira as cart  # noqa: E402
import comum  # noqa: E402
import ficha  # noqa: E402
import simulado  # noqa: E402
import taxonomia  # noqa: E402

TMP = isolamento.TMP
HOJE = simulado.HOJE
SEQ_BASE = 1234567                 # primeiro sequencial sintético
SEQ_LIMITE = SEQ_BASE + 500_000    # tudo que for gerado cai em [SEQ_BASE, SEQ_LIMITE)
_SEQ_VINCULADOS = 200_000          # vinculados usam outra faixa, sem colidir com a carteira (n < 200 mil)
SUFIXOS = ("Ltda", "S.A.", "Comércio Ltda", "Serviços Ltda", "Indústria Ltda")


def numero_ficticio(n=0, ano=2024, j=8, tr=6, origem=1):
    """Número CNJ sintético com dígito verificador correto: sequenciais 1234567 em diante."""
    seq = f"{SEQ_BASE + n:07d}"
    dv = 98 - int(f"{seq}{ano}{j}{tr:02d}{origem:04d}00") % 97
    return f"{seq}-{dv:02d}.{ano}.{j}.{tr:02d}.{origem:04d}"


def dv_confere(numero):
    """Confere o DV com a conta do CNJ, de forma independente de carteira.py."""
    m = cart.CNJ.fullmatch(numero.strip())
    if not m:
        return False
    seq, dv, ano, j, tr, origem = m.groups()
    return int(dv) == 98 - int(f"{seq}{ano}{j}{tr}{origem}00") % 97


def numero_com_dv_errado(numero):
    """Mesmo número com o dígito verificador trocado (erro de digitação típico)."""
    seq, resto = numero.split("-", 1)
    dv, final = resto.split(".", 1)
    return f"{seq}-{(int(dv) + 1) % 98:02d}.{final}" if dv_confere(numero) else numero


def nome_de_cliente(i):
    return f"Cliente Exemplo {i + 1:02d} {SUFIXOS[i % len(SUFIXOS)]}"


# ------------------------------------------------------------------ geografia e vocabulário usados na carteira

MUNICIPIOS_TJ = {"CE": ("Fortaleza", "Sobral"), "SP": ("São Paulo", "Campinas"), "RJ": ("Rio de Janeiro", "Niterói"),
                 "MG": ("Belo Horizonte", "Uberlândia"), "BA": ("Salvador", "Feira de Santana"),
                 "PE": ("Recife", "Caruaru"), "RS": ("Porto Alegre", "Caxias do Sul"), "PR": ("Curitiba", "Londrina"),
                 "SC": ("Florianópolis", "Joinville"), "GO": ("Goiânia", "Anápolis")}
TRTS = {7: ("CE", "Fortaleza"), 1: ("RJ", "Rio de Janeiro"), 2: ("SP", "São Paulo"), 3: ("MG", "Belo Horizonte"),
        4: ("RS", "Porto Alegre"), 5: ("BA", "Salvador"), 6: ("PE", "Recife"), 9: ("PR", "Curitiba"),
        15: ("SP", "Campinas"), 8: ("PA", "Belém")}
TRFS = {1: ("DF", "Brasília"), 2: ("RJ", "Rio de Janeiro"), 3: ("SP", "São Paulo"), 4: ("RS", "Porto Alegre"),
        5: ("PE", "Recife"), 6: ("MG", "Belo Horizonte")}

AREAS = (("Trabalhista", 55), ("Cível", 15), ("Consumidor", 10), ("Tributário", 8), ("Administrativo", 5),
         ("Empresarial", 4), ("Imobiliário", 3))
MATERIAS_TRABALHISTAS = tuple(k for k, (_, classe, _) in taxonomia.MATERIA.items() if classe == "Mérito")
MATERIAS_OUTRAS = {"Cível": ("Dano moral", "Outros"), "Consumidor": ("Dano moral", "Outros"), "Tributário": ("Outros",),
                   "Administrativo": ("Outros",), "Empresarial": ("Outros",), "Imobiliário": ("Outros",)}
CLASSES = {"Trabalhista": "Reclamação Trabalhista", "Cível": "Procedimento Comum Cível", "Consumidor": "Procedimento do Juizado Especial Cível",
           "Tributário": "Execução Fiscal", "Administrativo": "Mandado de Segurança", "Empresarial": "Procedimento Comum Cível",
           "Imobiliário": "Ação de Cobrança"}
ASSUNTOS = {"Trabalhista": ("Verbas rescisórias", "Duração do trabalho", "Reconhecimento de vínculo", "Acidente de trabalho"),
            "Cível": ("Responsabilidade civil", "Contratos", "Cobrança"), "Consumidor": ("Vício do produto", "Cobrança indevida"),
            "Tributário": ("Dívida ativa", "ICMS"), "Administrativo": ("Licitação", "Servidor público"),
            "Empresarial": ("Sociedades", "Recuperação de crédito"), "Imobiliário": ("Locação", "Posse")}

# momento atual dos processos ativos e dos encerrados, com pesos (distribuição de uma carteira de escritório)
MOMENTOS_ATIVOS = {"AGUARDANDO CITAÇÃO": 4, "AGUARDANDO CITAÇÃO DO RÉU": 3, "AGUARDANDO CITAÇÃO POR EDITAL": 1,
                   "AGUARDANDO INTIMAÇÃO DO RÉU": 2, "AGUARDANDO CONTESTAÇÃO": 8, "AGUARDANDO RÉPLICA": 6,
                   "AGUARDANDO AUDIÊNCIA": 10, "AGUARDANDO PROVA PERICIAL": 5, "AGUARDANDO SENTENÇA": 12,
                   "AGUARDANDO JULGAMENTO EM 1º GRAU": 2, "CONCLUSOS PARA DECISÃO": 4,
                   "AGUARDANDO JULGAMENTO DA APELAÇÃO": 9, "AGUARDANDO JULGAMENTO DO RECURSO": 6,
                   "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO": 3, "CUMPRIMENTO DE SENTENÇA": 12,
                   "AGUARDANDO CONVERSÃO EM PENHORA": 3, "AGUARDANDO PAGAMENTO": 4,
                   "AGUARDANDO PARCELAMENTO DAS CUSTAS": 1, "AGUARDANDO MANIFESTAÇÃO DE TERCEIROS": 1,
                   "AGUARDANDO SUBSTITUIÇÃO PROCESSUAL": 1, "AGUARDANDO CITAÇÃO DOS EXECUTADOS": 1, "SUSPENSO": 3}
MOMENTOS_ENCERRADOS = {"TRÂNSITO EM JULGADO": 35, "PROCESSO ARQUIVADO": 30, "ACORDO HOMOLOGADO": 20,
                       "EXTINTO SEM RESOLUÇÃO DE MÉRITO": 15}
_MERITO = ("Procedente", "Parcialmente procedente", "Improcedente")


def _escolher(rng, pesos):
    return rng.choices(list(pesos), list(pesos.values()))[0] if isinstance(pesos, dict) else rng.choices(
        [k for k, _ in pesos], [p for _, p in pesos])[0]


def _resultado_do_momento(momento, rng):
    m = momento
    if m == "ACORDO HOMOLOGADO":
        return "Acordo"
    if m.startswith("EXTINTO"):
        return "Extinto sem resolução de mérito"
    if m == "PROCESSO ARQUIVADO":
        return rng.choices(["Arquivado / desistência", "Improcedente", "Procedente", "Parcialmente procedente",
                            "Incompetência declarada"], [45, 20, 10, 15, 10])[0]
    if m == "TRÂNSITO EM JULGADO":
        return rng.choices(_MERITO, [30, 35, 35])[0]
    if "APELAÇÃO" in m or "RECURSO" in m or "AGRAVO" in m:
        return rng.choices(_MERITO, [35, 45, 20])[0]
    if m in ("CUMPRIMENTO DE SENTENÇA", "AGUARDANDO CONVERSÃO EM PENHORA", "AGUARDANDO PAGAMENTO"):
        return rng.choices(_MERITO[:2], [40, 60])[0]
    return None


def _dinheiro(valor):
    return f"{valor:.2f}"


class Carteira(list):
    """Lista de fichas com `.defeitos`: o que foi estragado de propósito (vazio sem `com_defeitos`)."""
    defeitos = None

    def __init__(self, fichas=(), defeitos=None):
        super().__init__(fichas)
        self.defeitos = defeitos or {}


def _ficha_sintetica(i, semente, clientes_n):
    rng = random.Random(f"{semente}:ficha:{i}")
    ativo = rng.random() < 0.55
    momento = _escolher(rng, MOMENTOS_ATIVOS if ativo else MOMENTOS_ENCERRADOS)
    resultado = _resultado_do_momento(momento, rng)
    sentenciado = resultado is not None
    area = _escolher(rng, AREAS)
    # tribunal e geografia
    if area == "Trabalhista":
        j, tr = 5, rng.choice(list(TRTS))
        uf, municipio = TRTS[tr]
        vara_texto = lambda k: f"{k}ª Vara do Trabalho de {municipio}"
    elif area in ("Tributário", "Administrativo") and rng.random() < 0.5:
        j, tr = 4, rng.choice(list(TRFS))
        uf, municipio = TRFS[tr]
        vara_texto = lambda k: f"{k}ª Vara Federal de {municipio}"
    else:
        uf = rng.choice(list(MUNICIPIOS_TJ))
        j, tr = 8, cart.UFS.index(uf) + 1
        municipio = rng.choice(MUNICIPIOS_TJ[uf])
        vara_texto = (lambda k: f"{k}º Juizado Especial Cível de {municipio}") if area == "Consumidor" else (
            lambda k: f"{k}ª Vara Cível da Comarca de {municipio}")
    k_vara = rng.randint(1, 12)
    # datas: o último andamento e o ajuizamento seguem o roteiro do momento atual
    houve_recurso = ("APELAÇÃO" in momento or "RECURSO" in momento or "AGRAVO" in momento
                     or (sentenciado and momento in ("TRÂNSITO EM JULGADO", "CUMPRIMENTO DE SENTENÇA",
                                                     "AGUARDANDO CONVERSÃO EM PENHORA", "AGUARDANDO PAGAMENTO")
                         and rng.random() < 0.4))
    etapas = simulado.roteiro(momento, houve_recurso)
    k = len(etapas)
    hoje = datetime.date.fromisoformat(HOJE)
    ultimo = hoje - datetime.timedelta(days=rng.randint(2, 120) if ativo else rng.randint(30, 500))
    ajuizamento = ultimo - datetime.timedelta(days=rng.randint(30 * (k - 1), 90 * (k - 1)))
    datas = simulado.planejar_datas(etapas, ajuizamento.isoformat(), ultimo.isoformat())
    citacao = datas[etapas.index("citacao")] if "citacao" in etapas else None
    numero = numero_ficticio(i, ajuizamento.year, j, tr, k_vara)
    f = ficha.nova_ficha(numero)
    f["ativo"] = bool(taxonomia.momento_ativo(momento))
    cliente = nome_de_cliente(i % clientes_n)
    # partes
    pessoa = f"Pessoa Fictícia {rng.randint(1, 9999):04d}"
    empresa = f"Empresa Fictícia {rng.randint(1, 999):03d} Ltda"
    if area == "Trabalhista":
        polo, autores, reus, terceirizado = "passivo", pessoa, cliente, rng.choice(["Sim", "Não", "Não"])
    elif area in ("Tributário", "Administrativo"):
        polo, autores, reus, terceirizado = "ativo", cliente, "Ente Público Exemplo", None
    else:
        polo = rng.choice(["passivo", "passivo", "ativo"])
        contraria = rng.choice([pessoa, empresa])
        autores, reus, terceirizado = (cliente, contraria, None) if polo == "ativo" else (contraria, cliente, None)
    contraria = autores if polo == "passivo" else reus

    def definir(campo, valor, origem=None, evidencia=None):
        origem = origem or rng.choices(["coletado", "migrado"], [7, 3])[0]
        ficha.definir(f, campo, valor, origem, evidencia)

    definir("cliente", cliente, "migrado")
    definir("responsavel", f"Responsável Exemplo {chr(65 + i % 3)}", "migrado")
    if rng.random() < 0.25:
        definir("apelido", f"Caso {i + 1:03d}", "humano")
    if rng.random() < 0.1:
        definir("observacoes", rng.choice(["Aguardando documentos do cliente.", "Prazo interno de revisão.",
                                           "Acompanhar pauta do órgão julgador."]), "humano")
    definir("polo_cliente", polo)
    definir("autores", autores)
    definir("reus", reus)
    definir("parte_contraria", contraria)
    if terceirizado:
        definir("terceirizado", terceirizado)
    definir("vara", vara_texto(k_vara))
    definir("municipio", municipio)
    definir("uf", uf)
    definir("data_ajuizamento", ajuizamento.isoformat())
    definir("data_citacao", citacao)
    definir("classe", CLASSES[area])
    definir("assunto", rng.choice(ASSUNTOS[area]))
    definir("area", area)
    materia = rng.choice(MATERIAS_TRABALHISTAS) if area == "Trabalhista" else rng.choice(MATERIAS_OUTRAS[area])
    definir("materia_principal", materia)
    definir("objeto", f"Pedido relativo a {materia.lower()} e reflexos")
    valor_causa = min(max(round(math.exp(rng.gauss(10.8, 1.1)), -1), 3000.0), 5_000_000.0)
    definir("valor_causa", _dinheiro(valor_causa))
    definir("momento_atual", momento)
    definir("situacao", "Suspenso" if momento == "SUSPENSO" else ("Ativo" if f["ativo"] else "Encerrado"), "derivado")
    categoria = taxonomia.categoria_do_momento(momento)
    fase = {"conhecimento": "Conhecimento", "recurso": "Recurso", "execução": "Execução"}.get(categoria)
    if fase is None:
        fase = "Execução" if etapas[-1] in ("transito", "arquivamento") and "execucao" in etapas else (
            "Recurso" if houve_recurso else "Conhecimento")
    definir("fase", fase, "derivado")
    definir("ultimo_andamento", ultimo.isoformat())
    if sentenciado and momento not in ("ACORDO HOMOLOGADO",) and not momento.startswith("EXTINTO"):
        definir("houve_recurso", "Sim" if houve_recurso else "Não", "derivado")
    # julgamento: ~30% das fichas têm esses campos lançados por humano; nas demais só o resultado, derivado da decisão
    humano = rng.random() < 0.30
    origem_julg = "humano" if humano else None
    valor_acordo = None
    if resultado == "Acordo":
        valor_acordo = round(valor_causa * rng.uniform(0.1, 0.5), 2)
        definir("valor_acordo", _dinheiro(valor_acordo), "humano" if humano else "coletado")
    if resultado:
        definir("resultado", resultado, origem_julg or "derivado")
    if humano:
        arbitrado = None
        if resultado in ("Procedente", "Parcialmente procedente"):
            arbitrado = round(valor_causa * (rng.uniform(0.5, 1.0) if resultado == "Procedente" else rng.uniform(0.2, 0.6)), 2)
            definir("valor_arbitrado", _dinheiro(arbitrado), "humano")
        estimado = (valor_causa if resultado in (None, "Incompetência declarada") else
                    arbitrado if arbitrado else valor_acordo if valor_acordo else 0.0)
        definir("valor_estimado", _dinheiro(estimado), "humano")
        if not f["ativo"]:
            # economia (causa − estimado) só de encerrado, e não do cliente autor nem de incompetência (PLANO 7.2)
            if polo == "passivo" and resultado != "Incompetência declarada":
                definir("valor_economizado", _dinheiro(valor_causa - estimado), "humano")
            definir("taxa_resolucao_dias", (ultimo - ajuizamento).days, "humano")
        if resultado in ("Acordo", "Extinto sem resolução de mérito", "Arquivado / desistência", "Incompetência declarada"):
            pass  # sem probabilidade: o processo acabou sem julgamento de mérito
        else:
            # probabilidade do RESULTADO do processo, igual para autor e réu (PLANO 7.2: sem inversão por polo)
            if resultado is None:
                prob = "Possível"
            elif resultado == "Improcedente":
                prob = "Remota"
            else:
                prob = "Provável"
            if rng.random() < 0.15:
                prob = rng.choice(["Possível", "Provável", "Remota"])
            definir("probabilidade", prob, "humano")
        if houve_recurso and rng.random() < 0.5:
            definir("depositos_recursais", _dinheiro(round(valor_causa * 0.05, 2)), "humano")
        if momento == "TRÂNSITO EM JULGADO":
            definir("data_transito", ultimo.isoformat(), "humano")
    # vínculos: ~12% têm processo vinculado (agravo, apenso ou recurso), com número próprio
    if rng.random() < 0.12:
        for v in range(rng.choice([1, 1, 2])):
            tipo = rng.choice(["agravo", "apenso", "recurso"])
            ficha.vincular(f, numero_ficticio(_SEQ_VINCULADOS + i * 3 + v, ajuizamento.year, j, tr, 0), tipo)
    return f


def _normalizar_carimbos(fichas):
    """`ficha.definir` carimba a hora real em cada campo; para a carteira ser reproduzível, fixa o carimbo."""
    for f in fichas:
        for c in f.get("campos", {}).values():
            c["em"] = f"{HOJE}T10:00:00"
    return fichas


def gerar_carteira(n=200, clientes=5, semente=1, com_defeitos=False, com_linha_de_base=False):
    """`n` fichas v2 determinísticas. Sem `com_defeitos`, a carteira é limpa (ficha.validar vazio e nenhum dos
    problemas que o verificador de qualidade procura). Com `com_defeitos=True` o tamanho continua `n` e o
    resultado traz `.defeitos` (ver `detectar_defeitos`). `com_linha_de_base` anexa o histórico em texto."""
    if n >= 50_000:
        raise ValueError("n grande demais para a faixa sintética de números")
    fichas = [_ficha_sintetica(i, semente, max(1, clientes)) for i in range(n)]
    if com_linha_de_base:
        for f in fichas:
            anexar_linha_de_base(f, semente)
    defeitos = _estragar(fichas, semente) if com_defeitos else {}
    return Carteira(_normalizar_carimbos(fichas), defeitos)


def _estragar(fichas, semente):
    """Aplica os defeitos intencionais, cada um em fichas diferentes. Volta o que foi feito."""
    rng = random.Random(f"{semente}:defeitos")
    n = len(fichas)
    k = max(1, round(n * 0.015))
    livres = list(range(n))
    rng.shuffle(livres)
    defeitos = {"numero_duplicado": [], "materia_dois_rotulos": [], "acordo_sem_valor": [], "encerrado_sem_resultado": [],
                "ativo_em_conflito": [], "dv_errado": [], "grafias_cliente": []}

    def tirar(condicao=lambda f: True, quantos=1):
        escolhidos = [i for i in livres if condicao(fichas[i])][:quantos]
        for i in escolhidos:
            livres.remove(i)
        return escolhidos

    for _ in range(k):  # número duplicado: a ficha de destino vira cópia da de origem
        destino, = tirar() or [None]
        origem, = tirar() or [None]
        if destino is not None and origem is not None:
            fichas[destino] = copy.deepcopy(fichas[origem])
            defeitos["numero_duplicado"].append(fichas[origem]["numero"])
    trabalhista = lambda f: ficha.obter(f, "area") == "Trabalhista"
    for _ in range(k):  # o mesmo processo (principal e vinculado "mesma ação") com duas grafias de matéria
        achados = tirar(trabalhista, 2)
        if len(achados) < 2:
            break
        a, b = (fichas[i] for i in achados)
        canonica = rng.choice(list(taxonomia.MATERIA_SINONIMOS))
        ficha.definir(a, "materia_principal", canonica, "humano", forcar=True)
        ficha.definir(b, "materia_principal", rng.choice(taxonomia.MATERIA_SINONIMOS[canonica]), "humano", forcar=True)
        ficha.vincular(a, b["numero"], "mesma_acao")
        defeitos["materia_dois_rotulos"].append((a["numero"], b["numero"]))
    for i in tirar(lambda f: ficha.obter(f, "resultado") == "Acordo", k):
        for campo in ("valor_acordo", "valor_estimado", "valor_economizado"):
            ficha.limpar(fichas[i], campo)
        defeitos["acordo_sem_valor"].append(fichas[i]["numero"])
    for i in tirar(lambda f: not f["ativo"] and ficha.obter(f, "resultado") not in (None, "Acordo"), k):
        for campo in ("resultado", "probabilidade", "valor_arbitrado", "valor_estimado", "valor_economizado"):
            ficha.limpar(fichas[i], campo)
        defeitos["encerrado_sem_resultado"].append(fichas[i]["numero"])
    for i in tirar(lambda f: not f["ativo"] and ficha.obter(f, "resultado"), k):  # encerrado marcado como ativo
        fichas[i]["ativo"] = True
        defeitos["ativo_em_conflito"].append(fichas[i]["numero"])
    for i in tirar(lambda f: not f["vinculados"], k):
        fichas[i]["numero"] = numero_com_dv_errado(fichas[i]["numero"])
        defeitos["dv_errado"].append(fichas[i]["numero"])
    por_cliente = defaultdict(list)
    for i in livres:
        por_cliente[ficha.obter(fichas[i], "cliente")].append(i)
    for nome, indices in sorted(por_cliente.items()):
        if len(indices) >= 4 and len(defeitos["grafias_cliente"]) < max(1, k // 2):
            variantes = [nome.upper() + ("" if nome.endswith(".") else "."), " ".join(nome.split()[:-1]) or nome]
            for i, v in zip(indices, variantes):
                ficha.definir(fichas[i], "cliente", v, "humano", forcar=True)
                livres.remove(i)
            defeitos["grafias_cliente"].append({"canonico": nome, "variantes": variantes})
    return defeitos


def detectar_defeitos(fichas):
    """Mesma lista de `.defeitos`, descoberta SÓ olhando as fichas (referência simples do que o verificador de
    qualidade, WS-11, precisa achar; os testes usam para provar que cada defeito é detectável)."""
    achados = {"numero_duplicado": [], "materia_dois_rotulos": [], "acordo_sem_valor": [], "encerrado_sem_resultado": [],
               "ativo_em_conflito": [], "dv_errado": [], "grafias_cliente": []}
    vistos = defaultdict(int)
    for f in fichas:
        vistos[f["numero"]] += 1
    achados["numero_duplicado"] = sorted(n for n, c in vistos.items() if c > 1)
    por_numero = {f["numero"]: f for f in fichas}
    for f in fichas:
        for v in f.get("vinculados", []):
            outro = por_numero.get(v["numero"])
            if v["tipo"] == "mesma_acao" and outro is not None:
                ra, rb = ficha.obter(f, "materia_principal"), ficha.obter(outro, "materia_principal")
                if ra and rb and ra != rb and taxonomia.normalizar("materia", ra) == taxonomia.normalizar("materia", rb):
                    achados["materia_dois_rotulos"].append((f["numero"], outro["numero"]))
        resultado = ficha.obter(f, "resultado")
        if resultado == "Acordo" and not ficha.obter(f, "valor_acordo"):
            achados["acordo_sem_valor"].append(f["numero"])
        if not f.get("ativo", True) and not resultado:
            achados["encerrado_sem_resultado"].append(f["numero"])
        if any("conflita" in p for p in ficha.validar(f)):
            achados["ativo_em_conflito"].append(f["numero"])
        if not dv_confere(f["numero"]):
            achados["dv_errado"].append(f["numero"])
    grupos = defaultdict(set)
    for f in fichas:
        nome = ficha.obter(f, "cliente")
        if nome:
            grupos[" ".join(cart._sem_sufixo(nome))].add(nome)
    for chave, nomes in sorted(grupos.items()):
        if len(nomes) > 1:
            achados["grafias_cliente"].append(sorted(nomes))
    return achados


# ------------------------------------------------------------------ texto de andamento (linha de base)

def gerar_textos_de_andamento(f, semente=1, ate=None):
    """Frases de relatório ('Em 18/06/2026 foi proferida sentença julgando ...'), uma por fato do processo, em ordem.
    `ate` (ISO) corta o que aconteceu depois da data-base de um relatório antigo."""
    corte = ficha.data(ate)
    return [simulado.frase_do_fato(f, fato) for fato in simulado.fatos(f, semente)
            if corte is None or ficha.data(fato["data"]) <= corte]


def gerar_historico(f, semente=1, ate=None):
    """O mesmo, como texto corrido (a coluna de andamentos de um relatório existente)."""
    return " ".join(gerar_textos_de_andamento(f, semente, ate))


def anexar_linha_de_base(f, semente=1, data_base=None, arquivo="relatorio-exemplo.docx"):
    """Preenche `ficha["linha_de_base"]` (formato do contrato) com o histórico coerente com a ficha."""
    data_base = data_base or HOJE
    fatos = [x for x in simulado.fatos(f, semente) if ficha.data(x["data"]) <= ficha.data(data_base)]
    f["linha_de_base"] = {"data_base": data_base, "arquivo": arquivo,
                          "andamentos_texto": " ".join(simulado.frase_do_fato(f, x) for x in fatos),
                          "ultimo_andamento": fatos[-1]["data"] if fatos else None}
    return f


# ------------------------------------------------------------------ listas brutas (entrada típica)

def _valido_ou_nao(numeros):
    return ([n for n in numeros if dv_confere(n)], [n for n in numeros if not dv_confere(n)])


def gerar_lista_bruta(destino_dir, fichas, semente=1):
    """Grava 4 arquivos de entrada típicos em `destino_dir` e devolve, por arquivo, o que `carteira.ler_lista`
    deve ler: {"txt": {"arquivo": Path, "validos": [...], "invalidos": [...]}, "csv": ..., "xlsx": ..., "xlsx_bagunca": ...}.
    Cada arquivo usa um bloco diferente da carteira e um número com dígito verificador errado (que deve ser
    recusado e listado)."""
    from openpyxl import Workbook
    rng = random.Random(f"{semente}:lista")
    destino = Path(destino_dir)
    destino.mkdir(parents=True, exist_ok=True)
    bloco = max(1, min(12, len(fichas) // 4))
    partes = [fichas[i * bloco:(i + 1) * bloco] for i in range(4)]
    erro = lambda grupo: numero_com_dv_errado(grupo[-1]["numero"])
    saida = {}

    # 1) texto de e-mail, com números no meio das frases, um colado sem máscara e um repetido
    grupo = partes[0]
    numeros = [f["numero"] for f in grupo]
    sem_mascara = numeros[1].replace("-", "").replace(".", "") if len(numeros) > 1 else ""
    linhas = ["De: Escritório Exemplo <contato@exemplo.invalid>", "Assunto: Processos para o relatório do mês", "",
              "Prezado Davi,", "", f"Seguem os processos do cliente {ficha.obter(grupo[0], 'cliente')}:"]
    for pos, num in enumerate(numeros[:-1]):
        linhas.append(rng.choice([f"{pos + 1}) {num} - tem audiência marcada", f"Processo nº {num}, em grau de recurso.",
                                  f"- {num}"]) if pos != 1 else f"{pos + 1}) o de número {sem_mascara}, que veio sem pontuação")
    linhas += [f"Atenção: o {erro(grupo)} acho que digitei errado.", f"E de novo o primeiro: {numeros[0]}.", "",
               "Abraço,", "Fulano Exemplo"]
    arq = destino / "email.txt"
    arq.write_text("\n".join(linhas), encoding="utf-8")
    validos, invalidos = _valido_ou_nao([*numeros[:-1], erro(grupo)])
    saida["txt"] = {"arquivo": arq, "validos": validos, "invalidos": invalidos}

    # 2) csv com ponto e vírgula e cabeçalho variado
    grupo = partes[1]
    linhas = ["Nº;Cliente;Polo;Parte contrária;Responsável"]
    usados = []
    for f in grupo[:-1]:
        usados.append(f["numero"])
        linhas.append(";".join([f["numero"], ficha.obter(f, "cliente") or "", "Réu" if ficha.obter(f, "polo_cliente") == "passivo" else "Autor",
                                ficha.obter(f, "parte_contraria") or "", ficha.obter(f, "responsavel") or ""]))
    linhas.append(";".join([erro(grupo), ficha.obter(grupo[-1], "cliente") or "", "Réu", "Pessoa Fictícia 0000", "Responsável Exemplo A"]))
    arq = destino / "lista.csv"
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    validos, invalidos = _valido_ou_nao([*usados, erro(grupo)])
    saida["csv"] = {"arquivo": arq, "validos": validos, "invalidos": invalidos}

    # 3) xlsx simples
    grupo = partes[2]
    wb = Workbook()
    ws = wb.active
    ws.append(["Processo", "Cliente", "Polo do cliente", "Parte contrária"])
    for f in grupo[:-1]:
        ws.append([f["numero"], ficha.obter(f, "cliente"), ficha.obter(f, "polo_cliente"), ficha.obter(f, "parte_contraria")])
    ws.append([erro(grupo), ficha.obter(grupo[-1], "cliente"), "passivo", "Pessoa Fictícia 0000"])
    arq = destino / "lista.xlsx"
    wb.save(arq)
    validos, invalidos = _valido_ou_nao([*[f["numero"] for f in grupo[:-1]], erro(grupo)])
    saida["xlsx"] = {"arquivo": arq, "validos": validos, "invalidos": invalidos}

    # 4) xlsx bagunçado: título, linhas vazias, cabeçalho só na linha 3, número misturado com texto
    grupo = partes[3]
    wb = Workbook()
    ws = wb.active
    ws.append(["Acompanhamento (rascunho)"])
    ws.append([])
    ws.append(["Seq", "Nº do processo / observações", "Cliente", "Situação"])
    numeros_planilha = []
    for pos, f in enumerate(grupo[:-1]):
        if pos % 3 == 2:
            ws.append([])
        texto = rng.choice([f"Proc. {f['numero']} (principal)", f"ver {f['numero']} - aguardando decisão", f"{f['numero']}"])
        numeros_planilha.append(f["numero"])
        ws.append([pos + 1, texto, ficha.obter(f, "cliente"), ficha.obter(f, "situacao")])
    ws.append([])
    ws.append(["", f"digitei errado? {erro(grupo)}", "", ""])
    arq = destino / "lista_bagunca.xlsx"
    wb.save(arq)
    validos, invalidos = _valido_ou_nao([*numeros_planilha, erro(grupo)])
    saida["xlsx_bagunca"] = {"arquivo": arq, "validos": validos, "invalidos": invalidos}
    return saida


# ------------------------------------------------------------------ projeto temporário

_GLOBAIS_DO_COMUM = ("PROJETOS_DIR", "ATUAL_FILE", "PROJETO", "PROJETO_DIR", "PROJETO_FILE", "DATA", "CARTEIRA_FILE",
                     "CLIENTES_FILE", "EVENTOS_FILE", "ESTADO_FILE", "DOCS_DIR", "TEXTOS_DIR", "RELATORIOS_DIR", "DIAG_DIR",
                     "PRINTS_DIR")
_SALVO = {}


def restaurar_comum():
    """Desfaz criar_projeto_de_teste: `comum` volta a apontar para a pasta temporária dos testes."""
    for nome, valor in _SALVO.items():
        setattr(comum, nome, valor)
    _SALVO.clear()


def criar_projeto_de_teste(fichas=(), nome="Relatório de Teste", clientes=None):
    """Cria um projeto de verdade (`comum.criar_projeto`) numa pasta temporária, grava a carteira e o cadastro de
    clientes e o torna o projeto ativo. Devolve um dict {slug, pasta, data, carteira, clientes}. Chame
    `restaurar_comum()` ao final (ou use o gerenciador `projeto_de_teste`)."""
    if not _SALVO:
        _SALVO.update({n: getattr(comum, n) for n in _GLOBAIS_DO_COMUM})
    base = TMP / "projetos-de-teste"
    comum.PROJETOS_DIR = base
    comum.ATUAL_FILE = base / ".projeto_atual"   # nunca grava no projetos/ real
    slug = comum.criar_projeto(nome)
    comum.usar_projeto(slug)
    ficha.salvar(list(fichas))
    nomes = clientes if clientes is not None else sorted({ficha.obter(f, "cliente") for f in fichas if ficha.obter(f, "cliente")})
    comum.save_json(comum.CLIENTES_FILE, {"clientes": [{"nome": c, "variacoes": []} for c in nomes]})
    return {"slug": slug, "pasta": comum.PROJETO_DIR, "data": comum.DATA, "carteira": comum.CARTEIRA_FILE,
            "clientes": comum.CLIENTES_FILE}


@contextmanager
def projeto_de_teste(fichas=(), nome="Relatório de Teste", clientes=None):
    try:
        yield criar_projeto_de_teste(fichas, nome, clientes)
    finally:
        restaurar_comum()
