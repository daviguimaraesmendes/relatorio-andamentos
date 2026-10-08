"""Fila de coleta em massa: um processo por vez, retomável, com prioridade, janelas de horário e parada segura.

A fila NÃO fala com tribunal. Ela decide QUEM é o próximo, QUANDO e o que fazer com cada resultado; quem
coleta é um objeto `Coletor` (CONTRATOS.md, seção 6): o `ColetorSimulado` (src/simulado.py) nos testes e o
`ColetorReal` (no fim deste arquivo, sobre coletor.py/trt.py) na máquina do usuário.

    f = Fila(projeto)                         # slug do relatório (ou None = relatório ativo)
    f.enfileirar(numeros, modo="continuo", profundidade="padrao", prioridade=0, desde="2026-09-18")
    rodar_fila(f, ColetorSimulado(fichas), ao_progresso=print)   # consome a fila até acabar (ou até parar)
    f.resumo()   # {"total", "pendente", "coletando", "coletado", "erro", "manual", "estimativa_s", ...}
    cobertura(projeto)   # {tribunal: {"coletado": n, "so_djen": n, "manual": n}}

Estado: `data/fila.json` do projeto, gravado de forma atômica (comum.save_json) a CADA transição. Uma queda
em qualquer ponto deixa o arquivo íntegro; `rodar_fila` devolve ao fim da fila o que ficou `coletando` e
retoma. Processo `coletado` nunca é pedido de novo (só com `enfileirar(..., recoletar=True)`, no ciclo
seguinte, ou `reabrir`). Várias instâncias (painel e rodada em outro processo) podem usar o mesmo arquivo: toda
operação lê o disco de novo e escreve sob trava de arquivo; `pausar`, `retomar` e `parar_com_seguranca`
funcionam entre processos porque são gravados no arquivo.

Estados: pendente -> coletando -> coletado | erro | manual.
- `proximo()` já RESERVA o item (vira `coletando`, conta uma tentativa); só há um `coletando` por vez
  (sequencial contra jus.br e TRT). Devolve None enquanto: a fila está pausada ou em parada; há janela
  fechada (modo `continuo`); a pausa entre processos não passou; ou uma tentativa repetida ainda espera.
  `espera_s()` diz quantos segundos faltam.
- `marcar(numero, estado, erro=None)` aplica a política de erro (única, em um lugar só):
    captcha, segredo, nao_encontrado   -> `manual`, sem repetir;
    timeout, sessao_expirada, outro    -> `erro` com `proxima_tentativa` (espera cresce: base * 2^(n-1), até
                                          o teto) até `tentativas_max`; esgotadas, `erro` definitivo.
  `erro` guarda o código, a mensagem e a contagem de tentativas (`tentativas`).
- Captcha de TRT: os processos do mesmo TRT (e mesma prioridade) ficam juntos na ordem de saída, para a
  verificação humana ser pedida uma vez por rodada (`rodar_fila` avisa uma vez por TRT em `ao_progresso`,
  evento `captcha`). Se `captcha_limite_por_trt` captchas seguidos (sem sucesso no meio) ficarem sem solução,
  o resto daquele TRT na rodada vai para `manual` (não trava o resto da fila; `reabrir` põe de volta).
- `so_djen`: tribunal sem coleta disponível (lista `coleta.tribunais_so_djen` do config, ou `marcar(...,
  so_djen=True)`) entra direto como `manual` com `so_djen=True`; é a rede de segurança por publicações.

Modos (por item): `continuo` só sai dentro das janelas de horário (padrão 20:00-06:00; vira o dia; retoma na
abertura seguinte) e `imediato` ignora a janela. Os dois são sequenciais e usam a mesma pausa.
`estimativa()` = restantes x (média móvel medida do tempo por processo + pausa média); sem medida ainda, vale
um padrão conservador (120 s por processo). A confirmação ao usuário é da tela; a fila só informa.

Configuração (todas OPCIONAIS, em config.json, bloco "coleta", além do que já existe):
    pausa_entre_processos_s [a, b]   (já existe)        janelas_continuo ["20:00-06:00"]
    tentativas_max 3                 espera_tentativa_s 60 (base; teto 3600)
    estimativa_inicial_s 120         captcha_limite_por_trt 3
    tribunais_so_djen []             (ex.: ["TJXX"])
Todos podem ser trocados no construtor (`Fila(..., pausa_s=(0, 0), janelas=[...])`), assim como o relógio
(`relogio`), o cronômetro (`cronometro`), o `dormir` e o sorteio da pausa, para testar sem esperar.

`rodar_fila(fila, coletor, ao_progresso=None, ...)` é o laço: pega o próximo, chama o coletor, entrega o
resultado a `ao_resultado(item, resultado)` (quem grava capa/eventos; se falhar, o item NÃO vira `coletado`),
marca o estado e chama `ao_progresso(resumo)` a cada transição (o resumo traz também `evento`, `numero`,
`codigo`). Falha inesperada do coletor (exceção) vira erro `outro`; interrupção (Ctrl+C) sobe e o estado já
está salvo.

`ColetorReal`: adaptador fino sobre coletor.py/trt.py. NÃO é testável sem certificado e rede; validar no
piloto (marco M5). Ver a classe.
"""
import contextlib
import copy
import datetime
import os
import random
import re
import sys
import threading
import time
from pathlib import Path

import carteira as cart
import comum
import ficha as fch

ESTADOS = ("pendente", "coletando", "coletado", "erro", "manual")
MODOS = ("continuo", "imediato")
PROFUNDIDADES = ("rapido", "padrao", "completo")
CODIGOS = ("captcha", "segredo", "nao_encontrado", "fisico", "timeout", "sessao_expirada", "outro")
PERMANENTES = ("captcha", "segredo", "nao_encontrado", "fisico")      # vão para manual, sem repetir
TRANSITORIOS = ("timeout", "sessao_expirada", "outro")      # repetem com espera crescente

PADRAO_PAUSA_S = (3, 5)
PADRAO_JANELAS = ("20:00-06:00",)
PADRAO_TENTATIVAS = 3
PADRAO_ESPERA_S = 60
TETO_ESPERA_S = 3600
PADRAO_ESTIMATIVA_S = 120        # conservador: só vale até a primeira medição
AMOSTRAS_DA_MEDIA = 20           # média móvel dos últimos N processos coletados
PADRAO_LIMITE_CAPTCHA = 3
FATIA_DE_ESPERA_S = 30           # rodar_fila dorme em fatias, para notar pausa/parada

