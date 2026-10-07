"""Conformidade dos módulos da Fase 2 com `docs/fase2/CONTRATOS.md` (teste transversal do WS-13).

Para cada módulo de `transversal.MODULOS` há um teste `test_contrato_<módulo>`:
- módulo ainda não existe  -> o teste é PULADO com a mensagem "<módulo> ainda não existe (WS-n)...";
- módulo existe            -> confere que as funções do contrato existem e que a assinatura atende (primeiros
  parâmetros e parâmetros nomeados); telas do painel também precisam estar REGISTRADAS em `revisao.app`
  (a tupla de `revisao.py` é do coordenador: módulo existente e não registrado falha aqui).

Não executa o módulo: só olha a interface. O comportamento é coberto pelos testes de cada workstream e pelos
transversais (`test_desempenho.py`, `test_confidencialidade.py`).

    python3 -m unittest tests/test_contratos.py -v
    python3 tests/test_contratos.py --matriz      # tabela módulo x estado, para colar no STATUS.md
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transversal as T  # noqa: E402  (importa o isolamento antes de tudo)


def conferir_contrato(nome, contrato):
    """(faltas, divergências): itens do contrato que não existem e assinaturas que não atendem."""
    mod = T.modulo(nome)
    faltas, divergencias = [], []
    for item, posicionais, nomeados in contrato:
        alvo = T.resolver(mod, item)
        if alvo is None:
            faltas.append(f"falta `{item}`")
            continue
        if callable(alvo):
            motivo = T.assinatura_compativel(alvo, posicionais, nomeados)
            if motivo:
                divergencias.append(f"`{item}`: {motivo}")
    return faltas, divergencias


def so_a_base_da_etapa0(nome, contrato, faltas):
    """True quando o módulo existe só na versão da Etapa 0 (ex.: taxonomia.py) e NENHUM item do contrato do
    workstream chegou ainda: ainda não há o que conferir (é o mesmo que 'módulo ausente')."""
    return bool(contrato) and len(faltas) == len(contrato)


def tela_registrada(nome):
    """None se a tela do painel está registrada em revisao.app (ou não tem prefixo de rota exigido)."""
    prefixo = T.PREFIXO_DE_ROTA.get(nome)
    if not prefixo:
        return None
    import revisao
    regras = [r.rule for r in revisao.app.url_map.iter_rules()]
    if any(r == prefixo or r.startswith(prefixo + "/") for r in regras):
        return None
    return (f"`{nome}` existe, mas nenhuma rota `{prefixo}...` está registrada em revisao.app "
            f"(acrescentar o módulo à tupla de revisao.py)")


def _teste_do_modulo(nome, contrato):
    def teste(self):
        T.exigir(nome)
        faltas, problemas = conferir_contrato(nome, contrato)
        if so_a_base_da_etapa0(nome, contrato, faltas):
            self.skipTest(f"{nome} existe só na versão da Etapa 0; as funções do {T.ws_do_modulo(nome)} ainda não "
                          f"chegaram ({', '.join(f.split('`')[1] for f in faltas)}); reativar na integração")
        problemas = faltas + problemas
        if nome in T.PREFIXO_DE_ROTA:
            achado = tela_registrada(nome)
            if achado:
                problemas.append(achado)
        self.assertEqual(problemas, [], f"{nome} diverge do CONTRATOS.md: " + "; ".join(problemas))
    teste.__doc__ = f"{nome} segue o contrato ({T.ws_do_modulo(nome)})"
    return teste


class Contratos(unittest.TestCase):
    """Os testes por módulo são acrescentados logo abaixo (um por entrada de transversal.MODULOS)."""

    def test_etapa0_existe(self):
        """O que o M1 entregou continua no lugar (ficha, taxonomia, coletor simulado, fixtures)."""
        import ficha
        import simulado
        import taxonomia
        import ficticio
        for nome in ("CAMPOS", "definir", "obter", "origem", "limpar", "vincular", "todos_os_numeros", "validar",
                     "carregar", "salvar", "nova_ficha", "de_carteira_v1", "dinheiro", "parse_data", "parse_dinheiro"):
            self.assertTrue(hasattr(ficha, nome), f"ficha.{nome} sumiu")
        for nome in ("normalizar", "momento_ativo", "categoria_do_momento"):
            self.assertTrue(hasattr(taxonomia, nome), f"taxonomia.{nome} sumiu")
        self.assertTrue(hasattr(simulado, "ColetorSimulado"))
        for nome in ("gerar_carteira", "numero_ficticio", "gerar_lista_bruta", "projeto_de_teste", "detectar_defeitos"):
            self.assertTrue(hasattr(ficticio, nome), f"ficticio.{nome} sumiu")

    def test_todo_modulo_da_tabela_tem_arquivo_coerente(self):
        """Se o arquivo esperado existe, o módulo importa; se o módulo importa, o arquivo existe (sem módulo órfão)."""
        for _ws, nome, arquivo, _contrato in T.MODULOS:
            existe_arquivo = (T.RAIZ / arquivo).exists()
            existe_modulo = T.modulo(nome) is not None
            self.assertEqual(existe_arquivo, existe_modulo, f"{nome}: arquivo {arquivo} x módulo importável divergem")


for _ws, _nome, _arquivo, _contrato in T.MODULOS:
    setattr(Contratos, "test_contrato_" + _nome.replace(".", "_"), _teste_do_modulo(_nome, _contrato))


def matriz():
    """[(ws, módulo, arquivo, estado)] com estado 'presente, no contrato' | 'presente, DIVERGE: ...' | 'ausente'."""
    linhas = []
    for ws, nome, arquivo, contrato in T.MODULOS:
        if T.modulo(nome) is None:
            estado = "ausente"
        else:
            faltas, problemas = conferir_contrato(nome, contrato)
            if so_a_base_da_etapa0(nome, contrato, faltas):
                linhas.append((ws, nome, arquivo, "só a base da Etapa 0 (extensões do workstream ausentes)"))
                continue
            problemas = faltas + problemas
            if nome in T.PREFIXO_DE_ROTA:
                achado = tela_registrada(nome)
                problemas += [achado] if achado else []
            estado = "presente, no contrato" if not problemas else "presente, DIVERGE: " + "; ".join(problemas)
        linhas.append((ws, nome, arquivo, estado))
    return linhas


if __name__ == "__main__":
    if "--matriz" in sys.argv:
        print("| WS | Módulo | Arquivo | Estado no repositório |\n| --- | --- | --- | --- |")
        for linha in matriz():
            print("| " + " | ".join(linha) + " |")
    else:
        unittest.main()
