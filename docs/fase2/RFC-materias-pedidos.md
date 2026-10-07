# RFC: matérias dos pedidos que faltam no vocabulário (`taxonomia.MATERIA`) e integração da tela de pedidos

Origem: WS-16 (kit de pedidos das iniciais). Destinatários: coordenador e WS-1 (dono de `taxonomia.py`), WS-9 (barra de abas).

## 1. Problema: o vocabulário de matérias não tem as matérias mais comuns de uma inicial trabalhista

`taxonomia.MATERIA` (ponto de partida da Etapa 0) cobre jornada, saúde e segurança, estabilidades, dano moral e acessórios, mas **não tem**, por exemplo:

- multas dos arts. 467 e 477 da CLT (a especificação do WS-16 manda tratá-las como matéria própria);
- verbas rescisórias (aviso prévio, saldo de salário, férias e 13º proporcionais);
- FGTS e multa de 40% (diferenças, liberação);
- reconhecimento de vínculo empregatício;
- reversão de justa causa e rescisão indireta;
- equiparação salarial; adicional de transferência; vale-transporte e vale-alimentação.

Com o vocabulário atual, esses pedidos caem em `Outros` (com `materia_sugerida`), o que é seguro (o validador nunca adivinha), mas esvazia os rankings por matéria.

## 2. Proposta

WS-1 amplia `MATERIA` (e `MATERIA_SINONIMOS`) com as matérias acima, mantendo todos os valores existentes (regra do CONTRATOS §2). O kit já se adapta: o prompt e o validador leem `taxonomia.MATERIA` em tempo de execução (o prompt embute a lista atual; há teste que cobre isso). O prompt v1.0.0 funciona antes e depois da ampliação: se a matéria não existir na lista, ele manda a IA usar `Outros` com `materia_sugerida`.

Também falta, para a aba "Parâmetros por matéria", a informação "pode ser causa geradora" (hoje `parametros_por_materia()` devolve essa coluna vazia). Sugestão: acrescentar um quarto elemento (booleano ou `None`) à tupla de `MATERIA`, ou um dicionário à parte; precisa de decisão do escritório.

## 3. Integração da tela `/pedidos` (nenhuma mudança de contrato)

- `src/revisao.py`: o WS-16 acrescentou `pedidos` ao import e à tupla do laço `for tela in (...)` (a única linha que o `painel-modulos.md` autoriza). WS-9 e WS-10 farão a mesma mudança na mesma linha: conflito trivial de merge.
- `tests/fixtures/painel_instantaneo.json`: a lista `rotas` ganhou 7 linhas (`/pedidos`, `/pedidos/enviar`, `/pedidos/gravar`, `/pedidos/pacote`, `/pedidos/planilha`, `/pedidos/prompt`, `/pedidos/validar`). Nenhum HTML de tela existente mudou. Cada workstream que registrar telas terá de regravar a lista; sugiro o coordenador regravar uma vez, no fim da integração (`PAINEL_GRAVAR=1 python3 -m unittest tests/test_painel.py`).
- `painel/base.py` (`SUBABAS`) **não foi alterado**: acrescentar `("pedidos", "/pedidos", "Pedidos")` muda o HTML de todas as telas e o instantâneo inteiro. Enquanto isso, a tela é alcançável por `/pedidos`. Quem fizer a barra de abas (WS-9) deve incluir a aba.

## 4. Provedor externo (WS-18)

`pedidos.PROVEDOR` é um ponto de extensão (função `(projeto, numeros) -> texto da resposta`). Enquanto for `None`, a tela mostra "indisponível". Quando o WS-18 estiver integrado e houver provedor cadastrado **e** consentimento no perfil, o coordenador atribui a função (o texto devolvido segue o mesmo caminho de um resultado colado: validar, conferir, gravar). O envio de PDF não está previsto: a especificação do WS-18 só envia texto extraído.
