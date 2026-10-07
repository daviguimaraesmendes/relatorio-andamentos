"""Testes dos provedores de IA (src/ia.py) e da tela /ia (src/painel/ia.py).

Sem rede, sem Ollama, sem SDK e sem cofre reais: o Ollama é uma função falsa, o provedor compatível com
OpenAI recebe um transporte falso, o da Anthropic recebe um cliente de SDK falso e o cofre (acesso.obter /
acesso.guardar) é um dicionário. Dados fictícios.

    python3 -m unittest tests/test_ia.py -v
"""
import hashlib
import json
import socket
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import ficticio  # noqa: E402
import acesso  # noqa: E402
import comum  # noqa: E402
import ia  # noqa: E402

CLIENTE = "Cliente Exemplo 01 Ltda"
CLIENTE_2 = "Cliente Exemplo 02 S.A."
CONTRARIA = "Pessoa Ficticia 0123"
CHAVE = "chave-ficticia-ABCDEF123456"
SEGREDO_TEXTO = "TEXTO-SIGILOSO-DO-DOCUMENTO"
CPF, CNPJ, EMAIL = "123.456.789-09", "12.345.678/0001-95", "pessoa.ficticia@exemplo.invalid"
ESQUEMA = {"type": "object",
           "properties": {"conteudo": {"type": "string"}, "prazo": {"type": ["string", "null"]}},
           "required": ["conteudo", "prazo"]}


class Cofre:
    """Substitui acesso.obter / acesso.guardar por um dicionário."""

    def __init__(self):
        self.dados = {}

    def __enter__(self):
        self.patches = [mock.patch.object(acesso, "obter", lambda c: self.dados.get(c)),
                        mock.patch.object(acesso, "guardar", lambda c, v: self.dados.__setitem__(c, v))]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()


def ollama_falso(chamadas=None, resposta=None, falha=None):
    def ollama(caminho, corpo=None, timeout=300):
        if chamadas is not None:
            chamadas.append((caminho, corpo))
        if falha:
            raise falha
        conteudo = resposta if resposta is not None else json.dumps({"conteudo": "resumo local", "prazo": None})
        return {"message": {"content": conteudo}}
    return ollama


def local_falso(chamadas=None, **kw):
    return ia.ProvedorLocal(modelo="modelo-teste:1b", ollama=ollama_falso(chamadas, **kw))


def resposta_openai(conteudo, status=200, modelo="modelo-x", finish="stop"):
    corpo = {"model": modelo, "choices": [{"message": {"content": conteudo}, "finish_reason": finish}]}
    return status, json.dumps(corpo).encode()


class Transporte:
    """Transporte HTTP falso: guarda os pedidos e devolve o que `resposta` (função ou tupla) mandar."""

    def __init__(self, resposta=None, falha=None):
        self.pedidos, self.resposta, self.falha = [], resposta, falha

    def __call__(self, url, cabecalhos, corpo, timeout):
        self.pedidos.append({"url": url, "cabecalhos": cabecalhos, "corpo": json.loads(corpo)})
        if self.falha:
            raise self.falha
        r = self.resposta
        return r(self.pedidos[-1]) if callable(r) else (r or resposta_openai(json.dumps({"conteudo": "ok", "prazo": None})))


def perfil(provedor="externo-a", consentimento=True, por_cliente=None, pseudonimizar=True):
    return {"versao": 1, "ia": {"provedor": provedor, "consentimento_externo": consentimento,
                                "por_cliente": por_cliente or {}, "pseudonimizar": pseudonimizar}}


class ClienteSDKFalso:
    """Imita o que o SDK da Anthropic usa: messages.create e beta.messages.create."""

    def __init__(self, resposta=None, falha=None):
        self.chamadas = []
        self.resposta, self.falha = resposta, falha
        self.messages = SimpleNamespace(create=lambda **kw: self._criar("messages", kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self._criar("beta", kw)))

    def _criar(self, via, kw):
        self.chamadas.append((via, kw))
        if self.falha:
            raise self.falha
        return self.resposta or resposta_sdk(json.dumps({"conteudo": "resumo claude", "prazo": "15 dias"}))


def resposta_sdk(texto, stop="end_turn", modelo="claude-opus-5-5"):
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
                           stop_reason=stop, model=modelo)


def erro_sdk(nome, mensagem="erro"):
    """Exceção com o nome de classe do SDK (a classificação é pelo nome, para não exigir o pacote)."""
    return type(nome, (Exception,), {})(mensagem)


class Base(unittest.TestCase):
    """Cofre falso, config.json temporário e um relatório temporário por teste; a rede é proibida."""

    def setUp(self):
        self.cofre = Cofre().__enter__()
        self.addCleanup(self.cofre.__exit__)
        nome = f"{type(self).__name__}-{self._testMethodName}"
        self.config = TMP / f"config-ia-{nome}.json"
        self.config.unlink(missing_ok=True)
        p = mock.patch.object(comum, "CONFIG_FILE", self.config)
        p.start()
        self.addCleanup(p.stop)
        self.projeto = TMP / "projetos-ia" / nome
        (self.projeto / "data").mkdir(parents=True, exist_ok=True)
        for alvo in (mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede usada")),
                     mock.patch.object(socket.socket, "connect", side_effect=AssertionError("rede usada"))):
            alvo.start()
            self.addCleanup(alvo.stop)

    def cadastrar(self, nome="externo-a", tipo="openai_compativel", **kw):
        kw.setdefault("modelo", "modelo-x")
        kw.setdefault("endereco", "https://api.exemplo.invalid/v1" if tipo == "openai_compativel" else "")
        self.assertEqual(ia.cadastrar(nome, tipo, chave=CHAVE, **kw), [])

    def arquivos_do_relatorio(self):
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in self.projeto.rglob("*") if p.is_file())


# --- consentimento -----------------------------------------------------------