_MENSAGENS = {
    "captcha": "O tribunal pediu verificação humana (captcha). Conferir manualmente.",
    "segredo": "Processo em segredo de justiça: sem acesso aos autos. Conferir manualmente.",
    "nao_encontrado": "Processo não localizado no tribunal. Conferir manualmente.",
    "fisico": "Processo físico (sem autos eletrônicos): o relatório segue pelo DJEN e pelo que for lançado à mão.",
}


# ------------------------------------------------------------------ tempo e janelas

def _iso(momento):
    return momento.isoformat(timespec="seconds")


def _de_iso(texto):
    return datetime.datetime.fromisoformat(texto) if texto else None


def parse_janelas(janelas):
    """['20:00-06:00'] (ou [('20:00', '06:00')]) -> [(time, time)]. Lista vazia = sem restrição de horário."""
    saida = []
    for j in janelas or ():
        if isinstance(j, str):
            m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})\s*", j)
            partes = m.groups() if m else None
        else:
            try:
                (h1, m1), (h2, m2) = (str(x).split(":") for x in j)
                partes = (h1, m1, h2, m2)
            except (ValueError, TypeError):
                partes = None
        try:
            if partes is None:
                raise ValueError
            h1, m1, h2, m2 = (int(x) for x in partes)
            saida.append((datetime.time(h1, m1), datetime.time(h2, m2)))
        except ValueError:
            raise ValueError(f"Janela de horário inválida: {j!r} (use o formato 'HH:MM-HH:MM', ex.: '20:00-06:00').") from None
    return saida


def dentro_da_janela(janelas, agora):
    """True se `agora` cai em alguma janela (a janela pode virar o dia: 20:00-06:00). Sem janelas, sempre."""
    if not janelas:
        return True
    t = agora.time()
    for ini, fim in janelas:
        if ini == fim:                       # 24 horas
            return True
        if (ini < fim and ini <= t < fim) or (ini > fim and (t >= ini or t < fim)):
            return True
    return False


def proxima_abertura(janelas, agora):
    """Primeiro instante em que a coleta contínua pode rodar (agora, se já está dentro de uma janela)."""
    if dentro_da_janela(janelas, agora):
        return agora
    candidatos = []
    for ini, _ in janelas:
        quando = datetime.datetime.combine(agora.date(), ini)
        candidatos.append(quando if quando > agora else quando + datetime.timedelta(days=1))
    return min(candidatos)


# ------------------------------------------------------------------ trava e arquivo

_TRAVAS = {}
_TRAVAS_GUARDA = threading.Lock()


def _trava_do_processo(caminho):
    with _TRAVAS_GUARDA:
        return _TRAVAS.setdefault(str(caminho), threading.RLock())


