"""Capa e metadados do processo (WS-4): extração por fonte (autos do jus.br, TRT, DJEN, DataJud), regras de
confiança, aplicação na ficha e cliente do DataJud com transporte falso. Só dados fictícios; nenhum teste usa rede
(o socket é bloqueado no setUp). Fixtures em tests/fixtures/capa/ com número e nomes trocados em tempo de execução."""
import copy
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: F401  (aponta comum.py para uma pasta temporária)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import capa  # noqa: E402
import carteira as cart  # noqa: E402
import comum  # noqa: E402
import djen  # noqa: E402
import ficha  # noqa: E402
from ficticio import gerar_carteira, numero_ficticio  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NUM = numero_ficticio(0)
DIGITOS = "".join(c for c in NUM if c.isdigit())
OUTRO = numero_ficticio(1)
CLIENTE = "Cliente Exemplo 01 Ltda"


def _fixture(nome):
    texto = (FIXTURES / "capa" / nome).read_text(encoding="utf-8")
    return json.loads(texto.replace("@@NUMERO@@", NUM).replace("@@DIGITOS@@", DIGITOS))


def _autos_html():
    return (FIXTURES / "autos_pdpj.html").read_text(encoding="utf-8")


def _autos_html_com_capa(extra_movimentos="", bloco=None, numero=None):
    """Deriva do HTML real da fixture: acrescenta um bloco "Dados do processo" (estrutura PRESUMIDA) depois do
    título e, se pedido, movimentos na aba Movimentos."""
    html = _autos_html()
    if numero:
        html = html.replace("0000000-00.0000.0.00.0000", numero)
    bloco = bloco if bloco is not None else (
        "<section class='dados-processo'>"
        "<div>Órgão julgador: 3ª Vara Cível da Comarca de Cidade Exemplo</div>"
        "<div>Assunto: Indenização por Dano Moral</div>"
        "<div>Valor da causa: R$ 12.345,67</div>"
        "<div>Data de ajuizamento: 05/05/2026</div>"
        "<div>Polo ativo: Pessoa Fictícia 0003</div>"
        "<div>Polo passivo: Cliente Exemplo 01 Ltda; Outra Empresa Fictícia ME</div>"
        "</section>")
    html = html.replace("</p>\n<div class=\"mat-tab-labels\">", "</p>" + bloco + "\n<div class=\"mat-tab-labels\">", 1)
    if extra_movimentos:
        html = html.replace('<mat-tab-body role="tabpanel" class="mat-tab-body mat-tab-body-active" id="b1"><div _ngcontent-all-c252="" class="movimentos ng-star-inserted">',
                            '<mat-tab-body role="tabpanel" class="mat-tab-body mat-tab-body-active" id="b1"><div _ngcontent-all-c252="" class="movimentos ng-star-inserted">'
                            + extra_movimentos, 1)
    return html


def _movimento(data_extenso, *textos):
    blocos = "".join(f'<div class="timeline"><div class="texto p-2 mr-3">{t}</div></div>' for t in textos)
    return f'<div class="movimento"><div class="data"><em></em>&nbsp; {data_extenso} </div>{blocos}</div>'


class Base(unittest.TestCase):
    def setUp(self):
        # nenhum teste deste arquivo pode tocar a rede
        p = mock.patch.object(socket.socket, "connect", side_effect=AssertionError("rede bloqueada nos testes"))
        p.start()
        self.addCleanup(p.stop)

    def valor(self, campos, nome):
        return campos[nome]["valor"]


