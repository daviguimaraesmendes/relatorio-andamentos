"""Leitor dos autos pelo PJe do advogado (src/pje_trt.py): sessão falsa, relatório temporário, dados fictícios, sem rede.

    python3 -m unittest tests/test_pje_trt.py -v
"""
import base64
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import acesso  # noqa: E402
import comum  # noqa: E402
import coletor  # noqa: E402
import pdpj  # noqa: E402
import pje_trt  # noqa: E402
from ficticio import numero_ficticio  # noqa: E402

N1 = numero_ficticio(1, j=5, tr=7)                  # Justiça do Trabalho, TRT7
N_TJ = numero_ficticio(1)                          # Justiça estadual
PDF = b"%PDF-1.4 conteudo ficticio"
CLIENTE = "Cliente Exemplo 01 Ltda"


def item(i, data, titulo, documento=False, tipo=None, sigiloso=False):
    return {"id": i, "idUnicoDocumento": f"u{i}", "titulo": titulo, "tipo": tipo or ("Petição" if documento else ""),
            "data": data, "documento": documento, "documentoSigiloso": sigiloso}


TIMELINE = [item(101, "2026-10-08T10:00:00.100", "Juntada de petição"),
            item(102, "2026-10-08T10:00:00.200", "Petição inicial", documento=True, tipo="Petição Inicial"),
            item(103, "2026-09-01T09:00:00.000", "Audiência designada"),
            item(104, "2026-08-01T09:00:00.000", "Contestação", documento=True, tipo="Contestação")]


class ChamadasFalsas:
    """Responde no lugar do `fetch` do navegador e guarda o que foi pedido."""

    def __init__(self, timeline=None, acervo=True, status=200, pdf=PDF, instancia=1, outra=False):
        self.pedidos, self.timeline, self.acervo, self.status, self.pdf = [], TIMELINE if timeline is None else timeline, acervo, status, pdf
        self.instancia, self.outra = instancia, outra

    def __call__(self, caminho, binario=False):
        self.pedidos.append(caminho)
        if self.status != 200:
            return {"status": self.status, "tipo": "", "texto": ""}
        if "/paineladvogado/" in caminho:
            res = [{"id": 555, "numeroProcesso": N1}] if self.acervo else []
            return {"status": 200, "tipo": "application/json", "texto": json.dumps({"resultado": res})}
        if re.search(r"/processos/id/\d+$", caminho):
            d = {"id": 555}
            if self.instancia is not None:
                d["instancia"] = self.instancia
            if self.outra is not None:
                d["outraInstancia"] = self.outra
            return {"status": 200, "tipo": "application/json", "texto": json.dumps(d)}
        if caminho.endswith("buscarDocumentos=true"):
            return {"status": 200, "tipo": "application/json", "texto": json.dumps(self.timeline)}
        if "/conteudo" in caminho:
            return {"status": 200, "tipo": "application/pdf", "b64": base64.b64encode(self.pdf).decode()}
        return {"status": 404, "tipo": "", "texto": ""}


class PaginaFalsa:
    def __init__(self, jwt_id=424242):
        carga = base64.urlsafe_b64encode(json.dumps({"id": jwt_id}).encode()).decode().rstrip("=")
        self.context = mock.Mock()
        self.context.cookies.return_value = [{"name": "access_token", "value": f"x.{carga}.y"}]


def sessao(**kw):
    ch = ChamadasFalsas(**kw)
    return pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=ch), ch


class Base(unittest.TestCase):
    def setUp(self):
        nome = f"{type(self).__name__}-{self._testMethodName}"
        self.salvo = {n: getattr(comum, n) for n in ("PROJETOS_DIR", "DOCS_DIR", "DIAG_DIR", "PRINTS_DIR")}
        raiz = TMP / "pje-trt" / nome
        raiz.mkdir(parents=True, exist_ok=True)
        comum.PROJETOS_DIR, comum.DOCS_DIR, comum.DIAG_DIR, comum.PRINTS_DIR = raiz, raiz / "docs", raiz / "diag", raiz / "prints"
        self.addCleanup(lambda: [setattr(comum, k, v) for k, v in self.salvo.items()])
        pdpj.liberar()
        pje_trt.zerar_rodada()
        self.cofre = {"pdpj_cpf": "x", "pdpj_senha": "y", "pdpj_totp": "z"}
        for alvo in (mock.patch.object(acesso, "obter", lambda c: self.cofre.get(c)),
                     mock.patch.object(coletor, "pausa", lambda *a: None)):
            alvo.start()
            self.addCleanup(alvo.stop)
        self.proc = {"numero": N1, "cliente": CLIENTE}