class Consentimento(Base):
    def test_so_com_true_explicito(self):
        casos = [
            (perfil(consentimento=True), CLIENTE, True),
            (perfil(consentimento=False), CLIENTE, False),
            (perfil(consentimento="true"), CLIENTE, False),
            (perfil(consentimento=1), CLIENTE, False),
            (perfil(consentimento=None), CLIENTE, False),
            (perfil(consentimento=True, provedor="local"), CLIENTE, False),
            (perfil(consentimento=True, provedor=""), CLIENTE, False),
            (perfil(consentimento=True, provedor=None), CLIENTE, False),
            (perfil(consentimento=True, provedor=["x"]), CLIENTE, False),
            # por cliente prevalece nos dois sentidos
            (perfil(consentimento=True, por_cliente={CLIENTE: False}), CLIENTE, False),
            (perfil(consentimento=False, por_cliente={CLIENTE: True}), CLIENTE, True),
            (perfil(consentimento=False, por_cliente={CLIENTE: True}), CLIENTE_2, False),
            (perfil(consentimento=True, por_cliente={CLIENTE: True}), CLIENTE_2, True),
            (perfil(consentimento=False, por_cliente={CLIENTE: "true"}), CLIENTE, False),
            (perfil(consentimento=True, por_cliente={CLIENTE: "true"}), CLIENTE, False),
            (perfil(consentimento=False, por_cliente={CLIENTE.upper(): True}), CLIENTE, True),
            (perfil(consentimento=False, por_cliente={CLIENTE: True, CLIENTE.upper(): False}), CLIENTE, False),
        ]
        for p, cliente, esperado in casos:
            self.assertEqual(ia.consentimento(p, cliente)[0], esperado, (p, cliente))

    def test_perfil_malformado_nunca_consente(self):
        for p in (None, [], "texto", 0, {}, {"ia": None}, {"ia": "externo-a"}, {"ia": []},
                  {"ia": {"provedor": "externo-a", "por_cliente": ["x"]}}, {"ia": {"consentimento_externo": True}}):
            ok, motivo = ia.consentimento(p, CLIENTE)
            self.assertFalse(ok, p)
            self.assertTrue(motivo)
        for cliente in (None, "", ["lista"], 7):                 # cliente malformado, perfil sem consentimento do relatório
            self.assertFalse(ia.consentimento(perfil(consentimento=False, por_cliente={CLIENTE: True}), cliente)[0])
        # por_cliente malformado cai no do relatório, que aqui é explícito
        malformado = {"ia": {"provedor": "externo-a", "consentimento_externo": True, "por_cliente": ["x"]}}
        self.assertTrue(ia.consentimento(malformado, CLIENTE)[0])

    def test_provedor_diferente_do_escolhido(self):
        self.assertFalse(ia.consentimento(perfil(provedor="externo-a"), CLIENTE, "externo-b")[0])
        self.assertTrue(ia.consentimento(perfil(provedor="Externo A"), CLIENTE, "externo-a")[0])


class SemConsentimentoNaoChamaARede(Base):
    """Teste obrigatório: sem `true` explícito, nem o transporte, nem o SDK, nem o socket são tocados."""

    def chamar(self, p):
        self.cadastrar()
        self.cadastrar("externo-b", "anthropic", modelo="claude-opus-5-5")
        proibido = Transporte(falha=AssertionError("transporte chamado sem consentimento"))

        def fabrica(chave, endereco):
            raise AssertionError("SDK criado sem consentimento")
        locais = []
        for nome in ("externo-a", "externo-b"):
            p2 = json.loads(json.dumps(p)) if isinstance(p, dict) else p
            if isinstance(p2, dict) and isinstance(p2.get("ia"), dict) and "provedor" in p2["ia"]:
                p2["ia"]["provedor"] = nome
            prov = ia.provedor(p2, CLIENTE, projeto=self.projeto, local=local_falso(locais),
                               transporte=proibido, fabrica_cliente=fabrica)
            r = prov.gerar("sistema", SEGREDO_TEXTO, esquema=ESQUEMA, cliente=CLIENTE)
            self.assertTrue(r["motor"].startswith("local:"), r)
            self.assertEqual(ia.selo(r["motor"]), "local")
            self.assertIn("ia_externa_sem_consentimento", [a["codigo"] for a in r["avisos"]])
            self.assertIn("consentimento", " ".join(a["mensagem"] for a in r["avisos"]).lower())
        self.assertEqual(len(locais), 2)
        self.assertEqual(proibido.pedidos, [])
        self.assertEqual(ia.registro_de_envios(self.projeto), [])

    def test_perfis_sem_consentimento(self):
        for p in (perfil(consentimento=False), perfil(consentimento="true"), perfil(consentimento=1),
                  perfil(consentimento=True, por_cliente={CLIENTE: False}), {"ia": {"provedor": "externo-a"}}):
            with self.subTest(p=p):
                self.chamar(p)

    def test_perfil_malformado(self):
        for p in (None, [], "texto", {}, {"ia": []}, {"ia": "externo-a"},
                  {"ia": {"provedor": "externo-a", "por_cliente": "x"}}):
            with self.subTest(p=p):
                self.cadastrar()
                prov = ia.provedor(p, CLIENTE, projeto=self.projeto, local=local_falso(),
                                   transporte=Transporte(falha=AssertionError("rede")), fabrica_cliente=None)
                self.assertIsInstance(prov, ia.ProvedorLocal)
                self.assertTrue(prov.gerar("s", "u", cliente=CLIENTE)["motor"].startswith("local:"))

    def test_provedor_externo_montado_a_mao_tambem_recusa(self):
        self.cadastrar()
        config = ia.provedores()["externo-a"]
        transporte = Transporte(falha=AssertionError("rede"))
        # mesmo construído direto, confere o consentimento a cada gerar (e para o cliente do gerar)
        for p, cliente in ((perfil(consentimento=False), CLIENTE), (perfil(por_cliente={CLIENTE_2: False}), CLIENTE_2),
                           (perfil(consentimento="sim"), CLIENTE)):
            prov = ia.ProvedorOpenAI("externo-a", config, perfil=p, projeto=self.projeto, local=local_falso(),
                                     transporte=transporte)
            r = prov.gerar("s", "u", cliente=cliente)
            self.assertTrue(r["motor"].startswith("local:"))
        self.assertEqual(transporte.pedidos, [])

    def test_consentimento_por_cliente_vale_so_para_ele(self):
        self.cadastrar()
        p = perfil(consentimento=False, por_cliente={CLIENTE: True, CLIENTE_2: False})
        t = Transporte()
        prov = ia.provedor(p, CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t)
        self.assertTrue(prov.gerar("s", "u", cliente=CLIENTE)["motor"].startswith("externo:"))
        self.assertEqual(len(t.pedidos), 1)
        # o mesmo objeto, chamado para outro cliente, não envia
        r = prov.gerar("s", "u", cliente=CLIENTE_2)
        self.assertTrue(r["motor"].startswith("local:"))
        self.assertEqual(len(t.pedidos), 1)
        self.assertEqual(ia.selo_para(p, CLIENTE), "externa: externo-a")
        self.assertEqual(ia.selo_para(p, CLIENTE_2), "local")

    def test_provedor_nao_cadastrado_cai_no_local(self):
        r = ia.provedor(perfil(provedor="fantasma"), CLIENTE, projeto=self.projeto,
                        local=local_falso()).gerar("s", "u", cliente=CLIENTE)
        self.assertTrue(r["motor"].startswith("local:"))
        self.assertEqual(r["avisos"][0]["codigo"], "ia_provedor_desconhecido")


# --- provedor compatível com OpenAI ------------------------------------------