class TestAutos(Base):
    def test_html_real_da_fixture_traz_so_o_que_a_tela_mostra(self):
        campos, avisos = capa.extrair_com_avisos("autos", _autos_html())
        self.assertEqual(self.valor(campos, "classe"), "PROCEDIMENTO COMUM CÍVEL")
        self.assertEqual(campos["classe"]["confianca"], "alta")
        # a tela não tem bloco de capa: só a distribuição (movimento) serve para a data, com confiança média
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-07-30")
        self.assertEqual(campos["data_ajuizamento"]["confianca"], "media")
        self.assertIn("Distribuído por sorteio", campos["data_ajuizamento"]["evidencia"])
        # o que não está na tela fica fora (nunca vazio-fantasma)
        for ausente in ("vara", "municipio", "uf", "valor_causa", "autores", "reus", "data_citacao", "assunto"):
            self.assertNotIn(ausente, campos)
        self.assertEqual(avisos, [])

    def test_html_nao_confunde_a_aba_de_documentos_com_a_de_movimentos(self):
        # a aba Documentos tem blocos .movimento com datas (outubro/setembro): nenhuma vira data de capa
        campos = capa.extrair("autos", _autos_html())
        self.assertNotEqual(self.valor(campos, "data_ajuizamento"), "2026-10-01")

    def test_html_derivado_com_bloco_de_dados_do_processo(self):
        campos = capa.extrair("autos", _autos_html_com_capa())
        self.assertEqual(self.valor(campos, "vara"), "3ª Vara Cível da Comarca de Cidade Exemplo")
        self.assertEqual(self.valor(campos, "municipio"), "Cidade Exemplo")
        self.assertEqual(self.valor(campos, "assunto"), "Indenização por Dano Moral")
        self.assertEqual(self.valor(campos, "valor_causa"), "12345.67")
        self.assertEqual(self.valor(campos, "autores"), "Pessoa Fictícia 0003")
        self.assertEqual(self.valor(campos, "reus"), "Cliente Exemplo 01 Ltda; Outra Empresa Fictícia ME")
        # a data do bloco (5/5) é a de ajuizamento; vale mais que a dedução pelo movimento de distribuição (30/07)
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-05-05")
        self.assertIn("rótulo", campos["vara"]["evidencia"])
        self.assertEqual(campos["vara"]["confianca"], "media")  # estrutura presumida

    def test_citacao_so_quando_realizada(self):
        html = _autos_html_com_capa(
            extra_movimentos=_movimento("20 de agosto de 2026", "Expedição de carta de citação")
            + _movimento("25 de agosto de 2026", "Decorrido prazo de citação")
            + _movimento("2 de setembro de 2026", "Citação realizada"))
        campos = capa.extrair("autos", html)
        self.assertEqual(self.valor(campos, "data_citacao"), "2026-09-02")
        self.assertIn("Citação realizada", campos["data_citacao"]["evidencia"])
        # só "expedida"/"prazo": campo fica vazio
        html2 = _autos_html_com_capa(extra_movimentos=_movimento("20 de agosto de 2026", "Expedição de carta de citação")
                                     + _movimento("25 de agosto de 2026", "Citação negativa, destinatário não localizado"))
        self.assertNotIn("data_citacao", capa.extrair("autos", html2))

    def test_json_da_busca_do_portal(self):
        campos, avisos = capa.extrair_com_avisos("autos", _fixture("pdpj_busca.json"), numero=NUM)
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-03-10")
        self.assertEqual(campos["data_ajuizamento"]["confianca"], "alta")
        self.assertEqual(self.valor(campos, "vara"), "1ª Vara Cível da Comarca de Cidade Exemplo")
        self.assertEqual(self.valor(campos, "classe"), "Procedimento Comum Cível")  # a do 1º grau, não "Apelação"
        self.assertEqual(self.valor(campos, "assunto"), "Indenização por Dano Moral")  # o marcado como principal
        self.assertIn("+1 outro", campos["assunto"]["evidencia"])
        self.assertEqual(self.valor(campos, "valor_causa"), "15000.50")
        # advogado e perito nunca entram como parte
        self.assertEqual(self.valor(campos, "autores"), "Pessoa Fictícia 0001")
        self.assertEqual(self.valor(campos, "reus"), "Cliente Exemplo 01 Ltda")
        self.assertEqual(self.valor(campos, "outras_partes"), "Terceira Interessada Fictícia")
        self.assertEqual(avisos, [])

    def test_json_e_html_juntos_e_lista_de_respostas(self):
        j = _fixture("pdpj_busca.json")
        campos = capa.extrair("autos", {"html": _autos_html_com_capa(), "json": [j]}, numero=None)
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-03-10")  # a alta (JSON) vence a média (HTML)
        self.assertEqual(self.valor(campos, "classe"), "Procedimento Comum Cível")
        campos2 = capa.extrair("autos", [j, {"content": []}], numero=NUM)
        self.assertEqual(self.valor(campos2, "classe"), "Procedimento Comum Cível")

    def test_numero_diferente_e_recusado(self):
        campos, avisos = capa.extrair_com_avisos("autos", _fixture("pdpj_busca.json"), numero=OUTRO)
        self.assertEqual(campos, {})
        self.assertEqual(avisos[0]["codigo"], "capa_processo_nao_encontrado")
        campos, avisos = capa.extrair_com_avisos("autos", _autos_html_com_capa(numero=NUM), numero=OUTRO)
        self.assertEqual(campos, {})
        self.assertEqual(avisos[0]["codigo"], "capa_processo_nao_encontrado")
        # e confere quando é o mesmo
        self.assertIn("classe", capa.extrair("autos", _autos_html_com_capa(numero=NUM), numero=NUM))


