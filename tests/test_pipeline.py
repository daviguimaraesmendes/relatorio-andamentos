"""Testa o caminho inteiro com um Ollama falso e um DJEN falso: sem rede, sem
login e sem tocar em data/, carteira.json ou clientes.json reais.

    python3 -m unittest tests/test_pipeline.py -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolamento import TMP  # noqa: E402  (antes de tudo)
import comum  # noqa: E402
import carteira, djen, extrair, relatorio, resumir, traduzir  # noqa: E402,E401
from traduzir import autoria, frase_documento, separar_nome_documento  # noqa: E402

CLIENTE = "EMPRESA TESTE COMERCIO LTDA"
PROC = "1234567-06.2026.8.06.0001"     # dígito verificador correto
PROC_2 = "1234568-72.2024.4.05.8100"
PROC_INVALIDO = "1234567-07.2026.8.06.0001"

DECISAO = f"""<html><body><p>PODER JUDICIÁRIO DO ESTADO DO CEARÁ</p><p>DECISÃO</p>
<p>Autor: FULANO DE TAL. Réu: {CLIENTE}.</p>
<p>Trata-se de pedido de tutela de urgência formulado pelo autor contra a ré Empresa Teste Comércio Ltda.</p>
<p>Ante o exposto, INDEFIRO o pedido de tutela de urgência, por ausência de perigo de dano.</p>
<p>Designo audiência de conciliação para o dia 12/11/2026, às 9h. Intime-se a ré para contestar no prazo de 15 dias.</p>
<p>Fortaleza, 01/10/2026. Juiz de Direito</p></body></html>"""

PETICAO_NOSSA = f"""<html><body><p>EXCELENTÍSSIMO SENHOR JUIZ</p><p>{CLIENTE}, já qualificada, requer a juntada
do comprovante de pagamento das custas processuais, para regular prosseguimento do feito.</p>
<p>Nestes termos, pede deferimento. Fortaleza, 02 de outubro de 2026.</p><p>Fulano Advogado Teste – OAB/CE 99.999</p></body></html>"""

RESPOSTAS = {
    "Decisão": {"conteudo": "dizendo que o pedido de urgência da parte contrária foi negado e marcando audiência de conciliação",
                "trecho_origem": "Ante o exposto, INDEFIRO o pedido de tutela de urgência",
                "prazo": "15 dias para a empresa contestar", "audiencia": "12/11/2026, às 9h", "efeito": "favoravel"},
    # trecho inventado e prazo com número que não existe: tem de virar alerta
    "Petição (outras)": {"conteudo": "pedindo a juntada do comprovante das custas",
                         "trecho_origem": "requer a condenação do réu em honorários de 20%",
                         "prazo": "30 dias", "audiencia": None, "efeito": "neutro"},
    "Sentença": {"conteudo": "dizendo que o pedido do autor contra nosso cliente foi julgado procedente",
                 "trecho_origem": "JULGO PROCEDENTE o pedido", "prazo": None, "audiencia": None, "efeito": "desfavoravel"},
}
PEDIDOS = []


class OllamaFalso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self._json({"models": [{"name": "teste:3b"}]})

    def do_POST(self):
        pedido = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        texto = pedido["messages"][1]["content"]
        PEDIDOS.append(texto)
        tipo = next(l for l in texto.splitlines() if l.startswith("Tipo do documento: ")).removeprefix("Tipo do documento: ")
        self._json({"message": {"content": json.dumps(RESPOSTAS[tipo])}})

    def _json(self, dados):
        corpo = json.dumps(dados).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corpo)


def item_djen(num, destinatarios, tipo="Intimação", texto="", id_=1, data="2026-09-30"):
    return {"id": id_, "numeroprocessocommascara": num, "siglaTribunal": "TJCE", "nomeClasse": "PROCEDIMENTO COMUM",
            "nomeOrgao": "1ª Vara", "tipoComunicacao": "Intimação", "tipoDocumento": tipo, "texto": texto,
            "data_disponibilizacao": data, "destinatarios": [{"nome": n, "polo": p} for n, p in destinatarios]}


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), OllamaFalso)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cfg = dict(comum.config())  # config.json ou config.exemplo.json (repositório recém-clonado)
        cfg.update(modelo="teste:3b", ollama_url=f"http://127.0.0.1:{cls.srv.server_port}",
                   identificadores_escritorio=["Fulano Advogado Teste", "99.999"])  # não depende de quem instala
        for mod in (comum, resumir, traduzir):
            mod.config = lambda: cfg
        comum.save_json(comum.CLIENTES_FILE, {"clientes": [{"nome": CLIENTE, "variacoes": ["EMPRESA TESTE"]}]})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_1_importar_lista(self):
        lista = TMP / "lista.csv"
        lista.write_text(f"Processo;Cliente;Polo;Parte contrária\n{PROC};{CLIENTE};réu;FULANO DE TAL\n"
                         f"{PROC_INVALIDO};{CLIENTE};réu;X\n", encoding="utf-8")
        regs, ruins = carteira.ler_lista(str(lista))
        self.assertEqual(ruins, [PROC_INVALIDO])
        self.assertEqual(regs[0]["polo_cliente"], "passivo")
        self.assertEqual(regs[0]["tribunal"], "TJCE")
        self.assertEqual(carteira.mesclar(regs, "lista"), 1)

        texto = TMP / "colado.txt"
        texto.write_text(f"Seguem: 12345687220244058100 e de novo {PROC}.", encoding="utf-8")
        regs, _ = carteira.ler_lista(str(texto), CLIENTE)
        self.assertEqual([(r["numero"], r["tribunal"]) for r in regs], [(PROC_2, "TRF5"), (PROC, "TJCE")])
        self.assertEqual(carteira.mesclar(regs, "lista"), 1, "processo já na carteira não duplica")
        proc = comum.carteira()[PROC]
        self.assertEqual(proc["parte_contraria"], "FULANO DE TAL", "mesclar não apaga o que já estava preenchido")

    def test_2_completar_e_descobrir_djen(self):
        publicacoes = {
            PROC_2: [item_djen(PROC_2, [("EMPRESA TESTE COMERCIO LTDA", "A"), ("UNIAO FEDERAL", "P")])],
        }
        por_nome = [
            item_djen(PROC, [(CLIENTE, "P"), ("FULANO DE TAL", "A")]),           # já na carteira
            item_djen("1234569-95.2026.5.07.0001", [("EMPRESA TESTE COMERCIO", "P"), ("BELTRANO", "A")]),  # novo
            item_djen("1234570-58.2026.8.06.0001", [("EMPRESA TESTE DE OUTRA COISA SA", "P")]),  # homônimo parcial
        ]
        djen.buscar = lambda **f: publicacoes.get(f.get("numeroProcesso"), []) if "numeroProcesso" in f else por_nome
        carteira.completar_com_djen()
        p2 = comum.carteira()[PROC_2]
        self.assertEqual((p2["polo_cliente"], p2["parte_contraria"]), ("ativo", "UNIAO FEDERAL"))

        djen.descobrir(30)
        pend = comum.load_json(djen.DESCOBERTA_FILE, {})["pendentes"]
        self.assertEqual([p["numero"] for p in pend], ["1234569-95.2026.5.07.0001"])
        self.assertEqual((pend[0]["polo_cliente"], pend[0]["outras_partes"]), ("passivo", "BELTRANO"))
        djen.incluir(["todos"])
        self.assertIn("1234569-95.2026.5.07.0001", comum.carteira())
        djen.ignorar(["1234570-58.2026.8.06.0001"])
        djen.descobrir(30)
        self.assertEqual(comum.load_json(djen.DESCOBERTA_FILE, {})["pendentes"], [])

    def test_3_caminho_completo_com_perspectiva(self):
        docs = comum.DATA / "documentos" / "teste"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "decisao.html").write_text(DECISAO, encoding="utf-8")
        (docs / "peticao.html").write_text(PETICAO_NOSSA, encoding="utf-8")
        sentenca = ("SENTENÇA. Autor: FULANO DE TAL. Ré: EMPRESA TESTE COMERCIO LTDA. " * 5
                    + "Ante o exposto, JULGO PROCEDENTE o pedido para condenar a ré.")
        (docs / "sentenca.html").write_text(f"<p>{sentenca}</p>", encoding="utf-8")
        base = {"numero": PROC, "cliente": CLIENTE, "apelido": "Teste", "tipo_evento": "documento",
                "detectado_em": "2026-10-03T19:00:00", "status": "coletado"}
        mov = {**base, "tipo_evento": "movimento"}
        comum.salvar_eventos([
            {**base, "id": "a:1", "titulo": "1 - Decisão - Decisão.html", "tipo": "Decisão", "descricao": "Decisão",
             "arquivo": str(docs / "decisao.html")},
            {**base, "id": "a:2", "titulo": "2 - Petição (outras) - Custas.html", "tipo": "Petição (outras)",
             "descricao": "Custas", "arquivo": str(docs / "peticao.html")},
            {**base, "id": "a:6", "titulo": "3 - Sentença - Sentença.html", "tipo": "Sentença", "descricao": "Sentença",
             "arquivo": str(docs / "sentenca.html")},
            {**mov, "id": "a:3", "titulo": "Conclusos para decisão", "data": "02/10/2026", "chave": "02/10/2026|Conclusos para decisão|1"},
            {**mov, "id": "a:4", "titulo": "Confirmada a comunicação eletrônica", "data": "29/09/2026"},
            {**mov, "id": "a:5", "titulo": "Juntada de Petição de petição", "data": "03/10/2026"},
        ])
        extrair.rodar()
        resumir.rodar()
        evs = {e["id"]: e for e in comum.eventos()}

        dec = evs["a:1"]
        self.assertEqual(dec["frase"], "Foi proferida decisão.")
        self.assertEqual(dec["efeito"], "favoravel")
        self.assertEqual(dec.get("alertas", []), [], "decisão conferida, cliente no texto e polo certo: sem alerta")
        pedido_dec = next(p for p in PEDIDOS if "Tipo do documento: Decisão" in p)
        self.assertIn(f"Nosso cliente: {CLIENTE}, que no processo é réu (polo passivo)", pedido_dec)
        self.assertIn("Parte contrária: FULANO DE TAL", pedido_dec)

        pet = evs["a:2"]
        self.assertEqual(pet["autoria"], "nos")
        self.assertTrue(any("trecho citado" in a for a in pet["alertas"]))
        self.assertTrue(any("prazo" in a for a in pet["alertas"]))

        self.assertTrue(any("desfavorável" in a for a in evs["a:6"]["alertas"]))
        self.assertEqual(evs["a:3"]["frase"], "O processo foi encaminhado ao juiz para decisão.")
        self.assertEqual(evs["a:4"]["status"], "descartado")
        self.assertEqual(evs["a:5"]["status"], "descartado", "juntada coberta pelo documento da mesma rodada")

        lista = comum.eventos()
        for e in lista:
            if e["id"] in ("a:1", "a:3"):
                e["status"] = "aprovado"
        comum.salvar_eventos(lista)
        gerados = relatorio.gerar()
        self.assertEqual(len(gerados), 1)
        html = gerados[0].read_text(encoding="utf-8")
        self.assertIn("Foi proferida decisão dizendo que o pedido de urgência da parte contrária foi negado", html)
        self.assertIn("Audiência: 12/11/2026", html)
        self.assertNotIn("custas", html, "rascunho não aprovado não pode sair no relatório")
        self.assertNotIn("favoravel", html, "a classificação de efeito é interna, não vai ao cliente")
        self.assertEqual(relatorio.gerar(), [], "evento já relatado não volta")

        # conferência semanal: o que já foi relatado não volta como pendência
        import conferencia
        relatados = conferencia.ja_relatados(comum.eventos(), PROC)
        movs = [("02/10/2026|Conclusos para decisão|1", "02/10/2026", "Conclusos para decisão"),
                ("01/10/2026|Conclusos para decisão|1", "01/10/2026", "Conclusos para decisão"),
                ("20/09/2026|Audiência designada|1", "20/09/2026", "Audiência designada")]
        docs_tela = [("1 - Decisão - Decisão.html", None), ("9 - Laudo - Laudo.pdf", None)]
        import datetime
        p_movs, p_docs = conferencia.pendencias(movs, docs_tela, relatados, datetime.date(2026, 9, 26))
        self.assertEqual(p_movs, [("01/10/2026", "Conclusos para decisão")],
                         "mesmo texto em outra data é pendência; fora da semana não entra")
        self.assertEqual([n for n, _ in p_docs], ["9 - Laudo - Laudo.pdf"])

    def test_4_regras(self):
        d = separar_nome_documento("189001119 - Petição (outras) - PFN.pdf")
        self.assertEqual((d["id"], d["tipo"], d["ext"]), ("189001119", "Petição (outras)", "pdf"))
        self.assertEqual(autoria("", "Petição (outras)"), "outro")
        self.assertEqual(autoria("... requer ... Fulano de Tal OAB/SP 1", "Contestação"), "contraria")
        self.assertEqual(autoria("Pede deferimento. Valor: R$ 99.999,00. Fulano OAB/SP 1", "Petição"), "contraria")
        self.assertEqual(autoria("Pede deferimento.\nFulano\nOAB-CE 99.999", "Petição"), "nos")
        self.assertEqual(frase_documento("Contestação", "Contestação", "contraria", "ESTADO DO CEARA; MUNICIPIO X"),
                         "A parte contrária (Estado do Ceara) apresentou contestação.")
        self.assertTrue(carteira.nome_bate("Solis Investimentos Ltda.", "SOLIS INVESTIMENTOS"))
        self.assertFalse(carteira.nome_bate("EMPRESA TESTE COMERCIO LTDA", "EMPRESA TESTE DE OUTRA COISA SA"))
        self.assertTrue(resumir.trecho_confere("INDEFIRO o pedido de\ntutela   de urgência", DECISAO))


if __name__ == "__main__":
    unittest.main(verbosity=2)
