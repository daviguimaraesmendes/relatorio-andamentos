"""Consolidação (WS-1): vinculados, duplicatas, grafias, rótulos, idempotência, campo humano e migração da Fase 1.
Só dados fictícios; números vêm de ficticio.numero_ficticio (calculados em tempo de execução)."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: F401  (aponta comum.py para uma pasta temporária)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import comum  # noqa: E402
import consolidar  # noqa: E402
import ficha  # noqa: E402
import taxonomia  # noqa: E402
import ficticio  # noqa: E402
from ficticio import numero_ficticio  # noqa: E402

PERSISTENTES = {"grafias_do_mesmo_nome", "duplicata_provavel", "vinculo_provavel", "numero_invalido",
                "rotulo_fora_do_vocabulario", "vinculado_em_dois_principais", "materia_divergente"}


def nova(i, **campos):
    """Ficha fictícia; cada campo é valor ou (valor, origem). Origem padrão: coletado."""
    f = ficha.nova_ficha(numero_ficticio(i))
    for nome, valor in campos.items():
        valor, origem = valor if isinstance(valor, tuple) else (valor, "coletado")
        assert ficha.definir(f, nome, valor, origem, forcar=True), (nome, valor)
    return f


def codigos(avisos):
    return [a["codigo"] for a in avisos]


def com_codigo(avisos, codigo):
    return [a for a in avisos if a["codigo"] == codigo]


class TestAceiteComDefeitos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sujas = ficticio.gerar_carteira(200, clientes=5, semente=1, com_defeitos=True)
        cls.original = copy.deepcopy(list(cls.sujas))
        cls.saida, cls.avisos = consolidar.consolidar(cls.sujas)
        cls.defeitos = cls.sujas.defeitos

    def test_gabarito_nao_e_vazio(self):
        for tipo in ("numero_duplicado", "materia_dois_rotulos", "grafias_cliente"):
            self.assertTrue(self.defeitos[tipo], tipo)

    def test_nao_altera_a_lista_recebida(self):
        self.assertEqual(list(self.sujas), self.original)

    def test_numero_duplicado(self):
        fundidos = {n for a in com_codigo(self.avisos, "duplicata_exata_fundida") for n in a["numeros"]}
        self.assertLessEqual(set(self.defeitos["numero_duplicado"]), fundidos)
        numeros = [f["numero"] for f in self.saida]
        self.assertEqual(len(numeros), len(set(numeros)))
        for n in self.defeitos["numero_duplicado"]:
            self.assertEqual(numeros.count(n), 1)

    def test_materia_dois_rotulos(self):
        pares = self.defeitos["materia_dois_rotulos"]
        achados = com_codigo(self.avisos, "materia_dois_rotulos")
        por_numero = {f["numero"]: f for f in self.saida}
        for a, b in pares:
            self.assertTrue(any({a, b} <= set(av["numeros"]) for av in achados), (a, b))
            self.assertIn(a, por_numero)
            self.assertNotIn(b, por_numero)                         # a mesma ação deixa de ser contada duas vezes
            principal = por_numero[a]
            self.assertIn((b, "mesma_acao"), [(v["numero"], v["tipo"]) for v in principal["vinculados"]])
            self.assertIn(b, [x["numero"] for x in principal["consolidacao"]["absorvidas"]])
            materia = ficha.obter(principal, "materia_principal")
            self.assertEqual(taxonomia.normalizar("materia", materia), materia)  # um rótulo só, o canônico

    def test_grafias_do_cliente_so_sao_sugeridas(self):
        achados = com_codigo(self.avisos, "grafias_do_mesmo_nome")
        for defeito in self.defeitos["grafias_cliente"]:
            aviso = next(a for a in achados if defeito["canonico"] in a["candidatos"])
            self.assertEqual(aviso["candidatos"][0], defeito["canonico"])           # a sugerida vem primeiro
            self.assertLessEqual(set(defeito["variantes"]), set(aviso["candidatos"]))
        nomes = {ficha.obter(f, "cliente") for f in self.saida}
        for defeito in self.defeitos["grafias_cliente"]:
            self.assertLessEqual(set(defeito["variantes"]), nomes)                  # nada foi fundido sem confirmação

    def test_aplicar_grafias_depois_da_confirmacao(self):
        grupos = consolidar.sugerir_grafias(self.saida)
        confirmadas = [g for g in grupos if g["canonico_sugerido"] in {d["canonico"] for d in self.defeitos["grafias_cliente"]}]
        self.assertTrue(confirmadas)
        unificadas, avisos = consolidar.aplicar_grafias(self.saida, confirmadas)
        for defeito in self.defeitos["grafias_cliente"]:
            nomes = {ficha.obter(f, "cliente") for f in unificadas}
            self.assertIn(defeito["canonico"], nomes)
            self.assertFalse(set(defeito["variantes"]) & nomes)
        self.assertTrue(avisos)
        alterada = next(f for f in unificadas if f.get("consolidacao", {}).get("originais", {}).get("cliente"))
        self.assertEqual(alterada["cliente"], ficha.obter(alterada, "cliente"))     # espelho plano em dia
        self.assertEqual(consolidar.campos_humanos_perdidos(self.saida, unificadas), [])
        self.assertEqual(ficticio.detectar_defeitos(unificadas)["grafias_cliente"], [])

    def test_dv_errado_vira_aviso_e_a_ficha_fica(self):
        invalidos = {n for a in com_codigo(self.avisos, "numero_invalido") for n in a["numeros"]}
        self.assertLessEqual(set(self.defeitos["dv_errado"]), invalidos)
        numeros = {f["numero"] for f in self.saida}
        self.assertLessEqual(set(self.defeitos["dv_errado"]), numeros)

    def test_outros_defeitos_ficam_para_o_verificador(self):
        antes, depois = ficticio.detectar_defeitos(self.sujas), ficticio.detectar_defeitos(self.saida)
        for tipo in ("acordo_sem_valor", "encerrado_sem_resultado", "ativo_em_conflito", "dv_errado"):
            self.assertEqual(depois[tipo], antes[tipo], tipo)
        self.assertEqual(depois["numero_duplicado"], [])
        self.assertEqual(depois["materia_dois_rotulos"], [])

    def test_tamanho_final(self):
        esperado = (len(self.sujas) - len(set(self.defeitos["numero_duplicado"]))
                    - len(self.defeitos["materia_dois_rotulos"]))
        self.assertEqual(len(self.saida), esperado)

    def test_nenhum_campo_humano_perdido(self):
        self.assertEqual(consolidar.campos_humanos_perdidos(self.sujas, self.saida), [])
        self.assertTrue(any(c["origem"] == "humano" for f in self.sujas for c in f["campos"].values()))

    def test_idempotente(self):
        de_novo, avisos = consolidar.consolidar(self.saida)
        self.assertEqual(de_novo, self.saida)
        self.assertLessEqual(set(codigos(avisos)), PERSISTENTES)
        self.assertEqual([a for a in avisos if a["codigo"] == "grafias_do_mesmo_nome"],
                         com_codigo(self.avisos, "grafias_do_mesmo_nome"))

    def test_outras_sementes_e_tamanhos(self):
        for semente, n in ((2, 60), (3, 150), (4, 300)):
            sujas = ficticio.gerar_carteira(n, clientes=4, semente=semente, com_defeitos=True)
            saida, avisos = consolidar.consolidar(sujas)
            fundidos = {x for a in com_codigo(avisos, "duplicata_exata_fundida") for x in a["numeros"]}
            self.assertLessEqual(set(sujas.defeitos["numero_duplicado"]), fundidos, semente)
            pares = com_codigo(avisos, "materia_dois_rotulos")
            for a, b in sujas.defeitos["materia_dois_rotulos"]:
                self.assertTrue(any({a, b} <= set(av["numeros"]) for av in pares), (semente, a, b))
            sugeridas = [a["candidatos"][0] for a in com_codigo(avisos, "grafias_do_mesmo_nome")]
            for d in sujas.defeitos["grafias_cliente"]:
                self.assertIn(d["canonico"], sugeridas, semente)
            self.assertEqual(consolidar.consolidar(saida)[0], saida, semente)
            self.assertEqual(consolidar.campos_humanos_perdidos(sujas, saida), [], semente)

    def test_carteira_limpa_passa_sem_mudanca(self):
        limpa = ficticio.gerar_carteira(200, clientes=5, semente=1)
        saida, avisos = consolidar.consolidar(limpa)
        self.assertEqual(saida, list(limpa))
        self.assertEqual([a for a in avisos if a["nivel"] != "info"], [])


class TestNumeroEDuplicatas(unittest.TestCase):
    def test_mesmo_numero_com_formatacao_diferente(self):
        a, b = nova(1, vara=("1ª Vara", "coletado")), nova(1)
        b["numero"] = b["numero"].replace("-", "").replace(".", "")
        ficha.definir(b, "municipio", "Fortaleza", "coletado")
        saida, avisos = consolidar.consolidar([a, b])
        self.assertEqual(len(saida), 1)
        self.assertEqual(saida[0]["numero"], numero_ficticio(1))
        self.assertEqual(ficha.obter(saida[0], "vara"), "1ª Vara")
        self.assertEqual(ficha.obter(saida[0], "municipio"), "Fortaleza")           # completa o que faltava
        self.assertIn("duplicata_exata_fundida", codigos(avisos))
        self.assertIn("numero_normalizado", codigos(avisos))
        self.assertEqual(saida[0]["consolidacao"]["numeros_originais"], [numero_ficticio(1).replace("-", "").replace(".", "")])

    def test_humano_vence_coletado_em_qualquer_ordem(self):
        for ordem in (0, 1):
            humano = nova(2, valor_estimado=("1000.00", "humano"), apelido=("Caso A", "humano"))
            coletado = nova(2, valor_estimado=("2000.00", "coletado"), vara=("2ª Vara", "coletado"))
            linhas = [humano, coletado] if ordem == 0 else [coletado, humano]
            saida, avisos = consolidar.consolidar(linhas)
            self.assertEqual(len(saida), 1)
            self.assertEqual(ficha.obter(saida[0], "valor_estimado"), "1000.00")
            self.assertEqual(ficha.origem(saida[0], "valor_estimado"), "humano")
            self.assertEqual(ficha.obter(saida[0], "apelido"), "Caso A")
            self.assertEqual(ficha.obter(saida[0], "vara"), "2ª Vara")
            conflito = saida[0]["consolidacao"]["conflitos"][0]
            self.assertEqual((conflito["campo"], conflito["valor_descartado"]), ("valor_estimado", "2000.00"))
            self.assertEqual(consolidar.campos_humanos_perdidos(linhas, saida), [])
            self.assertEqual(com_codigo(avisos, "campo_divergente")[0]["nivel"], "info")  # origens diferentes: sem drama

    def test_dois_humanos_divergentes_vale_o_mais_recente_e_o_outro_fica_guardado(self):
        velho, novo = nova(3, observacoes=("Aguardando cliente.", "humano")), nova(3, observacoes=("Prazo interno.", "humano"))
        velho["campos"]["observacoes"]["em"] = "2026-09-01T10:00:00"
        novo["campos"]["observacoes"]["em"] = "2026-10-01T10:00:00"
        for linhas in ([velho, novo], [novo, velho]):
            saida, avisos = consolidar.consolidar(linhas)
            self.assertEqual(ficha.obter(saida[0], "observacoes"), "Prazo interno.")
            self.assertEqual(saida[0]["consolidacao"]["conflitos"][0]["valor_descartado"], "Aguardando cliente.")
            self.assertEqual(com_codigo(avisos, "campo_divergente")[0]["nivel"], "atencao")
            self.assertEqual(consolidar.campos_humanos_perdidos(linhas, saida), [])

    def test_linha_de_base_divergente_fica_a_mais_recente(self):
        a, b = nova(4), nova(4)
        a["linha_de_base"] = {"data_base": "2026-08-01", "andamentos_texto": "Em 01/07/2026 foi feito X.", "arquivo": "a.docx",
                              "ultimo_andamento": "2026-07-01"}
        b["linha_de_base"] = {"data_base": "2026-09-01", "andamentos_texto": "Em 01/07/2026 foi feito X. Em 01/08/2026 Y.",
                              "arquivo": "b.docx", "ultimo_andamento": "2026-08-01"}
        saida, avisos = consolidar.consolidar([a, b])
        self.assertEqual(saida[0]["linha_de_base"]["arquivo"], "b.docx")
        self.assertEqual(saida[0]["consolidacao"]["linhas_de_base_descartadas"][0]["arquivo"], "a.docx")
        self.assertIn("linha_de_base_divergente", codigos(avisos))

    def test_numero_invalido_e_avisado_nao_corrigido(self):
        ruim = nova(5)
        ruim["numero"] = ficticio.numero_com_dv_errado(ruim["numero"])
        saida, avisos = consolidar.consolidar([ruim, {"numero": "123", "v": 2, "campos": {}, "vinculados": []}])
        self.assertEqual(len(saida), 2)
        self.assertEqual(saida[0]["numero"], ruim["numero"])
        self.assertEqual(len(com_codigo(avisos, "numero_invalido")), 2)
        self.assertTrue(all(a["nivel"] == "erro" for a in com_codigo(avisos, "numero_invalido")))

    def test_linhas_sem_numero_nao_se_fundem(self):
        saida, _ = consolidar.consolidar([{"numero": "", "v": 2, "campos": {}, "vinculados": []},
                                          {"numero": "", "v": 2, "campos": {}, "vinculados": []}])
        self.assertEqual(len(saida), 2)

    def test_aceita_itens_da_fase_1(self):
        item = {"numero": numero_ficticio(6), "tribunal": "TJCE", "cliente": "Cliente Exemplo 01 Ltda", "polo_cliente": "passivo",
                "ativo": True}
        saida, avisos = consolidar.consolidar([item])
        self.assertEqual(saida[0]["v"], 2)
        self.assertEqual(ficha.obter(saida[0], "cliente"), "Cliente Exemplo 01 Ltda")
        self.assertNotIn("v", item)                                                  # o original não foi tocado


class TestVinculados(unittest.TestCase):
    def test_agravo_e_apenso_viram_vinculos_do_principal(self):
        principal = nova(10, cliente="Cliente Exemplo 01 Ltda", materia_principal="Dano moral")
        agravo = nova(11, cliente="Cliente Exemplo 01 Ltda", classe="Agravo de Instrumento", vara=("Câmara", "coletado"))
        apenso = nova(12, cliente="Cliente Exemplo 01 Ltda", valor_causa="500,00")
        ficha.vincular(principal, agravo["numero"], "agravo")
        ficha.vincular(principal, apenso["numero"], "apenso")
        saida, avisos = consolidar.consolidar([principal, agravo, apenso])
        self.assertEqual([f["numero"] for f in saida], [principal["numero"]])
        self.assertEqual([(v["numero"], v["tipo"]) for v in saida[0]["vinculados"]],
                         [(agravo["numero"], "agravo"), (apenso["numero"], "apenso")])
        self.assertEqual(ficha.obter(saida[0], "vara"), None)                        # dados do agravo não vazam para a principal
        guardados = {a["numero"]: a for a in saida[0]["consolidacao"]["absorvidas"]}
        self.assertEqual(ficha.obter(guardados[agravo["numero"]]["ficha"], "vara"), "Câmara")
        self.assertEqual(len(com_codigo(avisos, "vinculo_absorvido")), 2)

    def test_cadeia_principal_agravo_apenso_do_agravo(self):
        a, b, c = nova(20), nova(21), nova(22)
        ficha.vincular(a, b["numero"], "agravo")
        ficha.vincular(b, c["numero"], "apenso")
        for ordem in ([a, b, c], [c, b, a], [b, a, c]):
            saida, _ = consolidar.consolidar(ordem)
            self.assertEqual(len(saida), 1, [f["numero"] for f in ordem])
            self.assertEqual(saida[0]["numero"], a["numero"])
            tipos = {v["numero"]: v["tipo"] for v in saida[0]["vinculados"]}
            self.assertEqual(tipos, {b["numero"]: "agravo", c["numero"]: "apenso"})

    def test_citacao_mutua_nao_cria_ciclo(self):
        a, b = nova(30), nova(31)
        ficha.vincular(a, b["numero"], "mesma_acao")
        ficha.vincular(b, a["numero"], "mesma_acao")
        saida, _ = consolidar.consolidar([a, b])
        self.assertEqual([f["numero"] for f in saida], [a["numero"]])
        self.assertEqual([v["numero"] for v in saida[0]["vinculados"]], [b["numero"]])

    def test_vinculado_citado_por_dois_principais_fica_no_primeiro(self):
        a, b, filho = nova(40), nova(41), nova(42)
        ficha.vincular(a, filho["numero"], "agravo")
        ficha.vincular(b, filho["numero"], "agravo")
        saida, avisos = consolidar.consolidar([a, b, filho])
        self.assertEqual({f["numero"] for f in saida}, {a["numero"], b["numero"]})
        self.assertEqual([v["numero"] for v in saida[0]["vinculados"]], [filho["numero"]])
        self.assertIn("vinculado_em_dois_principais", codigos(avisos))

    def test_vinculado_sem_ficha_propria_continua_vinculado(self):
        a = nova(50)
        ficha.vincular(a, numero_ficticio(51), "recurso")
        saida, avisos = consolidar.consolidar([a])
        self.assertEqual(saida[0]["vinculados"], [{"numero": numero_ficticio(51), "tipo": "recurso"}])
        self.assertNotIn("vinculo_absorvido", codigos(avisos))

    def test_sem_absorver_so_mantem_as_linhas(self):
        a, b = nova(60), nova(61)
        ficha.vincular(a, b["numero"], "agravo")
        saida, avisos = consolidar.consolidar([a, b], absorver_vinculadas=False)
        self.assertEqual(len(saida), 2)
        self.assertNotIn("vinculo_absorvido", codigos(avisos))

    def test_materia_dois_rotulos_e_materia_divergente(self):
        a = nova(70, materia_principal=("Reversão de justa causa", "humano"))
        b = nova(71, materia_principal=("Reversão Justa Causa.", "humano"))
        ficha.vincular(a, b["numero"], "mesma_acao")
        saida, avisos = consolidar.consolidar([a, b])
        aviso = com_codigo(avisos, "materia_dois_rotulos")[0]
        self.assertEqual(aviso["candidatos"], ["Reversão de justa causa", "Reversão Justa Causa.", "Reversão de justa causa"])
        c, d = nova(72, materia_principal="Dano moral"), nova(73, materia_principal="Horas extras")
        ficha.vincular(c, d["numero"], "reajuizamento")
        _, avisos = consolidar.consolidar([c, d])
        self.assertEqual(len(com_codigo(avisos, "materia_divergente")), 1)
        self.assertEqual(com_codigo(avisos, "materia_dois_rotulos"), [])

    def test_campo_humano_da_linha_absorvida_fica_guardado(self):
        a = nova(80)
        b = nova(81, valor_estimado=("777.00", "humano"), observacoes=("Conferir com o cliente.", "humano"))
        ficha.vincular(a, b["numero"], "mesma_acao")
        saida, _ = consolidar.consolidar([a, b])
        self.assertEqual(consolidar.campos_humanos_perdidos([a, b], saida), [])
        saida[0]["consolidacao"]["absorvidas"].clear()                              # sem o retrato guardado, o verificador acusa
        self.assertEqual({c for _, c, _ in consolidar.campos_humanos_perdidos([a, b], saida)},
                         {"valor_estimado", "observacoes"})


class TestSugestoes(unittest.TestCase):
    def test_duplicata_provavel_nao_funde(self):
        base = dict(cliente="Cliente Exemplo 01 Ltda", autores="Pessoa Fictícia 0001", reus="Cliente Exemplo 01 Ltda",
                    data_ajuizamento="2026-01-10")
        a, b = nova(90, **base), nova(91, **base)
        c = nova(92, **{**base, "data_ajuizamento": "2026-02-10"})                  # data diferente: outra ação
        saida, avisos = consolidar.consolidar([a, b, c])
        self.assertEqual(len(saida), 3)
        achados = com_codigo(avisos, "duplicata_provavel")
        self.assertEqual(len(achados), 1)
        self.assertEqual(set(achados[0]["numeros"]), {a["numero"], b["numero"]})

    def test_duplicata_provavel_exige_dados_suficientes(self):
        a, b = nova(93, cliente="Cliente Exemplo 01 Ltda"), nova(94, cliente="Cliente Exemplo 01 Ltda")
        _, avisos = consolidar.consolidar([a, b])
        self.assertEqual(com_codigo(avisos, "duplicata_provavel"), [])

    def test_vinculo_provavel_por_classe_e_partes(self):
        partes = dict(cliente="Cliente Exemplo 01 Ltda", autores="Pessoa Fictícia 0002", reus="Cliente Exemplo 01 Ltda")
        principal = nova(100, classe="Procedimento Comum Cível", **partes)
        agravo = nova(101, classe="Agravo de Instrumento", **partes)
        outro = nova(102, classe="Procedimento Comum Cível", cliente="Cliente Exemplo 02 S.A.", autores="Pessoa Fictícia 0003",
                     reus="Cliente Exemplo 02 S.A.")
        saida, avisos = consolidar.consolidar([principal, agravo, outro])
        self.assertEqual(len(saida), 3)
        achado = com_codigo(avisos, "vinculo_provavel")[0]
        self.assertEqual(achado["numeros"], [agravo["numero"], principal["numero"]])
        self.assertIn("agravo", achado["candidatos"])
        self.assertEqual(com_codigo(avisos, "duplicata_provavel"), [])
        ficha.vincular(principal, agravo["numero"], "agravo")                         # declarado: não é mais "provável"
        _, avisos = consolidar.consolidar([principal, agravo, outro])
        self.assertEqual(com_codigo(avisos, "vinculo_provavel"), [])


class TestGrafias(unittest.TestCase):
    def fichas(self, nomes):
        return [nova(200 + i, cliente=n) for i, n in enumerate(nomes)]

    def test_variantes_de_acento_caixa_e_sufixo(self):
        fichas = self.fichas(["Chácara Exemplo Ltda", "Chácara Exemplo Ltda", "Chacara Exemplo", "CHACARA EXEMPLO LTDA.",
                              "Outro Cliente S.A."])
        grupos = consolidar.sugerir_grafias(fichas)
        self.assertEqual(len(grupos), 1)
        g = grupos[0]
        self.assertEqual(g["canonico_sugerido"], "Chácara Exemplo Ltda")
        self.assertEqual(g["variantes"][0], "Chácara Exemplo Ltda")
        self.assertEqual(set(g["variantes"]), {"Chácara Exemplo Ltda", "Chacara Exemplo", "CHACARA EXEMPLO LTDA."})
        self.assertEqual(g["ocorrencias"]["Chácara Exemplo Ltda"], 2)
        self.assertEqual(g["campos"], ["cliente"])

    def test_empate_prefere_acento_e_caixa_mista(self):
        grupos = consolidar.sugerir_grafias(self.fichas(["Chacara Exemplo", "Chácara Exemplo", "CHACARA EXEMPLO"]))
        self.assertEqual(grupos[0]["canonico_sugerido"], "Chácara Exemplo")

    def test_nomes_diferentes_nao_agrupam(self):
        self.assertEqual(consolidar.sugerir_grafias(self.fichas(["Empresa Alfa Ltda", "Empresa Beta Ltda", "Empresa Alfa Ltda"])), [])
        self.assertEqual(consolidar.sugerir_grafias(self.fichas(["Pessoa Fictícia 0001", "Pessoa Fictícia 0002"])), [])

    def test_consolidar_so_sugere_e_aplicar_unifica_so_o_confirmado(self):
        fichas = self.fichas(["Chácara Exemplo Ltda", "Chacara Exemplo", "Outro Nome Ltda", "OUTRO NOME"])
        saida, avisos = consolidar.consolidar(fichas)
        self.assertEqual([ficha.obter(f, "cliente") for f in saida], [ficha.obter(f, "cliente") for f in fichas])
        self.assertEqual(len(com_codigo(avisos, "grafias_do_mesmo_nome")), 2)
        confirmadas = {"Chacara Exemplo": "Chácara Exemplo Ltda"}                       # só o primeiro grupo foi confirmado
        novas, avisos = consolidar.aplicar_grafias(saida, confirmadas)
        self.assertEqual([ficha.obter(f, "cliente") for f in novas],
                         ["Chácara Exemplo Ltda", "Chácara Exemplo Ltda", "Outro Nome Ltda", "OUTRO NOME"])
        self.assertEqual(novas[1]["cliente"], "Chácara Exemplo Ltda")                  # espelho plano
        self.assertEqual(novas[1]["consolidacao"]["originais"]["cliente"], "Chacara Exemplo")
        self.assertEqual(ficha.origem(novas[1], "cliente"), "coletado")              # origem preservada
        self.assertEqual(avisos[0]["codigo"], "grafia_unificada")
        self.assertEqual(ficha.obter(saida[1], "cliente"), "Chacara Exemplo")           # a lista recebida não muda
        self.assertEqual(consolidar.campos_humanos_perdidos(saida, novas), [])

    def test_partes_com_varios_nomes(self):
        f1 = nova(300, autores="Maria Exemplo; José Exemplo")
        f2 = nova(301, autores="JOSE EXEMPLO")
        grupos = consolidar.sugerir_grafias([f1, f2], campos=("autores",))
        self.assertEqual(len(grupos), 1)
        novas, _ = consolidar.aplicar_grafias([f1, f2], [{"canonico": "José Exemplo", "variantes": ["JOSE EXEMPLO"]}])
        self.assertEqual(ficha.obter(novas[1], "autores"), "José Exemplo")
        self.assertEqual(ficha.obter(novas[0], "autores"), "Maria Exemplo; José Exemplo")  # sem mudança, não reescreve


class TestRotulos(unittest.TestCase):
    def test_normaliza_e_guarda_o_original(self):
        f = nova(400, materia_principal=("Horas extras", "humano"), resultado="Parcial procedência.", area="Justiça do Trabalho",
                 momento_atual="aguardando sentença")
        saida, avisos = consolidar.consolidar([f])
        s = saida[0]
        self.assertEqual(ficha.obter(s, "materia_principal"), "Horas extras e reflexos")
        self.assertEqual(ficha.origem(s, "materia_principal"), "humano")                # a origem não muda
        self.assertEqual(s["consolidacao"]["originais"]["materia_principal"], "Horas extras")
        self.assertEqual(consolidar.campos_humanos_perdidos([f], saida), [])
        self.assertEqual(len(com_codigo(avisos, "rotulo_normalizado")), 1)

    def test_fora_do_vocabulario_avisa_com_sugestao_e_nao_altera(self):
        f = nova(401, materia_principal="Reversao de justa cauza")
        saida, avisos = consolidar.consolidar([f])
        self.assertEqual(ficha.obter(saida[0], "materia_principal"), "Reversao de justa cauza")
        aviso = com_codigo(avisos, "rotulo_fora_do_vocabulario")[0]
        self.assertIn("Reversão de justa causa", aviso["candidatos"])

    def test_momento_com_qualificador_e_preservado(self):
        f = nova(402)
        f["campos"]["momento_atual"] = {"valor": "cumprimento de sentença (honorários suspensos)", "origem": "migrado",
                                        "em": "2026-10-07T10:00:00"}
        saida, avisos = consolidar.consolidar([f])
        self.assertEqual(ficha.obter(saida[0], "momento_atual"), "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)")
        self.assertEqual(com_codigo(avisos, "rotulo_fora_do_vocabulario"), [])
        de_novo, _ = consolidar.consolidar(saida)
        self.assertEqual(de_novo, saida)

    def test_polo_normalizado_atualiza_o_espelho_plano(self):
        f = nova(403)
        f["campos"]["polo_cliente"] = {"valor": "Reclamada", "origem": "migrado", "em": "2026-10-07T10:00:00"}
        f["polo_cliente"] = "Reclamada"
        saida, _ = consolidar.consolidar([f])
        self.assertEqual(saida[0]["polo_cliente"], "passivo")


class TestMigrarProjeto(unittest.TestCase):
    def tearDown(self):
        ficticio.restaurar_comum()

    def _itens_da_fase_1(self):
        return [{"numero": numero_ficticio(500 + i), "tribunal": "TJCE", "cliente": "Cliente Exemplo 01 Ltda",
                 "polo_cliente": "passivo" if i % 2 else "", "parte_contraria": f"Pessoa Fictícia {i:04d}",
                 "responsavel": "Responsável Exemplo A", "contato": "", "ativo": True, "origem": "lista",
                 "incluido_em": "2026-10-01"} for i in range(5)]

    def test_migra_em_lote_e_e_idempotente(self):
        proj = ficticio.criar_projeto_de_teste([], nome="Projeto Antigo")
        itens = self._itens_da_fase_1()
        itens.append({**itens[0], "numero": ficticio.numero_com_dv_errado(numero_ficticio(600))})
        itens.append({**itens[1], "numero": numero_ficticio(601), "v": 2, "campos": {}, "vinculados": []})   # já é v2
        comum.save_json(proj["carteira"], itens)
        original = (proj["pasta"] / "carteira.json").read_bytes()
        ativo_antes = comum.PROJETO

        r = consolidar.migrar_projeto(proj["slug"])
        self.assertTrue(r["ok"])
        self.assertEqual((r["total"], r["migradas"], r["ja_v2"]), (7, 6, 1))
        self.assertEqual(comum.PROJETO, ativo_antes)                                # não troca o relatório ativo
        self.assertEqual([a["codigo"] for a in r["avisos"]], ["numero_invalido"])
        self.assertEqual((proj["pasta"] / "carteira.fase1.json").read_bytes(), original)   # backup do arquivo antigo
        gravado = comum.load_json(proj["carteira"], [])
        self.assertTrue(all(f["v"] == 2 for f in gravado))
        self.assertEqual(ficha.obter(gravado[0], "cliente"), "Cliente Exemplo 01 Ltda")
        self.assertEqual(gravado[0]["cliente"], "Cliente Exemplo 01 Ltda")           # campo plano continua
        self.assertEqual(ficha.origem(gravado[0], "cliente"), "migrado")
        self.assertEqual(gravado[0]["origem"], "lista")
        self.assertEqual(gravado[0]["incluido_em"], "2026-10-01")

        depois = (proj["pasta"] / "carteira.json").read_bytes()
        r2 = consolidar.migrar_projeto(proj["slug"])
        self.assertEqual((r2["total"], r2["migradas"], r2["ja_v2"], r2["backup"]), (7, 0, 7, None))
        self.assertEqual((proj["pasta"] / "carteira.json").read_bytes(), depois)     # nada regravado
        self.assertEqual((proj["pasta"] / "carteira.fase1.json").read_bytes(), original)

    def test_abre_pelo_carregador_da_ficha_sem_perda(self):
        proj = ficticio.criar_projeto_de_teste([], nome="Projeto Antigo 2")
        itens = self._itens_da_fase_1()
        comum.save_json(proj["carteira"], itens)
        consolidar.migrar_projeto(proj["slug"])
        fichas = ficha.carregar()
        self.assertEqual([f["numero"] for f in fichas], [i["numero"] for i in itens])
        self.assertTrue(all(ficha.validar(f) == [] for f in fichas))

    def test_projeto_inexistente_e_carteira_ilegivel_viram_aviso(self):
        r = consolidar.migrar_projeto("nao-existe")
        self.assertFalse(r["ok"])
        self.assertEqual(r["avisos"][0]["codigo"], "projeto_nao_encontrado")
        proj = ficticio.criar_projeto_de_teste([], nome="Projeto Quebrado")
        proj["carteira"].write_text("[ isto não é json", encoding="utf-8")
        r = consolidar.migrar_projeto(proj["slug"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["avisos"][0]["codigo"], "carteira_ilegivel")
        self.assertEqual(proj["carteira"].read_text(encoding="utf-8"), "[ isto não é json")
        self.assertFalse((proj["pasta"] / "carteira.fase1.json").exists())

    def test_migrar_itens_mantem_item_ilegivel(self):
        novos, avisos, contagem = consolidar.migrar_itens(["texto solto", self._itens_da_fase_1()[0]])
        self.assertEqual(novos[0], "texto solto")
        self.assertEqual(avisos[0]["codigo"], "item_ilegivel")
        self.assertEqual(contagem, {"migradas": 1, "ja_v2": 0})


if __name__ == "__main__":
    unittest.main()