class TestTRT(Base):
    def test_fixture_do_trt(self):
        campos, avisos = capa.extrair_com_avisos("trt", _fixture("trt_processo.json"), numero=NUM)
        self.assertEqual(self.valor(campos, "classe"), "Ação Trabalhista - Rito Ordinário")
        self.assertEqual(self.valor(campos, "vara"), "2ª Vara do Trabalho de Cidade Exemplo")
        self.assertEqual(self.valor(campos, "municipio"), "Cidade Exemplo")
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-02-02")  # autuação vale mais que o movimento de distribuição
        self.assertEqual(self.valor(campos, "valor_causa"), "50000.00")
        self.assertEqual(self.valor(campos, "assunto"), "Horas Extras")
        self.assertEqual(self.valor(campos, "autores"), "Pessoa Fictícia 0002")
        self.assertEqual(self.valor(campos, "reus"), "Cliente Exemplo 01 Ltda; Empresa Tomadora Fictícia S.A.")
        self.assertEqual(self.valor(campos, "data_citacao"), "2026-03-01")
        self.assertEqual(avisos, [])

    def test_lacunas_ficam_vazias(self):
        d = _fixture("trt_processo.json")
        for k in ("valorDaCausa", "assuntos", "autuadoEm", "poloPassivo"):
            d.pop(k)
        d["itensProcesso"] = [i for i in d["itensProcesso"] if i["titulo"] != "Citação realizada"]
        campos = capa.extrair("trt", d, numero=NUM)
        for ausente in ("valor_causa", "assunto", "reus", "data_citacao"):
            self.assertNotIn(ausente, campos)
        # sem autuação, a distribuição (movimento) serve de data, com a ressalva escrita na evidência
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-02-03")
        self.assertIn("distribuição", campos["data_ajuizamento"]["evidencia"])

    def test_outro_processo_e_segredo_de_justica(self):
        campos, avisos = capa.extrair_com_avisos("trt", _fixture("trt_processo.json"), numero=OUTRO)
        self.assertEqual((campos, avisos[0]["codigo"]), ({}, "capa_processo_nao_encontrado"))
        d = _fixture("trt_processo.json")
        d["segredoJustica"] = True
        campos, avisos = capa.extrair_com_avisos("trt", d, numero=NUM)
        self.assertEqual((campos, avisos[0]["codigo"]), ({}, "capa_sigilo"))


class TestDJEN(Base):
    def test_cliente_identificavel_em_um_polo(self):
        campos, avisos = capa.extrair_com_avisos("djen", _fixture("djen_publicacoes.json"), numero=NUM, cliente=CLIENTE)
        self.assertEqual(self.valor(campos, "autores"), "PESSOA FICTICIA 0001")
        self.assertEqual(self.valor(campos, "reus"), "CLIENTE EXEMPLO 01 LTDA; Empresa Tomadora Fictícia S.A.")
        self.assertEqual(self.valor(campos, "parte_contraria"), "PESSOA FICTICIA 0001")  # cliente é réu: contrária = polo ativo
        self.assertEqual(self.valor(campos, "outras_partes"), "Administrador Judicial Fictício")
        self.assertTrue(all(c["confianca"] == "baixa" for c in campos.values()))
        self.assertNotIn("polo_cliente", campos)
        self.assertEqual(avisos, [])

    def test_cliente_no_polo_ativo_inverte_a_parte_contraria(self):
        campos = capa.extrair("djen", _fixture("djen_publicacoes.json"), cliente="Pessoa Fictícia 0001")
        self.assertEqual(self.valor(campos, "parte_contraria"), "CLIENTE EXEMPLO 01 LTDA; Empresa Tomadora Fictícia S.A.")

    def test_variacao_do_nome_e_sufixo_societario(self):
        campos = capa.extrair("djen", _fixture("djen_publicacoes.json"), cliente=["Outro Nome Qualquer", "CLIENTE EXEMPLO 01"])
        self.assertIn("parte_contraria", campos)

    def test_sem_cliente_ou_ambiguo_nao_devolve_partes(self):
        for cliente in (None, "Empresa Que Nao Aparece Ltda"):
            campos, avisos = capa.extrair_com_avisos("djen", _fixture("djen_publicacoes.json"), cliente=cliente)
            self.assertEqual(campos, {})
            self.assertEqual(avisos[0]["codigo"], "capa_cliente_nao_identificado")
        itens = _fixture("djen_publicacoes.json")["items"]
        itens[0]["destinatarios"].append({"nome": "Cliente Exemplo 01 Ltda", "polo": "A"})  # nos dois polos
        campos, avisos = capa.extrair_com_avisos("djen", itens, cliente=CLIENTE)
        self.assertEqual((campos, avisos[0]["codigo"]), ({}, "capa_cliente_nao_identificado"))

    def test_publicacao_de_outro_processo_e_ignorada(self):
        itens = _fixture("djen_publicacoes.json")["items"]
        campos, avisos = capa.extrair_com_avisos("djen", itens, numero=OUTRO, cliente=CLIENTE)
        self.assertEqual(campos, {})

    def test_extensoes_do_modulo_djen_sem_rede(self):
        itens = _fixture("djen_publicacoes.json")["items"]
        partes = djen.partes_por_polo(itens)
        self.assertEqual(partes["A"], ["PESSOA FICTICIA 0001"])
        self.assertEqual(len(partes["P"]), 2)
        self.assertEqual(partes["outros"], ["Administrador Judicial Fictício"])
        self.assertEqual(djen.partes_por_polo({"items": itens}), partes)
        chamadas = []
        djen.publicacoes_do_processo(NUM, buscar_=lambda **f: chamadas.append(f) or itens)
        self.assertEqual(chamadas, [{"numeroProcesso": NUM}])