class CompativelComOpenAI(Base):
    def test_envio_e_resposta(self):
        self.cadastrar()
        t = Transporte(lambda p: resposta_openai(json.dumps({"conteudo": "resumo externo", "prazo": None})))
        prov = ia.provedor(perfil(pseudonimizar=False), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t)
        r = prov.gerar("Sistema X", "Usuário Y", esquema=ESQUEMA, cliente=CLIENTE)
        self.assertEqual(r["json"], {"conteudo": "resumo externo", "prazo": None})
        self.assertEqual(r["motor"], "externo:externo-a:modelo-x")
        self.assertEqual(ia.selo(r["motor"]), "externa: externo-a")
        self.assertEqual(r["avisos"], [])
        pedido = t.pedidos[0]
        self.assertEqual(pedido["url"], "https://api.exemplo.invalid/v1/chat/completions")
        self.assertEqual(pedido["cabecalhos"]["Authorization"], f"Bearer {CHAVE}")
        self.assertEqual(pedido["corpo"]["model"], "modelo-x")
        self.assertEqual([m["role"] for m in pedido["corpo"]["messages"]], ["system", "user"])
        rf = pedido["corpo"]["response_format"]
        self.assertEqual(rf["type"], "json_schema")
        self.assertIs(rf["json_schema"]["schema"]["additionalProperties"], False)
        self.assertNotIn("additionalProperties", ESQUEMA)  # o esquema do chamador não é alterado

    def test_formatos_alternativos_de_json(self):
        for formato, esperado in (("json_object", {"type": "json_object"}), ("nenhum", None)):
            with self.subTest(formato):
                self.cadastrar(formato_json=formato)
                t = Transporte(lambda p: resposta_openai('```json\n{"conteudo": "c", "prazo": null}\n```'))
                r = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(),
                                transporte=t).gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE)
                self.assertEqual(r["json"]["conteudo"], "c")
                self.assertEqual(t.pedidos[0]["corpo"].get("response_format"), esperado)
                self.assertIn("esquema", t.pedidos[0]["corpo"]["messages"][0]["content"])

    def test_sem_esquema_devolve_so_texto(self):
        self.cadastrar()
        t = Transporte(lambda p: resposta_openai("texto livre"))
        r = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(),
                        transporte=t).gerar("s", "u", cliente=CLIENTE)
        self.assertEqual((r["texto"], r["json"]), ("texto livre", None))
        self.assertNotIn("response_format", t.pedidos[0]["corpo"])

    def test_barra_final_no_endereco(self):
        self.cadastrar(endereco="https://api.exemplo.invalid/v1/")
        t = Transporte()
        ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t).gerar(
            "s", "u", cliente=CLIENTE)
        self.assertEqual(t.pedidos[0]["url"], "https://api.exemplo.invalid/v1/chat/completions")


# --- provedor Anthropic ------------------------------------------------------

class AnthropicTestes(Base):
    def fabrica(self, cliente):
        usados = []

        def f(chave, endereco):
            usados.append((chave, endereco))
            return cliente
        f.usados = usados
        return f

    def test_pedido_padrao(self):
        self.assertTrue(ia.cadastrar("claude", "anthropic", "", chave=CHAVE))      # modelo é obrigatório
        self.assertEqual(ia.cadastrar("claude", "anthropic", ia.MODELO_ANTHROPIC_PADRAO, chave=CHAVE), [])
        sdk = ClienteSDKFalso()
        fab = self.fabrica(sdk)
        prov = ia.provedor(perfil("claude", pseudonimizar=False), CLIENTE, projeto=self.projeto, local=local_falso(),
                           fabrica_cliente=fab)
        r = prov.gerar("Sistema", "Usuário", esquema=ESQUEMA, cliente=CLIENTE)
        self.assertEqual(r["json"], {"conteudo": "resumo claude", "prazo": "15 dias"})
        self.assertEqual(r["motor"], "externo:claude:claude-opus-5-5")
        self.assertEqual(ia.selo(r["motor"]), "externa: claude")
        self.assertEqual(fab.usados, [(CHAVE, None)])
        via, kw = sdk.chamadas[0]
        self.assertEqual(via, "beta")                       # fallbacks do servidor: ligado por padrão no Opus 5.5
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["system"], "Sistema")
        self.assertEqual(kw["messages"], [{"role": "user", "content": "Usuário"}])
        self.assertGreaterEqual(kw["max_tokens"], 16000)
        for proibido in ("thinking", "temperature", "top_p", "top_k", "tool_choice"):
            self.assertNotIn(proibido, kw)
        formato = kw["output_config"]["format"]
        self.assertEqual(formato["type"], "json_schema")
        esquema = formato["schema"]
        self.assertIs(esquema["additionalProperties"], False)
        self.assertEqual(esquema["properties"]["prazo"], {"anyOf": [{"type": "string"}, {"type": "null"}]})
        self.assertEqual(ESQUEMA["properties"]["prazo"], {"type": ["string", "null"]})  # original intacto

    def test_sem_fallback_do_servidor_usa_o_endpoint_normal(self):
        ia.cadastrar("claude", "anthropic", "claude-haiku-4-5", chave=CHAVE, endereco="", fallback_servidor=False)
        sdk = ClienteSDKFalso(resposta_sdk("só texto", modelo="claude-haiku-4-5"))
        r = ia.provedor(perfil("claude"), CLIENTE, projeto=self.projeto, local=local_falso(),
                        fabrica_cliente=self.fabrica(sdk)).gerar("s", "u", cliente=CLIENTE)
        self.assertEqual(sdk.chamadas[0][0], "messages")
        self.assertNotIn("fallbacks", sdk.chamadas[0][1])
        self.assertNotIn("output_config", sdk.chamadas[0][1])    # sem esquema, sem formato
        self.assertEqual((r["texto"], r["json"], r["motor"]), ("só texto", None, "externo:claude:claude-haiku-4-5"))

    def test_outro_modelo_responde_pelo_reencaminhamento(self):
        ia.cadastrar("claude", "anthropic", "claude-opus-5-5", chave=CHAVE)
        sdk = ClienteSDKFalso(resposta_sdk(json.dumps({"conteudo": "c", "prazo": None}), modelo="claude-opus-4-8"))
        r = ia.provedor(perfil("claude"), CLIENTE, projeto=self.projeto, local=local_falso(),
                        fabrica_cliente=self.fabrica(sdk)).gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE)
        self.assertEqual(r["motor"], "externo:claude:claude-opus-4-8")      # o motor é o que respondeu de fato
        self.assertEqual(ia.registro_de_envios(self.projeto)[0]["modelo_resposta"], "claude-opus-4-8")

    def test_endereco_proprio(self):
        ia.cadastrar("claude", "anthropic", "claude-opus-5-5", chave=CHAVE, endereco="https://gateway.exemplo.invalid")
        fab = self.fabrica(ClienteSDKFalso())
        ia.provedor(perfil("claude"), CLIENTE, projeto=self.projeto, local=local_falso(),
                    fabrica_cliente=fab).gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE)
        self.assertEqual(fab.usados[0][1], "https://gateway.exemplo.invalid")

    def test_pacote_ausente_cai_no_local(self):
        ia.cadastrar("claude", "anthropic", "claude-opus-5-5", chave=CHAVE)
        with mock.patch.dict(sys.modules, {"anthropic": None}):      # `import anthropic` falha
            r = ia.provedor(perfil("claude"), CLIENTE, projeto=self.projeto, local=local_falso()).gerar(
                "s", "u", esquema=ESQUEMA, cliente=CLIENTE)
        self.assertTrue(r["motor"].startswith("local:"))
        self.assertEqual(r["avisos"][0]["codigo"], "ia_pacote_ausente")


