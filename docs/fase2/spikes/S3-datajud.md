# Spike S3 — DataJud (API pública do CNJ) para metadados de capa

Data da consulta à documentação: **07/10/2026**. Autor: agente do WS-4. Código: `src/capa.py` (fonte `"datajud"` e `consultar_datajud`); testes: `tests/test_capa.py`.

## 1. Veredito

**Go com ressalvas, para uso como fonte de apoio, desligada por padrão.** A API é pública e documentada, mas devolve só **metadados de capa e movimentos**. Ela serve para classe, assunto, órgão julgador (vara) e uma data de ajuizamento. **Não serve** para partes, valor da causa, polo ou parte contrária, e não traz documentos. Ficou atrás da flag `fontes_externas.datajud` (padrão: desligada).

Antes de ligar, o escritório precisa decidir sobre o item 5 (termo de uso: "fins não comerciais").

## 2. O que a documentação diz (fonte: wiki do DataJud, `datajud-wiki.cnj.jus.br/api-publica/`, páginas Acesso, Endpoints, Exemplos 1 a 3, Glossário de Dados, Termo de Uso e o PDF "Termos de uso API pública V1.2")

- **Endereço**: `POST https://api-publica.datajud.cnj.jus.br/api_publica_<tribunal>/_search`, um índice por tribunal (aliases `tjce`, `tjdft`, `trf1` a `trf6`, `trt1` a `trt24`, `tst`, `stj`, `tse`, `stm`, `tre-<uf>`, `tjm...`). Não há índice do STF.
- **Autenticação**: cabeçalho `Authorization: APIKey <chave pública>`. A chave é pública, fica publicada na própria wiki e **o CNJ pode trocá-la a qualquer momento**. Por isso o código **não** a embute: ela vem de `config.json` ou da variável `DATAJUD_CHAVE`. Sem a chave, a ferramenta avisa e não faz chamada.
- **Consulta**: corpo no padrão Elasticsearch (`{"query": {"match": {"numeroProcesso": "<20 dígitos sem máscara>"}}}`). Resposta: `hits.hits[]._source`. Paginação por `size` (10 a 10.000) e `search_after` com ordenação por `@timestamp`.
- **Campos do `_source` (glossário)**: `numeroProcesso`, `tribunal`, `grau` (`G1`, `G2`, `JE`...), `dataAjuizamento`, `nivelSigilo`, `classe {codigo, nome}`, `assuntos [{codigo, nome}]`, `orgaoJulgador {codigo, nome, codigoMunicipioIBGE}`, `movimentos [{codigo, nome, dataHora, complementosTabelados[], orgaoJulgador}]`, `formato`, `sistema`, `dataHoraUltimaAtualizacao`, `@timestamp`, `id`.
- **O que não existe na API pública**: partes (a wiki diz que há "resguardo de processos sigilosos e dados de partes"), CPF/CNPJ, documentos, **valor da causa** (não consta do glossário nem dos exemplos), polo, advogados.
- **Mapa para a ficha**:

| Campo da ficha | Vem do DataJud? | De onde | Confiança no código |
| --- | --- | --- | --- |
| `classe` | sim | `classe.nome` | alta |
| `assunto` | sim | `assuntos[].nome` (lista, às vezes lista de listas; fica o primeiro) | alta |
| `vara` | sim | `orgaoJulgador.nome` | alta (baixa se o texto vier corrompido) |
| `data_ajuizamento` | sim | `dataAjuizamento` | média |
| `data_citacao` | só por dedução | movimento chamado "Citação" (nome do movimento; ver item 4) | média |
| `uf` | por dedução | dois primeiros dígitos de `orgaoJulgador.codigoMunicipioIBGE` (7 dígitos) | média |
| `municipio` | por dedução | padrão no nome do órgão ("... da Comarca de X"); o código IBGE **não** vira nome (não há tabela offline) | média |
| `valor_causa`, `autores`, `reus`, `parte_contraria`, `polo_cliente` | **não** | — | nunca preenchidos por esta fonte |

## 3. Peculiaridades vistas nos exemplos da wiki (e tratadas no código)