class TestDataJud(Base):
    def test_fixture_no_formato_da_documentacao(self):
        campos, avisos = capa.extrair_com_avisos("datajud", _fixture("datajud_resposta.json"), numero=NUM)
        self.assertEqual(self.valor(campos, "classe"), "Procedimento Comum Cível")  # G1, não a apelação (G2)
        self.assertEqual(self.valor(campos, "vara"), "1ª Vara Cível da Comarca de Cidade Exemplo")
        self.assertEqual(self.valor(campos, "assunto"), "Indenização por Dano Moral")  # assuntos como lista de listas
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-03-10")
        self.assertEqual(campos["data_ajuizamento"]["confianca"], "media")
        self.assertEqual(self.valor(campos, "data_citacao"), "2026-04-15")
        self.assertEqual(self.valor(campos, "uf"), "CE")  # do código IBGE do município (2 primeiros dígitos)
        self.assertEqual(self.valor(campos, "municipio"), "Cidade Exemplo")  # deduzido do nome, não do código IBGE
        # a documentação NÃO traz partes nem valor da causa: nunca aparecem
        for ausente in ("valor_causa", "autores", "reus", "parte_contraria", "polo_cliente", "outras_partes"):
            self.assertNotIn(ausente, campos)
        self.assertEqual([a["codigo"] for a in avisos], ["capa_varias_tramitacoes"])

    def test_aceita_so_o_source_ou_a_lista_de_hits(self):
        resposta = _fixture("datajud_resposta.json")
        hits = resposta["hits"]["hits"]
        self.assertEqual(capa.extrair("datajud", hits[1]["_source"], numero=NUM)["classe"]["valor"], "Procedimento Comum Cível")
        self.assertEqual(capa.extrair("datajud", hits, numero=NUM)["classe"]["valor"], "Procedimento Comum Cível")

    def test_nao_ha_valor_nem_partes_mesmo_que_a_fonte_mande(self):
        resposta = _fixture("datajud_resposta.json")
        src = resposta["hits"]["hits"][1]["_source"]
        src.update(valorCausa=1000, poloAtivo=[{"nome": "X"}], partes=[{"nome": "Y", "polo": "ATIVO"}])
        campos = capa.extrair("datajud", resposta, numero=NUM)
        self.assertFalse({"valor_causa", "autores", "reus"} & set(campos))

    def test_orgao_com_texto_corrompido_vira_confianca_baixa(self):
        resposta = _fixture("datajud_resposta.json")
        resposta["hits"]["hits"][1]["_source"]["orgaoJulgador"]["nome"] = "VARA DE EXECU??O FISCAL DO DF"  # visto na wiki do CNJ
        campos, avisos = capa.extrair_com_avisos("datajud", resposta, numero=NUM)
        self.assertEqual(campos["vara"]["confianca"], "baixa")
        self.assertNotIn("municipio", campos)
        self.assertIn("capa_texto_corrompido", [a["codigo"] for a in avisos])

    def test_sigilo_e_processo_ausente(self):
        resposta = _fixture("datajud_resposta.json")
        for h in resposta["hits"]["hits"]:
            h["_source"]["nivelSigilo"] = 1
        campos, avisos = capa.extrair_com_avisos("datajud", resposta, numero=NUM)
        self.assertEqual(campos, {})
        self.assertIn("capa_sigilo", [a["codigo"] for a in avisos])
        campos, avisos = capa.extrair_com_avisos("datajud", _fixture("datajud_resposta.json"), numero=OUTRO)
        self.assertEqual((campos, avisos[0]["codigo"]), ({}, "capa_processo_nao_encontrado"))
        vazio = {"hits": {"total": {"value": 0}, "hits": []}}
        self.assertEqual(capa.extrair_com_avisos("datajud", vazio, numero=NUM)[1][0]["codigo"], "capa_processo_nao_encontrado")

    def test_ibge_invalido_nao_gera_uf(self):
        resposta = _fixture("datajud_resposta.json")
        resposta["hits"]["hits"][1]["_source"]["orgaoJulgador"]["codigoMunicipioIBGE"] = 5128  # visto na wiki: 4 dígitos
        self.assertNotIn("uf", capa.extrair("datajud", resposta, numero=NUM))
        resposta["hits"]["hits"][1]["_source"]["orgaoJulgador"]["codigoMunicipioIBGE"] = 9900000
        self.assertNotIn("uf", capa.extrair("datajud", resposta, numero=NUM))