# --- falhas e fallback para o local -------------------------------------------

class FallbackParaOLocal(Base):
    def gerar(self, transporte, locais=None, **kw):
        self.cadastrar()
        prov = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(locais, **kw), transporte=transporte)
        return prov.gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE)

    def confere(self, r, codigo, locais):
        self.assertTrue(r["motor"].startswith("local:"), r)
        self.assertEqual(ia.selo(r["motor"]), "local")
        self.assertEqual(r["json"], {"conteudo": "resumo local", "prazo": None})
        self.assertEqual(r["avisos"][0]["codigo"], codigo)
        self.assertEqual(r["avisos"][0]["nivel"], "atencao")
        self.assertIn("motor local", r["avisos"][0]["mensagem"])
        self.assertEqual(len(locais), 1)

    def test_sem_chave(self):
        self.cadastrar()
        self.cofre.dados.clear()
        t, locais = Transporte(falha=AssertionError("rede")), []
        r = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(locais),
                        transporte=t).gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE)
        self.confere(r, "ia_sem_chave", locais)
        self.assertEqual(t.pedidos, [])
        self.assertEqual(ia.registro_de_envios(self.projeto), [])    # nada saiu, nada registrado

    def test_sem_rede(self):
        for falha in (urllib.error.URLError("sem rede"), TimeoutError("lento"), ConnectionResetError("caiu")):
            with self.subTest(falha=type(falha).__name__):
                locais = []
                self.confere(self.gerar(Transporte(falha=falha), locais), "ia_falha_rede", locais)

    def test_erros_http(self):
        for status, codigo in ((401, "ia_chave_invalida"), (403, "ia_chave_invalida"), (429, "ia_erro_provedor"),
                               (500, "ia_erro_provedor"), (404, "ia_erro_provedor")):
            with self.subTest(status=status):
                locais = []
                self.confere(self.gerar(Transporte(lambda p, s=status: (s, b'{"error": {"message": "falhou"}}')), locais),
                             codigo, locais)

    def test_resposta_fora_do_formato(self):
        for resposta in (resposta_openai("isto não é json"), (200, b"<html>"), (200, b'{"choices": []}'),
                         resposta_openai('["lista"]')):
            with self.subTest(resposta=resposta):
                locais = []
                self.confere(self.gerar(Transporte(lambda p, r=resposta: r), locais), "ia_resposta_invalida", locais)

    def test_recusa_do_provedor(self):
        locais = []
        self.confere(self.gerar(Transporte(lambda p: resposta_openai("", finish="content_filter")), locais),
                     "ia_recusa_do_provedor", locais)

    def test_erros_do_sdk(self):
        ia.cadastrar("claude", "anthropic", "claude-opus-5-5", chave=CHAVE)
        for falha, codigo in ((erro_sdk("APIConnectionError"), "ia_falha_rede"), (erro_sdk("APITimeoutError"), "ia_falha_rede"),
                              (erro_sdk("AuthenticationError"), "ia_chave_invalida"),
                              (erro_sdk("PermissionDeniedError"), "ia_chave_invalida"),
                              (erro_sdk("RateLimitError"), "ia_erro_provedor"), (erro_sdk("BadRequestError"), "ia_erro_provedor")):
            with self.subTest(falha=type(falha).__name__):
                locais = []
                prov = ia.provedor(perfil("claude"), CLIENTE, projeto=self.projeto, local=local_falso(locais),
                                   fabrica_cliente=lambda c, e, f=falha: ClienteSDKFalso(falha=f))
                self.confere(prov.gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE), codigo, locais)

    def test_recusa_do_sdk_e_json_invalido(self):
        ia.cadastrar("claude", "anthropic", "claude-opus-5-5", chave=CHAVE)
        for resposta, codigo in ((resposta_sdk("", stop="refusal"), "ia_recusa_do_provedor"),
                                 (resposta_sdk("sem json"), "ia_resposta_invalida")):
            locais = []
            prov = ia.provedor(perfil("claude"), CLIENTE, projeto=self.projeto, local=local_falso(locais),
                               fabrica_cliente=lambda c, e, r=resposta: ClienteSDKFalso(r))
            self.confere(prov.gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE), codigo, locais)

    def test_registro_marca_o_erro(self):
        self.gerar(Transporte(falha=urllib.error.URLError("x")))
        (envio,) = ia.registro_de_envios(self.projeto)
        self.assertEqual(envio["resultado"], "erro:ia_falha_rede")

    def test_local_tambem_indisponivel(self):
        locais = []
        r = self.gerar(Transporte(falha=urllib.error.URLError("x")), locais, falha=OSError("ollama parado"))
        self.assertEqual((r["texto"], r["json"], r["motor"]), ("", None, "nenhum"))
        self.assertEqual([a["codigo"] for a in r["avisos"]], ["ia_falha_rede", "ia_local_indisponivel"])
        self.assertEqual(r["avisos"][1]["nivel"], "erro")
        self.assertEqual(ia.selo("nenhum"), "local")


# --- provedor local ----------------------------------------------------------

class Local(Base):
    def test_pedido_ao_ollama(self):
        chamadas = []
        r = local_falso(chamadas).gerar("Sistema", "Usuário", esquema=ESQUEMA, cliente=CLIENTE)
        caminho, corpo = chamadas[0]
        self.assertEqual(caminho, "/api/chat")
        self.assertEqual(corpo["model"], "modelo-teste:1b")
        self.assertEqual(corpo["format"], ESQUEMA)
        self.assertEqual(corpo["options"]["temperature"], 0)
        self.assertEqual((r["motor"], r["json"], r["avisos"]), ("local:modelo-teste:1b",
                                                                  {"conteudo": "resumo local", "prazo": None}, []))

    def test_sem_esquema_e_json_ruim(self):
        chamadas = []
        r = local_falso(chamadas, resposta="texto livre").gerar("s", "u", cliente=CLIENTE)
        self.assertEqual((r["texto"], r["json"]), ("texto livre", None))
        self.assertNotIn("format", chamadas[0][1])
        r = local_falso(resposta="não é json").gerar("s", "u", esquema=ESQUEMA, cliente=CLIENTE)
        self.assertEqual(r["avisos"][0]["codigo"], "ia_resposta_invalida")

    def test_padrao_sem_perfil_e_local(self):
        self.assertIsInstance(ia.provedor(None, CLIENTE), ia.ProvedorLocal)
        self.assertIsInstance(ia.provedor({"ia": {"provedor": "local", "consentimento_externo": True}}, CLIENTE),
                              ia.ProvedorLocal)

    def test_reaproveita_o_resumir(self):
        """O local usa as funções do resumir.py (não duplica)."""
        import resumir
        chamadas = []

        def ollama(caminho, corpo=None, timeout=300):
            chamadas.append(corpo)
            return {"message": {"content": "{}"}}
        with mock.patch.object(resumir, "_ollama", ollama), mock.patch.object(resumir, "modelo_escolhido",
                                                                               lambda: "gemma-teste"):
            r = ia.ProvedorLocal().gerar("s", "u", cliente=CLIENTE)
        self.assertEqual(r["motor"], "local:gemma-teste")
        self.assertEqual(chamadas[0]["model"], "gemma-teste")


