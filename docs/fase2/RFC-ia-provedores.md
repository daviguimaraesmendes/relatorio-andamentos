# RFC: extensões aditivas ao contrato de IA (CONTRATOS §8) e integração do WS-18

Autor: WS-18. Nenhuma mudança é incompatível com o contrato; tudo é aditivo.

## Problema

CONTRATOS §8 devolve `{"texto", "json", "motor"}` e prevê "falha de rede cai no local e avisa", mas não diz **onde**
o aviso viaja, nem como o provedor sabe quais nomes pseudonimizar, onde fica o registro, nem o formato de `motor`.

## Proposta (já implementada em `src/ia.py`)

1. `Provedor.gerar(...)` devolve uma quarta chave, `"avisos"`: lista de Avisos estruturados (CONTRATOS §0), vazia
   quando tudo correu bem. Consumidores que ignoram a chave continuam funcionando.
2. `Provedor.gerar` aceita o argumento opcional `partes=()` (nomes extras a pseudonimizar). Além dele, o provedor
   já pseudonimiza o `cliente` e os nomes de `carteira.json`/`clientes.json` do relatório.
3. `ia.provedor(perfil, cliente, *, projeto=None, local=None, transporte=None, fabrica_cliente=None)`: `projeto`
   (pasta, slug ou None = o ativo) diz onde ficam registro e mapa; os demais são ganchos de teste.
4. `motor`: `local:<modelo>` | `externo:<id do provedor>:<modelo que respondeu>` | `nenhum` (nem o local
   respondeu; `texto` vazio e aviso `ia_local_indisponivel`). `ia.selo(motor)` converte para o rótulo da tela;
   motor ausente (evento da Fase 1) = "local".
5. `perfil["ia"]`: `provedor` é `"local"` ou o id de um provedor cadastrado (tela IA); `por_cliente[cliente]`
   (comparação sem diferenciar caixa/acento) prevalece sobre `consentimento_externo` nos dois sentidos;
   `pseudonimizar` só desliga com `false` explícito.
6. Armazenamento: catálogo de provedores (sem chave) em `config.json`, chave `ia_provedores`; chave de API no
   cofre como `ia_chave:<id>` (serviço do `acesso.py`); registro e mapa em `<relatório>/data/ia/`; a tela IA grava só
   `perfil["ia"]` em `<relatório>/perfil.json`, sem tocar no resto (o WS-9 é dono do arquivo).

## Impacto e o que o coordenador precisa integrar

- `src/revisao.py`: incluir `ia` (de `painel`) na tupla do laço `for tela in (...)`. Não fiz: mudaria a lista de rotas
  que `tests/test_painel.py` compara com o instantâneo, e todas as telas novas fazem a mesma mudança.
- `src/painel/base.py`: aba nova em `SUBABAS`, por exemplo `("ia", "/ia", "IA")`. Não fiz: muda o HTML de todas as telas.
  Enquanto isso, a tela abre digitando `/ia`.
- `requirements.txt`: acrescentar `anthropic` (o SDK é importado só quando um provedor Anthropic é chamado; sem ele, o
  sistema avisa `ia_pacote_ausente` e usa o local). Ensaiei com `anthropic` 1.11.0. O provedor compatível com OpenAI
  usa só a biblioteca padrão.
- README: texto em `docs/confidencialidade-ia.md`.
- WS-5/WS-9/WS-16: chamar `ia.provedor(perfil, cliente, projeto=...)`, gravar `motor` no evento e mostrar
  `ia.selo(motor)`; tratar `motor == "nenhum"` (sem resumo) e propagar `avisos`.