class TestClienteDataJud(Base):
    def setUp(self):
        super().setUp()
        self.chamadas = []
        capa._ultima_datajud[0] = 0.0

    def transporte(self, status=200, corpo=None, erro=None):
        def f(url, cabecalhos, corpo_req):
            self.chamadas.append((url, cabecalhos, json.loads(corpo_req)))
            if erro:
                raise erro
            return status, json.dumps(corpo if corpo is not None else _fixture("datajud_resposta.json")).encode()
        return f

    def consultar(self, **kw):
        kw.setdefault("ativo", True)
        kw.setdefault("chave", "CHAVE-FALSA")
        kw.setdefault("dormir", lambda s: None)
        return capa.consultar_datajud(NUM, **kw)

    def test_flag_desligada_nao_chama(self):
        resp, avisos = self.consultar(ativo=False, transporte=self.transporte())
        self.assertIsNone(resp)
        self.assertEqual(avisos[0]["codigo"], "datajud_desativado")
        self.assertEqual(self.chamadas, [])

    def test_flag_vem_da_configuracao_e_padrao_e_desligado(self):
        with mock.patch.object(comum, "config", return_value={}):
            self.assertEqual(self.consultar(ativo=None, transporte=self.transporte())[1][0]["codigo"], "datajud_desativado")
        cfg = {"fontes_externas": {"datajud": {"ativo": True, "chave": "K"}}}
        with mock.patch.object(comum, "config", return_value=cfg):
            resp, avisos = self.consultar(ativo=None, chave=None, transporte=self.transporte())
        self.assertIsNotNone(resp)
        self.assertEqual(self.chamadas[0][1]["Authorization"], "APIKey K")

    def test_sem_chave_nao_chama(self):
        with mock.patch.dict("os.environ", {}, clear=False), mock.patch.object(comum, "config", return_value={}):
            import os
            os.environ.pop("DATAJUD_CHAVE", None)
            resp, avisos = self.consultar(chave=None, transporte=self.transporte())
        self.assertEqual((resp, avisos[0]["codigo"], self.chamadas), (None, "datajud_sem_chave", []))

    def test_requisicao_no_formato_da_documentacao(self):
        resp, avisos = self.consultar(transporte=self.transporte())
        self.assertEqual(avisos, [])
        url, cab, corpo = self.chamadas[0]
        self.assertEqual(url, "https://api-publica.datajud.cnj.jus.br/api_publica_tjce/_search")  # TJCE = 8.06
        self.assertEqual(cab["Authorization"], "APIKey CHAVE-FALSA")
        self.assertEqual(cab["Content-Type"], "application/json")
        self.assertEqual(corpo, {"query": {"match": {"numeroProcesso": DIGITOS}}})
        self.assertEqual(capa.extrair("datajud", resp, numero=NUM)["uf"]["valor"], "CE")

    def test_erros_viram_avisos(self):
        casos = [({"status": 401}, "datajud_chave_recusada"), ({"status": 403}, "datajud_chave_recusada"),
                 ({"status": 429}, "datajud_limite"), ({"status": 503}, "datajud_indisponivel"),
                 ({"erro": TimeoutError()}, "datajud_indisponivel"), ({"erro": OSError("sem rede")}, "datajud_indisponivel")]
        for kw, codigo in casos:
            resp, avisos = self.consultar(transporte=self.transporte(**kw))
            self.assertEqual((resp, avisos[0]["codigo"]), (None, codigo), kw)
        resp, avisos = self.consultar(transporte=lambda *a: (200, b"<html>nao eh json</html>"))
        self.assertEqual((resp, avisos[0]["codigo"]), (None, "datajud_resposta_ilegivel"))

    def test_respeita_o_limite_de_120_por_minuto(self):
        espera, tempo = [], [100.0]
        relogio = lambda: tempo[0]
        def dormir(s):
            espera.append(s)
            tempo[0] += s
        self.consultar(transporte=self.transporte(), relogio=relogio, dormir=dormir)   # a 1ª não espera (intervalo já passou)
        self.consultar(transporte=self.transporte(), relogio=relogio, dormir=dormir)   # a 2ª, colada na anterior, espera
        self.assertEqual(len(espera), 1)
        self.assertGreaterEqual(espera[0], 0.5)  # 120/min = 1 a cada 0,5 s

    def test_alias_por_tribunal(self):
        casos = {numero_ficticio(0, tr=6): "tjce", numero_ficticio(0, tr=7): "tjdft", numero_ficticio(0, j=4, tr=3): "trf3",
                 numero_ficticio(0, j=5, tr=7): "trt7", numero_ficticio(0, j=5, tr=0): "tst", numero_ficticio(0, j=3, tr=0): "stj",
                 numero_ficticio(0, j=1, tr=0): None, numero_ficticio(0, j=6, tr=6): None, "lixo": None}
        for numero, esperado in casos.items():
            self.assertEqual(capa.alias_datajud(numero), esperado, numero)
        resp, avisos = capa.consultar_datajud(numero_ficticio(0, j=1, tr=0), ativo=True, chave="K", transporte=self.transporte())
        self.assertEqual((resp, avisos[0]["codigo"]), (None, "datajud_tribunal_sem_indice"))