# --- pseudonimização ---------------------------------------------------------

class Pseudonimizacao(Base):
    TEXTO = (f"O cliente {CLIENTE} move ação contra {CONTRARIA} (CPF {CPF}) e contra a empresa de CNPJ {CNPJ}. "
             f"Contato: {EMAIL}. Processo {ficticio.numero_ficticio(0)}; recurso {ficticio.numero_ficticio(1)}. "
             f"{CONTRARIA} pediu o prazo.")

    def test_ida_e_volta(self):
        pseudo, mapa = ia.pseudonimizar(self.TEXTO, [CLIENTE, CONTRARIA])
        for sensivel in (CLIENTE, CONTRARIA, CPF, CNPJ, EMAIL, ficticio.numero_ficticio(0), ficticio.numero_ficticio(1)):
            self.assertNotIn(sensivel, pseudo)
        self.assertIn("[PARTE_1]", pseudo)
        self.assertEqual(pseudo.count("[PARTE_2]"), 2)       # o mesmo nome, o mesmo marcador
        self.assertEqual(ia.restaurar(pseudo, mapa), self.TEXTO)
        self.assertEqual(set(mapa.values()), {CLIENTE, CONTRARIA, CPF, CNPJ, EMAIL,
                                              ficticio.numero_ficticio(0), ficticio.numero_ficticio(1)})

    def test_marcadores_estaveis_entre_chamadas(self):
        _, mapa = ia.pseudonimizar(f"{CLIENTE} e {CONTRARIA}", [CLIENTE, CONTRARIA])
        pseudo, mapa2 = ia.pseudonimizar(f"{CONTRARIA}, {CLIENTE} e {CNPJ}", [CLIENTE, CONTRARIA], mapa)
        self.assertEqual(pseudo, "[PARTE_2], [PARTE_1] e [CNPJ_1]")
        self.assertEqual({k: mapa2[k] for k in mapa}, mapa)

    def test_variacoes_de_caixa_acento_e_espaco(self):
        pseudo, mapa = ia.pseudonimizar("JOSÉ  da   SILVA e jose da silva e Josés", ["José da Silva"])
        self.assertEqual(pseudo, "[PARTE_1] e [PARTE_1] e Josés")     # palavra inteira: "Josés" não casa
        self.assertEqual(ia.restaurar(pseudo, mapa), "José da Silva e José da Silva e Josés")

    def test_nome_maior_vence_o_menor(self):
        pseudo, mapa = ia.pseudonimizar("Acme Comercio Ltda e Acme", ["Acme", "Acme Comercio Ltda"])
        self.assertEqual(pseudo, "[PARTE_1] e [PARTE_2]")
        self.assertEqual(mapa["[PARTE_1]"], "Acme Comercio Ltda")

    def test_partes_invalidas_sao_ignoradas(self):
        pseudo, mapa = ia.pseudonimizar("Al e Bo", ["Al", "", None, 7, "  "])
        self.assertEqual((pseudo, mapa), ("Al e Bo", {}))

    def test_restaurar_json_e_marcador_desconhecido(self):
        _, mapa = ia.pseudonimizar(CLIENTE, [CLIENTE])
        self.assertEqual(ia._restaurar_json({"a": ["[PARTE_1] ganhou", None, 3], "b": "[PARTE_9]"}, mapa),
                         {"a": [f"{CLIENTE} ganhou", None, 3], "b": "[PARTE_9]"})

    def test_o_que_sai_nao_tem_os_nomes_e_a_resposta_volta_com_eles(self):
        self.cadastrar()
        t = Transporte(lambda p: resposta_openai(json.dumps(
            {"conteudo": "[PARTE_1] pediu o prazo", "prazo": None})))
        prov = ia.provedor(perfil(pseudonimizar=True), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t)
        r = prov.gerar("Sistema", self.TEXTO, esquema=ESQUEMA, cliente=CLIENTE, partes=[CONTRARIA])
        enviado = json.dumps(t.pedidos[0]["corpo"], ensure_ascii=False)
        for sensivel in (CLIENTE, CONTRARIA, CPF, CNPJ, EMAIL, ficticio.numero_ficticio(0)):
            self.assertNotIn(sensivel, enviado)
        self.assertEqual(r["json"]["conteudo"], f"{CLIENTE} pediu o prazo")       # [PARTE_1] = o cliente
        self.assertEqual(r["texto"], json.dumps({"conteudo": f"{CLIENTE} pediu o prazo", "prazo": None}, ensure_ascii=False))
        # o mapa fica só no relatório, e o registro marca que houve pseudônimos
        mapa = json.loads((self.projeto / "data" / "ia" / "mapa_pseudonimos.json").read_text(encoding="utf-8"))
        self.assertEqual(mapa["[PARTE_1]"], CLIENTE)
        self.assertTrue(ia.registro_de_envios(self.projeto)[0]["pseudonimizado"])

    def test_pega_as_partes_do_relatorio_sem_o_chamador_informar(self):
        self.cadastrar()
        comum.save_json(self.projeto / "carteira.json", [{"numero": ficticio.numero_ficticio(0), "cliente": CLIENTE,
                                                          "parte_contraria": CONTRARIA, "ativo": True}])
        comum.save_json(self.projeto / "clientes.json", {"clientes": [{"nome": CLIENTE_2, "variacoes": ["Exemplo Dois"]}]})
        t = Transporte()
        ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t).gerar(
            "s", f"{CONTRARIA}, {CLIENTE_2} e Exemplo Dois", cliente=CLIENTE)
        enviado = json.dumps(t.pedidos[0]["corpo"], ensure_ascii=False)
        for nome in (CONTRARIA, CLIENTE_2, "Exemplo Dois"):
            self.assertNotIn(nome, enviado)

    def test_desligar_pseudonimizacao(self):
        self.cadastrar()
        t = Transporte()
        ia.provedor(perfil(pseudonimizar=False), CLIENTE, projeto=self.projeto, local=local_falso(),
                    transporte=t).gerar("s", f"fala de {CLIENTE}", cliente=CLIENTE)
        self.assertIn(CLIENTE, json.dumps(t.pedidos[0]["corpo"], ensure_ascii=False))
        # `pseudonimizar` ausente = ligado (o seguro é o padrão)
        p = perfil()
        del p["ia"]["pseudonimizar"]
        t2 = Transporte()
        ia.provedor(p, CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t2).gerar(
            "s", f"fala de {CLIENTE}", cliente=CLIENTE)
        self.assertNotIn(CLIENTE, json.dumps(t2.pedidos[0]["corpo"], ensure_ascii=False))