class Mapeamento(Base):
    def test_timeline_vira_andamentos_e_documentos(self):
        movs, docs = pje_trt.itens_da_timeline(TIMELINE)
        self.assertEqual([m[2] for m in movs], ["Juntada de petição", "Audiência designada"])
        self.assertEqual(movs[0][:2], ("2026-10-08T10:00:00.100|Juntada de petição", "08/10/2026"))
        self.assertEqual([d["id"] for d in docs], ["102", "104"])                       # do mais recente ao mais antigo
        self.assertEqual((docs[0]["unico"], docs[0]["tipo"], docs[0]["data"], docs[0]["publico"]), ("u102", "Petição Inicial", "08/10/2026", True))

    def test_documento_sigiloso_nao_e_publico(self):
        _, docs = pje_trt.itens_da_timeline([item(1, "2026-01-01T00:00:00", "x", documento=True, sigiloso=True)])
        self.assertFalse(docs[0]["publico"])

    def test_numero_do_trt(self):
        self.assertEqual(pje_trt.trt_do_numero(N1), 7)
        self.assertEqual(pje_trt.trt_do_numero(numero_ficticio(2, j=5, tr=11)), 11)
        self.assertIsNone(pje_trt.trt_do_numero(N_TJ))


class Sessao(Base):
    def test_id_do_usuario_vem_do_token_e_a_busca_usa_so_o_numero(self):
        s, ch = sessao()
        achado = s.buscar(N1)
        self.assertEqual(achado["id"], 555)
        self.assertIn("/paineladvogado/424242/processos?numeroProcesso=" + N1, ch.pedidos[0])

    def test_fora_do_acervo(self):
        s, _ = sessao(acervo=False)
        with self.assertRaises(pje_trt.NaoNoAcervo):
            s.buscar(N1)

    def test_sessao_expirada(self):
        s, _ = sessao(status=401)
        with self.assertRaises(pje_trt.SessaoExpirada):
            s.timeline(1)

    def test_so_aceita_pdf(self):
        s, _ = sessao(pdf=b"<html>nao e pdf</html>")
        self.assertIsNone(s.pdf(555, "102"))


