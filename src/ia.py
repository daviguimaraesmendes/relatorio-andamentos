"""Provedores de IA: local (Ollama), Claude (API da Anthropic) e API compatível com
OpenAI, com consentimento por relatório e por cliente.

Padrão: **tudo local**. Nada sai do computador sem `true` explícito em
`perfil["ia"]["consentimento_externo"]` (do relatório) ou em `perfil["ia"]["por_cliente"][cliente]`
(que vale para aquele cliente e prevalece sobre o do relatório, nos dois sentidos). Perfil
malformado, valor que não seja o booleano `True` (texto "true", número 1...) ou provedor
desconhecido = sem consentimento.

Uso (CONTRATOS §8):

    import ia
    prov = ia.provedor(perfil, cliente)                       # local ou externo, conforme o consentimento
    r = prov.gerar(sistema, usuario, esquema=ESQ, cliente=cliente, partes=["Fulano"])
    r["texto"], r["json"], r["motor"], r["avisos"]            # `avisos`: Avisos estruturados (CONTRATOS §0)
    ia.selo(r["motor"])                                       # "local" | "externa: <provedor>", para as telas
    ia.registro_de_envios(projeto)                            # tudo o que saiu do computador (só externo)

`motor` é o que **realmente** respondeu: `local:<modelo>`, `externo:<provedor>:<modelo>` ou
`nenhum` (nem o local respondeu; `texto` vem vazio e há aviso com o motivo).

Provedores externos são cadastrados no painel (/ia): nome, tipo, endereço, modelo e chave. A chave
vai para o cofre do sistema (`acesso.guardar`, serviço do jusbr-autologin, nome `ia_chave:<provedor>`);
o catálogo (sem a chave) fica em `config.json`, na chave `ia_provedores`. A chave nunca é mostrada de
volta, nunca vai para log, aviso, registro nem HTML.

O que sai: só o texto de `sistema` e `usuario` (texto extraído dos documentos, nunca print,
certificado, senha ou arquivo). Antes do envio: (1) o texto é barrado se contiver a senha do
certificado, o segredo do autenticador ou a chave do provedor; (2) caminhos do computador viram
"[CAMINHO]"; (3) com `perfil["ia"]["pseudonimizar"]` verdadeiro (padrão: ligado), nomes das partes,
CPF, CNPJ, número de processo e e-mail viram marcadores como `[PARTE_1]`, e a resposta é devolvida
com os nomes de volta (`pseudonimizar` e `restaurar`). O mapa marcador -> original fica só em
`data/ia/mapa_pseudonimos.json` do relatório. É um esforço razoável, não uma garantia: um nome
escrito de forma diferente da cadastrada (apelido, abreviação) passa.

Registro local (`data/ia/envios.jsonl`, uma linha JSON por evento, só acrescenta): para cada envio,
quando, provedor, modelo, cliente, número de caracteres e SHA-256 do que foi enviado -- **sem** o
texto. É gravado ANTES da chamada (se o registro não puder ser gravado, nada é enviado).

Falha (sem chave, sem rede, erro ou recusa do provedor, resposta fora do esquema, pacote ausente)
cai no motor local e devolve o aviso. Códigos estáveis dos avisos: `ia_externa_sem_consentimento`,
`ia_provedor_desconhecido`, `ia_sem_chave`, `ia_chave_invalida`, `ia_falha_rede`, `ia_erro_provedor`,
`ia_recusa_do_provedor`, `ia_resposta_invalida`, `ia_pacote_ausente`, `ia_conteudo_bloqueado`,
`ia_registro_falhou`, `ia_local_indisponivel`, `ia_cofre_indisponivel`.

Testes e ensaios: nada de rede. `provedor(..., transporte=..., fabrica_cliente=...)` troca o HTTP do
provedor compatível com OpenAI e o cliente do SDK da Anthropic; `ProvedorLocal(ollama=...)` troca o Ollama.
O pacote `anthropic` só é importado quando um provedor Anthropic é de fato chamado.
"""
import copy
import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import acesso
import comum

TIPOS = {"anthropic": "Claude (API da Anthropic)", "openai_compativel": "API compatível com OpenAI"}
MODELO_ANTHROPIC_PADRAO = "claude-opus-5-5"
# modelos para os quais o reencaminhamento no servidor da Anthropic (fallbacks) é ligado por padrão
MODELOS_COM_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
BETA_FALLBACK = "server-side-fallback-2026-07-01"
PREFIXO_CHAVE = "ia_chave:"
CHAVE_CONFIG = "ia_provedores"
TIMEOUT_S = 120
MAX_TOKENS = 16000
MIN_SEGREDO = 6          # tamanho mínimo para um segredo contar como "achado no texto"
CLIENTE_TESTE = "(teste de conexão)"