# --- o que sai e o registro --------------------------------------------------

class RegistroEGuardas(Base):
    def test_registro_nunca_guarda_o_texto(self):
        self.cadastrar()
        t = Transporte()
        prov = ia.provedor(perfil(pseudonimizar=False), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t)
        usuario = f"{SEGREDO_TEXTO} sobre {CONTRARIA}"
        prov.gerar("Sistema", usuario, esquema=ESQUEMA, cliente=CLIENTE)
        prov.gerar("Sistema", "segundo texto", esquema=ESQUEMA, cliente=CLIENTE)
        bruto = (self.projeto / "data" / "ia" / "envios.jsonl").read_text(encoding="utf-8")
        for texto in (SEGREDO_TEXTO, CONTRARIA, "segundo texto"):
            self.assertNotIn(texto, bruto)
        envios = ia.registro_de_envios(self.projeto)
        self.assertEqual(len(envios), 2)
        e = envios[0]
        self.assertEqual((e["provedor"], e["modelo"], e["cliente"], e["resultado"], e["pseudonimizado"]),
                         ("externo-a", "modelo-x", CLIENTE, "ok", False))
        self.assertEqual(e["caracteres"], len("Sistema") + len(usuario))
        self.assertEqual(e["sha256"], hashlib.sha256(f"Sistema\n{usuario}".encode()).hexdigest())
        self.assertRegex(e["quando"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertEqual(set(e), {"id", "quando", "provedor", "modelo", "cliente", "caracteres", "sha256",
                                  "pseudonimizado", "resultado"})

    def test_registro_por_slug_e_vazio_quando_nada_saiu(self):
        self.assertEqual(ia.registro_de_envios(self.projeto), [])
        with mock.patch.object(comum, "PROJETOS_DIR", self.projeto.parent):
            self.assertEqual(ia.registro_de_envios(self.projeto.name), [])

    def test_linha_corrompida_e_envio_pendente(self):
        (self.projeto / "data" / "ia").mkdir(parents=True)
        (self.projeto / "data" / "ia" / "envios.jsonl").write_text(
            'lixo\n{"tipo": "envio", "id": "a1", "quando": "2026-01-01T00:00:00", "provedor": "p"}\n[1]\n', encoding="utf-8")
        (envio,) = ia.registro_de_envios(self.projeto)
        self.assertEqual((envio["id"], envio["resultado"]), ("a1", "pendente"))

    def test_registro_que_nao_grava_impede_o_envio(self):
        self.cadastrar()
        t = Transporte(falha=AssertionError("enviou sem registrar"))
        with mock.patch.object(ia, "_acrescentar", side_effect=OSError("disco cheio")):
            r = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(),
                            transporte=t).gerar("s", "u", cliente=CLIENTE)
        self.assertEqual(r["avisos"][0]["codigo"], "ia_registro_falhou")
        self.assertTrue(r["motor"].startswith("local:"))
        self.assertEqual(t.pedidos, [])

    def test_segredos_do_cofre_nunca_saem(self):
        self.cadastrar()
        self.cofre.dados.update(cert_senha="senha-do-certificado-ficticia", totp_secret="JBSWY3DPEHPK3PXPJBSWY3DP")
        for texto in ("a senha é senha-do-certificado-ficticia", "segredo JBSWY3DPEHPK3PXPJBSWY3DP", f"chave {CHAVE}"):
            t, locais = Transporte(falha=AssertionError("segredo enviado")), []
            r = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(locais), transporte=t).gerar(
                "s", texto, cliente=CLIENTE)
            self.assertEqual(r["avisos"][0]["codigo"], "ia_conteudo_bloqueado")
            self.assertTrue(r["motor"].startswith("local:"))
            self.assertEqual(t.pedidos, [])
        self.assertEqual(ia.registro_de_envios(self.projeto), [])

    def test_caminhos_do_computador_nao_saem(self):
        self.cadastrar()
        t = Transporte()
        texto = f"arquivo em {comum.RAIZ}/projetos/x/data/doc.pdf e {Path.home()}/Documentos/a.pdf"
        ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t).gerar(
            "s", texto, cliente=CLIENTE)
        enviado = json.dumps(t.pedidos[0]["corpo"], ensure_ascii=False)
        self.assertNotIn(str(comum.RAIZ), enviado)
        self.assertNotIn(str(Path.home()), enviado)
        self.assertIn("[CAMINHO]", enviado)

    def test_so_texto_vai_no_corpo(self):
        """O corpo do pedido tem só as mensagens de texto: sem anexos, imagens ou arquivos."""
        self.cadastrar()
        t = Transporte()
        ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=t).gerar(
            "s", "u", esquema=ESQUEMA, cliente=CLIENTE)
        corpo = t.pedidos[0]["corpo"]
        self.assertTrue(all(isinstance(m["content"], str) for m in corpo["messages"]))
        self.assertEqual(set(corpo), {"model", "messages", "response_format"})

    def test_chave_nunca_aparece(self):
        """Nem em avisos, nem no registro, nem nos arquivos do relatório, nem no config.json."""
        self.cadastrar()
        eco = Transporte(lambda p: (401, json.dumps({"error": {"message": f"chave inválida: {CHAVE} (Bearer {CHAVE})"}}).encode()))
        r = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(), transporte=eco).gerar(
            "s", "u", cliente=CLIENTE)
        r2 = ia.provedor(perfil(), CLIENTE, projeto=self.projeto, local=local_falso(),
                         transporte=Transporte(lambda p: (500, json.dumps({"error": {"message": f"erro com {CHAVE}"}}).encode()))
                         ).gerar("s", "u", cliente=CLIENTE)
        sdk = ClienteSDKFalso(falha=erro_sdk("BadRequestError", f"rejeitado: {CHAVE}"))
        ia.cadastrar("claude", "anthropic", "claude-opus-5-5", chave=CHAVE)
        r3 = ia.provedor(perfil("claude"), CLIENTE, projeto=self.projeto, local=local_falso(),
                         fabrica_cliente=lambda c, e: sdk).gerar("s", "u", cliente=CLIENTE)
        for resultado in (r, r2, r3):
            self.assertNotIn(CHAVE, json.dumps(resultado, ensure_ascii=False))
            self.assertEqual(resultado["avisos"][0]["codigo"] in ("ia_chave_invalida", "ia_erro_provedor"), True)
        self.assertNotIn(CHAVE, self.arquivos_do_relatorio())
        self.assertNotIn(CHAVE, self.config.read_text(encoding="utf-8"))
        self.assertEqual(self.cofre.dados["ia_chave:externo-a"], CHAVE)

    def test_perfil_salvo_preserva_o_resto(self):
        comum.save_json(ia.arquivo_perfil(self.projeto), {"versao": 1, "entregas": ["docx_a"], "ia": {"x": 1}})
        ia.salvar_ia_no_perfil({"provedor": "local", "consentimento_externo": False}, self.projeto)
        p = ia.carregar_perfil(self.projeto)
        self.assertEqual(p["entregas"], ["docx_a"])
        self.assertEqual(p["ia"], {"x": 1, "provedor": "local", "consentimento_externo": False})
        ia.arquivo_perfil(self.projeto).write_text("{quebrado", encoding="utf-8")
        self.assertEqual(ia.carregar_perfil(self.projeto), {})