class TestRegrasGerais(Base):
    def test_campos_so_da_ficha_e_polo_cliente_nunca(self):
        fontes = [("autos", _fixture("pdpj_busca.json")), ("trt", _fixture("trt_processo.json")),
                  ("datajud", _fixture("datajud_resposta.json")), ("djen", _fixture("djen_publicacoes.json")),
                  ("autos", _autos_html_com_capa())]
        for fonte, dados in fontes:
            campos = capa.extrair(fonte, dados, cliente=CLIENTE)
            self.assertTrue(set(campos) <= set(ficha.CAMPOS), fonte)
            self.assertNotIn("polo_cliente", campos)
            for reg in campos.values():
                self.assertEqual(set(reg), {"valor", "confianca", "evidencia"})
                self.assertIn(reg["confianca"], capa.CONFIANCAS)
                self.assertTrue(reg["evidencia"])
            if fonte != "djen":
                self.assertNotIn("parte_contraria", campos, fonte)

    def test_polo_cliente_e_parte_contraria_do_dado_bruto_sao_ignorados(self):
        d = _fixture("trt_processo.json")
        d.update(polo_cliente="ativo", parte_contraria="Alguém", partes=[{"nome": "Z", "polo": "ATIVO"}])
        campos = capa.extrair("trt", d, numero=NUM)
        self.assertNotIn("polo_cliente", campos)
        self.assertNotIn("parte_contraria", campos)

    def test_normalizacao_de_valores_e_datas(self):
        d = _fixture("trt_processo.json")
        d.update(valorDaCausa="R$ 1.234,56", autuadoEm="10/03/2026")
        campos = capa.extrair("trt", d, numero=NUM)
        self.assertEqual(self.valor(campos, "valor_causa"), "1234.56")
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-03-10")
        d.update(autuadoEm="31/02/2026", valorDaCausa="não informado")
        campos, avisos = capa.extrair_com_avisos("trt", d, numero=NUM)
        self.assertNotIn("valor_causa", campos)
        self.assertEqual(self.valor(campos, "data_ajuizamento"), "2026-02-03")  # caiu na distribuição (movimento), com aviso
        self.assertIn("capa_valor_ilegivel", [a["codigo"] for a in avisos])
        d.update(valorDaCausa=0)
        campos, avisos = capa.extrair_com_avisos("trt", d, numero=NUM)
        self.assertNotIn("valor_causa", campos)
        self.assertIn("capa_valor_zerado", [a["codigo"] for a in avisos])

    def test_dados_vazios_ou_ilegiveis_viram_aviso_nao_excecao(self):
        self.assertEqual(capa.extrair_com_avisos("autos", None)[1][0]["codigo"], "capa_sem_dados")
        self.assertEqual(capa.extrair_com_avisos("trt", "texto solto")[1][0]["codigo"], "capa_dados_ilegiveis")
        self.assertEqual(capa.extrair_com_avisos("autos", 12345)[1][0]["codigo"], "capa_dados_ilegiveis")
        self.assertEqual(capa.extrair_com_avisos("datajud", {"hits": "estranho"})[1][0]["codigo"], "capa_processo_nao_encontrado")
        self.assertEqual(capa.extrair("djen", {"items": "x"}), {})
        self.assertEqual(capa.extrair("autos", "<html><body>nada de processo aqui</body></html>"), {})

    def test_fonte_desconhecida_e_erro_de_programacao(self):
        with self.assertRaises(ValueError):
            capa.extrair("receita", {})

    def test_mesclar_e_divergencia_entre_fontes(self):
        trt = capa.extrair("trt", _fixture("trt_processo.json"), numero=NUM)
        dj = capa.extrair("datajud", _fixture("datajud_resposta.json"), numero=NUM)
        m = capa.mesclar(trt, dj)
        self.assertEqual(self.valor(m, "vara"), "2ª Vara do Trabalho de Cidade Exemplo")  # empate de confiança: a primeira
        self.assertEqual(self.valor(m, "uf"), "CE")  # só o DataJud trouxe
        final, avisos = capa.extrair_varias([("trt", _fixture("trt_processo.json")), ("datajud", _fixture("datajud_resposta.json"))], numero=NUM)
        divergentes = [a for a in avisos if a["codigo"] == "capa_fontes_divergem"]
        self.assertTrue(any("Vara" in a["mensagem"] for a in divergentes))
        self.assertTrue(all(a["candidatos"] for a in divergentes))
        # mesma capa em duas fontes não gera aviso de divergência
        _, avisos = capa.extrair_varias([("datajud", _fixture("datajud_resposta.json")), ("datajud", _fixture("datajud_resposta.json"))], numero=NUM)
        self.assertNotIn("capa_fontes_divergem", [a["codigo"] for a in avisos])

    def test_de_coleta_converte_o_capa_do_resultado_do_coletor(self):
        resultado = {"capa": {"vara": "1ª Vara", "classe": "Classe X", "polo_cliente": "ativo", "parte_contraria": "Fulano",
                              "data_ajuizamento": "2026-01-05"}, "movimentos": [], "documentos": [], "erro": None}
        c = capa.de_coleta(resultado)
        self.assertEqual(set(c), {"vara", "classe", "data_ajuizamento"})
        self.assertEqual(c["vara"]["confianca"], "alta")