def aviso(codigo, mensagem, nivel="atencao", onde="ia"):
    """Aviso estruturado (CONTRATOS §0)."""
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": []}


class ErroProvedor(Exception):
    """Falha esperada de um provedor externo; vira aviso + queda no local."""

    def __init__(self, codigo, mensagem):
        super().__init__(mensagem)
        self.codigo, self.mensagem = codigo, mensagem


# --- consentimento -----------------------------------------------------------

def _chave_nome(texto):
    return comum.normalizar(texto) if isinstance(texto, str) else ""


def consentimento(perfil, cliente, provedor=None):
    """(permitido, motivo). `True` só com consentimento explícito; qualquer dúvida é "não".

    Vale `por_cliente[cliente]` quando o cliente consta ali (todas as grafias equivalentes precisam
    ser `True`); senão, `consentimento_externo` do relatório. `provedor`, se dado, precisa ser o
    escolhido no perfil."""
    try:
        cfg = perfil.get("ia") if isinstance(perfil, dict) else None
        if not isinstance(cfg, dict):
            return False, "O perfil não tem a seção de IA: vale o motor local."
        escolhido = cfg.get("provedor")
        if not isinstance(escolhido, str) or comum.slug(escolhido) in ("sem-nome", "local"):
            return False, "O relatório usa a IA local."
        if provedor is not None and comum.slug(escolhido) != comum.slug(provedor):
            return False, "O provedor pedido não é o escolhido para este relatório."
        por = cfg.get("por_cliente")
        if isinstance(por, dict) and isinstance(cliente, str) and cliente.strip():
            achados = [v for k, v in por.items() if _chave_nome(k) == _chave_nome(cliente)]
            if achados:
                if all(v is True for v in achados):
                    return True, "Consentimento registrado para este cliente."
                return False, "Sem consentimento: este cliente não autorizou o envio a provedor externo."
        if cfg.get("consentimento_externo") is True:
            return True, "Consentimento registrado para este relatório."
        return False, "Falta o consentimento para enviar texto a provedor externo (tela IA)."
    except Exception:
        return False, "Perfil de IA ilegível: vale o motor local."


def _pseudonimizar_ligado(perfil):
    try:
        return perfil["ia"].get("pseudonimizar") is not False   # só desliga com `false` explícito
    except Exception:
        return True


# --- pastas do relatório -----------------------------------------------------

def _pasta(projeto=None):
    """Pasta do relatório: `Path` (a própria pasta), `str` (slug em projetos/) ou None (o relatório ativo)."""
    if isinstance(projeto, Path):
        return projeto
    if isinstance(projeto, str) and projeto:
        return comum.PROJETOS_DIR / projeto
    return comum.PROJETO_DIR or Path(comum.DATA).parent


def _dir_ia(projeto=None):
    return _pasta(projeto) / "data" / "ia"


def arquivo_perfil(projeto=None):
    return _pasta(projeto) / "perfil.json"


def carregar_perfil(projeto=None):
    try:
        perfil = comum.load_json(arquivo_perfil(projeto), {})
    except (OSError, ValueError):
        return {}
    return perfil if isinstance(perfil, dict) else {}


def salvar_ia_no_perfil(dados_ia, projeto=None):
    """Mescla `dados_ia` em `perfil["ia"]` sem tocar no resto do perfil (que é do WS-9)."""
    perfil = carregar_perfil(projeto)
    atual = perfil.get("ia") if isinstance(perfil.get("ia"), dict) else {}
    perfil.setdefault("versao", 1)
    perfil["ia"] = {**atual, **dados_ia}
    comum.save_json(arquivo_perfil(projeto), perfil)
    return perfil


# --- registro de envios ------------------------------------------------------

def _agora():
    return datetime.now().isoformat(timespec="seconds")


def _acrescentar(projeto, linha):
    pasta = _dir_ia(projeto)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "envios.jsonl"
    novo = not arquivo.exists()
    with arquivo.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    if novo:
        try:
            arquivo.chmod(0o600)
        except OSError:
            pass


def registro_de_envios(projeto=None):
    """Tudo o que saiu do computador (só provedor externo), do mais antigo ao mais recente.

    Cada item: `id`, `quando`, `provedor`, `modelo`, `cliente`, `caracteres`, `sha256`,
    `pseudonimizado`, `resultado` (`ok`, `erro:<codigo>` ou `pendente`: a chamada começou e não
    terminou) e, se outro modelo respondeu, `modelo_resposta`. Nunca contém o texto enviado."""
    arquivo = _dir_ia(projeto) / "envios.jsonl"
    if not arquivo.exists():
        return []
    envios, ordem = {}, []
    for bruta in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            linha = json.loads(bruta)
        except ValueError:
            continue
        if not isinstance(linha, dict) or "id" not in linha:
            continue
        if linha.get("tipo") == "envio":
            envios[linha["id"]] = {k: v for k, v in linha.items() if k != "tipo"} | {"resultado": "pendente"}
            ordem.append(linha["id"])
        elif linha.get("tipo") == "resultado" and linha["id"] in envios:
            envios[linha["id"]]["resultado"] = linha.get("resultado", "pendente")
            if linha.get("modelo_resposta"):
                envios[linha["id"]]["modelo_resposta"] = linha["modelo_resposta"]
    return [envios[i] for i in ordem]