# --- catálogo, teste e selo ----------------------------------------------------

class Catalogo(Base):
    def test_cadastro_guarda_a_chave_no_cofre_e_nao_no_arquivo(self):
        self.assertEqual(ia.cadastrar("Meu Provedor", "openai_compativel", "m1", "https://api.exemplo.invalid/v1", CHAVE), [])
        self.assertEqual(self.cofre.dados["ia_chave:meu-provedor"], CHAVE)
        self.assertNotIn(CHAVE, self.config.read_text(encoding="utf-8"))
        self.assertEqual(ia.provedores()["meu-provedor"], {"nome": "Meu Provedor", "tipo": "openai_compativel",
                                                           "modelo": "m1", "endereco": "https://api.exemplo.invalid/v1"})
        self.assertTrue(ia.chave_configurada("Meu Provedor"))
        # atualizar sem chave mantém a que está no cofre
        ia.cadastrar("Meu Provedor", "openai_compativel", "m2", "https://api.exemplo.invalid/v1")
        self.assertEqual((ia.provedores()["meu-provedor"]["modelo"], self.cofre.dados["ia_chave:meu-provedor"]),
                         ("m2", CHAVE))

    def test_preserva_o_resto_do_config(self):
        self.config.write_text(json.dumps({"modelo": "auto", "revisor": "Fulana"}), encoding="utf-8")
        self.cadastrar()
        cfg = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual((cfg["modelo"], cfg["revisor"]), ("auto", "Fulana"))
        self.assertIn("externo-a", cfg["ia_provedores"])

    def test_validacoes(self):
        casos = [("", "anthropic", "m", ""), ("local", "anthropic", "m", ""), ("x", "inventado", "m", ""),
                 ("x", "anthropic", "  ", ""), ("x", "openai_compativel", "m", ""),
                 ("x", "openai_compativel", "m", "http://api.exemplo.invalid/v1"),   # chave em claro
                 ("x", "openai_compativel", "m", "ftp://api.exemplo.invalid"), ("x", "openai_compativel", "m", "file:///etc"),
                 ("x", "openai_compativel", "m", "api.exemplo.invalid/v1")]
        for nome, tipo, modelo, endereco in casos:
            avisos = ia.cadastrar(nome, tipo, modelo, endereco, chave=CHAVE)
            self.assertEqual(avisos[0]["codigo"], "ia_cadastro_invalido", (nome, tipo, modelo, endereco))
            self.assertEqual(avisos[0]["nivel"], "erro")
        self.assertEqual(ia.provedores(), {})
        self.assertEqual(self.cofre.dados, {})
        # http só para serviço neste computador
        self.assertEqual(ia.cadastrar("lm", "openai_compativel", "m", "http://127.0.0.1:1234/v1", chave="k"), [])

    def test_cofre_indisponivel(self):
        with mock.patch.object(acesso, "guardar", side_effect=RuntimeError("sem cofre")):
            avisos = ia.cadastrar("x", "anthropic", "claude-opus-5-5", chave=CHAVE)
        self.assertEqual(avisos[0]["codigo"], "ia_cofre_indisponivel")
        self.assertEqual(ia.provedores(), {})

    def test_remover(self):
        self.cadastrar()
        self.assertTrue(ia.remover("externo-a"))
        self.assertEqual(ia.provedores(), {})
        self.assertFalse(ia.chave_configurada("externo-a"))
        self.assertFalse(ia.remover("externo-a"))

    def test_testar_ok_e_falha_sem_cair_no_local(self):
        self.cadastrar()
        t = Transporte(lambda p: resposta_openai("ok"))
        r = ia.testar("externo-a", projeto=self.projeto, transporte=t)
        self.assertEqual((r["ok"], r["resposta"], r["motor"]), (True, "ok", "externo:externo-a:modelo-x"))
        self.assertNotIn("Cliente", json.dumps(t.pedidos[0]["corpo"]))     # frase fixa, nada de cliente
        falha = ia.testar("externo-a", projeto=self.projeto, transporte=Transporte(falha=urllib.error.URLError("x")))
        self.assertFalse(falha["ok"])
        self.assertEqual(falha["avisos"][0]["codigo"], "ia_falha_rede")
        self.assertNotIn("motor local", falha["avisos"][0]["mensagem"])
        self.assertFalse(ia.testar("fantasma", projeto=self.projeto)["ok"])
        # o teste também fica no registro
        self.assertEqual([e["cliente"] for e in ia.registro_de_envios(self.projeto)], [ia.CLIENTE_TESTE] * 2)

    def test_selo(self):
        casos = {"local:gemma3:4b": "local", "local": "local", "": "local", None: "local", "nenhum": "local",
                 "externo:anthropic:claude-opus-5-5": "externa: anthropic", "externo:meu-gw:llama3:8b": "externa: meu-gw"}
        for motor, esperado in casos.items():
            self.assertEqual(ia.selo(motor), esperado, motor)


# --- tela /ia -----------------------------------------------------------------