class TestAplicar(Base):
    def setUp(self):
        super().setUp()
        super_ = capa.extrair("trt", _fixture("trt_processo.json"), numero=NUM)
        self.capa = super_
        self.f = ficha.nova_ficha(NUM)

    def test_grava_como_coletado_com_evidencia_e_devolve_o_que_mudou(self):
        mudancas = capa.aplicar(self.f, self.capa)
        campos_mudados = {m["campo"] for m in mudancas}
        self.assertEqual(campos_mudados, set(self.capa))
        self.assertEqual(ficha.obter(self.f, "vara"), "2ª Vara do Trabalho de Cidade Exemplo")
        self.assertEqual(ficha.origem(self.f, "vara"), "coletado")
        self.assertEqual(ficha.obter(self.f, "data_ajuizamento"), "2026-02-02")
        self.assertEqual(ficha.obter(self.f, "valor_causa"), "50000.00")
        self.assertIn("confiança alta", self.f["campos"]["vara"]["evidencia"])
        self.assertIn("confiança media", self.f["campos"]["data_ajuizamento"]["evidencia"])
        self.assertEqual(ficha.validar(self.f), [])
        self.assertTrue(all(m["antes"] is None for m in mudancas))

    def test_idempotente(self):
        capa.aplicar(self.f, self.capa)
        antes = copy.deepcopy(self.f)
        self.assertEqual(capa.aplicar(self.f, self.capa), [])
        self.assertEqual(self.f["campos"].keys(), antes["campos"].keys())
        self.assertEqual({k: v["valor"] for k, v in self.f["campos"].items()}, {k: v["valor"] for k, v in antes["campos"].items()})

    def test_humano_nunca_e_sobrescrito_e_migrado_e_substituido_por_coletado(self):
        ficha.definir(self.f, "vara", "Vara digitada à mão", "humano")
        ficha.definir(self.f, "classe", "Classe do relatório antigo", "migrado")
        mudancas = {m["campo"]: m for m in capa.aplicar(self.f, self.capa)}
        self.assertEqual(ficha.obter(self.f, "vara"), "Vara digitada à mão")
        self.assertNotIn("vara", mudancas)
        self.assertEqual(ficha.obter(self.f, "classe"), "Ação Trabalhista - Rito Ordinário")
        self.assertEqual(mudancas["classe"]["antes"], "Classe do relatório antigo")

    def test_coleta_nova_substitui_a_coleta_antiga(self):
        capa.aplicar(self.f, self.capa)
        nova = copy.deepcopy(self.capa)
        nova["vara"]["valor"] = "5ª Vara do Trabalho de Cidade Exemplo"
        m = capa.aplicar(self.f, nova)
        self.assertEqual([x["campo"] for x in m], ["vara"])
        self.assertEqual(ficha.obter(self.f, "vara"), "5ª Vara do Trabalho de Cidade Exemplo")

    def test_somente_vazios_preserva_o_migrado(self):
        ficha.definir(self.f, "classe", "Classe do relatório antigo", "migrado")
        capa.aplicar(self.f, self.capa, somente_vazios=True)
        self.assertEqual(ficha.obter(self.f, "classe"), "Classe do relatório antigo")
        self.assertEqual(ficha.obter(self.f, "vara"), "2ª Vara do Trabalho de Cidade Exemplo")

    def test_confianca_baixa_so_preenche_vazio(self):
        dj = capa.extrair("djen", _fixture("djen_publicacoes.json"), cliente=CLIENTE)
        ficha.definir(self.f, "autores", "Autor curado à mão", "migrado")
        capa.aplicar(self.f, dj)
        self.assertEqual(ficha.obter(self.f, "autores"), "Autor curado à mão")      # baixa não sobrescreve
        self.assertEqual(ficha.obter(self.f, "reus"), "CLIENTE EXEMPLO 01 LTDA; Empresa Tomadora Fictícia S.A.")  # vazio: preenche

    def test_parte_contraria_so_quando_vazia_e_polo_cliente_nunca(self):
        dj = capa.extrair("djen", _fixture("djen_publicacoes.json"), cliente=CLIENTE)
        dj["polo_cliente"] = {"valor": "passivo", "confianca": "alta", "evidencia": "forçado no teste"}
        capa.aplicar(self.f, dj)
        self.assertEqual(ficha.obter(self.f, "parte_contraria"), "PESSOA FICTICIA 0001")
        self.assertIsNone(ficha.obter(self.f, "polo_cliente"))
        ficha.limpar(self.f, "parte_contraria")
        dj["parte_contraria"] = {"valor": "Outra Pessoa", "confianca": "alta", "evidencia": "x"}
        capa.aplicar(self.f, dj)
        self.assertEqual(ficha.obter(self.f, "parte_contraria"), "Outra Pessoa")
        dj["parte_contraria"]["valor"] = "Ainda Outra"
        capa.aplicar(self.f, dj)
        self.assertEqual(ficha.obter(self.f, "parte_contraria"), "Outra Pessoa")  # já preenchida: não troca

    def test_nao_toca_campos_fora_da_capa(self):
        ficha.definir(self.f, "resultado", "Procedente", "humano")
        ficha.definir(self.f, "momento_atual", "CUMPRIMENTO DE SENTENÇA", "migrado")
        capa.aplicar(self.f, self.capa)
        self.assertEqual(ficha.obter(self.f, "resultado"), "Procedente")
        self.assertEqual(ficha.obter(self.f, "momento_atual"), "CUMPRIMENTO DE SENTENÇA")

    def test_capa_vazia_nao_faz_nada(self):
        self.assertEqual(capa.aplicar(self.f, {}), [])
        self.assertEqual(capa.aplicar(self.f, None), [])
        self.assertEqual(self.f["campos"], {})


