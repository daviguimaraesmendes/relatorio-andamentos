# RFC: fixture de julgamento contradiz o PLANO 7.2 (e três pontos de contrato do WS-17)

Autor: WS-17 (`src/julgamento.py`). Destinatário: coordenador e WS-13 (dono de `tests/ficticio.py`).

## 1. Problema: `ficticio._ficha_sintetica` lança julgamento "humano" que a regra do plano não produz

Nas fichas com campos de julgamento lançados por humano (cerca de 30% da carteira sintética), o gerador:

1. **inverte a probabilidade pelo polo**: com o cliente autor, procedência vira "Remota" e improcedência vira "Provável". O PLANO 7.2 (corrigido) diz o contrário: a probabilidade é a do **resultado**, sem inversão por polo;
2. **lança probabilidade para "Arquivado / desistência" e "Incompetência declarada"**; a regra do plano deixa a probabilidade vazia nos desfechos sem julgamento de mérito (o gerador só omite em Acordo e Extinto);
3. **lança `valor_economizado` para processo em que o cliente é autor**; o plano manda **não contar** esse caso (a regra devolve `valor: None` com a ressalva "Cliente é autor");
4. troca a probabilidade por outra ao acaso em 15% dos casos (ruído deliberado, útil, mas faz a concordância nunca chegar a 100%).

Efeito medido (`julgamento.concordancia` sobre `gerar_carteira(200, semente=1..3)` + `anexar_linha_de_base`): resultado 100% de concordância (39/39, 47/47, 36/36) e valor estimado 98 a 100%; probabilidade 62 a 66% (as divergências são exatamente os itens 1, 2 e 4); valor economizado 62 a 78% (as divergências são todas de cliente autor, item 3).

## 2. Proposta (WS-13)

Em `tests/ficticio.py`, no bloco "julgamento": usar a mesma regra do plano (sem inversão por polo; sem probabilidade para desistência e incompetência; sem `valor_economizado` quando `polo == "ativo"`), mantendo o ruído de 15% se quiserem testar a divergência. Os testes do WS-17 já aceitam o gerador como está (conferem só o resultado, o valor estimado e que toda divergência de economia é de cliente autor), então a mudança não os quebra; ela só faz o relatório de concordância sobre a fixture refletir a regra.

## 3. Pontos de contrato do WS-17 que o coordenador precisa conhecer (CONTRATOS §10)

- `sugerir(ficha, eventos)` mantém a assinatura e o formato. Acrescentei **opcionais e aditivos**: `sugerir(..., usar_relatorio=True)`, `sugerir_com_avisos(...) -> (sugestoes, avisos)` (avisos estruturados do que não foi sugerido e por quê), `eventos_do_relatorio(ficha)`, `concordancia(fichas, eventos=None)` e, dentro de cada campo da concordância, a chave extra `por_regra`.
- **`valor_economizado` com `valor: None`** é uma entrada válida: significa "caso que não conta como economia" e carrega o motivo nas `ressalvas`. Quem exibir ou aplicar sugestões precisa tratar `None` (a função `aplicar` ignora). Alternativa, se a tela preferir: tratar `valor None` como "sem sugestão" e mostrar só a ressalva.
- **Texto do relatório anterior como fonte**: como a `concordancia(fichas_migradas)` recebe só fichas, e a decisão antiga de um processo migrado só existe no texto de andamentos, `sugerir` lê também `linha_de_base.andamentos_texto` e `ultimo_texto_gravado.texto` (sempre com a ressalva "Lido do texto do relatório anterior, não de documento aprovado"). `usar_relatorio=False` desliga.
- **Só sugere onde o campo não tem origem maior que `sugerido`** (humano, coletado, migrado ou derivado): `ficha.definir` recusaria a gravação de qualquer modo, e o CONTRATOS §1 diz "só sugere onde estiver vazio".