@contextlib.contextmanager
def _trava_de_arquivo(caminho):
    """Trava entre processos (painel x rodada). Melhor esforço: sem fcntl/msvcrt segue sem a trava de arquivo."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a+b") as f:
        travado = False
        try:
            if sys.platform.startswith("win"):
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX)
            travado = True
        except (ImportError, OSError):
            pass
        try:
            yield
        finally:
            if travado:
                try:
                    if sys.platform.startswith("win"):
                        import msvcrt
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f, fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass


def _pid_vivo(pid):
    if sys.platform.startswith("win"):
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _pasta_do_projeto(projeto):
    """slug, Path, dict {"pasta": ...} (como devolve tests.ficticio.projeto_de_teste) ou None (relatório ativo).
    Devolve (arquivo da fila, arquivo da carteira)."""
    if isinstance(projeto, dict):
        projeto = projeto.get("pasta") or projeto.get("slug")
    if projeto is None:
        if comum.PROJETO_DIR:
            return Path(comum.PROJETO_DIR) / "data" / "fila.json", Path(comum.PROJETO_DIR) / "carteira.json"
        return Path(comum.DATA) / "fila.json", Path(comum.CARTEIRA_FILE)
    por_slug = Path(comum.PROJETOS_DIR) / str(projeto)
    if isinstance(projeto, str) and os.sep not in projeto and por_slug.is_dir():
        caminho = por_slug
    elif Path(projeto).is_dir():
        caminho = Path(projeto)
    else:
        raise ValueError(f"Relatório não encontrado: {projeto}")
    return caminho / "data" / "fila.json", caminho / "carteira.json"


def _tribunal_do_numero(numero, padrao=""):
    m = cart.CNJ.search(numero or "")
    return cart.tribunal(m.groups()) if m else (padrao or "")


def _e_trt(tribunal):
    return (tribunal or "").upper().startswith("TRT")


def _vazio():
    return {"versao": 1, "itens": {}, "proxima_ordem": 1, "pausada": False, "parar": False, "livre_apos": None,
            "medicoes": [], "rodada": 0, "captcha": {}, "executor": None}


# ------------------------------------------------------------------ a fila

class Fila:
    """Fila persistente de coleta de UM relatório. Veja o cabeçalho do módulo."""

    def __init__(self, projeto=None, *, relogio=None, cronometro=None, dormir=None, sorteio=None, janelas=None,
                 pausa_s=None, tentativas_max=None, espera_base_s=None, estimativa_inicial_s=None,
                 tribunais_so_djen=None, captcha_limite=None):
        self.arquivo, self.carteira_arquivo = _pasta_do_projeto(projeto)
        cfg = comum.config().get("coleta") or {}
        self.relogio = relogio or datetime.datetime.now
        self.cronometro = cronometro or time.monotonic
        self.dormir = dormir or time.sleep
        self.sorteio = sorteio or random.uniform
        self.janelas = parse_janelas(janelas if janelas is not None else cfg.get("janelas_continuo", PADRAO_JANELAS))
        pausa = pausa_s if pausa_s is not None else cfg.get("pausa_entre_processos_s", PADRAO_PAUSA_S)
        self.pausa_s = (float(pausa[0]), float(pausa[1])) if isinstance(pausa, (list, tuple)) else (float(pausa), float(pausa))
        self.tentativas_max = int(tentativas_max if tentativas_max is not None else cfg.get("tentativas_max", PADRAO_TENTATIVAS))
        self.espera_base_s = float(espera_base_s if espera_base_s is not None else cfg.get("espera_tentativa_s", PADRAO_ESPERA_S))
        self.estimativa_inicial_s = float(estimativa_inicial_s if estimativa_inicial_s is not None
                                          else cfg.get("estimativa_inicial_s", PADRAO_ESTIMATIVA_S))
        self.captcha_limite = int(captcha_limite if captcha_limite is not None else cfg.get("captcha_limite_por_trt", PADRAO_LIMITE_CAPTCHA))
        self.tribunais_so_djen = {t.upper() for t in (tribunais_so_djen if tribunais_so_djen is not None
                                                      else cfg.get("tribunais_so_djen", []))}
        self._ativa = None            # estado da transação corrente (evita travar duas vezes na mesma thread)
        self._dono = None

    # -- disco
    def _ler(self):
        try:
            estado = comum.load_json(self.arquivo, None)
        except ValueError as e:
            raise ValueError(f"O arquivo da fila está ilegível ({self.arquivo}): {e}") from e
        if not isinstance(estado, dict):
            return _vazio()
        for chave, valor in _vazio().items():
            estado.setdefault(chave, valor)
        return estado

    @contextlib.contextmanager
    def _transacao(self):
        """Lê o disco, deixa alterar e grava de volta, sob trava (outras threads e outros processos)."""
        if self._ativa is not None and self._dono == threading.get_ident():
            yield self._ativa
            return
        with _trava_do_processo(self.arquivo):
            with _trava_de_arquivo(self.arquivo.with_name(self.arquivo.name + ".lock")):
                estado = self._ler()
                self._ativa, self._dono = estado, threading.get_ident()
                try:
                    yield estado
                    comum.save_json(self.arquivo, estado)
                finally:
                    self._ativa = self._dono = None

    def _cliente_da_carteira(self, numero):
        for item in comum.load_json(self.carteira_arquivo, []):
            if item.get("numero") == numero:
                return fch.obter(fch.de_carteira_v1(item), "cliente"), item.get("apelido")
        return None, None

    # -- enfileirar
    def enfileirar(self, numeros, *, modo="continuo", profundidade="padrao", prioridade=0, desde=None,
                   cliente=None, recoletar=False):
        """Coloca processos na fila. `numeros`: números ou dicts {"numero", "cliente"}. Devolve
        {"enfileirados": [...], "ja_coletados": [...], "ja_na_fila": [...]}.
        Número que já está `pendente` só atualiza modo/profundidade/prioridade/desde; `coletado` é ignorado
        (a menos que `recoletar=True`, para o ciclo seguinte); `erro`/`manual`/`coletando` ficam como estão
        (use `reabrir`). `desde` é estrito (só o que for posterior) e vale para movimentos e documentos."""
        if modo not in MODOS:
            raise ValueError(f"Modo desconhecido: {modo!r} (use {' ou '.join(MODOS)}).")
        if profundidade not in PROFUNDIDADES:
            raise ValueError(f"Profundidade desconhecida: {profundidade!r}.")
        desde_iso = None
        if desde:
            desde_iso = fch.parse_data(desde)
            if desde_iso is None:
                raise ValueError(f"Data 'desde' inválida: {desde!r}.")
        pedidos = []
        for n in numeros:
            if isinstance(n, dict):
                pedidos.append((str(n["numero"]).strip(), n.get("cliente") or cliente))
            else:
                pedidos.append((str(n).strip(), cliente))
        agora = _iso(self.relogio())
        saida = {"enfileirados": [], "ja_coletados": [], "ja_na_fila": []}
        carteira = {}
        for it in comum.load_json(self.carteira_arquivo, []):
            carteira[it.get("numero")] = it
        with self._transacao() as d:
            for numero, cli in pedidos:
                if not numero:
                    continue
                item = d["itens"].get(numero)
                if item is not None:
                    novos = dict(modo=modo, profundidade=profundidade, prioridade=prioridade, desde=desde_iso)
                    if item["estado"] == "coletado" and not recoletar:
                        saida["ja_coletados"].append(numero)
                    elif item["estado"] == "coletado":      # novo ciclo: volta para a fila
                        item.update(novos, estado="pendente", tentativas=0, erro=None, proxima_tentativa=None,
                                    motivo=None, so_djen=False, coletado_em=None)
                        saida["enfileirados"].append(numero)
                    else:
                        if item["estado"] == "pendente":
                            item.update(novos)
                        saida["ja_na_fila"].append(numero)
                    continue
                if not cli and numero in carteira:
                    cli = fch.obter(fch.de_carteira_v1(carteira[numero]), "cliente")
                tribunal = _tribunal_do_numero(numero, (carteira.get(numero) or {}).get("tribunal"))
                item = {"numero": numero, "estado": "pendente", "modo": modo, "profundidade": profundidade,
                        "prioridade": prioridade, "desde": desde_iso, "ordem": d["proxima_ordem"],
                        "tribunal": tribunal, "cliente": cli or "", "tentativas": 0, "erro": None,
                        "proxima_tentativa": None, "so_djen": False, "motivo": None, "enfileirado_em": agora,
                        "atualizado_em": agora, "coletado_em": None, "duracao_s": None}
                d["proxima_ordem"] += 1
                d["itens"][numero] = item
                if tribunal.upper() in self.tribunais_so_djen:
                    item.update(estado="manual", so_djen=True,
                                motivo="Coleta indisponível neste tribunal: só publicações (DJEN).")
                saida["enfileirados"].append(numero)
        return saida

    # -- escolha do próximo
    def _filtro(self, cliente=None, numeros=None):
        alvo = {str(n).strip() for n in numeros} if numeros is not None else None
        return lambda i: (cliente is None or i["cliente"] == cliente) and (alvo is None or i["numero"] in alvo)

    def _aguarda_retentativa(self, i):
        return i["estado"] == "erro" and bool(i["proxima_tentativa"])

    @staticmethod
    def _adiado(d, i):
        """Item pulado nesta rodada por captcha do TRT sem solução: só volta quando não houver mais nada a coletar."""
        return i.get("adiado") == d["rodada"] and not i.get("segunda_chance")

    def _ha_outros(self, d, filtro):
        """Há item (pendente ou à espera de nova tentativa) que NÃO foi adiado por captcha?"""
        return any(filtro(i) and not self._adiado(d, i) and (i["estado"] == "pendente" or self._aguarda_retentativa(i))
                   for i in d["itens"].values())

    def _candidatos(self, d, agora, filtro):
        """Itens que podem sair agora (sem considerar pausa global nem pausa/parada)."""
        saida = []
        segurar_adiados = self._ha_outros(d, filtro)
        for i in d["itens"].values():
            if segurar_adiados and self._adiado(d, i):
                continue
            if not filtro(i):
                continue
            if i["estado"] == "pendente":
                pronto = True
            elif self._aguarda_retentativa(i):
                pronto = _de_iso(i["proxima_tentativa"]) <= agora
            else:
                continue
            if pronto and (i["modo"] == "imediato" or dentro_da_janela(self.janelas, agora)):
                saida.append(i)
        return saida

    @staticmethod
    def _ordenar(candidatos, ultimo_tribunal=None):
        """Maior prioridade primeiro; empate por ordem de entrada. Processos do mesmo TRT (e da mesma prioridade)
        ficam juntos, para a verificação humana ser pedida uma vez por rodada: continua no TRT do processo
        anterior enquanto ele tiver itens naquela prioridade e, depois, vai pelo TRT que entrou primeiro."""
        primeiro = {}
        for i in candidatos:
            if _e_trt(i["tribunal"]):
                chave = (i["prioridade"], i["tribunal"])
                primeiro[chave] = min(primeiro.get(chave, i["ordem"]), i["ordem"])

        def chave(i):
            trt = _e_trt(i["tribunal"])
            grupo = primeiro[(i["prioridade"], i["tribunal"])] if trt else i["ordem"]
            continua = 0 if trt and i["tribunal"] == ultimo_tribunal else 1
            return (-i["prioridade"], continua, grupo, i["ordem"])
        return sorted(candidatos, key=chave)

    def _escolher(self, d, agora, cliente, numeros):
        """O item que sairia agora (ou None), conforme controle, pausa entre processos, janela e prioridade."""
        if d["pausada"] or d["parar"]:
            return None
        if any(i["estado"] == "coletando" for i in d["itens"].values()):
            return None                         # sequencial: um processo por vez
        livre = _de_iso(d["livre_apos"])
        if livre and agora < livre:
            return None
        ordenados = self._ordenar(self._candidatos(d, agora, self._filtro(cliente, numeros)), d.get("ultimo_tribunal"))
        return ordenados[0] if ordenados else None

    def proximo(self, cliente=None, numeros=None):
        """Reserva e devolve o próximo item (agora `coletando`), ou None. Não espera: veja `espera_s()`."""
        if self._escolher(self._ler(), self.relogio(), cliente, numeros) is None:
            return None                         # caminho barato: sem trava e sem gravar
        with self._transacao() as d:
            agora = self.relogio()
            item = self._escolher(d, agora, cliente, numeros)
            if item is None:
                return None
            item.update(estado="coletando", tentativas=item["tentativas"] + 1, iniciado_em=_iso(agora),
                        atualizado_em=_iso(agora), proxima_tentativa=None)
            if item.get("adiado") == d["rodada"]:
                item["segunda_chance"] = True       # voltou depois de adiado por captcha: nova falha vai para manual
            d["ultimo_tribunal"] = item["tribunal"]
            return copy.deepcopy(item)

    def espera_s(self, cliente=None, numeros=None):
        """Segundos até haver um item que possa sair (0 = já pode). None = nada a esperar (fila vazia, só
        itens finais) ou fila pausada/em parada."""
        d = self._ler()
        if d["pausada"] or d["parar"]:
            return None
        agora, filtro = self.relogio(), self._filtro(cliente, numeros)
        segurar_adiados = self._ha_outros(d, filtro)
        candidatos = [i for i in d["itens"].values() if filtro(i) and (i["estado"] == "pendente" or self._aguarda_retentativa(i))
                      and not (segurar_adiados and self._adiado(d, i))]
        if not candidatos:
            return None
        livre = _de_iso(d["livre_apos"])
        espera_pausa = max(0.0, (livre - agora).total_seconds()) if livre else 0.0

        def quando(i):
            t = max(agora, _de_iso(i["proxima_tentativa"])) if self._aguarda_retentativa(i) else agora
            if i["modo"] == "continuo":
                t = proxima_abertura(self.janelas, t)
            return (t - agora).total_seconds()
        return max(espera_pausa, min(quando(i) for i in candidatos))

    # -- marcar
    def _pausa_entre_processos(self, d, agora):
        a, b = self.pausa_s
        espera = self.sorteio(a, b) if b > a else a
        d["livre_apos"] = _iso(agora + datetime.timedelta(seconds=espera)) if espera > 0 else None

    def marcar(self, numero, estado, erro=None, *, duracao_s=None, so_djen=False, motivo=None):
        """Registra a transição de um item e devolve uma cópia dele. Para `estado="erro"`, `erro` é
        {"codigo", "mensagem"} e a política de erro decide o destino (veja o cabeçalho). `coletado` é final."""
        if estado not in ESTADOS:
            raise ValueError(f"Estado desconhecido: {estado!r}.")
        with self._transacao() as d:
            item = d["itens"].get(numero)
            if item is None:
                raise ValueError(f"Processo fora da fila: {numero}")
            agora = self.relogio()
            if item["estado"] == "coletado":
                if estado == "coletado":
                    return copy.deepcopy(item)
                raise ValueError(f"{numero} já foi coletado; para coletar de novo use enfileirar(..., recoletar=True).")
            estava_coletando = item["estado"] == "coletando"
            adiado = False
            item["atualizado_em"] = _iso(agora)
            item["proxima_tentativa"] = None
            if estado == "coletado":
                item.update(estado="coletado", erro=None, motivo=None, coletado_em=_iso(agora), duracao_s=duracao_s)
                item.pop("adiado", None)
                item.pop("segunda_chance", None)
                if duracao_s is not None:
                    d["medicoes"] = (d["medicoes"] + [float(duracao_s)])[-AMOSTRAS_DA_MEDIA:]
                d["captcha"].get("por_tribunal", {}).pop(item["tribunal"], None)
            elif estado == "erro":
                codigo = (erro or {}).get("codigo")
                codigo = codigo if codigo in CODIGOS else "outro"
                mensagem = (erro or {}).get("mensagem") or _MENSAGENS.get(codigo, "Falha na coleta.")
                item["erro"] = {"codigo": codigo, "mensagem": mensagem}
                if (codigo == "captcha" and (erro or {}).get("adiavel") and _e_trt(item["tribunal"])
                        and not item.get("segunda_chance")):
                    # ninguém resolveu o captcha no prazo: pula este e o resto do TRT, e volta no fim da rodada
                    self._adiar_captcha(d, item)
                    adiado = True
                elif codigo in PERMANENTES:
                    item["estado"] = "manual"
                    item["motivo"] = _MENSAGENS[codigo]
                    if codigo == "captcha" and _e_trt(item["tribunal"]):
                        self._captcha_do_trt(d, item, agora)
                else:
                    item["estado"] = "erro"
                    if item["tentativas"] < self.tentativas_max:
                        espera = min(self.espera_base_s * 2 ** max(item["tentativas"] - 1, 0), TETO_ESPERA_S)
                        item["proxima_tentativa"] = _iso(agora + datetime.timedelta(seconds=espera))
                    else:
                        item["motivo"] = f"Esgotadas as {self.tentativas_max} tentativas. Conferir manualmente."
            elif estado == "manual":
                codigo = (erro or {}).get("codigo")
                item.update(estado="manual", so_djen=bool(so_djen) or item["so_djen"],
                            motivo=motivo or _MENSAGENS.get(codigo) or item["motivo"])
                if erro:
                    item["erro"] = {"codigo": codigo if codigo in CODIGOS else "outro", "mensagem": erro.get("mensagem") or ""}
            else:  # pendente / coletando
                item["estado"] = estado
                if estado == "pendente":
                    item["erro"] = None
            if estava_coletando and (item["estado"] in ("coletado", "erro", "manual") or adiado):
                self._pausa_entre_processos(d, agora)
            return copy.deepcopy(item)

    def _adiar_captcha(self, d, item):
        """O item volta a `pendente` (sem gastar tentativa) e, com os outros pendentes do mesmo TRT, fica adiado até
        o fim da rodada; a primeira volta pede o captcha uma vez e libera o grupo."""
        item.update(estado="pendente", tentativas=max(item["tentativas"] - 1, 0), adiado=d["rodada"], motivo=None)
        for outro in d["itens"].values():
            if outro["tribunal"] == item["tribunal"] and outro["estado"] == "pendente" and outro is not item:
                outro["adiado"] = d["rodada"]

    def devolver(self, numero):
        """O processo reservado volta a `pendente` sem gastar tentativa (a falha não foi dele: login, navegador)."""
        with self._transacao() as d:
            item = d["itens"].get(numero)
            if item is None or item["estado"] != "coletando":
                return
            item.update(estado="pendente", tentativas=max(item["tentativas"] - 1, 0), atualizado_em=_iso(self.relogio()),
                        proxima_tentativa=None)
            d["livre_apos"] = None

    def _captcha_do_trt(self, d, item, agora):
        """Captchas seguidos de um TRT sem solução: o resto do TRT vai para manual (nesta rodada)."""
        contagem = d["captcha"].setdefault("por_tribunal", {})
        contagem[item["tribunal"]] = contagem.get(item["tribunal"], 0) + 1
        if contagem[item["tribunal"]] < self.captcha_limite:
            return
        for outro in d["itens"].values():
            if outro["tribunal"] == item["tribunal"] and outro["estado"] == "pendente" and outro is not item:
                outro.update(estado="manual", atualizado_em=_iso(agora), erro={
                    "codigo": "captcha", "mensagem": "Captcha do TRT não resolvido nesta rodada."},
                    motivo="Captcha do TRT não resolvido nesta rodada. Conferir manualmente ou reabrir mais tarde.")

    # -- controle (valem entre processos: ficam gravados no arquivo)
    def pausar(self):
        """Não sai mais item novo (o processo corrente termina). `retomar()` desfaz."""
        with self._transacao() as d:
            d["pausada"] = True

    def retomar(self):
        with self._transacao() as d:
            d["pausada"] = False
            d["parar"] = False

    def parar_com_seguranca(self):
        """Pede para a rodada parar: termina o processo corrente, grava e sai (`rodar_fila` volta)."""
        with self._transacao() as d:
            d["parar"] = True

    def limpar_parada(self):
        with self._transacao() as d:
            d["parar"] = False

    def controle(self):
        d = self._ler()
        return {"pausada": d["pausada"], "parar": d["parar"]}

    def recuperar_interrompidos(self):
        """Depois de queda: o que ficou `coletando` volta a `pendente` (a tentativa interrompida não conta)."""
        voltaram = []
        with self._transacao() as d:
            for i in d["itens"].values():
                if i["estado"] == "coletando":
                    i.update(estado="pendente", tentativas=max(i["tentativas"] - 1, 0), atualizado_em=_iso(self.relogio()))
                    voltaram.append(i["numero"])
        return voltaram

    def reabrir(self, numeros=None, estados=("erro", "manual")):
        """Ação explícita do usuário: devolve `erro`/`manual` à fila (tentativas zeradas). Nunca mexe em `coletado`."""
        alvo = {str(n).strip() for n in numeros} if numeros is not None else None
        reabertos = []
        with self._transacao() as d:
            for i in d["itens"].values():
                if i["estado"] in estados and i["estado"] != "coletado" and (alvo is None or i["numero"] in alvo):
                    i.update(estado="pendente", tentativas=0, erro=None, proxima_tentativa=None, motivo=None,
                             so_djen=False, atualizado_em=_iso(self.relogio()))
                    i.pop("adiado", None)
                    i.pop("segunda_chance", None)
                    reabertos.append(i["numero"])
        return reabertos

    def nova_rodada(self):
        """Zera a contagem de captchas por TRT e conta a rodada (chamado no início de `rodar_fila`)."""
        with self._transacao() as d:
            d["rodada"] += 1
            d["captcha"] = {}
            d["parar"] = False
            return d["rodada"]

    def registrar_executor(self):
        with self._transacao() as d:
            ex = d.get("executor")
            if ex and ex.get("pid") != os.getpid() and _pid_vivo(ex["pid"]):
                raise RuntimeError("Já há uma coleta em andamento nesta fila (outro programa a está rodando).")
            d["executor"] = {"pid": os.getpid(), "desde": _iso(self.relogio())}

    def liberar_executor(self):
        with self._transacao() as d:
            if (d.get("executor") or {}).get("pid") == os.getpid():
                d["executor"] = None

    # -- consulta
    def item(self, numero):
        i = self._ler()["itens"].get(numero)
        return copy.deepcopy(i) if i else None

    def itens(self, estado=None, cliente=None, numeros=None):
        filtro = self._filtro(cliente, numeros)
        return [copy.deepcopy(i) for i in sorted(self._ler()["itens"].values(), key=lambda x: x["ordem"])
                if filtro(i) and (estado is None or i["estado"] == estado)]

    def media_s(self):
        """Média móvel medida do tempo por processo coletado (segundos); sem medida, o padrão conservador."""
        medicoes = self._ler()["medicoes"]
        return sum(medicoes) / len(medicoes) if medicoes else self.estimativa_inicial_s

    def medido(self):
        """True quando a média já vem de medições reais (e não do padrão)."""
        return bool(self._ler()["medicoes"])

    def estimativa(self, n=None, cliente=None, numeros=None):
        """Segundos previstos: n processos (padrão: o que falta na fila) x (média medida + pausa média)."""
        if n is None:
            n = self._restantes(self._ler(), self._filtro(cliente, numeros))
        return int(round(n * (self.media_s() + sum(self.pausa_s) / 2)))

    def _restantes(self, d, filtro):
        return sum(1 for i in d["itens"].values()
                   if filtro(i) and (i["estado"] in ("pendente", "coletando") or self._aguarda_retentativa(i)))

    def resumo(self, cliente=None, numeros=None):
        d = self._ler()
        filtro = self._filtro(cliente, numeros)
        itens = [i for i in d["itens"].values() if filtro(i)]
        contagem = {e: sum(1 for i in itens if i["estado"] == e) for e in ESTADOS}
        medicoes = d["medicoes"]
        media = sum(medicoes) / len(medicoes) if medicoes else self.estimativa_inicial_s
        restantes = self._restantes(d, filtro)
        return {"total": len(itens), **contagem,
                "estimativa_s": int(round(restantes * (media + sum(self.pausa_s) / 2))),
                "so_djen": sum(1 for i in itens if i["so_djen"]),
                "fisico": sum(1 for i in itens if (i["erro"] or {}).get("codigo") == "fisico" and i["estado"] == "manual"),
                "erro_definitivo": sum(1 for i in itens if i["estado"] == "erro" and not i["proxima_tentativa"]),
                "pausada": d["pausada"], "parando": d["parar"], "rodada": d["rodada"], "medido": bool(medicoes)}

    def conferir_manualmente(self):
        """Lista "conferir manualmente": manual (captcha, segredo, não localizado, só DJEN...) e erro definitivo."""
        saida = []
        for i in self.itens():
            if i["estado"] == "manual" or (i["estado"] == "erro" and not i["proxima_tentativa"]):
                saida.append({"numero": i["numero"], "tribunal": i["tribunal"], "cliente": i["cliente"],
                              "estado": i["estado"], "so_djen": i["so_djen"],
                              "fisico": (i["erro"] or {}).get("codigo") == "fisico",
                              "codigo": (i["erro"] or {}).get("codigo"), "motivo": i["motivo"] or (i["erro"] or {}).get("mensagem")})
        return saida


def cobertura(projeto):
    """{tribunal: {"coletado": n, "so_djen": n, "manual": n}} dos processos que já passaram pela fila.
    `manual` inclui o que precisa de conferência manual: estado `manual` (exceto só DJEN) e `erro` definitivo.
    Pendentes, em coleta e em nova tentativa ainda não contam. Sem fila, {}."""
    arquivo, _ = _pasta_do_projeto(projeto)
    estado = comum.load_json(arquivo, None) or {}
    saida = {}
    for i in (estado.get("itens") or {}).values():
        tribunal = i.get("tribunal") or "?"
        if i["estado"] == "coletado":
            chave = "coletado"
        elif i["estado"] == "manual" and (i.get("erro") or {}).get("codigo") == "fisico":
            chave = "fisico"
        elif i["estado"] == "manual" and i.get("so_djen"):
            chave = "so_djen"
        elif i["estado"] == "manual" or (i["estado"] == "erro" and not i.get("proxima_tentativa")):
            chave = "manual"
        else:
            continue
        linha = saida.setdefault(tribunal, {"coletado": 0, "so_djen": 0, "manual": 0})
        linha[chave] = linha.get(chave, 0) + 1      # "fisico" só aparece nos tribunais que têm processo físico
    return dict(sorted(saida.items()))


def taxa_de_sucesso(projeto):
    """A taxa de sucesso da coleta SÓ sobre os processos eletrônicos. Processo físico (sem autos eletrônicos) e
    tribunal só-DJEN ficam de fora do denominador e aparecem à parte. Pendentes e em coleta ainda não contam.

        {"coletados", "eletronicos", "taxa" (0..1 ou None), "fisicos", "so_djen", "manuais", "erros"}
    `eletronicos` = coletados + manuais (captcha, segredo, não localizado...) + erros definitivos."""
    arquivo, _ = _pasta_do_projeto(projeto)
    estado = comum.load_json(arquivo, None) or {}
    c = {"coletados": 0, "fisicos": 0, "so_djen": 0, "manuais": 0, "erros": 0}
    for i in (estado.get("itens") or {}).values():
        if i["estado"] == "coletado":
            c["coletados"] += 1
        elif i["estado"] == "manual" and (i.get("erro") or {}).get("codigo") == "fisico":
            c["fisicos"] += 1
        elif i["estado"] == "manual" and i.get("so_djen"):
            c["so_djen"] += 1
        elif i["estado"] == "manual":
            c["manuais"] += 1
        elif i["estado"] == "erro" and not i.get("proxima_tentativa"):
            c["erros"] += 1
    eletronicos = c["coletados"] + c["manuais"] + c["erros"]
    return {**c, "eletronicos": eletronicos, "taxa": round(c["coletados"] / eletronicos, 4) if eletronicos else None}


# ------------------------------------------------------------------ o laço

def rodar_fila(fila, coletor, ao_progresso=None, *, ao_resultado=None, esperar=True, cliente=None, numeros=None,
               max_processos=None):
    """Consome a fila, um processo por vez, até acabar, parar (`parar_com_seguranca`) ou, com `esperar=False`,
    até não haver nada que possa sair agora (janela fechada, pausa, nova tentativa distante). Com `esperar=True`
    (padrão) dorme até a próxima abertura/tentativa, em fatias, e segue. Devolve o `resumo()` final.

    `ao_progresso(resumo)`: a cada transição (`coletando`, `coletado`, `erro`, `manual`) e nos avisos `captcha`,
    `espera`, `pausada`, `parada` e `fim` (campo `evento`; mais `numero` e `codigo` quando houver).
    `ao_resultado(item, resultado)`: quem grava o que foi coletado; se levantar exceção, o item vira erro `outro`
    e NÃO fica `coletado` (será tentado de novo)."""
    def avisar(evento, **extra):
        if ao_progresso:
            ao_progresso({**fila.resumo(cliente, numeros), "evento": evento, **extra})

    fila.registrar_executor()
    try:
        fila.recuperar_interrompidos()
        fila.nova_rodada()
        avisados, feitos, esperando = set(), 0, False
        while True:
            controle = fila.controle()
            if controle["parar"]:
                fila.limpar_parada()
                avisar("parada")
                break
            if controle["pausada"]:
                if not esperar:
                    break
                avisar("pausada")
                while fila.controle()["pausada"] and not fila.controle()["parar"]:
                    fila.dormir(1)
                continue
            if max_processos is not None and feitos >= max_processos:
                break
            item = fila.proximo(cliente, numeros)
            if item is None:
                espera = fila.espera_s(cliente, numeros)
                if espera is None or not esperar:
                    break
                if not esperando:
                    avisar("espera", espera_s=int(espera))
                    esperando = True
                fila.dormir(max(min(espera, FATIA_DE_ESPERA_S), 0.001))
                continue
            esperando = False
            numero = item["numero"]
            avisar("coletando", numero=numero)
            inicio = fila.cronometro()
            erro, resultado = None, None
            try:
                resultado = coletor.coletar({"numero": numero, "cliente": item["cliente"], "tribunal": item["tribunal"]},
                                            item["profundidade"], item["desde"])
                erro = (resultado or {}).get("erro")
                if not erro and ao_resultado:
                    ao_resultado(item, resultado)
            except Exception as e:   # falha inesperada: vira erro "outro" e a fila segue
                erro = {"codigo": "outro", "mensagem": f"{type(e).__name__}: {e}"}
            duracao = fila.cronometro() - inicio
            if erro and erro.get("fatal"):
                # o acesso caiu (login, navegador): o processo volta à fila sem gastar tentativa, a fila pausa e
                # só uma pessoa a retoma. Evita repetir o login (e acordar o jus.br) para cada processo.
                fila.devolver(numero)
                fila.pausar()
                avisar("login", numero=numero, codigo=erro.get("codigo"), mensagem=erro.get("mensagem"))
                continue
            feitos += 1
            if erro:
                marcado = fila.marcar(numero, "erro", erro)
                codigo = marcado["erro"]["codigo"]
                if codigo == "captcha" and _e_trt(item["tribunal"]) and item["tribunal"] not in avisados:
                    avisados.add(item["tribunal"])
                    avisar("captcha", numero=numero, tribunal=item["tribunal"], codigo=codigo)
                avisar(marcado["estado"], numero=numero, codigo=codigo)
            else:
                fila.marcar(numero, "coletado", duracao_s=duracao)
                avisar("coletado", numero=numero)
        avisar("fim")
        return fila.resumo(cliente, numeros)
    finally:
        fila.liberar_executor()


# ------------------------------------------------------------------ adaptador real

def classificar_erro(excecao):
    """Exceção do coletor real -> {"codigo", "mensagem"} do contrato. Reconhece as mensagens de coletor.py e
    trt.py e o TimeoutError do Playwright; o resto vira `outro` (repetível)."""
    texto = str(excecao)
    baixo = texto.lower()
    nome = type(excecao).__name__.lower()
    if "captcha" in baixo:
        codigo = "captcha"
    elif "segredo de justiça" in baixo or "segredo de justica" in baixo:
        codigo = "segredo"
    elif "não encontrado" in baixo or "nao encontrado" in baixo or "não reconheceu o número" in baixo \
            or "tribunal superior" in baixo:
        codigo = "nao_encontrado"
    elif "login" in baixo or "sessão" in baixo or "sessao" in baixo or "has been closed" in baixo or "target closed" in baixo:
        codigo = "sessao_expirada"
    elif "timeout" in nome or "timeout" in baixo or "a tempo" in baixo:
        codigo = "timeout"
    else:
        codigo = "outro"
    saida = {"codigo": codigo, "mensagem": texto or type(excecao).__name__}
    if codigo == "captcha" and getattr(excecao, "adiavel", False):
        saida["adiavel"] = True      # captcha de TRT que ninguém resolveu no prazo: a fila pode pular e voltar no fim
    return saida


def parece_fisico(numero, *, buscar_djen=None, consultar_datajud=None):
    """O processo "não encontrado" é FÍSICO (sem autos eletrônicos)? Só quando as duas fontes públicas respondem
    e as duas estão vazias: o DJEN sem nenhuma publicação E o DataJud sem nenhum registro do número. Fonte
    desligada, sem chave, sem rede ou com erro => False: na dúvida o processo continua "manual" (nunca se marca
    como físico um eletrônico que apenas falhou). `buscar_djen(numero)` e `consultar_datajud(numero)` são
    injetáveis (testes sem rede); `consultar_datajud` devolve (dados | None, avisos)."""
    try:
        import capa
        import djen
        if consultar_datajud is None:
            ativo, chave = capa._config_datajud()
            if not (ativo and chave):
                return False
            consultar_datajud = capa.consultar_datajud
        dados, _ = consultar_datajud(numero)
        if dados is None:                       # DataJud indisponível: não dá para afirmar
            return False
        digitos = re.sub(r"\D", "", numero)
        if any(re.sub(r"\D", "", str(f.get("numeroProcesso", ""))) == digitos for f in capa._fontes_datajud(dados)):
            return False                        # o DataJud conhece o processo: tem autos eletrônicos
        publicacoes = (buscar_djen or djen.publicacoes_do_processo)(numero)
        return not publicacoes
    except Exception:
        return False


def _iso_do_evento(texto):
    return fch.parse_data(texto)


def eventos_para_resultado(novos):
    """Eventos que o coletor real acrescentou (formato de comum.py) -> movimentos e documentos do contrato.
    Documento sem arquivo baixado (só com print) fica fora de `documentos`, mas continua em eventos.json."""
    movimentos, documentos = [], []
    for ev in novos:
        data = _iso_do_evento(ev.get("data"))
        if ev.get("tipo_evento") == "movimento" and data:
            movimentos.append({"data": data, "texto": ev.get("titulo") or "", "grau": ev.get("grau"), "chave": ev.get("chave") or ev["id"]})
        elif ev.get("tipo_evento") == "documento" and data and ev.get("arquivo"):
            documentos.append({"nome": ev.get("titulo") or "", "tipo": ev.get("tipo") or "", "data": data, "caminho": ev["arquivo"]})
    return movimentos, documentos


class ColetorReal:
    """Implementa o protocolo `Coletor` sobre coletor.py (jus.br) e trt.py (TRTs). Fino de propósito.

    NÃO TESTÁVEL AQUI (exige certificado A1, PJe Office, autenticador, rede e navegador): **validar no piloto
    (marco M5)**. Os testes cobrem só a importação e a tradução (`classificar_erro`, `eventos_para_resultado`).

        with ColetorReal() as c:                 # abre o navegador e faz o login UMA vez
            rodar_fila(fila, c, ao_progresso=...)

    Como mapeia o contrato:
    - Grava eventos (eventos.json) e estado (estado_coleta.json) como o `coletor.rodar()` da Fase 1, a cada
      processo (relê os eventos antes de cada um, porque a revisão pode estar aberta). O `ResultadoColeta`
      devolvido espelha o que foi acrescentado: `movimentos` e `documentos` (só os baixados).
    - `capa` vem VAZIA: o coletor atual não lê a capa (é o WS-4, `capa.py`).
    - `desde` (estrito, igual ao `_depois` do coletor): vale na PRIMEIRA vez que o processo é visto; depois, o
      coletor usa o estado por processo (só o que ainda não conhecia). Primeira vez SEM `desde` e sem `historico`
      informado traz o histórico COMPLETO (beta 3.1: antes virava "linha de base" e não trazia nada, o que fazia o
      relatório inicial e a atualização de processos sem data-base voltarem vazios). A profundidade `rapido` limita
      os documentos (cota 0), não os andamentos.
    - `profundidade`: `rapido` não baixa documentos (cota 0; os andamentos entram); `padrao` usa
      `max_documentos_por_rodada` do config; `completo` não limita. O real não separa "documentos-chave".
    - Exceção do coletor vira `erro` com código (`classificar_erro`); falha de sessão/navegador fecha o
      navegador, que reabre (com novo login) na próxima chamada.
    """

    COTA_COMPLETO = 10 ** 6
    HISTORICO_TODO = 10 ** 6

    def __init__(self, historico=0):
        import trt
        self.historico = historico
        self._pw = self._navegador = self._contexto = None
        trt.zerar_rodada()     # as contagens de captcha valem por rodada (por ColetorReal), não por navegador

    # -- navegador
    def abrir(self):
        import coletor
        import janela
        from playwright.sync_api import sync_playwright
        print(f"Relatório de Andamentos {comum.versao_do_programa() or '?'}: abrindo o navegador e entrando no jus.br", flush=True)
        self._pw = sync_playwright().start()
        try:
            self._navegador, self._contexto = janela.abrir_navegador(self._pw)
            coletor.logar(self._contexto)
        except BaseException:
            self.fechar()
            raise

    def fechar(self):
        import trt
        print(trt.resumo_dos_captchas(), flush=True)
        try:
            trt.fechar_consultas(self._contexto)
        except Exception:
            pass
        for alvo, metodo in ((self._navegador, "close"), (self._pw, "stop")):
            try:
                if alvo is not None:
                    getattr(alvo, metodo)()
            except Exception:
                pass
        self._pw = self._navegador = self._contexto = None

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *_):
        self.fechar()

    # -- protocolo Coletor
    def coletar(self, processo, profundidade="padrao", desde=None):
        import coletor
        vazio = {"capa": {}, "movimentos": [], "documentos": [], "erro": None}
        try:
            if self._contexto is None:
                self.abrir()
        except Exception as e:
            # sem navegador ou sem login não adianta tentar o próximo processo: `fatal` faz o laço pausar a fila
            return {**vazio, "erro": {**classificar_erro(e), "codigo": "sessao_expirada", "fatal": True}}
        cota = {"rapido": 0, "padrao": comum.config().get("coleta", {}).get("max_documentos_por_rodada", 30),
                "completo": self.COTA_COMPLETO}[profundidade]
        proc = {"numero": processo["numero"], "cliente": processo.get("cliente") or "", "apelido": processo.get("apelido")}
        trabalhista = _e_trabalhista(processo["numero"])
        if trabalhista:
            proc["indicio_2grau"] = _datajud_indica_segundo_grau(processo["numero"])
        estado = comum.load_json(comum.ESTADO_FILE, {})
        lista = comum.eventos()
        antes = len(lista)
        erro, relato = None, {}
        try:
            historico = self.historico if (self.historico or desde) else self.HISTORICO_TODO
            coletor.coletar_processo(self._contexto, proc, estado, lista, historico, cota, fch.data(desde), relato)
        except Exception as e:
            erro = classificar_erro(e)
            if erro["codigo"] == "sessao_expirada":
                self.fechar()
        finally:
            comum.save_json(comum.ESTADO_FILE, estado)
            comum.salvar_eventos(lista)
        if erro and erro["codigo"] == "nao_encontrado" and parece_fisico(processo["numero"]):
            erro = {"codigo": "fisico", "mensagem": _MENSAGENS["fisico"]}
        movimentos, documentos = eventos_para_resultado(lista[antes:])
        resultado = {"capa": {}, "movimentos": movimentos, "documentos": documentos, "erro": erro}
        if relato.get("graus_lidos") or relato.get("graus_falhos"):
            resultado["graus"] = {"lidos": relato.get("graus_lidos", []), "falhos": relato.get("graus_falhos", [])}
        if relato.get("avisos"):
            resultado["avisos"] = relato["avisos"]
        if "tst" in relato.get("graus_disponiveis", []):  # a própria consulta do TRT lista o TST
            resultado["no_tst"] = True
        if trabalhista and not erro:
            _acrescentar_tst(resultado, processo["numero"])
        return resultado


def _e_trabalhista(numero):
    """Número CNJ da Justiça do Trabalho (segmento 5), que passa pelo TRT e pode chegar ao TST."""
    return bool(re.search(r"\d{7}-\d{2}\.\d{4}\.5\.", str(numero)))


def _datajud_indica_segundo_grau(numero):
    """O DataJud mostra o processo no 2º grau? Só com a fonte ligada e a chave pública; qualquer falha vale False
    (e a coleta decide pelos andamentos)."""
    try:
        import capa
        ativo, chave = capa._config_datajud()
        if not (ativo and chave):
            return False
        dados, _ = capa.consultar_datajud(numero)
        return bool(dados) and capa.indica_segundo_grau(dados, numero)
    except Exception:
        return False


def _acrescentar_tst(resultado, numero):
    """Se o DataJud tem o processo no TST (mesmo número CNJ, índice `tst`), traz os movimentos do TST (grau "TST") e
    marca `no_tst`. Sem DataJud ligado, nada acontece. O coletor dos DOCUMENTOS do TST não existe ainda: ver
    docs/fase2/PROXIMA-SESSAO.md (gancho `coletor_tst`)."""
    try:
        import capa
        ativo, chave = capa._config_datajud()
        if not (ativo and chave):
            return
        dados, avisos = capa.consultar_tst(numero)
        if dados is None or not capa.no_tst(dados, numero):
            return
        resultado["no_tst"] = True
        conhecidos = {m.get("chave") for m in resultado["movimentos"]}
        resultado["movimentos"] += [m for m in capa.movimentos_do_tst(dados, numero) if m["chave"] not in conhecidos]
        resultado.setdefault("avisos", []).append({"nivel": "info", "codigo": "no_tst", "onde": f"datajud/{numero}",
                                                    "mensagem": "O processo tem tramitação no TST (movimentos pelo DataJud; "
                                                                "os documentos do TST ainda não são coletados)."})
    except Exception:
        pass


def verificar_importacao():
    """Lista (vazia = tudo certo) do que impediria o ColetorReal de rodar aqui: módulos que não importam.
    Não abre navegador nem rede."""
    problemas = []
    for modulo in ("coletor", "trt", "janela", "acesso", "playwright.sync_api"):
        try:
            __import__(modulo)
        except Exception as e:
            problemas.append(f"{modulo}: {type(e).__name__}: {e}")
    return problemas