class TestCarteiraFicticia(Base):
    def test_fluxo_completo_em_fichas_da_carteira_ficticia(self):
        fichas = gerar_carteira(30, clientes=3, semente=4)
        trt = _fixture("trt_processo.json")
        for f in fichas:
            ok = capa.extrair("trt", {**trt, "numero": f["numero"]}, numero=f["numero"])
            capa.aplicar(f, ok)
            self.assertEqual(ficha.validar(f), [], f["numero"])
        # dados de outro processo nunca entram
        f = fichas[0]
        antes = copy.deepcopy(f)
        campos, avisos = capa.extrair_com_avisos("trt", {**trt, "numero": fichas[1]["numero"]}, numero=f["numero"])
        self.assertEqual(campos, {})
        self.assertEqual(capa.aplicar(f, campos), [])
        self.assertEqual(f["campos"], antes["campos"])


class TestConfidencialidade(unittest.TestCase):
    def test_nenhum_numero_real_nos_arquivos_do_workstream(self):
        import re
        padrao = re.compile(r"\b[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}\b")
        permitido = re.compile(r"0000000-00\.0000\.0\.00\.0000|9999999-99\.9999\.9\.99\.9999|123456[7-9]-|1234570-")
        raiz = Path(__file__).resolve().parent.parent
        arquivos = [raiz / "src" / "capa.py", raiz / "src" / "djen.py", Path(__file__), *(FIXTURES / "capa").glob("*")]
        arquivos.append(raiz / "docs" / "fase2" / "spikes" / "S3-datajud.md")
        for a in arquivos:
            if not a.exists():
                continue
            for n in padrao.findall(a.read_text(encoding="utf-8")):
                self.assertTrue(permitido.search(n), f"{a.name}: número fora do permitido ({n})")


if __name__ == "__main__":
    unittest.main()