class Tela(Base):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from painel import base, ia as tela
        cls.tela = tela
        nomes = ("PROJETOS_DIR", "ATUAL_FILE", "PROJETO", "PROJETO_DIR", "PROJETO_FILE", "DATA", "CARTEIRA_FILE",
                 "CLIENTES_FILE", "EVENTOS_FILE", "ESTADO_FILE", "DOCS_DIR", "TEXTOS_DIR", "RELATORIOS_DIR", "DIAG_DIR",
                 "PRINTS_DIR")
        cls.globais = {n: getattr(comum, n) for n in nomes}
        comum.PROJETOS_DIR = TMP / "projetos-tela"
        comum.ATUAL_FILE = comum.PROJETOS_DIR / ".projeto_atual"
        comum.PROJETOS_DIR.mkdir(parents=True, exist_ok=True)
        cls.slug = comum.criar_projeto("Grupo Exemplo IA")
        comum.usar_projeto(cls.slug)
        comum.save_json(comum.CLIENTES_FILE, {"clientes": [{"nome": CLIENTE}, {"nome": CLIENTE_2}]})
        cls.app = Flask(__name__)
        cls.app.config["TESTING"] = True
        cls.token = "token-de-teste"
        tela.registrar(cls.app, cls.token, base.cabecalho, base.criar_token_ok(cls.token))
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for n, v in cls.globais.items():
            setattr(comum, n, v)
        cls.tela.TRANSPORTE = cls.tela.FABRICA_CLIENTE = None

    def setUp(self):
        super().setUp()
        self.projeto = comum.PROJETO_DIR
        ia.arquivo_perfil().unlink(missing_ok=True)
        pasta_ia = comum.PROJETO_DIR / "data" / "ia"
        for arquivo in (pasta_ia.glob("*") if pasta_ia.exists() else ()):
            arquivo.unlink()

    def post(self, caminho, dados=None, token=True):
        corpo = dict(dados or {})
        if token:
            corpo["token"] = self.token
        return self.c.post(caminho, data=corpo)

    def seguir(self, resp):
        self.assertEqual(resp.status_code, 302)
        return self.c.get(resp.headers["Location"]).get_data(as_text=True)

    def test_paginas_abrem_sem_provedor(self):
        for caminho in ("/ia", "/ia/registro"):
            self.assertEqual(self.c.get(caminho).status_code, 200, caminho)
        pagina = self.c.get("/ia").get_data(as_text=True)
        self.assertIn("IA local", pagina)
        self.assertIn("Nada saiu do computador", pagina)
        self.assertIn(CLIENTE, pagina)

    def test_posts_exigem_token(self):
        for caminho in ("/ia/provedor", "/ia/remover", "/ia/testar", "/ia/consentimento"):
            self.assertEqual(self.post(caminho, {"nome": "x"}, token=False).status_code, 403, caminho)
        self.assertEqual(ia.provedores(), {})

    def test_cadastro_pela_tela_e_a_chave_nao_volta(self):
        resp = self.post("/ia/provedor", {"nome": "Gateway <b>X</b>", "tipo": "openai_compativel", "modelo": "m1",
                                          "endereco": "https://api.exemplo.invalid/v1", "chave": CHAVE})
        self.assertIn("salvo", self.seguir(resp))
        (chave_id,) = ia.provedores()
        pagina = self.c.get("/ia").get_data(as_text=True)
        self.assertNotIn(CHAVE, pagina)
        self.assertNotIn(CHAVE, self.c.get(f"/ia?editar={chave_id}").get_data(as_text=True))
        self.assertIn("guardada", pagina)
        self.assertNotIn("<b>X</b>", pagina)                 # nome escapado
        self.assertIn("&lt;b&gt;X&lt;/b&gt;", pagina)
        self.assertEqual(self.cofre.dados[f"ia_chave:{chave_id}"], CHAVE)
        self.assertNotIn(CHAVE, self.config.read_text(encoding="utf-8"))
        # cadastro inválido mostra o motivo e não grava
        pagina = self.seguir(self.post("/ia/provedor", {"nome": "ruim", "tipo": "openai_compativel", "modelo": "m",
                                                        "endereco": "http://api.exemplo.invalid", "chave": "k"}))
        self.assertIn("https", pagina)
        self.assertNotIn("ruim", ia.provedores())

    def test_testar_pela_tela(self):
        self.cadastrar()
        self.tela.TRANSPORTE = Transporte(lambda p: resposta_openai("ok"))
        self.assertIn("Teste concluído", self.seguir(self.post("/ia/testar", {"nome": "externo-a"})))
        self.tela.TRANSPORTE = Transporte(lambda p: (401, json.dumps({"error": {"message": CHAVE}}).encode()))
        pagina = self.seguir(self.post("/ia/testar", {"nome": "externo-a"}))
        self.assertIn("O teste falhou", pagina)
        self.assertNotIn(CHAVE, pagina)
        registro = self.c.get("/ia/registro").get_data(as_text=True)
        self.assertNotIn(CHAVE, registro)
        self.assertIn("erro:ia_chave_invalida", registro)

    def test_consentimento_pela_tela(self):
        self.cadastrar()
        base = {"provedor": "externo-a", "cliente_0": CLIENTE, "cliente_1": CLIENTE_2, "pseudonimizar": "1"}
        # sem a confirmação, nada é salvo
        self.assertIn("confirmação", self.seguir(self.post("/ia/consentimento", {**base, "cons_0": "1"})))
        self.assertIsNone(ia.carregar_perfil().get("ia"))
        # com a confirmação: só o cliente 1 autorizado
        self.assertIn("Salvo", self.seguir(self.post("/ia/consentimento", {**base, "cons_0": "1", "entendi": "1"})))
        self.assertEqual(ia.carregar_perfil()["ia"], {"provedor": "externo-a", "consentimento_externo": False,
                                                      "por_cliente": {CLIENTE: True, CLIENTE_2: False},
                                                      "pseudonimizar": True})
        self.assertEqual(ia.selo_para(ia.carregar_perfil(), CLIENTE), "externa: externo-a")
        self.assertEqual(ia.selo_para(ia.carregar_perfil(), CLIENTE_2), "local")
        self.assertIn("externa: externo-a", self.c.get("/ia").get_data(as_text=True))
        # voltar ao local não exige confirmação
        self.seguir(self.post("/ia/consentimento", {**base, "provedor": "local"}))
        self.assertEqual(ia.carregar_perfil()["ia"]["provedor"], "local")
        self.assertEqual(ia.selo_para(ia.carregar_perfil(), CLIENTE), "local")

    def test_consentimento_com_provedor_inexistente_vira_local(self):
        self.seguir(self.post("/ia/consentimento", {"provedor": "fantasma", "consentimento_externo": "1", "entendi": "1"}))
        self.assertEqual(ia.carregar_perfil()["ia"]["provedor"], "local")

    def test_registro_na_tela(self):
        self.cadastrar()
        ia.salvar_ia_no_perfil({"provedor": "externo-a", "consentimento_externo": True, "pseudonimizar": False})
        ia.provedor(ia.carregar_perfil(), CLIENTE, local=local_falso(), transporte=Transporte()).gerar(
            "s", SEGREDO_TEXTO, cliente=CLIENTE)
        for caminho in ("/ia", "/ia/registro"):
            pagina = self.c.get(caminho).get_data(as_text=True)
            self.assertIn("externo-a", pagina)
            self.assertIn(CLIENTE, pagina)
            self.assertNotIn(SEGREDO_TEXTO, pagina)

    def test_remover_pela_tela(self):
        self.cadastrar()
        self.assertIn("removido", self.seguir(self.post("/ia/remover", {"nome": "externo-a"})))
        self.assertEqual(ia.provedores(), {})


if __name__ == "__main__":
    unittest.main()