class Coleta(Base):
    def coletar(self, s, estado=None, lista=None, historico=5, cota=10, desde=None, relato=None):
        estado = {} if estado is None else estado
        lista = [] if lista is None else lista
        n = pje_trt.coletar_processo(s, self.proc, estado, lista, historico, cota, desde, relato)
        return n, estado, lista

    def test_primeira_leitura_grava_eventos_pdfs_e_estado(self):
        s, _ = sessao()
        n, estado, lista = self.coletar(s)
        self.assertEqual(n, 2)
        tipos = sorted(e["tipo_evento"] for e in lista)
        self.assertEqual(tipos, ["documento", "documento", "movimento", "movimento"])
        docs = [e for e in lista if e["tipo_evento"] == "documento"]
        for d in docs:
            self.assertEqual(Path(d["arquivo"]).read_bytes(), PDF)
            self.assertIsNone(d["print"])
        reg = estado[N1]["trt"]["1"]
        self.assertEqual(len(reg["movimentos"]), 2)
        self.assertEqual(reg["documentos"], ["102", "104"])

    def test_segunda_rodada_sem_novidade_nao_duplica_nada(self):
        s, ch = sessao()
        _, estado, lista = self.coletar(s)
        antes = len(lista)
        ch.pedidos.clear()
        n, _, lista = self.coletar(s, estado=estado, lista=lista)
        self.assertEqual((n, len(lista)), (0, antes))
        self.assertFalse([p for p in ch.pedidos if "/conteudo" in p])                 # nenhum PDF pedido de novo

    def test_so_o_novo_na_segunda_rodada(self):
        s, _ = sessao()
        _, estado, lista = self.coletar(s)
        novo = TIMELINE + [item(105, "2026-10-09T08:00:00.000", "Sentença", documento=True, tipo="Sentença"),
                           item(106, "2026-10-09T08:00:01.000", "Conclusos para julgamento")]
        s2, ch2 = sessao(timeline=novo)
        n, _, lista = self.coletar(s2, estado=estado, lista=lista)
        self.assertEqual(n, 1)
        self.assertEqual(len(lista), 6)
        self.assertEqual(sum("/conteudo" in p for p in ch2.pedidos), 1)

    def test_historico_e_desde_na_primeira_vez(self):
        s, _ = sessao()
        _, _, lista = self.coletar(s, historico=1)
        self.assertEqual(sorted(e["tipo_evento"] for e in lista), ["documento", "movimento"])      # só o mais recente de cada
        import datetime
        _, _, lista = self.coletar(s, historico=0, desde=datetime.date(2026, 9, 15))
        self.assertEqual(sorted(e["tipo_evento"] for e in lista), ["documento", "movimento"])      # os de depois de 15/09

    def test_cota_de_documentos(self):
        s, _ = sessao()
        n, estado, _ = self.coletar(s, cota=1)
        self.assertEqual(n, 1)
        self.assertEqual(estado[N1]["trt"]["1"]["documentos"], ["102"])                # o outro fica para a próxima rodada

    def test_documento_sem_pdf_conta_falha_e_fica_sem_arquivo(self):
        s, _ = sessao(pdf=b"nao pdf")
        n, estado, lista = self.coletar(s)
        self.assertEqual(n, 0)
        self.assertTrue(all(e["arquivo"] is None for e in lista if e["tipo_evento"] == "documento"))
        self.assertEqual(estado[N1]["trt"]["1"]["falhas_documentos"], {"102": 1, "104": 1})

    RECURSO = item(110, "2026-10-09T09:00:00.000", "Remetidos os autos para o TRT (recurso ordinário)")

    def test_pje_diz_que_ha_outra_instancia_vira_aviso_e_fica_registrado(self):
        s, _ = sessao(outra=True)
        relato = {}
        _, estado, _ = self.coletar(s, relato=relato)
        self.assertEqual([a["codigo"] for a in relato["avisos"]], ["grau_nao_lido"])
        self.assertIn("também está em outra instância", relato["avisos"][0]["mensagem"])
        self.assertEqual(relato["graus_lidos"], ["1"])
        self.assertEqual((estado[N1]["instancia"]["atual"], estado[N1]["instancia"]["outra_instancia"]), (1, True))

    def test_pje_diz_que_nao_ha_outra_instancia_nao_avisa_mesmo_com_texto_de_recurso(self):
        s, _ = sessao(timeline=TIMELINE + [self.RECURSO], outra=False)
        relato = {}
        _, estado, _ = self.coletar(s, relato=relato)
        self.assertEqual(relato["avisos"], [])
        self.assertIs(estado[N1]["instancia"]["outra_instancia"], False)

    def test_sem_a_informacao_do_pje_vale_o_indicio_pelos_andamentos(self):
        s, _ = sessao(timeline=TIMELINE + [self.RECURSO], instancia=None, outra=None)
        relato = {}
        _, estado, _ = self.coletar(s, relato=relato)
        self.assertEqual([a["codigo"] for a in relato["avisos"]], ["grau_nao_lido"])
        self.assertEqual(estado[N1]["instancia"], {"atual": None, "outra_instancia": None, "verificado_em": estado[N1]["instancia"]["verificado_em"]})

    def test_preserva_estado_de_outro_grau_ja_lido(self):
        s, _ = sessao()
        estado = {N1: {"trt": {"2": {"movimentos": ["a"], "documentos": [], "falhas_documentos": {}}}}}
        _, estado, _ = self.coletar(s, estado=estado)
        self.assertEqual(set(estado[N1]["trt"]), {"1", "2"})

    def test_sessao_expirada_no_meio_sobe_para_o_chamador(self):
        s, _ = sessao(status=403)
        with self.assertRaises(pje_trt.SessaoExpirada):
            self.coletar(s)