# --- pseudonimização ---------------------------------------------------------

_ACENTOS = {"a": "aáàâãä", "e": "eéèêë", "i": "iíìîï", "o": "oóòôõö", "u": "uúùûü", "c": "cç", "n": "nñ"}
_MARCADOR = re.compile(r"\[([A-Z]+)_(\d+)\]")
# Em ordem: o mais específico primeiro, para um CNPJ não ser lido como CPF.
_DOCUMENTOS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("PROCESSO", re.compile(r"(?<!\d)\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?!\d)")),
    ("CNPJ", re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")),
    ("CPF", re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")),
]


def _padrao_parte(nome):
    """Regex que casa o nome sem diferenciar maiúsculas, acentos nem quebras/espaços repetidos."""
    base = "".join(c for c in unicodedata.normalize("NFKD", nome.strip()) if not unicodedata.combining(c))
    pedacos = []
    for c in base:
        if c.isspace():
            if not pedacos or pedacos[-1] != r"\s+":
                pedacos.append(r"\s+")
        elif c.lower() in _ACENTOS:
            pedacos.append("[" + _ACENTOS[c.lower()] + "]")
        else:
            pedacos.append(re.escape(c))
    return "".join(pedacos)


def _indice_do_mapa(mapa):
    """(categoria, chave do original) -> marcador, e o maior número usado por categoria."""
    achados, maior = {}, {}
    for marcador, original in mapa.items():
        m = _MARCADOR.fullmatch(marcador)
        if not m:
            continue
        cat, n = m.group(1), int(m.group(2))
        chave = _chave_nome(original) if cat == "PARTE" else original
        achados[(cat, chave)] = marcador
        maior[cat] = max(maior.get(cat, 0), n)
    return achados, maior


def pseudonimizar(texto, partes, mapa=None):
    """Troca nomes de `partes`, CPF, CNPJ, número de processo e e-mail por marcadores.

    Devolve `(texto_pseudonimizado, mapa)`; o `mapa` (marcador -> original) é o que permite
    `restaurar` e só deve ficar no computador. Passe o mapa de chamadas anteriores para reaproveitar
    os marcadores (o mesmo nome sempre vira o mesmo marcador). Partes com menos de 3 letras são
    ignoradas. Nomes casam sem diferenciar maiúsculas/acentos, mas voltam como foram cadastrados."""
    mapa = dict(mapa or {})
    achados, maior = _indice_do_mapa(mapa)

    def marcador(cat, original, chave):
        if (cat, chave) not in achados:
            maior[cat] = maior.get(cat, 0) + 1
            achados[(cat, chave)] = f"[{cat}_{maior[cat]}]"
            mapa[achados[(cat, chave)]] = original
        return achados[(cat, chave)]

    nomes, vistos = [], set()
    for p in sorted((p.strip() for p in (partes or ()) if isinstance(p, str)), key=len, reverse=True):
        if len(p) >= 3 and _chave_nome(p) not in vistos:
            vistos.add(_chave_nome(p))
            nomes.append(p)
    texto = texto if isinstance(texto, str) else str(texto)
    if nomes:
        alternativas = "|".join(f"(?P<p{i}>{_padrao_parte(n)})" for i, n in enumerate(nomes))
        regex = re.compile(rf"(?<!\w)(?:{alternativas})(?!\w)", re.IGNORECASE)
        texto = regex.sub(lambda m: marcador("PARTE", nomes[int(m.lastgroup[1:])], _chave_nome(nomes[int(m.lastgroup[1:])])),
                          texto)
    for cat, regex in _DOCUMENTOS:
        texto = regex.sub(lambda m, cat=cat: marcador(cat, m.group(0), m.group(0)), texto)
    return texto, mapa


def restaurar(texto, mapa):
    """Desfaz `pseudonimizar` (marcador desconhecido fica como está)."""
    if not isinstance(texto, str) or not mapa:
        return texto
    return _MARCADOR.sub(lambda m: mapa.get(m.group(0), m.group(0)), texto)


def _restaurar_json(valor, mapa):
    if isinstance(valor, str):
        return restaurar(valor, mapa)
    if isinstance(valor, list):
        return [_restaurar_json(v, mapa) for v in valor]
    if isinstance(valor, dict):
        return {k: _restaurar_json(v, mapa) for k, v in valor.items()}
    return valor


def _mapa_arquivo(projeto):
    return _dir_ia(projeto) / "mapa_pseudonimos.json"


def _carregar_mapa(projeto):
    try:
        mapa = comum.load_json(_mapa_arquivo(projeto), {})
        return mapa if isinstance(mapa, dict) else {}
    except (OSError, ValueError):
        return {}


def _partes_do_relatorio(projeto):
    """Nomes de clientes e partes que constam do relatório (carteira.json e clientes.json), para
    pseudonimizar mesmo quando quem chama não os informa. Melhor esforço: falha vira lista vazia."""
    nomes = []
    try:
        if projeto:
            carteira_file, clientes_file = _pasta(projeto) / "carteira.json", _pasta(projeto) / "clientes.json"
        else:  # o relatório ativo (nos testes, os arquivos fixados por isolamento.py)
            carteira_file, clientes_file = comum.CARTEIRA_FILE, comum.CLIENTES_FILE
        carteira, clientes = comum.load_json(carteira_file, []), comum.load_json(clientes_file, {})
        for c in (clientes.get("clientes", []) if isinstance(clientes, dict) else []):
            nomes.append(c.get("nome", ""))
            nomes.extend(c.get("variacoes", []))
        for p in (carteira if isinstance(carteira, list) else []):
            for campo in ("cliente", "parte_contraria", "autores", "reus"):
                valor = p.get(campo)
                if isinstance(valor, str):
                    nomes.extend(re.split(r"[;\n]", valor))
                elif isinstance(valor, list):
                    nomes.extend(v for v in valor if isinstance(v, str))
    except Exception:
        pass
    return [n for n in nomes if isinstance(n, str) and n.strip()]


# --- guardas do que sai ------------------------------------------------------

def _segredos_locais(chave):
    return [s for s in (acesso.obter("cert_senha"), acesso.obter("totp_secret"), chave)
            if isinstance(s, str) and len(s) >= MIN_SEGREDO]


def _tira_caminhos(texto):
    for raiz in {str(comum.RAIZ), str(comum.PROJETOS_DIR), str(Path.home())}:
        if len(raiz) > 3:
            texto = texto.replace(raiz, "[CAMINHO]")
    return texto


def _sem_chave(texto, chave):
    texto = str(texto)
    if chave:
        texto = texto.replace(chave, "***")
    return re.sub(r"\b(sk-[A-Za-z0-9_-]{6,}|Bearer\s+\S+)", "***", texto)[:300]


# --- provedor local ----------------------------------------------------------

class ProvedorLocal:
    """Ollama no próprio computador (reaproveita `resumir._ollama`, `modelo_escolhido` e `ollama_pronto`)."""

    nome = "local"

    def __init__(self, *, modelo=None, ollama=None, avisos=()):
        self._modelo, self._ollama, self.avisos_iniciais = modelo, ollama, list(avisos)

    def com_avisos(self, avisos):
        novo = copy.copy(self)
        novo.avisos_iniciais = list(avisos)
        return novo

    def _resolver(self):
        import resumir
        return self._modelo or resumir.modelo_escolhido(), self._ollama or resumir._ollama, resumir.ollama_pronto

    def gerar(self, sistema, usuario, *, esquema=None, cliente="", partes=()):
        avisos = list(self.avisos_iniciais)
        modelo = pronto = None
        try:
            modelo, ollama, pronto = self._resolver()
            corpo = {"model": modelo, "stream": False, "options": {"temperature": 0, "num_ctx": 8192},
                     "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}
            if esquema:
                corpo["format"] = esquema
            texto = ollama("/api/chat", corpo)["message"]["content"]
        except Exception as e:  # Ollama parado, modelo não baixado, resposta fora do formato
            motivo = None
            try:
                motivo = pronto(modelo) if pronto and modelo else None
            except Exception:
                pass
            avisos.append(aviso("ia_local_indisponivel", motivo or f"O motor local não respondeu ({type(e).__name__}).",
                                "erro"))
            return {"texto": "", "json": None, "motor": "nenhum", "avisos": avisos}
        dados = None
        if esquema:
            dados = _json_da_resposta(texto)
            if dados is None:
                avisos.append(aviso("ia_resposta_invalida", "O motor local não devolveu o JSON pedido: conferir."))
        return {"texto": texto, "json": dados, "motor": f"local:{modelo}", "avisos": avisos}


def _json_da_resposta(texto):
    """O objeto JSON da resposta (aceita cerca de código ```json), ou None."""
    texto = (texto or "").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.I)
    try:
        dados = json.loads(texto)
    except ValueError:
        return None
    return dados if isinstance(dados, dict) else None


# --- provedores externos -----------------------------------------------------

def _esquema_estrito(esquema, tipos_em_anyof):
    """Cópia do esquema com `additionalProperties: false` em todo objeto (exigido pelas saídas
    estruturadas) e, se `tipos_em_anyof`, `type: [a, "null"]` reescrito como `anyOf`."""
    if isinstance(esquema, list):
        return [_esquema_estrito(e, tipos_em_anyof) for e in esquema]
    if not isinstance(esquema, dict):
        return esquema
    novo = {k: _esquema_estrito(v, tipos_em_anyof) for k, v in esquema.items()}
    if novo.get("type") == "object" or "properties" in novo:
        novo.setdefault("additionalProperties", False)
    if tipos_em_anyof and isinstance(novo.get("type"), list):
        novo["anyOf"] = [{"type": t} for t in novo.pop("type")]
    return novo


def _classificar(e):
    """ErroProvedor a partir de uma exceção do SDK ou da rede (pelo nome da classe: não exige o SDK)."""
    nomes = {c.__name__ for c in type(e).__mro__}
    msg = _sem_chave(e, None)
    if nomes & {"APIConnectionError", "APITimeoutError", "DeadlineExceededError", "URLError", "TimeoutError",
                "ConnectionError"}:
        return ErroProvedor("ia_falha_rede", "Sem conexão com o provedor ou tempo esgotado.")
    if nomes & {"AuthenticationError", "PermissionDeniedError"}:
        return ErroProvedor("ia_chave_invalida", "O provedor recusou a chave: confira a chave cadastrada.")
    return ErroProvedor("ia_erro_provedor", f"O provedor devolveu erro ({type(e).__name__}): {msg}")


class ProvedorExterno:
    """Base dos provedores externos. `gerar` confere consentimento, barra segredos, pseudonimiza,
    registra, chama (`_chamar`, de cada tipo) e, se algo falhar, cai no motor local."""

    tipo = ""

    def __init__(self, nome, config, *, perfil, projeto=None, local=None):
        self.nome, self.config, self.perfil, self.projeto = comum.slug(nome), dict(config), perfil, projeto
        self.local = local or ProvedorLocal()
        self.modelo = self.config.get("modelo", "")

    def _chave(self):
        return acesso.obter(PREFIXO_CHAVE + self.nome)

    def _chamar(self, chave, sistema, usuario, esquema):
        """-> (texto, json | None, modelo que respondeu). Levanta ErroProvedor."""
        raise NotImplementedError

    def _motor(self, modelo):
        return f"externo:{self.nome}:{modelo or self.modelo}"

    def _enviar(self, sistema, usuario, esquema, cliente, partes, pseudonimizar_ligado):
        """Um envio completo. -> (resultado | None, avisos). None = nada foi respondido (ver avisos)."""
        permitido, motivo = consentimento(self.perfil, cliente, self.nome)
        if not permitido:
            return None, [aviso("ia_externa_sem_consentimento", motivo)]
        chave = self._chave()
        if not chave:
            return None, [aviso("ia_sem_chave", f"O provedor '{self.config.get('nome', self.nome)}' está sem chave "
                                                "no cofre do sistema (tela IA).")]
        sistema, usuario = str(sistema), str(usuario)
        if any(s in sistema or s in usuario for s in _segredos_locais(chave)):
            return None, [aviso("ia_conteudo_bloqueado", "O texto continha uma senha ou chave guardada no cofre; "
                                                          "nada foi enviado.", "erro")]
        mapa = {}
        if pseudonimizar_ligado:
            todas = list(partes) + [cliente] + _partes_do_relatorio(self.projeto)
            mapa = _carregar_mapa(self.projeto)
            sistema, mapa = pseudonimizar(sistema, todas, mapa)
            usuario, mapa = pseudonimizar(usuario, todas, mapa)
        sistema, usuario = _tira_caminhos(sistema), _tira_caminhos(usuario)
        identificador = uuid.uuid4().hex[:12]
        try:
            if mapa:
                comum.save_json(_mapa_arquivo(self.projeto), mapa)
            _acrescentar(self.projeto, {
                "tipo": "envio", "id": identificador, "quando": _agora(), "provedor": self.nome,
                "modelo": self.modelo, "cliente": cliente, "caracteres": len(sistema) + len(usuario),
                "sha256": hashlib.sha256((sistema + "\n" + usuario).encode("utf-8")).hexdigest(),
                "pseudonimizado": bool(pseudonimizar_ligado)})
        except OSError:
            return None, [aviso("ia_registro_falhou", "Não foi possível gravar o registro de envios; nada foi enviado.",
                                "erro")]
        try:
            texto, dados, modelo_real = self._chamar(chave, sistema, usuario, esquema)
        except ErroProvedor as e:
            erro = e
        except Exception as e:
            erro = _classificar(e)
            erro.mensagem = _sem_chave(erro.mensagem, chave)
        else:
            extra = {"modelo_resposta": modelo_real} if modelo_real and modelo_real != self.modelo else {}
            self._resultado(identificador, "ok", **extra)
            if mapa:
                texto, dados = restaurar(texto, mapa), _restaurar_json(dados, mapa)
            return {"texto": texto, "json": dados, "motor": self._motor(modelo_real)}, []
        self._resultado(identificador, f"erro:{erro.codigo}")
        return None, [aviso(erro.codigo, erro.mensagem)]

    def _resultado(self, identificador, resultado, **extra):
        try:
            _acrescentar(self.projeto, {"tipo": "resultado", "id": identificador, "quando": _agora(),
                                        "resultado": resultado, **extra})
        except OSError:
            pass

    def gerar(self, sistema, usuario, *, esquema=None, cliente, partes=()):
        resultado, avisos = self._enviar(sistema, usuario, esquema, cliente, partes, _pseudonimizar_ligado(self.perfil))
        if resultado is not None:
            return {**resultado, "avisos": avisos}
        local = self.local.gerar(sistema, usuario, esquema=esquema, cliente=cliente, partes=partes)
        for a in avisos:
            a["mensagem"] += " O resumo foi feito pelo motor local."
        return {**local, "avisos": avisos + local["avisos"]}


def _criar_cliente_anthropic(chave, endereco):
    try:
        import anthropic
    except ImportError:
        raise ErroProvedor("ia_pacote_ausente", "O pacote 'anthropic' não está instalado (rode: pip install anthropic).")
    return anthropic.Anthropic(api_key=chave, base_url=endereco or None, timeout=TIMEOUT_S)


class ProvedorAnthropic(ProvedorExterno):
    """API de mensagens da Anthropic, pelo SDK oficial. Saída JSON forçada por esquema
    (`output_config.format`); sem `thinking` (o modelo padrão decide) e sem pré-preenchimento."""

    tipo = "anthropic"

    def __init__(self, nome, config, *, fabrica_cliente=None, **kw):
        config = {"modelo": MODELO_ANTHROPIC_PADRAO, **config}
        super().__init__(nome, config, **kw)
        self._fabrica = fabrica_cliente or _criar_cliente_anthropic

    def _pedido(self, sistema, usuario, esquema):
        pedido = {"model": self.modelo, "max_tokens": int(self.config.get("max_tokens") or MAX_TOKENS),
                  "messages": [{"role": "user", "content": usuario}]}
        if sistema:
            pedido["system"] = sistema
        saida = {}
        if esquema:
            saida["format"] = {"type": "json_schema", "schema": _esquema_estrito(esquema, True)}
        if self.config.get("esforco"):
            saida["effort"] = self.config["esforco"]
        if saida:
            pedido["output_config"] = saida
        return pedido

    def _chamar(self, chave, sistema, usuario, esquema):
        cliente = self._fabrica(chave, self.config.get("endereco") or None)
        pedido = self._pedido(sistema, usuario, esquema)
        if self.config.get("fallback_servidor", self.modelo in MODELOS_COM_FALLBACK):
            resposta = cliente.beta.messages.create(betas=[BETA_FALLBACK], fallbacks="default", **pedido)
        else:
            resposta = cliente.messages.create(**pedido)
        if getattr(resposta, "stop_reason", None) == "refusal":
            raise ErroProvedor("ia_recusa_do_provedor", "O provedor recusou a solicitação.")
        texto = "".join(b.text for b in resposta.content if getattr(b, "type", "") == "text")
        dados = None
        if esquema:
            dados = _json_da_resposta(texto)
            if dados is None:
                raise ErroProvedor("ia_resposta_invalida", "A resposta do provedor não veio no formato pedido.")
        return texto, dados, getattr(resposta, "model", None)


def _http_post(url, cabecalhos, corpo, timeout):
    """Transporte padrão do provedor compatível com OpenAI: (status, corpo em bytes)."""
    pedido = urllib.request.Request(url, data=corpo, headers=cabecalhos, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class ProvedorOpenAI(ProvedorExterno):
    """Qualquer serviço com `POST <endereço>/chat/completions` no formato da OpenAI.
    `formato_json` (config): `json_schema` (padrão), `json_object` ou `nenhum` (o esquema vai no texto)."""

    tipo = "openai_compativel"

    def __init__(self, nome, config, *, transporte=None, **kw):
        super().__init__(nome, config, **kw)
        self._transporte = transporte or _http_post

    def _url(self):
        base = (self.config.get("endereco") or "").rstrip("/")
        return base if base.endswith("/chat/completions") else base + "/chat/completions"

    def _chamar(self, chave, sistema, usuario, esquema):
        formato = self.config.get("formato_json", "json_schema")
        if esquema and formato != "json_schema":
            sistema += "\n\nResponda apenas com um objeto JSON neste esquema:\n" + json.dumps(esquema, ensure_ascii=False)
        corpo = {"model": self.modelo, "messages": [{"role": "system", "content": sistema},
                                                     {"role": "user", "content": usuario}]}
        if esquema and formato == "json_schema":
            corpo["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "resposta", "strict": True, "schema": _esquema_estrito(esquema, False)}}
        elif esquema and formato == "json_object":
            corpo["response_format"] = {"type": "json_object"}
        cabecalhos = {"Content-Type": "application/json", "Authorization": f"Bearer {chave}"}
        status, bruto = self._transporte(self._url(), cabecalhos, json.dumps(corpo).encode("utf-8"), TIMEOUT_S)
        if status in (401, 403):
            raise ErroProvedor("ia_chave_invalida", "O provedor recusou a chave: confira a chave cadastrada.")
        if status != 200:
            raise ErroProvedor("ia_erro_provedor", f"O provedor respondeu com erro HTTP {status}"
                                                   f"{_detalhe_http(bruto, chave)}.")
        try:
            escolha = json.loads(bruto)["choices"][0]
            texto = escolha["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise ErroProvedor("ia_resposta_invalida", "A resposta do provedor não tem o formato esperado.")
        if escolha.get("finish_reason") == "content_filter":
            raise ErroProvedor("ia_recusa_do_provedor", "O provedor recusou a solicitação.")
        dados = None
        if esquema:
            dados = _json_da_resposta(texto)
            if dados is None:
                raise ErroProvedor("ia_resposta_invalida", "A resposta do provedor não veio no formato pedido.")
        return texto, dados, json.loads(bruto).get("model")


def _detalhe_http(bruto, chave):
    try:
        msg = json.loads(bruto)["error"]["message"]
    except Exception:
        return ""
    return ": " + _sem_chave(msg, chave)


CLASSES = {"anthropic": ProvedorAnthropic, "openai_compativel": ProvedorOpenAI}


# --- catálogo de provedores (tela IA) ----------------------------------------

def provedores():
    """Catálogo `{id: {nome, tipo, endereco, modelo, ...}}`, sem chaves (config.json, `ia_provedores`)."""
    try:  # lê o config.json direto (o exemplo nunca traz provedores)
        cfg = comum.load_json(comum.CONFIG_FILE, {})
        catalogo = cfg.get(CHAVE_CONFIG, {}) if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in catalogo.items() if isinstance(v, dict) and v.get("tipo") in CLASSES} \
        if isinstance(catalogo, dict) else {}


def _salvar_catalogo(catalogo):
    cfg = comum.load_json(comum.CONFIG_FILE, None) if Path(comum.CONFIG_FILE).exists() else None
    cfg = cfg if isinstance(cfg, dict) else dict(comum.load_json(comum.RAIZ / "config.exemplo.json", {}))
    cfg[CHAVE_CONFIG] = catalogo
    comum.save_json(comum.CONFIG_FILE, cfg)


def chave_configurada(nome):
    return bool(acesso.obter(PREFIXO_CHAVE + comum.slug(nome)))


def _endereco_ok(endereco):
    u = urllib.parse.urlparse(endereco)
    if u.scheme not in ("http", "https") or not u.hostname:
        return "O endereço precisa começar com https:// (ou http:// para um serviço neste computador)."
    if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
        return "Endereço sem https: a chave e o texto viajariam sem proteção. Use https://."
    return None


def cadastrar(nome, tipo, modelo, endereco="", chave=None, **opcoes):
    """Cadastra ou atualiza um provedor. Devolve lista de avisos; **vazia = salvo**. Chave vazia/None
    mantém a que já está no cofre. `opcoes` aceitas: `fallback_servidor` (bool, Anthropic), `esforco`
    (Anthropic), `formato_json` (compatível com OpenAI), `max_tokens`."""
    nome = (nome or "").strip()
    chave_id = comum.slug(nome)
    erro = None
    if not nome or chave_id in ("sem-nome", "local"):
        erro = "Dê um nome ao provedor (o nome \"local\" é reservado)."
    elif tipo not in CLASSES:
        erro = "Tipo de provedor desconhecido."
    elif not (modelo or "").strip():
        erro = "Informe o modelo."
    elif tipo == "openai_compativel" and not (endereco or "").strip():
        erro = "Informe o endereço da API (ex.: https://api.exemplo.com/v1)."
    elif (endereco or "").strip():
        erro = _endereco_ok(endereco.strip())
    if erro:
        return [aviso("ia_cadastro_invalido", erro, "erro")]
    registro = {"nome": nome, "tipo": tipo, "modelo": modelo.strip(), "endereco": (endereco or "").strip()}
    for k in ("fallback_servidor", "esforco", "formato_json", "max_tokens"):
        if opcoes.get(k) not in (None, ""):
            registro[k] = opcoes[k]
    if chave:
        try:
            acesso.guardar(PREFIXO_CHAVE + chave_id, chave.strip())
        except Exception:
            return [aviso("ia_cofre_indisponivel", "Não foi possível guardar a chave no cofre do sistema; nada foi salvo.",
                          "erro")]
    catalogo = dict(provedores())
    catalogo[chave_id] = registro
    _salvar_catalogo(catalogo)
    return []


def remover(nome):
    """Tira o provedor do catálogo e esvazia a chave no cofre."""
    chave_id = comum.slug(nome)
    catalogo = dict(provedores())
    if chave_id not in catalogo:
        return False
    del catalogo[chave_id]
    _salvar_catalogo(catalogo)
    try:
        acesso.guardar(PREFIXO_CHAVE + chave_id, "")
    except Exception:
        pass
    return True


# --- escolha do provedor -----------------------------------------------------

def _resolver(perfil, cliente):
    """(id do provedor externo | None, config | None, avisos de por que não)."""
    try:
        escolhido = perfil["ia"]["provedor"]
    except Exception:
        return None, None, []
    if not isinstance(escolhido, str) or comum.slug(escolhido) in ("sem-nome", "local"):
        return None, None, []
    chave_id = comum.slug(escolhido)
    config = provedores().get(chave_id)
    if config is None:
        return None, None, [aviso("ia_provedor_desconhecido", f"O provedor '{escolhido}' não está cadastrado (tela IA): "
                                                               "usando o motor local.")]
    permitido, motivo = consentimento(perfil, cliente, chave_id)
    if not permitido:
        return None, None, [aviso("ia_externa_sem_consentimento", motivo + " Usando o motor local.")]
    return chave_id, config, []


def provedor(perfil, cliente, *, projeto=None, local=None, transporte=None, fabrica_cliente=None):
    """O provedor a usar para este relatório e cliente: o externo escolhido **só com consentimento
    explícito**; em qualquer outro caso, o local (com o aviso de por quê, devolvido no `gerar`).

    `projeto`: pasta do relatório (`Path`), slug ou None (o ativo), onde ficam registro e mapa.
    `local`: `ProvedorLocal` a usar (padrão: Ollama). `transporte`/`fabrica_cliente`: substitutos de
    rede para testes (ver cabeçalho)."""
    local = local or ProvedorLocal()
    chave_id, config, avisos = _resolver(perfil, cliente)
    if chave_id is None:
        return local.com_avisos(avisos) if avisos else local
    extra = {"transporte": transporte} if config["tipo"] == "openai_compativel" else {"fabrica_cliente": fabrica_cliente}
    return CLASSES[config["tipo"]](chave_id, config, perfil=perfil, projeto=projeto, local=local, **extra)


def testar(nome, *, projeto=None, transporte=None, fabrica_cliente=None):
    """Botão Testar: manda uma frase fixa (nenhum dado de cliente) ao provedor, **sem** cair no local.
    -> {"ok", "motor", "resposta", "avisos"}. Fica no registro de envios, como qualquer envio."""
    chave_id = comum.slug(nome)
    config = provedores().get(chave_id)
    if config is None:
        return {"ok": False, "motor": None, "resposta": "", "avisos": [aviso("ia_provedor_desconhecido",
                                                                           "Provedor não cadastrado.", "erro")]}
    perfil = {"ia": {"provedor": chave_id, "consentimento_externo": True, "pseudonimizar": False}}
    extra = {"transporte": transporte} if config["tipo"] == "openai_compativel" else {"fabrica_cliente": fabrica_cliente}
    prov = CLASSES[config["tipo"]](chave_id, config, perfil=perfil, projeto=projeto, **extra)
    resultado, avisos = prov._enviar("Responda somente com a palavra: ok", "Teste de conexão.", None,
                                     CLIENTE_TESTE, (), False)
    if resultado is None:
        return {"ok": False, "motor": None, "resposta": "", "avisos": avisos}
    return {"ok": True, "motor": resultado["motor"], "resposta": resultado["texto"].strip()[:80], "avisos": []}


# --- selo --------------------------------------------------------------------

def selo(motor):
    """Rótulo para as telas: "local" ou "externa: <provedor>". Sem motor (evento da Fase 1) = local."""
    motor = (motor or "").strip()
    if not motor or motor == "nenhum" or motor.split(":", 1)[0] == "local":
        return "local"
    partes = motor.split(":", 2)
    return f"externa: {partes[1] if partes[0] == 'externo' and len(partes) > 1 else motor}"


def selo_para(perfil, cliente):
    """O selo do que **seria** usado agora para este cliente (para mostrar antes de gerar)."""
    chave_id, _, _ = _resolver(perfil, cliente)
    return f"externa: {chave_id}" if chave_id else "local"
