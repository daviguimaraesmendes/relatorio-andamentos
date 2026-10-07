"""Verificador de qualidade da base e "o que mudou neste ciclo" (src/qualidade.py, WS-11).

    python3 -m unittest tests/test_qualidade.py -v

Tudo com dados fictícios (tests/ficticio.py); nenhum teste usa rede ou projeto real.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolamento  # noqa: E402,F401  (antes de tudo)
import ficha  # noqa: E402
import ficticio  # noqa: E402
import qualidade  # noqa: E402
import taxonomia  # noqa: E402

HOJE = ficticio.HOJE
NUM = ficticio.numero_ficticio


def mk(n, ativo=True, **campos):
    """Ficha mínima e coerente (passa em tudo); `campos` sobrescreve. Origem humano; `ativo` à parte."""
    padrao = {"cliente": "Cliente Exemplo 01 Ltda", "polo_cliente": "passivo", "autores": f"Pessoa Fictícia {n:04d}",
              "reus": "Cliente Exemplo 01 Ltda", "parte_contraria": f"Pessoa Fictícia {n:04d}", "vara": "1ª Vara do Trabalho de Fortaleza",
              "municipio": "Fortaleza", "data_ajuizamento": "2025-01-10", "assunto": "Verbas rescisórias", "area": "Trabalhista",
              "materia_principal": "Horas extras e reflexos", "valor_causa": "10000.00", "momento_atual": "AGUARDANDO SENTENÇA",
              "situacao": "Ativo", "ultimo_andamento": "2026-08-01"}
    f = ficha.nova_ficha(NUM(n))
    for campo, valor in {**padrao, **campos}.items():
        if valor is not None:
            assert ficha.definir(f, campo, valor, "humano", forcar=True), (campo, valor)
    f["ativo"] = ativo
    return f


def bruta(f, campo, valor):
    """Grava o campo como veio de um arquivo, sem passar pelo vocabulário (para testar o que `definir` não deixa gravar)."""
    f["campos"][campo] = {"valor": valor, "origem": "migrado", "em": HOJE}
    return f


def encerrada(n, momento="TRÂNSITO EM JULGADO", **campos):
    return mk(n, ativo=False, momento_atual=momento, situacao="Encerrado", **campos)


def achados_de(fichas, codigo, **kw):
    return [a for a in qualidade.verificar(fichas, hoje=HOJE, **kw) if a["codigo"] == codigo]


def codigos(fichas, **kw):
    return {a["codigo"] for a in qualidade.verificar(fichas, hoje=HOJE, **kw)}


class TestBase(unittest.TestCase):
    def test_ficha_correta_nao_gera_achado(self):
        self.assertEqual(qualidade.verificar([mk(1), encerrada(2, resultado="Improcedente")], hoje=HOJE), [])

    def test_estrutura_do_achado_e_codigos_conhecidos(self):
        achados = qualidade.verificar(ficticio.gerar_carteira(60, com_defeitos=True), hoje=HOJE)
        self.assertTrue(achados)
        for a in achados:
            self.assertEqual(set(a), {"codigo", "gravidade", "numeros", "mensagem", "sugestao"})
            self.assertIn(a["codigo"], qualidade.CODIGOS)
            self.assertIn(a["gravidade"], qualidade.GRAVIDADES)
            self.assertTrue(a["numeros"] and a["mensagem"] and isinstance(a["numeros"], list))

    def test_saida_estavel_e_ordenada_e_nao_altera_as_fichas(self):
        sujas = ficticio.gerar_carteira(80, com_defeitos=True)
        antes = copy.deepcopy(list(sujas))
        a1 = qualidade.verificar(sujas, hoje=HOJE)
        self.assertEqual(antes, list(sujas), "o verificador não pode alterar as fichas")
        self.assertEqual(a1, qualidade.verificar(list(reversed(sujas)), hoje=HOJE), "ordem de entrada não muda o resultado")
        ordem = [qualidade.GRAVIDADES.index(a["gravidade"]) for a in a1]
        self.assertEqual(ordem, sorted(ordem), "do mais grave ao menos grave")

    def test_aceita_item_da_fase_1(self):
        antigo = {"numero": NUM(3), "cliente": "Cliente Exemplo 01 Ltda", "polo_cliente": "passivo", "ativo": True}
        self.assertEqual(achados_de([antigo], "numero_invalido"), [])

    def test_lista_vazia(self):
        self.assertEqual(qualidade.verificar([], hoje=HOJE), [])
        self.assertEqual(qualidade.verificar(None, hoje=HOJE), [])
        self.assertIn("nenhum problema", qualidade.como_texto([]))


class TestFixturesDefeitos(unittest.TestCase):
    """Cada tipo de defeito injetado em tests/ficticio.py tem de ser encontrado, e só ele."""

    @classmethod
    def setUpClass(cls):
        cls.limpa = ficticio.gerar_carteira(200)
        cls.suja = ficticio.gerar_carteira(200, com_defeitos=True)
        cls.defeitos = cls.suja.defeitos
        cls.achados = qualidade.verificar(cls.suja, hoje=HOJE)

    def numeros(self, codigo):
        return {n for a in self.achados if a["codigo"] == codigo for n in a["numeros"]}

    def test_numero_duplicado(self):
        self.assertTrue(self.defeitos["numero_duplicado"])
        self.assertEqual(self.numeros("numero_duplicado"), set(self.defeitos["numero_duplicado"]))

    def test_digito_verificador_errado(self):
        self.assertTrue(self.defeitos["dv_errado"])
        self.assertEqual(self.numeros("numero_invalido"), set(self.defeitos["dv_errado"]))
        for a in self.achados:
            if a["codigo"] == "numero_invalido":
                self.assertEqual(a["gravidade"], "erro")

    def test_mesma_acao_contada_duas_vezes_e_rotulos_da_materia(self):
        pares = {frozenset(p) for p in self.defeitos["materia_dois_rotulos"]}
        self.assertTrue(pares)
        achados = {frozenset(a["numeros"]) for a in self.achados if a["codigo"] == "mesma_acao_contada_duas_vezes"}
        self.assertEqual(achados, pares)
        parecidos = self.numeros("rotulo_parecido")
        for _, b in self.defeitos["materia_dois_rotulos"]:
            self.assertIn(b, parecidos, "a grafia fora do vocabulário (a do segundo processo) é apontada")

    def test_acordo_sem_valor(self):
        self.assertEqual(self.numeros("acordo_sem_valor"), set(self.defeitos["acordo_sem_valor"]))

    def test_encerrado_sem_resultado(self):
        self.assertEqual(self.numeros("encerrado_sem_resultado"), set(self.defeitos["encerrado_sem_resultado"]))

    def test_ativo_em_conflito(self):
        self.assertEqual(self.numeros("ativo_x_momento"), set(self.defeitos["ativo_em_conflito"]))

    def test_grafias_do_cliente(self):
        grupos = self.defeitos["grafias_cliente"]
        self.assertTrue(grupos)
        textos = [a["mensagem"] for a in self.achados if a["codigo"] == "grafias_diferentes_da_parte"]
        for g in grupos:
            for nome in (g["canonico"], *g["variantes"]):
                self.assertTrue(any(repr(nome) in t for t in textos), f"grafia não apontada: {nome}")

    def test_cobre_o_gabarito_minimo_do_ficticio(self):
        detectado = ficticio.detectar_defeitos(self.suja)
        self.assertEqual(self.numeros("numero_duplicado"), set(detectado["numero_duplicado"]))
        self.assertEqual(self.numeros("acordo_sem_valor"), set(detectado["acordo_sem_valor"]))
        self.assertEqual(self.numeros("encerrado_sem_resultado"), set(detectado["encerrado_sem_resultado"]))
        self.assertEqual(self.numeros("ativo_x_momento"), set(detectado["ativo_em_conflito"]))
        self.assertEqual(self.numeros("numero_invalido"), set(detectado["dv_errado"]))
        self.assertEqual(len([a for a in self.achados if a["codigo"] == "grafias_diferentes_da_parte"]), len(detectado["grafias_cliente"]))

    def test_carteira_limpa_nao_tem_nenhum_dos_defeitos_conhecidos(self):
        achados = qualidade.verificar(self.limpa, hoje=HOJE)
        conhecidos = {"numero_duplicado", "numero_invalido", "mesma_acao_contada_duas_vezes", "acordo_sem_valor",
                      "encerrado_sem_resultado", "ativo_x_momento", "grafias_diferentes_da_parte", "rotulo_parecido",
                      "rotulo_fora_do_vocabulario", "rotulos_parecidos_na_base", "possivel_acao_repetida", "linha_marcador",
                      "resultado_x_situacao", "fase_x_momento", "data_incoerente", "campo_obrigatorio_ausente",
                      "valor_causa_vazio_ou_zero", "vinculado_invalido", "vinculado_duplicado", "vinculado_com_ficha_propria",
                      "data_invalida", "valor_invalido", "ficha_invalida", "economia_inconsistente", "vinculo_tipo_invalido"}
        self.assertEqual({a["codigo"] for a in achados} & conhecidos, set())
        self.assertEqual([a for a in achados if a["gravidade"] == "erro"], [])

    def test_carteira_limpa_so_tem_as_ressalvas_esperadas_do_gerador(self):
        # O gerador lança economia e probabilidade em processos de cliente autor sem olhar o polo: é o que o
        # verificador existe para apontar (ver economia_inflada / probabilidade_x_resultado).
        achados = qualidade.verificar(self.limpa, hoje=HOJE)
        self.assertEqual({a["codigo"] for a in achados}, {"economia_inflada", "probabilidade_x_resultado", "ressalva_cliente_autor"})
        por_numero = {f["numero"]: f for f in self.limpa}
        for a in achados:
            if a["codigo"] == "economia_inflada":
                self.assertEqual(ficha.obter(por_numero[a["numeros"][0]], "polo_cliente"), "ativo")

    def test_200_fichas_em_tempo_razoavel(self):
        import time
        t = time.time()
        qualidade.verificar(self.suja, hoje=HOJE)
        self.assertLess(time.time() - t, 5)


class TestNumerosEVinculos(unittest.TestCase):
    def test_marcadores(self):
        marcador = mk(1)
        marcador["numero"] = "0000000-00.0000.0.00.0000"   # permitido no repositório (empacotar.sh)
        outro = mk(2)
        outro["numero"] = "TOTAL"
        terceiro = ficha.nova_ficha("")
        quarto = mk(4, cliente="Total")
        quarto["numero"] = "-"
        achados = achados_de([marcador, outro, terceiro, quarto, mk(5)], "linha_marcador")
        self.assertEqual({a["numeros"][0] for a in achados}, {"0000000-00.0000.0.00.0000", "TOTAL", "", "-"})
        self.assertEqual(codigos([marcador, outro, terceiro, quarto]) - {"linha_marcador"}, set(),
                         "marcador não gera os outros achados (número inválido, duplicado...)")

    def test_numero_sem_mascara_e_so_atencao(self):
        f = mk(1)
        f["numero"] = NUM(1).replace("-", "").replace(".", "")
        a, = achados_de([f], "numero_invalido")
        self.assertEqual(a["gravidade"], "atencao")
        self.assertIn(NUM(1), a["sugestao"])

    def test_vinculados(self):
        a, b, c = mk(1), mk(2), mk(3)
        ficha.vincular(a, NUM(50), "agravo")
        ficha.vincular(b, NUM(50), "apenso")
        a["vinculados"].append({"numero": NUM(51), "tipo": "recurso"})
        a["vinculados"].append({"numero": NUM(51), "tipo": "recurso"})
        a["vinculados"].append({"numero": ficticio.numero_com_dv_errado(NUM(52)), "tipo": "agravo"})
        a["vinculados"].append({"numero": NUM(53), "tipo": "tipo_que_nao_existe"})
        ficha.vincular(c, NUM(2), "agravo")   # o vinculado de c tem ficha própria (b)
        achados = qualidade.verificar([a, b, c], hoje=HOJE)
        por_codigo = {k: [x for x in achados if x["codigo"] == k] for k in qualidade.CODIGOS}
        self.assertEqual({tuple(x["numeros"]) for x in por_codigo["vinculado_invalido"]}, {(a["numero"], ficticio.numero_com_dv_errado(NUM(52)))})
        duplicados = {x["numeros"][0] for x in por_codigo["vinculado_duplicado"]}
        self.assertEqual(duplicados, {a["numero"], NUM(50)}, "repetido na mesma ficha e ligado a duas fichas")
        self.assertEqual([x["numeros"] for x in por_codigo["vinculado_com_ficha_propria"]], [[c["numero"], b["numero"]]])
        self.assertEqual([x["numeros"][1] for x in por_codigo["vinculo_tipo_invalido"]], [NUM(53)])

    def test_mesma_acao_e_reajuizamento_com_duas_fichas(self):
        a, b = mk(1), mk(2)
        ficha.vincular(a, b["numero"], "reajuizamento")
        ficha.vincular(b, a["numero"], "reajuizamento")   # os dois lados dizem a mesma coisa: um achado só
        achados = achados_de([a, b], "mesma_acao_contada_duas_vezes")
        self.assertEqual([x["numeros"] for x in achados], [sorted([a["numero"], b["numero"]], key=lambda n: n != a["numero"])])
        self.assertEqual(achados[0]["gravidade"], "erro")

    def test_acao_repetida_sem_vinculo(self):
        igual = {"autores": "Pessoa Fictícia 0100", "parte_contraria": "Pessoa Fictícia 0100"}
        a, b, c = mk(1, **igual), mk(2, **igual), mk(3, valor_causa="10001.00", **igual)
        achados = achados_de([a, b, c], "possivel_acao_repetida")
        self.assertEqual([x["numeros"] for x in achados], [sorted([a["numero"], b["numero"]])])
        ficha.vincular(a, b["numero"], "apenso")
        self.assertEqual(achados_de([a, b, c], "possivel_acao_repetida"), [], "vínculo declarado já explica")

    def test_falso_positivo_documentado_da_acao_repetida(self):
        # duas ações realmente distintas, mesmas partes, mesmo valor e matéria: o verificador pergunta (atencao)
        igual = {"autores": "Pessoa Fictícia 0100", "parte_contraria": "Pessoa Fictícia 0100"}
        a, b = mk(1, data_ajuizamento="2024-01-10", **igual), mk(2, data_ajuizamento="2025-07-01", **igual)
        self.assertEqual(len(achados_de([a, b], "possivel_acao_repetida")), 1)
        self.assertIn("possivel_acao_repetida", qualidade.__doc__)


class TestRotulos(unittest.TestCase):
    def test_rotulo_que_o_vocabulario_reconhece_e_so_escrito_diferente(self):
        f = bruta(encerrada(1, resultado="Improcedente"), "resultado", "improcedencia")
        a, = achados_de([f], "rotulo_parecido")
        self.assertIn("Improcedente", a["sugestao"])

    def test_rotulo_fora_do_vocabulario(self):
        f = bruta(mk(1), "area", "Direito Marciano")
        a, = achados_de([f], "rotulo_fora_do_vocabulario")
        self.assertEqual((a["gravidade"], a["numeros"]), ("atencao", [f["numero"]]))

    def test_materia_livre_fora_do_vocabulario_e_so_info(self):
        f = mk(1, area="Tributário", materia_principal="ICMS sobre energia elétrica")
        a, = achados_de([f], "rotulo_fora_do_vocabulario")
        self.assertEqual(a["gravidade"], "info")

    def test_momento_atual_com_qualificador_vale_e_minuscula_e_parecido(self):
        ok = bruta(mk(1), "momento_atual", "CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)")
        self.assertEqual(achados_de([ok], "rotulo_fora_do_vocabulario") + achados_de([ok], "rotulo_parecido"), [])
        minuscula = bruta(mk(2), "momento_atual", "aguardando sentença")
        self.assertEqual(len(achados_de([minuscula], "rotulo_parecido")), 1)
        inventado = bruta(mk(3), "momento_atual", "ESPERANDO O FIM DO MUNDO")
        self.assertEqual(len(achados_de([inventado], "rotulo_fora_do_vocabulario")), 1)

    def test_agrupa_por_valor_do_rotulo(self):
        fichas = [bruta(mk(n), "materia_principal", "horas extras") for n in (1, 2, 3)]
        a, = achados_de(fichas, "rotulo_parecido")
        self.assertEqual(sorted(a["numeros"]), sorted(f["numero"] for f in fichas))

    def test_rotulos_soltos_da_mesma_coisa_na_base(self):
        # os exemplos do PLANO.md: "Reversão Justa Causa" x "Reversão da justa causa."
        a, b = mk(1, materia_principal="Reversão Justa Causa"), mk(2, materia_principal="Reversão da justa causa.")
        c = mk(3, materia_principal="Estabilidade pré-aposentadoria")
        achado, = achados_de([a, b, c], "rotulos_parecidos_na_base")
        self.assertEqual(sorted(achado["numeros"]), sorted([a["numero"], b["numero"]]))
        self.assertIn("Reversão Justa Causa", achado["mensagem"])

    def test_vara_com_numero_diferente_nao_e_parecida(self):
        a, b = mk(1, vara="1ª Vara do Trabalho de Fortaleza"), mk(2, vara="2ª Vara do Trabalho de Fortaleza")
        self.assertEqual(achados_de([a, b], "rotulos_parecidos_na_base"), [])
        c = mk(3, vara="1a Vara do Trabalho de Fortaleza.")
        self.assertEqual(len(achados_de([a, c], "rotulos_parecidos_na_base")), 1)

    def test_grafias_da_parte(self):
        a, b = mk(1, autores="Sitio Exemplo Ltda"), mk(2, autores="Sítio Exemplo LTDA.")
        achado, = achados_de([a, b], "grafias_diferentes_da_parte")
        self.assertEqual(sorted(achado["numeros"]), sorted([a["numero"], b["numero"]]))
        # sufixo societário, caixa e pontuação não distinguem; a mesma grafia repetida não é achado
        c = mk(3, autores="SITIO EXEMPLO S.A.")
        self.assertEqual(len(achados_de([a, b, c], "grafias_diferentes_da_parte")), 1)
        self.assertEqual(achados_de([a, mk(9, autores="Sitio Exemplo Ltda")], "grafias_diferentes_da_parte"), [])

    def test_falso_negativo_documentado_da_grafia(self):
        # erro de letra NÃO é pego de propósito: Silva e Silvia podem ser pessoas diferentes
        a, b = mk(1, autores="Maria Silva"), mk(2, autores="Maria Silvia")
        self.assertEqual(achados_de([a, b], "grafias_diferentes_da_parte"), [])


class TestRessalvasDeEconomia(unittest.TestCase):
    def test_convencao_dos_marcadores(self):
        for texto in ("[acordo pago por terceiro]", "[Acordo-Terceiro]", "Acordo foi pago por terceiro (seguradora)",
                      "acordo pago por um terceiro", "[ACORDO PAGO POR TERCEIRO] conforme e-mail"):
            f = encerrada(1, resultado="Acordo", valor_acordo="5000.00", observacoes=texto)
            self.assertIn("acordo_terceiro", qualidade.ressalvas_de_economia(f), texto)
        for texto in ("[exclusão da lide]", "[exclusao-da-lide]", "Cliente excluído da lide em 05/2026"):
            f = encerrada(2, resultado="Extinto sem resolução de mérito", observacoes=texto)
            self.assertIn("exclusao_lide", qualidade.ressalvas_de_economia(f), texto)
        via_outras_partes = encerrada(3, resultado="Acordo", valor_acordo="1.00", outras_partes="[acordo pago por terceiro]")
        self.assertIn("acordo_terceiro", qualidade.ressalvas_de_economia(via_outras_partes))
        self.assertEqual(qualidade.ressalvas_de_economia(encerrada(4, resultado="Acordo", valor_acordo="1.00", observacoes="Aguardando documentos.")), [])

    def test_cliente_autor_e_acordo_sem_valor(self):
        autor = encerrada(1, resultado="Procedente", polo_cliente="ativo")
        self.assertEqual(qualidade.ressalvas_de_economia(autor), ["cliente_autor"])
        sem_valor = encerrada(2, resultado="Acordo")
        self.assertEqual(qualidade.ressalvas_de_economia(sem_valor), ["acordo_sem_valor"])

    def test_falso_positivo_documentado_do_marcador(self):
        f = encerrada(1, resultado="Improcedente", observacoes="Não houve exclusão da lide.")
        self.assertIn("exclusao_lide", qualidade.ressalvas_de_economia(f))

    def test_ressalvas_informativas_agrupadas_e_economia_inflada(self):
        terceiro = encerrada(1, resultado="Acordo", valor_acordo="4000.00", valor_estimado="4000.00", valor_economizado="6000.00",
                             observacoes="[acordo pago por terceiro]")
        exclusao = encerrada(2, resultado="Extinto sem resolução de mérito", observacoes="[exclusão da lide]")
        autor = encerrada(3, resultado="Procedente", polo_cliente="ativo", valor_economizado="500.00")
        normal = encerrada(4, resultado="Improcedente", valor_estimado="0.00", valor_economizado="10000.00")
        achados = qualidade.verificar([terceiro, exclusao, autor, normal], hoje=HOJE)
        por = {a["codigo"]: a for a in achados}
        self.assertEqual(por["ressalva_acordo_terceiro"]["numeros"], [terceiro["numero"]])
        self.assertEqual(por["ressalva_exclusao_lide"]["numeros"], [exclusao["numero"]])
        self.assertEqual(por["ressalva_cliente_autor"]["numeros"], [autor["numero"]])
        self.assertEqual(sorted(n for a in achados if a["codigo"] == "economia_inflada" for n in a["numeros"]),
                         sorted([terceiro["numero"], autor["numero"]]))
        self.assertEqual([a for a in achados if a["gravidade"] == "info" and a["codigo"].startswith("ressalva_")][0]["gravidade"], "info")

    def test_economia_em_processo_ativo_e_acordo_sem_valor_com_economia(self):
        ativo = mk(1, valor_economizado="100.00")
        sem_valor = encerrada(2, resultado="Acordo", valor_economizado="10000.00")
        achados = achados_de([ativo, sem_valor], "economia_inflada")
        self.assertEqual(sorted(a["numeros"][0] for a in achados), sorted([ativo["numero"], sem_valor["numero"]]))

    def test_economia_inconsistente(self):
        f = encerrada(1, resultado="Procedente", valor_arbitrado="3000.00", valor_estimado="3000.00", valor_economizado="9999.00")
        self.assertEqual(len(achados_de([f], "economia_inconsistente")), 1)
        certa = encerrada(2, resultado="Procedente", valor_arbitrado="3000.00", valor_estimado="3000.00", valor_economizado="7000.00")
        self.assertEqual(achados_de([certa], "economia_inconsistente"), [])

    def test_desfecho_pecuniario_definido(self):
        d = qualidade.desfecho_pecuniario_definido
        self.assertTrue(d(encerrada(1, resultado="Acordo", valor_acordo="10.00")))
        self.assertFalse(d(encerrada(2, resultado="Acordo")))
        self.assertTrue(d(encerrada(3, resultado="Procedente", valor_arbitrado="10.00")))
        self.assertFalse(d(encerrada(4, resultado="Procedente")))
        self.assertTrue(d(encerrada(5, resultado="Improcedente")))
        for r in ("Extinto sem resolução de mérito", "Arquivado / desistência", "Incompetência declarada"):
            self.assertFalse(d(encerrada(6, resultado=r)), r)


class TestSituacao(unittest.TestCase):
    def test_encerrado_sem_resultado(self):
        self.assertEqual(len(achados_de([encerrada(1)], "encerrado_sem_resultado")), 1)
        self.assertEqual(achados_de([encerrada(1, resultado="Improcedente")], "encerrado_sem_resultado"), [])
        # qualquer sinal de encerramento conta: aqui só o momento atual diz
        so_momento = mk(2, momento_atual="PROCESSO ARQUIVADO")
        self.assertEqual(len(achados_de([so_momento], "encerrado_sem_resultado")), 1)

    def test_ativo_x_momento_e_situacao(self):
        f = mk(1, momento_atual="TRÂNSITO EM JULGADO", situacao="Encerrado", resultado="Improcedente")
        a, = achados_de([f], "ativo_x_momento")
        self.assertIn("momento atual", a["mensagem"])
        g = encerrada(2, resultado="Improcedente")
        g["ativo"] = True
        self.assertTrue(achados_de([g], "ativo_x_momento"))
        h = mk(3, ativo=False)   # inativo mas momento e situação dizem ativo
        self.assertTrue(achados_de([h], "ativo_x_momento"))

    def test_ativo_x_momento_com_qualificador(self):
        f = bruta(mk(1, resultado="Improcedente", situacao="Encerrado"), "momento_atual", "PROCESSO ARQUIVADO (DECISÃO FAVORÁVEL)")
        self.assertEqual(len(achados_de([f], "ativo_x_momento")), 1)

    def test_resultado_x_situacao(self):
        acordo_em_ativo = mk(1, resultado="Acordo", valor_acordo="100.00")
        self.assertEqual(len(achados_de([acordo_em_ativo], "resultado_x_situacao")), 1)
        merito_antes_da_sentenca = mk(2, resultado="Procedente", momento_atual="AGUARDANDO CONTESTAÇÃO")
        self.assertEqual(len(achados_de([merito_antes_da_sentenca], "resultado_x_situacao")), 1)
        acordo_extinto = encerrada(3, momento="EXTINTO SEM RESOLUÇÃO DE MÉRITO", resultado="Acordo", valor_acordo="1.00")
        self.assertEqual(len(achados_de([acordo_extinto], "resultado_x_situacao")), 1)
        extinto_acordo = encerrada(4, momento="ACORDO HOMOLOGADO", resultado="Extinto sem resolução de mérito")
        self.assertEqual(len(achados_de([extinto_acordo], "resultado_x_situacao")), 1)
        merito_acordo = encerrada(5, momento="ACORDO HOMOLOGADO", resultado="Procedente")
        self.assertEqual(len(achados_de([merito_acordo], "resultado_x_situacao")), 1)
        # combinações corretas não geram nada
        ok = [mk(6, resultado="Procedente", momento_atual="AGUARDANDO JULGAMENTO DA APELAÇÃO", fase="Recurso"),
              encerrada(7, momento="ACORDO HOMOLOGADO", resultado="Acordo", valor_acordo="1.00"),
              mk(8, resultado="Incompetência declarada")]
        self.assertEqual(achados_de(ok, "resultado_x_situacao"), [])

    def test_fase_x_momento(self):
        self.assertEqual(len(achados_de([mk(1, fase="Recurso")], "fase_x_momento")), 1)
        self.assertEqual(achados_de([mk(2, fase="Conhecimento")], "fase_x_momento"), [])
        self.assertEqual(achados_de([encerrada(3, resultado="Improcedente", fase="Recurso")], "fase_x_momento"), [],
                         "momento encerrado não tem fase")

    def test_probabilidade_x_resultado_sem_inversao_por_polo(self):
        procedente_remota = encerrada(1, resultado="Procedente", probabilidade="Remota")
        improcedente_provavel = encerrada(2, resultado="Improcedente", probabilidade="Provável")
        acordo_com_prob = encerrada(3, momento="ACORDO HOMOLOGADO", resultado="Acordo", valor_acordo="1.00", probabilidade="Possível")
        correto = [encerrada(4, resultado="Procedente", probabilidade="Provável"),
                   encerrada(5, resultado="Parcialmente procedente", probabilidade="Provável"),
                   encerrada(6, resultado="Improcedente", probabilidade="Remota"),
                   mk(7, probabilidade="Possível")]
        self.assertEqual(len(achados_de([procedente_remota, improcedente_provavel, acordo_com_prob], "probabilidade_x_resultado")), 3)
        self.assertEqual(achados_de(correto, "probabilidade_x_resultado"), [])
        # cliente autor: a regra é a mesma (Procedente = Provável), o polo não inverte
        autor = encerrada(8, resultado="Improcedente", probabilidade="Provável", polo_cliente="ativo")
        self.assertEqual(len(achados_de([autor], "probabilidade_x_resultado")), 1)
        self.assertTrue(all(a["gravidade"] == "info" for a in achados_de([procedente_remota], "probabilidade_x_resultado")))


class TestCamposEDatas(unittest.TestCase):
    def test_obrigatorios_por_perfil(self):
        f = mk(1, assunto=None, vara=None, materia_principal=None)
        self.assertEqual(achados_de([f], "campo_obrigatorio_ausente"), [], "sem perfil só vale a base")
        perfil = {"entregas": ["docx_a"]}
        a, = achados_de([f], "campo_obrigatorio_ausente", perfil=perfil)
        for rotulo in ("Assunto", "Vara / Juízo", "Matéria principal"):
            self.assertIn(rotulo, a["mensagem"])
        # coluna inativa não é exigida
        perfil["colunas_ativas"] = ["numero", "assunto", "autores", "reus", "data_ajuizamento", "area"]
        a, = achados_de([f], "campo_obrigatorio_ausente", perfil=perfil)
        self.assertIn("Assunto", a["mensagem"])
        self.assertNotIn("Vara", a["mensagem"])
        # campo exigido à parte e base sempre exigida
        extra = {"obrigatorios": ["responsavel"]}
        self.assertIn("Responsável", achados_de([mk(2)], "campo_obrigatorio_ausente", perfil=extra)[0]["mensagem"])
        semcli = mk(3, cliente=None)
        self.assertIn("Cliente", achados_de([semcli], "campo_obrigatorio_ausente")[0]["mensagem"])

    def test_valor_da_causa(self):
        sem, zero, negativo = mk(1, valor_causa=None), mk(2), mk(3)
        zero["campos"]["valor_causa"]["valor"] = "0.00"
        negativo["campos"]["valor_causa"]["valor"] = "-5.00"
        achados = achados_de([sem, zero, negativo], "valor_causa_vazio_ou_zero")
        self.assertEqual(sorted(a["numeros"][0] for a in achados), sorted(f["numero"] for f in (sem, zero, negativo)))
        self.assertEqual(achados_de([sem], "campo_obrigatorio_ausente", perfil={"entregas": ["xlsx_b"]}), [],
                         "valor da causa tem achado próprio, não repete como obrigatório")

    def test_datas_incoerentes(self):
        depois_do_andamento = mk(1, data_ajuizamento="2026-09-01", ultimo_andamento="2026-08-01")
        citacao_antes = mk(2, data_citacao="2024-12-01")
        transito_antes = mk(3, data_transito="2024-01-01")
        no_futuro = mk(4, ultimo_andamento="2027-01-01")
        citacao_depois = mk(5, data_citacao="2026-09-30")
        base_depois = mk(6)
        base_depois["linha_de_base"] = {"data_base": "2026-06-30", "andamentos_texto": "", "arquivo": "x.docx", "ultimo_andamento": "2026-07-15"}
        for f, trecho in ((depois_do_andamento, "ajuizamento depois"), (citacao_antes, "citação antes"), (transito_antes, "trânsito"),
                          (no_futuro, "no futuro"), (citacao_depois, "citação depois"), (base_depois, "data-base")):
            a, = achados_de([f], "data_incoerente")
            self.assertIn(trecho, a["mensagem"])
        self.assertEqual(achados_de([mk(7, data_citacao="2025-02-01")], "data_incoerente"), [])

    def test_hoje_padrao_e_o_de_verdade(self):
        f = mk(1, ultimo_andamento="2999-01-01")
        self.assertTrue([a for a in qualidade.verificar([f]) if a["codigo"] == "data_incoerente"])

    def test_valores_e_datas_invalidos_e_ficha_adulterada(self):
        f = mk(1)
        f["campos"]["valor_causa"]["valor"] = "abc"
        f["campos"]["data_citacao"] = {"valor": "31/02/2025", "origem": "migrado", "em": HOJE}
        g = mk(2)
        g["campos"]["campo_que_nao_existe"] = {"valor": "x", "origem": "humano", "em": HOJE}
        g["campos"]["vara"]["origem"] = "inventada"
        self.assertEqual(len(achados_de([f], "valor_invalido")), 1)
        self.assertEqual(len(achados_de([f], "data_invalida")), 1)
        self.assertEqual(len(achados_de([g], "ficha_invalida")), 2)
        self.assertTrue(all(a["gravidade"] == "erro" for a in qualidade.verificar([f, g], hoje=HOJE)
                            if a["codigo"] in ("valor_invalido", "data_invalida", "ficha_invalida")))


class TestRelatorio(unittest.TestCase):
    def test_resumir_e_como_texto(self):
        achados = qualidade.verificar(ficticio.gerar_carteira(200, com_defeitos=True), hoje=HOJE)
        r = qualidade.resumir(achados)
        self.assertEqual(r["total"], len(achados))
        self.assertEqual(sum(r["por_gravidade"].values()), len(achados))
        self.assertEqual(r["por_codigo"]["numero_duplicado"]["gravidade"], "erro")
        self.assertEqual(r["por_codigo"]["acordo_sem_valor"]["processos"], 3)
        texto = qualidade.como_texto(achados)
        self.assertIn("ERROS (corrigir antes de entregar)", texto)
        self.assertLess(texto.index("ERROS"), texto.index("PARA CONFERIR"))
        self.assertIn("Sugestão:", texto)


# ================================================================== o que mudou

def evento(numero, data, frase, conteudo="", status="aprovado", tipo="Sentença", **extra):
    return {"id": f"{numero}:{data}", "tipo_evento": "documento", "numero": numero, "titulo": f"{tipo} - {data}", "status": status,
            "tipo": tipo, "data": data, "frase": frase, "conteudo": conteudo, "audiencia": None, "prazo": None, **extra}


class TestOQueMudou(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fichas = [mk(n, cliente=("Cliente Exemplo 01 Ltda" if n % 2 else "Cliente Exemplo 02 S.A."), autores=f"Pessoa Fictícia {n:04d}",
                         parte_contraria=f"Pessoa Fictícia {n:04d}") for n in range(1, 13)]
        cls.antes = {"fichas": cls.fichas, "data_base": "2026-08-31", "eventos": []}
        depois = copy.deepcopy(cls.fichas)
        cls.n_novo = mk(40, autores="Pessoa Fictícia 0040", parte_contraria="Pessoa Fictícia 0040")
        depois.append(cls.n_novo)
        # 1: encerrado por acordo; 2: mudou de momento; 3: valor estimado mudou (humano); 4: valor estimado só sugerido;
        # 5: saiu da carteira; 6: sentença nova (evento aprovado); 7: só evento em rascunho; 8: audiência marcada
        f1 = depois[0]
        f1["ativo"] = False
        ficha.definir(f1, "momento_atual", "ACORDO HOMOLOGADO", "humano", forcar=True)
        ficha.definir(f1, "situacao", "Encerrado", "humano", forcar=True)
        ficha.definir(f1, "resultado", "Acordo", "humano")
        ficha.definir(f1, "valor_acordo", "4000.00", "humano")
        ficha.definir(depois[1], "momento_atual", "AGUARDANDO JULGAMENTO DA APELAÇÃO", "humano", forcar=True)
        ficha.definir(depois[2], "valor_estimado", "7000.00", "humano")
        ficha.definir(depois[3], "valor_estimado", "9000.00", "sugerido")
        cls.removido = depois.pop(4)["numero"]
        n = [f["numero"] for f in cls.fichas]
        eventos = [
            evento(n[5], "2026-09-10", "O juiz proferiu sentença.", "Foram julgados parcialmente procedentes os pedidos."),
            evento(n[6], "2026-09-12", "O juiz proferiu decisão.", "RASCUNHO NAO APROVADO", status="rascunho"),
            evento(n[7], "2026-09-15", "O juiz designou audiência.", "", tipo="Decisão", audiencia="20/10/2026"),
            evento(n[8], "2026-09-20", "Foi aberto prazo para manifestação.", "", tipo="Despacho", prazo="05/10/2026"),
            evento(n[9], "2026-08-15", "Evento antigo, de antes da data-base.", ""),
            evento(n[10], "2026-09-18", "Movimento ja relatado antes.", "", status="relatado"),
        ]
        cls.depois = {"fichas": depois, "data_base": "2026-09-30", "eventos": eventos}
        cls.r = qualidade.o_que_mudou(cls.antes, cls.depois)

    def por(self, numero):
        return next(p for p in self.r["por_processo"] if p["numero"] == numero)

    def test_classifica_cada_processo(self):
        n = [f["numero"] for f in self.fichas]
        self.assertEqual(self.por(self.n_novo["numero"])["tipo"], "novo")
        self.assertEqual(self.por(n[0])["tipo"], "encerrado")
        self.assertEqual(self.por(n[1])["tipo"], "alterado")
        self.assertEqual(self.por(self.removido)["tipo"], "removido")
        self.assertEqual(self.por(n[5])["tipo"], "alterado")
        self.assertEqual(self.por(n[11])["tipo"], "sem_mudanca")
        self.assertEqual(self.r["data_antes"], "2026-08-31")
        self.assertEqual(self.r["totais"]["antes"]["processos"], 12)
        self.assertEqual(self.r["totais"]["depois"], {"processos": 12, "ativos": 11, "encerrados": 1})

    def test_mudancas_de_campo(self):
        n = [f["numero"] for f in self.fichas]
        campos = lambda num: {m["campo"] for m in self.por(num)["mudancas"]}
        self.assertEqual(campos(n[0]), {"momento_atual", "resultado", "valor_acordo"})
        self.assertEqual(campos(n[1]), {"momento_atual"})
        self.assertEqual(campos(n[2]), {"valor_estimado"})
        m, = self.por(n[2])["mudancas"]
        self.assertEqual((m["antes"], m["depois"], m["origem"]), (None, "7000.00", "humano"))

    def test_so_eventos_aprovados_da_janela(self):
        n = [f["numero"] for f in self.fichas]
        self.assertEqual(len(self.por(n[5])["eventos"]), 1)
        self.assertEqual(self.por(n[6])["eventos"], [], "rascunho nunca entra")
        self.assertEqual(self.por(n[9])["eventos"], [], "antes da data-base")
        self.assertEqual(len(self.por(n[10])["eventos"]), 1, "relatado dentro da janela entra (a janela é a data-base)")
        self.assertNotIn("RASCUNHO", self.r["texto"] + "".join(c["texto"] for c in self.r["por_cliente"].values()))

    def test_por_cliente(self):
        c1, c2 = self.r["por_cliente"]["Cliente Exemplo 01 Ltda"], self.r["por_cliente"]["Cliente Exemplo 02 S.A."]
        n = [f["numero"] for f in self.fichas]
        # números ímpares são do cliente 01 (n = 1, 3, 5, ...), ou seja, índices pares da lista
        self.assertIn(n[0], c1["encerrados"])
        self.assertEqual(c1["novos"] + c2["novos"], [self.n_novo["numero"]])
        self.assertEqual(c1["novos"], [self.n_novo["numero"]] if ficha.obter(self.n_novo, "cliente") == "Cliente Exemplo 01 Ltda" else [])
        self.assertIn({"numero": n[1], "antes": "AGUARDANDO SENTENÇA", "depois": "AGUARDANDO JULGAMENTO DA APELAÇÃO"}, c2["mudancas_de_momento"])
        self.assertTrue(any(d["numero"] == n[5] and "sentença" in d["texto"] for d in c2["decisoes"]))
        self.assertTrue(any(a["numero"] == n[7] and "20/10/2026" in a["texto"] for a in c2["audiencias_e_prazos"]))
        self.assertTrue(any(a["numero"] == n[8] and "05/10/2026" in a["texto"] for a in c1["audiencias_e_prazos"] + c2["audiencias_e_prazos"]))
        self.assertIn(self.removido, c1["removidos"] + c2["removidos"])
        self.assertEqual(c1["totais"]["antes"]["processos"] + c2["totais"]["antes"]["processos"], 12)

    def test_texto_do_cliente_e_so_do_que_foi_aprovado(self):
        for cliente, r in self.r["por_cliente"].items():
            t = r["texto"]
            self.assertTrue(t.startswith(f"Assunto: Andamento dos processos de {cliente}"))
            self.assertIn("Prezados,", t)
            self.assertIn("entre 31/08/2026 e 30/09/2026", t)
            self.assertIn(qualidade.AVISO_FINAL, t)
            self.assertLessEqual(len(t.splitlines()), 60, "uma página")
        t1 = self.r["por_cliente"]["Cliente Exemplo 01 Ltda"]["texto"]
        t2 = self.r["por_cliente"]["Cliente Exemplo 02 S.A."]["texto"]
        # valor estimado SÓ SUGERIDO (processo 4, cliente 02) não vai ao cliente; o humano (processo 3, cliente 01) vai
        self.assertIn("R$ 7.000,00", t1)
        self.assertNotIn("9.000,00", t2)
        self.assertNotIn("R$ 9.000,00", self.r["texto"])
        # a mudança sugerida continua na estrutura, com a origem, para a revisão
        sugerida = [m for m in self.por(self.fichas[3]["numero"])["mudancas"] if m["campo"] == "valor_estimado"]
        self.assertEqual([m["origem"] for m in sugerida], ["sugerido"])
        self.assertIn("estimativa", t1)
        self.assertIn("4.000,00", t1)    # valor do acordo (humano)

    def test_texto_nao_promete_resultado(self):
        todos = " ".join(c["texto"] for c in self.r["por_cliente"].values()).lower()
        for proibida in ("garantimos", "certamente", "vitória", "vitoria", "ganhamos", "com certeza", "sem dúvida"):
            self.assertNotIn(proibida, todos)
        self.assertIn("não constitui promessa nem garantia", todos)

    def test_texto_geral_e_por_processo(self):
        self.assertIn("Processos: 12 para 12", self.r["texto"])
        self.assertIn("Novos: 1", self.r["texto"])
        self.assertIn("saiu da carteira", self.por(self.removido)["texto"])
        self.assertIn("incluído na carteira", self.por(self.n_novo["numero"])["texto"])
        self.assertIn("sem alterações", self.por(self.fichas[11]["numero"])["texto"])
        self.assertIn("encerrado neste período", self.por(self.fichas[0]["numero"])["texto"])

    def test_sem_estado_anterior_tudo_e_novo(self):
        r = qualidade.o_que_mudou(None, self.depois)
        self.assertEqual({p["tipo"] for p in r["por_processo"]}, {"novo"})
        self.assertIsNone(r["data_antes"])
        self.assertIn("até 30/09/2026", " ".join(c["texto"] for c in r["por_cliente"].values()))
        # sem data-base anterior só entram eventos ainda aprovados e não relatados (nem rascunho, nem relatado)
        n = [f["numero"] for f in self.fichas]
        eventos = {p["numero"]: p["eventos"] for p in r["por_processo"]}
        self.assertEqual(sum(len(v) for v in eventos.values()), 4)
        self.assertEqual(eventos[n[10]], [])
        self.assertEqual(eventos[n[6]], [])

    def test_sem_mudanca_nenhuma(self):
        r = qualidade.o_que_mudou(self.antes, {**self.antes, "data_base": "2026-09-30"})
        self.assertEqual({p["tipo"] for p in r["por_processo"]}, {"sem_mudanca"})
        for c in r["por_cliente"].values():
            self.assertIn("Não houve novidades", c["texto"])

    def test_aceita_lista_de_fichas_e_retrato(self):
        import historico
        r = qualidade.o_que_mudou(self.fichas, self.depois["fichas"])
        self.assertEqual(r["totais"]["depois"]["processos"], 12)
        retrato = historico.retrato(self.fichas, "2026-08-31")
        r2 = qualidade.o_que_mudou(retrato, self.depois)
        n = [f["numero"] for f in self.fichas]
        self.assertEqual({p["numero"]: p["tipo"] for p in r2["por_processo"] if p["numero"] in (n[0], n[1], n[11])},
                         {n[0]: "encerrado", n[1]: "alterado", n[11]: "sem_mudanca"})
        # com retrato só se comparam os campos que ele tem: o valor do acordo não aparece como mudança, o momento sim
        self.assertEqual({m["campo"] for m in next(p for p in r2["por_processo"] if p["numero"] == n[0])["mudancas"]},
                         {"momento_atual", "resultado"})
        self.assertIn("estado_atual_e_retrato", {a["codigo"] for a in qualidade.o_que_mudou(self.antes, retrato)["avisos"]})

    def test_limite_de_itens_no_texto(self):
        muitos = [mk(n, cliente="Cliente Exemplo 01 Ltda") for n in range(100, 125)]
        r = qualidade.o_que_mudou({"fichas": [], "data_base": "2026-08-31"}, {"fichas": muitos, "data_base": "2026-09-30"}, max_itens=5)
        texto = r["por_cliente"]["Cliente Exemplo 01 Ltda"]["texto"]
        self.assertIn("e mais 20", texto)
        self.assertEqual(len(r["por_cliente"]["Cliente Exemplo 01 Ltda"]["novos"]), 25, "a estrutura tem todos")

    def test_reativado_e_aviso_sem_data_base(self):
        a = encerrada(1, resultado="Improcedente")
        b = mk(1)
        r = qualidade.o_que_mudou({"fichas": [a], "data_base": "2026-08-31"}, {"fichas": [b]})
        self.assertEqual(r["por_processo"][0]["tipo"], "reativado")
        self.assertIn("sem_data_base", {x["codigo"] for x in r["avisos"]})
        self.assertIn("voltaram a tramitar", r["por_cliente"]["Cliente Exemplo 01 Ltda"]["texto"])

    def test_resultado_sugerido_nao_vai_ao_cliente(self):
        a = mk(1, momento_atual="AGUARDANDO JULGAMENTO DA APELAÇÃO", resultado=None)
        b = copy.deepcopy(a)
        ficha.definir(b, "resultado", "Procedente", "sugerido")
        r = qualidade.o_que_mudou({"fichas": [a], "data_base": "2026-08-31"}, {"fichas": [b], "data_base": "2026-09-30"})
        self.assertNotIn("Procedente", r["por_cliente"]["Cliente Exemplo 01 Ltda"]["texto"])
        self.assertEqual(r["por_cliente"]["Cliente Exemplo 01 Ltda"]["decisoes"], [])
        ficha.definir(b, "resultado", "Procedente", "humano")
        r = qualidade.o_que_mudou({"fichas": [a], "data_base": "2026-08-31"}, {"fichas": [b], "data_base": "2026-09-30"})
        self.assertIn("Procedente", r["por_cliente"]["Cliente Exemplo 01 Ltda"]["texto"])

    def test_carteira_de_200(self):
        f = ficticio.gerar_carteira(200)
        depois = copy.deepcopy(list(f))
        for x in [x for x in depois if x["ativo"]][:20]:
            ficha.definir(x, "momento_atual", "AGUARDANDO JULGAMENTO", "humano", forcar=True)
        r = qualidade.o_que_mudou({"fichas": list(f), "data_base": "2026-08-31"}, {"fichas": depois, "data_base": "2026-09-30"})
        self.assertEqual(len(r["por_processo"]), 200)
        self.assertEqual(len(r["por_cliente"]), 5)
        self.assertTrue(all(len(c["texto"].splitlines()) <= 60 for c in r["por_cliente"].values()))


if __name__ == "__main__":
    unittest.main()