1. `assuntos` pode ser lista de listas (`[[{...}], [{...}]]`) em um exemplo e lista simples em outro.
2. `orgaoJulgador.nome` aparece corrompido num exemplo (`VARA DE EXECU??O FISCAL DO DF`): acento perdido. O código marca como confiança **baixa** (só preenche campo vazio) e avisa `capa_texto_corrompido`.
3. `dataAjuizamento` vem com hora `00:00:00.000Z` (só a data vale) e, num exemplo, difere da data do movimento "Distribuição" (anos de diferença): a data de ajuizamento do DataJud fica como confiança **média**.
4. O mesmo processo pode vir em mais de um grau (`G1`, `G2`, `JE`); o código usa o de 1º grau e avisa (`capa_varias_tramitacoes`).
5. `codigoMunicipioIBGE` aparece com 4 dígitos em um exemplo (valor que não é código IBGE de 7 dígitos): só se usa quando tem 7 dígitos e prefixo de UF válido.
6. A API é "Beta" segundo a própria wiki.

## 4. Verificado × não verificado

**Verificado (lido na documentação pública em 07/10/2026)**: endereço e formato do endpoint; formato da autenticação; formato da consulta por número; lista de campos do glossário; formato de resposta dos exemplos 1 e 2 (estrutura e tipos); limite de 120 requisições por minuto e as cláusulas do termo de uso; ausência de partes e de valor da causa no glossário.

**NÃO verificado**:
- **Nenhuma chamada real foi feita** (os testes não usam rede; este spike também não consultou a API). A fixture `tests/fixtures/capa/datajud_resposta.json` está marcada "formato conforme documentação, não capturado".
- Se `dataAjuizamento` é a data de ajuizamento ou a de distribuição, e o fuso das datas (a parte da data é usada como vem; datas com hora perto da meia-noite podem divergir um dia).
- O nome exato do movimento de citação nos tribunais reais (o código aceita o nome "Citação" e variações como "Citação realizada"; na Justiça do Trabalho o ato costuma chamar-se notificação, e ele **não** é reconhecido).
- A cobertura real por tribunal e a defasagem dos dados (a própria wiki diz que o CNJ não garante precisão, integridade ou atualidade; item 3.6 do termo).
- Se a chave publicada hoje continua valendo no dia do piloto.
- Como a API trata processos em segredo de justiça além do `nivelSigilo` (o código descarta o processo com `nivelSigilo` diferente de zero).

## 5. Pontos de atenção do termo de uso (a decidir pelo escritório)

- **3.3**: a API é fornecida "exclusivamente para fins legais, **não comerciais** e autorizados"; **3.8**: não "explorar comercialmente a API ou qualquer informação derivada dela". Não está claro se o uso por escritório de advocacia, para montar relatórios a clientes, se enquadra. **Recomendação: deixar desligada até o escritório decidir (ou consultar o CNJ).**
- **3.13**: no máximo 120 requisições por minuto. O cliente em `capa.consultar_datajud` espera 0,55 s entre chamadas (menos de 110 por minuto).
- **3.9**: o usuário concorda em dar ciência ao CNJ de relatórios ou estudos que divulgue ao público. Não se aplica a relatório privado ao cliente, mas está no termo.
- **3.11 e 4.2**: não coletar dados pessoais de terceiros pela API. O código só lê metadados e descarta `partes` mesmo que apareçam.
- **3.4 e 3.14**: o CNJ pode alterar, limitar ou revogar o acesso sem aviso. O código trata isso como aviso (`datajud_chave_recusada`, `datajud_limite`, `datajud_indisponivel`) e a ferramenta continua com as outras fontes.

## 6. Como ligar (quando houver decisão)

Em `config.json` (arquivo pessoal, fora do repositório):

```json
"fontes_externas": {"datajud": {"ativo": true, "chave": "<chave pública da página Acesso da wiki>"}}
```

(ou `"datajud": true` e a chave na variável de ambiente `DATAJUD_CHAVE`). `config.exemplo.json` não foi alterado por este workstream; o coordenador decide se acrescenta a chave `fontes_externas` ao exemplo. Uso:

```python
resposta, avisos = capa.consultar_datajud(numero)          # None + aviso se desligado, sem chave ou com erro
campos = capa.extrair("datajud", resposta, numero=numero)  # {campo: {valor, confianca, evidencia}}
capa.aplicar(ficha, campos)                                 # origem "coletado"; confiança baixa só preenche vazio
```

## 7. Recomendação de uso na fila (para o WS-3/coordenador)

DataJud não substitui o jus.br: serve para **preencher classe, assunto, vara e data de ajuizamento de processos que o jus.br não abriu** (captcha, segredo, sessão), e para **conferir** a capa do jus.br (`capa.extrair_varias` avisa quando duas fontes divergem). Valor da causa e partes continuam dependendo do jus.br/TRT (ou de preenchimento humano).