class SessaoDaRodada(Base):
    def entrar_falso(self, falha=None):
        chamadas = []

        def entrar(nav, trt, consulta=True):
            chamadas.append((trt, consulta))
            if falha:
                raise falha
        entrar.chamadas = chamadas
        return entrar

    def test_sem_credenciais_nao_tenta_nada(self):
        self.cofre.pop("pdpj_senha")
        e = self.entrar_falso()
        self.assertIsNone(pje_trt.sessao_da_rodada(object(), N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(e.chamadas, [])

    def test_fora_da_justica_do_trabalho_nao_tenta_nada(self):
        e = self.entrar_falso()
        self.assertIsNone(pje_trt.sessao_da_rodada(object(), N_TJ, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(e.chamadas, [])

    def test_login_uma_vez_por_trt_e_rodada(self):
        e, ctx = self.entrar_falso(), object()
        a = pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        b = pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        self.assertIsNotNone(a)
        self.assertIs(a, b)
        self.assertEqual(e.chamadas, [(7, False)])

    def test_falha_do_login_nunca_e_repetida_na_rodada(self):
        e, ctx = self.entrar_falso(pdpj.PdpjErro("recusado", "x", trava=True)), object()
        self.assertIsNone(pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertIsNone(pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(len(e.chamadas), 1)                                           # uma tentativa só
        self.assertTrue(pje_trt.AVISOS)

    def test_erro_inesperado_tambem_nao_repete_nem_derruba(self):
        e, ctx = self.entrar_falso(RuntimeError("boom")), object()
        self.assertIsNone(pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertIsNone(pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(len(e.chamadas), 1)

    def test_com_trava_nao_abre_nem_a_pagina(self):
        pdpj.travar("recusado", "x")
        self.addCleanup(pdpj.liberar)
        aberturas = []
        self.assertIsNone(pje_trt.sessao_da_rodada(object(), N1, abrir_pagina=lambda c: aberturas.append(1), entrar=self.entrar_falso()))
        self.assertEqual(aberturas, [])

    def test_sessao_que_cai_vai_para_a_consulta_publica_sem_novo_login(self):
        e, ctx = self.entrar_falso(), object()
        pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        pje_trt.encerrar_sessao(ctx, N1)
        self.assertIsNone(pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(len(e.chamadas), 1)

    def test_navegador_reaberto_no_meio_da_rodada_nao_repete_o_login(self):
        """ColetorReal.fechar() + reabertura (sessao_expirada da consulta pública) gera outro contexto: o PDPJ não é refeito."""
        e = self.entrar_falso()
        antigo, novo = object(), object()
        self.assertIsNotNone(pje_trt.sessao_da_rodada(antigo, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertIsNone(pje_trt.sessao_da_rodada(novo, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertIsNone(pje_trt.sessao_da_rodada(novo, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(len(e.chamadas), 1)
        self.assertEqual(len(pje_trt.AVISOS), 1)                                       # avisa uma vez só

    def test_navegador_reaberto_depois_de_falha_sem_envio_tambem_nao_tenta_de_novo(self):
        """Falha antes de enviar credencial não deixa trava, mas a rodada já gastou a tentativa."""
        e = self.entrar_falso(pdpj.PdpjErro("site", "bloqueado", trava=False))
        self.assertIsNone(pje_trt.sessao_da_rodada(object(), N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertIsNone(pje_trt.sessao_da_rodada(object(), N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(len(e.chamadas), 1)

    def test_sessao_que_cai_e_navegador_reaberto_nao_loga_de_novo(self):
        e, antigo = self.entrar_falso(), object()
        pje_trt.sessao_da_rodada(antigo, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        pje_trt.encerrar_sessao(antigo, N1)
        self.assertIsNone(pje_trt.sessao_da_rodada(object(), N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(len(e.chamadas), 1)

    def test_outro_trt_na_mesma_rodada_tem_o_seu_proprio_login(self):
        e, ctx = self.entrar_falso(), object()
        pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        pje_trt.sessao_da_rodada(ctx, numero_ficticio(2, j=5, tr=11), abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        self.assertEqual([c[0] for c in e.chamadas], [7, 11])

    def test_nova_rodada_permite_novo_login(self):
        e, ctx = self.entrar_falso(), object()
        pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        pje_trt.zerar_rodada()
        pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        self.assertEqual(len(e.chamadas), 2)

    def test_ctrl_c_durante_o_login_sobe_e_a_tentativa_fica_gasta(self):
        e, ctx = self.entrar_falso(KeyboardInterrupt()), object()
        with self.assertRaises(KeyboardInterrupt):
            pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        self.assertIsNone(pje_trt.sessao_da_rodada(ctx, N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e))
        self.assertEqual(len(e.chamadas), 1)

    def test_aviso_nao_carrega_dados_da_pagina_alem_da_mensagem_ja_limpa(self):
        e = self.entrar_falso(RuntimeError("https://x.invalid/?token=abc"))
        pje_trt.sessao_da_rodada(object(), N1, abrir_pagina=lambda c: PaginaFalsa(), entrar=e)
        self.assertNotIn("abc", " ".join(pje_trt.AVISOS))                              # só o nome da exceção


class RespostasDoPje(Base):
    def test_pagina_de_login_com_http_200_e_sessao_vencida(self):
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 200, "tipo": "text/html", "texto": "<html>login</html>"})
        with self.assertRaises(pje_trt.SessaoExpirada):
            s.timeline(1)

    def test_token_ilegivel_e_sessao_expirada_sem_citar_o_token(self):
        pagina = PaginaFalsa()
        pagina.context.cookies.return_value = [{"name": "access_token", "value": "a.@@@.c"}]
        s = pje_trt.SessaoPje(pagina, 7, chamar=ChamadasFalsas())
        with self.assertRaises(pje_trt.SessaoExpirada) as ctx:
            s.buscar(N1)
        self.assertNotIn("@@@", str(ctx.exception))

    def test_resultado_com_id_que_nao_e_numero_nao_vira_url(self):
        ch = ChamadasFalsas()
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 200, "tipo": "json", "texto": json.dumps(
            {"resultado": [{"id": "../../admin", "numeroProcesso": N1}]})})
        with self.assertRaises(pje_trt.NaoNoAcervo):
            s.buscar(N1)
        self.assertEqual(ch.pedidos, [])

    def test_varios_resultados_escolhe_o_numero_exato(self):
        outro = numero_ficticio(3, j=5, tr=7)
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 200, "tipo": "json", "texto": json.dumps(
            {"resultado": [{"id": 1, "numeroProcesso": outro}, {"id": 2, "numeroProcesso": re.sub(r"\D", "", N1)}]})})
        self.assertEqual(s.buscar(N1)["id"], 2)                                        # compara só os dígitos: pontuação não importa

    def test_numero_vai_codificado_na_url(self):
        ch = ChamadasFalsas()
        pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=ch).buscar(N1)
        self.assertEqual(ch.pedidos[0].count("&"), 3)                                  # nenhum parâmetro extra vindo do número

    def test_documento_sem_id_na_timeline_e_ignorado(self):
        _, docs = pje_trt.itens_da_timeline(TIMELINE + [item(None, "2026-10-09T00:00:00", "Sem id", documento=True)])
        self.assertEqual([d["id"] for d in docs], ["102", "104"])

    def test_403_em_um_documento_nao_derruba_a_sessao(self):
        ch = ChamadasFalsas()
        base = ch.__call__

        def chamar(caminho, binario=False):
            if "/documentos/id/102/" in caminho:
                return {"status": 403, "tipo": "", "texto": ""}
            return base(caminho, binario)
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=chamar)
        with self.assertRaises(pje_trt.SemAcesso):
            s.pdf(555, "102")
        self.assertEqual(s.pdf(555, "104"), PDF)                                       # o resto continua
        with self.assertRaises(pje_trt.SessaoExpirada):                                # 403 fora de documento continua sendo sessão
            pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 403, "tipo": "", "texto": ""}).timeline(1)

    def test_documento_sigiloso_negado_fica_sem_arquivo_e_a_coleta_segue(self):
        ch = ChamadasFalsas()
        base = ch.__call__
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 403, "tipo": "", "texto": ""}
                              if "/documentos/id/102/" in c else base(c, b))
        estado, lista = {}, []
        n = pje_trt.coletar_processo(s, self.proc, estado, lista, 5, 10, None, {})
        self.assertEqual(n, 1)
        self.assertEqual(estado[N1]["trt"]["1"]["falhas_documentos"], {"102": 1})

    def test_pdf_corrompido_em_base64_invalido_nao_derruba_a_coleta(self):
        ch = ChamadasFalsas()
        base = ch.__call__
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 200, "tipo": "application/pdf", "b64": "@@@"}
                              if "/conteudo" in c else base(c, b))
        estado, lista = {}, []
        self.assertEqual(pje_trt.coletar_processo(s, self.proc, estado, lista, 5, 10, None, {}), 0)
        self.assertEqual(estado[N1]["trt"]["1"]["falhas_documentos"], {"102": 1, "104": 1})

    def test_documento_gigante_nao_e_trazido(self):
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 200, "tipo": "application/pdf", "grande": True})
        with self.assertRaises(RuntimeError):
            s.pdf(555, "102")

    def test_a_chamada_do_navegador_so_faz_get_e_com_limite(self):
        self.assertIn("method: 'GET'", pje_trt._JS)
        for proibido in ("POST", "PUT", "DELETE", "PATCH", "body:", "XMLHttpRequest", "sendBeacon"):
            self.assertNotIn(proibido, pje_trt._JS)
        pagina = mock.Mock()
        pagina.evaluate.return_value = {"status": 200, "texto": "{}"}
        pje_trt.SessaoPje(pagina, 7).timeline(1)
        _, args = pagina.evaluate.call_args[0]
        self.assertEqual(args[1:], [False, pje_trt.LIMITE_PDF])

    def test_so_ha_caminhos_de_leitura(self):
        """Todos os caminhos que a sessão pede são de leitura do painel/autos: nada de protocolo, assinatura ou ciência."""
        s, ch = sessao()
        pje_trt.coletar_processo(s, self.proc, {}, [], 5, 10, None, {})
        for caminho in ch.pedidos:
            self.assertTrue(caminho.startswith(pje_trt.API), caminho)
            self.assertNotRegex(caminho.split("?")[0],r"(?i)protocol|assin|ciencia|expediente|peticion|intima")


class SessaoCaiNoMeio(Base):
    def test_relato_do_chamador_nao_fica_com_restos_da_leitura_interrompida(self):
        """O PJe cai no PDF do 1º documento: o relato (que a consulta pública vai preencher) fica como estava."""
        ch = ChamadasFalsas(outra=True)
        base = ch.__call__
        s = pje_trt.SessaoPje(PaginaFalsa(), 7, chamar=lambda c, b=False: {"status": 401, "tipo": "", "texto": ""}
                              if "/conteudo" in c else base(c, b))
        relato, estado = {}, {}
        with self.assertRaises(pje_trt.SessaoExpirada):
            pje_trt.coletar_processo(s, self.proc, estado, [], 5, 10, None, relato)
        self.assertEqual(relato, {})
        self.assertEqual(estado, {})                                                   # o estado só avança quando a leitura termina

    def test_relato_preenchido_so_no_fim(self):
        s, _ = sessao(outra=True)
        relato = {"avisos": [{"codigo": "antigo"}]}
        pje_trt.coletar_processo(s, self.proc, {}, [], 5, 10, None, relato)
        self.assertEqual([a["codigo"] for a in relato["avisos"]], ["antigo", "grau_nao_lido"])
        self.assertEqual(relato["graus_lidos"], ["1"])


if __name__ == "__main__":
    unittest.main()
