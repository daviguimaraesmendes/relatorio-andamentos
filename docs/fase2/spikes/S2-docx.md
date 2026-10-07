# Spike S2 — atualizar e gerar o `.docx` do modelo A

Data: 07/10/2026. Autor: agente do spike S2 (Etapa 0 da Fase 2). Código em `spikes/s2_docx/`.

## 1. Veredito

**Go com ressalvas.** Dá para gerar o `.docx` do zero e para atualizar um `.docx` existente no formato do modelo A, preservando fontes, negrito, tabelas, mesclagens, larguras e o texto escrito à mão, **na amostra sintética e abrindo em python-docx e em LibreOffice**. Não há prova nenhuma de que o Word ou o Google Docs abram o resultado sem aviso: isso exige uma exportação real e conferência humana (seção 7).

As ressalvas que seguram o "Go" sem ressalvas:

1. Tudo foi validado com um fixture que **eu escrevi** imitando o Google Docs. Rótulos, redação do fecho e formato do título são **suposições** até alguém passar uma exportação real pelo `ler_estrutura`.
2. A regra "só acrescenta" tem **exceções mecânicas** que o contrato não nomeia: o sistema troca a data da frase de fecho, o "momento atual" (resumo e título) e o "último andamento". Se o advogado editou esses campos à mão, o sistema os sobrescreve (aviso só quando resumo e título já divergiam).
3. A detecção de duplicata e de edição manual é **heurística** (limiares escolhidos por mim, sem calibração com texto real). Erra para os dois lados; por isso sempre devolve aviso e lista de ignorados para a revisão.

## 2. O que foi feito

| Arquivo | Conteúdo |
| --- | --- |
| `spikes/s2_docx/gerar_modelo.py` | Gera o `.docx` fictício "tipo Google Docs": 12 processos, runs fragmentados em pontos aleatórios, rPr repetido em todo run, sem estilos nomeados, larguras explícitas, parágrafos vazios entre tabelas. Casos de borda: um processo com 3 números no título, um sem valor da causa, um com citação "-", um com anotação do advogado em destaque, um com mesclagem vertical, um sem fecho, um com fecho todo em negrito, um com "sem atualização" (singular), datas escritas no meio da frase |
| `spikes/s2_docx/docx_atualizador.py` | Protótipo: `ler_estrutura`, `atualizar`, `gerar`, `gravar` (contrato de `CONTRATOS.md` seção 5), `verificar_coerencia` |
| `spikes/s2_docx/test_s2.py` | 38 testes `unittest` |

Rodar: `python3 -m unittest spikes/s2_docx/test_s2.py -v` (14 s; os 3 testes do LibreOffice são pulados se não houver `soffice`).

**Resultado: 38 passando em 38.** A cobertura é descrita na seção 3.

Todos os dados são inventados. Os números CNJ são calculados em tempo de execução (dígito verificador correto, sequenciais `1234567` a `1234570`, as faixas que o `empacotar.sh` aceita); nenhum número real ou fora da lista foi gravado como literal (conferido com o mesmo `grep` do `empacotar.sh`).

## 3. O que funcionou

**Técnica: edição cirúrgica do pacote.** Como o `planilha.py` faz com o `.xlsx`, o `atualizar` abre o `.docx` como zip, edita só `word/document.xml` com lxml e copia todas as outras partes byte a byte (estilos, tema, mídia, comentários, cabeçalhos). Quando não há mudança alguma, o `document.xml` também sai idêntico byte a byte. Não passa pelo python-docx na gravação (que reserializa partes e não precisamos dele).

| Requisito | Resultado nos testes |
| --- | --- |
| Reconhecer o processo por qualquer um dos números do título | Funciona (agravo identificado pelo 2º número; título de 3 números lido e escrito) |
| Runs fragmentados (até no meio da data) | O texto é tratado como um fluxo contínuo mapeado para os runs. O resultado final é idêntico com 12 fragmentações diferentes (sementes 1 a 12) |
| Acrescentar frases com runs que copiam a formatação do vizinho, datas em negrito | O rPr (fonte, tamanho, cor) é copiado do último run normal e do último run em negrito do parágrafo; a data fica em negrito, o resto não. Anotação em destaque do advogado (itálico, marca-texto) **não é herdada** pelo texto novo |
| Detectar o fecho e substituí-lo | Regex tolerante (espaço não separável, vírgula opcional, "sem atualização/atualizações/andamentos", "Em" ou "Até", negrito parcial ou total, fragmentação). Sem novidade: só a **data** é trocada no próprio run (preserva a formatação original do fecho). Com novidade: o fecho antigo sai, as frases entram e um fecho novo (data-base) é acrescentado (opção `fecho_apos_novidade`) |
| Fecho ausente | Acrescentado, com aviso informativo |
| Não duplicar andamento | Mesma data + núcleo de texto parecido (tokens sem acento, caixa ou palavras-ponte) é ignorado e listado em `ignorados`. Mesma data com texto diferente entra. Texto "quase igual" digitado à mão entra em `ignorados` com aviso |
| Edição manual recente | Se a atualização traz `texto_conhecido` (o texto como o sistema o deixou no último ciclo) e o final do texto atual diverge, o sistema **só acrescenta**, não remove nada além do fecho exato e devolve o aviso `edicao_manual`. Reaplicar a mesma atualização não gera esse aviso |
| Resumo e bloco coerentes | "Momento atual" muda no quadro-resumo (em negrito e caixa alta) e no `[ ... ]` do título; "último andamento" vira a maior data entre a atual e as novas. `verificar_coerencia` confere números, momento, último andamento, fecho e data-base |
| Processo novo | Clona o último bloco "limpo" (todos os campos mapeados, sem mesclagem vertical, imagem, revisão ou texto solto) e a última linha do resumo; preenche por rótulo; separa com parágrafo vazio; não duplica se algum número já existe. Se o modelo é ruim, avisa; célula fora do padrão do modelo é esvaziada no clone (texto do processo antigo não vaza) |
| Idempotência | Aplicar duas vezes a mesma lista (inclusive processo novo) dá `document.xml` idêntico byte a byte e `mudancas == []` |
| Preservação | Blocos não atualizados: XML canônico (C14N) idêntico. Nos atualizados: tblPr, tblGrid, linhas fora do título e dos andamentos, rótulo e tcPr da célula de andamentos idênticos. Parágrafos fora das tabelas: só o da data-base muda. Outras partes do pacote: byte a byte. Runs antigos antes do fecho: idênticos |
| Original intacto | `destino == origem` (inclusive por link simbólico) e destino existente são recusados |
| python-docx | Recarrega e regrava o arquivo atualizado; negrito, fonte Arial e 11 pt do run novo conferem |
| LibreOffice | `soffice --headless --convert-to pdf` converte original, atualizado e gerado do zero; o texto novo (data-base, datas novas, frases, número do processo novo, momento novo no resumo e no título) aparece no PDF extraído com pypdf. Conferi também a página renderizada: datas em negrito, marca-texto do advogado preservada, texto novo sem marca-texto |
| Variante de layout | "Andamentos:" numa linha e o texto na linha de baixo é suportado |
| Escala | 200 processos: `gerar` 0,9 s, `atualizar` com 200 atualizações 0,7 s, `ler_estrutura` 0,2 s (sem coleta) |

## 4. O que não funcionou ou foi tratado como limite

**Limites conhecidos (cobertos por aviso ou por regra conservadora):**

| Situação | O que o protótipo faz |
| --- | --- |
| Controle de alterações (`w:ins`/`w:del`) ou âncora de comentário no parágrafo de andamentos | Não remove nada; acrescenta no fim e avisa (`revisao_no_trecho`). Modo "sugestão" do Google Docs vira controle de alterações na exportação. Com `trackRevisions` ligado nas configurações, avisa que as edições do sistema **não** aparecem como revisão (não sabemos gerar revisão; implementado, **sem teste**) |
| Mesclagem vertical (`vMerge`) | Preservada ao atualizar. O clone **evita** blocos com `vMerge`; se só houver blocos assim, clona e avisa. Mesclagem vertical que cruza a linha de andamentos não foi testada |
| Imagens (`drawing`) dentro de bloco | Intactas ao atualizar. Clonar bloco com imagem duplicaria `docPr id`: o seletor evita e, no fallback, avisa (implementado, **sem teste com imagem**). Imagem em cabeçalho/rodapé: partes não tocadas |
| Fecho num parágrafo anterior (o advogado escreveu outro parágrafo depois) | Nunca apagado; sem novidade renova a data ali mesmo; com novidade o texto vai no último parágrafo e avisa (`fecho_fora_do_fim`). Pode ficar com dois fechos |
| Fecho editado à mão ("..., sem atualizações, aguardando alvará.") | Não casa o padrão: tratado como texto do advogado; o fecho novo é acrescentado depois. Sem aviso |
| Andamentos escritos fora do padrão "Em DD/MM/AAAA" (ex.: "No dia 18/06/2026, ...", "18/06/26") | Não são separados em frases, logo a **checagem de duplicata não os enxerga** e o andamento pode ser repetido. É o maior risco de duplicação real |
| Negrito por estilo nomeado (`rStyle`) em vez de direto no run | Não detectado (o Google exporta direto no run; confirmar na exportação real) |
| Dois processos no mesmo bloco, tabelas aninhadas, controles de conteúdo (`w:sdt`), caixas de texto | Não tratados |
| Rótulos de linha diferentes dos supostos ("Autor(es)", "Réu(s)", "Ajuizamento", "Valor da Causa", "Data de citação", "Juízo", "Área do Direito", "Matéria Principal", "Andamentos:") | Campo não mapeado: o clone avisa; a atualização de andamentos exige só "Andamentos" |
| Título sem `[ ... ]` | Momento não atualizado no título, aviso `titulo_sem_momento`; resumo atualizado |
| Número de processo sem a pontuação CNJ | Não reconhecido |
| Mesmo número em dois blocos | Atualiza só o primeiro e avisa |
| Processo do arquivo ausente da carteira | Intacto, listado em `processos_sem_atualizacao`. Com `renovar_fecho_dos_demais=True` só o fecho é renovado |
| Processo que sumiu do `.docx` mas está na ficha | Vira processo novo (decisão do chamador; o `gravar` faz isso) |
| Quebra de página | Bloco novo ou texto maior apenas empurra o conteúdo; não há controle de "manter junto" |

**Coisas que dei como decisão provisória e precisam de confirmação:**

- **Fecho depois de novidade.** A descrição do modelo diz que cada texto termina por "Em DD/MM/AAAA, sem atualizações." (data = data-base). Adotei isso: com novidade, o texto fica "... novidade. Em DD/MM/AAAA, sem atualizações." com a data-base. Na planilha da Fase 1 não é assim (o fecho só aparece sem novidade). Parâmetro `fecho_apos_novidade` (padrão `True`). **Perguntar ao usuário qual é o certo.**
- O sistema **ordena** os andamentos novos por data, mas os coloca sempre no fim do texto (não reordena o histórico).
- A cláusula do andamento começa em minúscula após "Em DATA, " (mantém siglas), como a `planilha.py` já faz; ponto final garantido.

## 5. Editar o arquivo existente x gerar do zero

| | Atualizar o existente (`atualizar`) | Gerar do zero (`gerar`) |
| --- | --- | --- |
| Fidelidade ao arquivo do cliente | Total no que não é tocado (byte a byte nas outras partes; C14N nos blocos intactos) | Nenhuma: usa o layout do protótipo (Arial 11, cabeçalho cinza). Não herda logotipo, cabeçalho, margens, fontes do escritório |
| Texto editado à mão | Preservado | Perdido: a ficha só tem o que o sistema sabe (a linha de base migrada reaparece como texto, sem negrito das datas e sem anotações em destaque) |
| Risco | Estrutura inesperada no arquivo real (rótulos, título, fecho) | Baixo; é o que o código controla |
| Esforço de compatibilidade | Alto: cada variação da exportação real é um caso | Baixo: um modelo fixo |
| Quando usar | Todo ciclo mensal em que o cliente já tem o `.docx` | Relatório inicial; fallback se o arquivo do cliente falhar na leitura; "Migrar de modelo" |

Recomendação para o WS-6: o "modelo padrão" do contrato (`src/modelos/docx_a/`) deve ser um `.docx` sanitizado com **um bloco-modelo e uma linha-modelo de resumo**; `gerar` = abrir esse modelo, inserir todos os processos pelo mesmo caminho de "processo novo" e remover o bloco-modelo. Assim existe **um** caminho de código (o clonador) e o modelo é editável pelo escritório. O `gerar` do protótipo monta o XML em código só para o spike.

## 6. Esboço da API para o WS-6 (`src/escritores/docx_a.py`)

O protótipo já tem a forma do contrato (`CONTRATOS.md` seção 5):

```python
gravar(molde: Path | None, estado: EstadoRelatorio, destino: Path, **opcoes) -> Resultado
```

- `estado["fichas"]` + `estado["eventos"]` viram, internamente, uma lista de atualizações por processo: `{"numeros": [...], "momento_atual", "ultimo_andamento", "andamentos": [{"data", "texto"}], "texto_conhecido"}`, ou `{"novo": proc}` se nenhum número da ficha está no arquivo. A conversão está em `_proc_da_ficha` (usa `data_ajuizamento`, `data_citacao`, `vara`, `area`, `materia_principal`, `valor_causa`, `momento_atual`, `ultimo_andamento` da ficha e `vinculados` para o título). `texto_do_evento` repete as regras de `relatorio.linha`; em produção deve **importar** `relatorio.linha`/`planilha.frase_planilha`, e usar `ficha.data_br`/`ficha.dinheiro_br` (o protótipo não importa `ficha` para ficar sem dependência de `comum`).
- `molde=None`: `gerar` (ver seção 5).
- `Resultado`: `{"destino", "processos_atualizados", "processos_novos", "mudancas": [{"numero", "campo", "antes", "depois"}], "avisos": [{"nivel", "onde", "mensagem", "candidatos"}]}`. Campos de `mudancas.campo` usados: `data_base`, `momento_atual`, `ultimo_andamento`, `andamentos` (texto acrescentado), `andamentos_fecho`, `processo`.
- Funções auxiliares a manter públicas: `ler_estrutura(docx) -> dict` (para o leitor `leitores/docx_a.py` do WS-2 **reaproveitar** a mesma leitura de blocos e resumo, evitando dois parsers do mesmo arquivo) e `verificar_coerencia(docx) -> list[str]` (para o WS-11).

**Pedidos de ajuste de contrato (RFC, não alterei o contrato):**

1. `Resultado` ganha, de forma aditiva, `"ignorados"` (andamentos não acrescentados por já existirem, com motivo), `"nao_encontrados"` e `"andamentos_texto_depois": {numero: texto}`. A ficha precisa **guardar esse texto a cada ciclo** (campo novo, ex.: `ficha["andamentos_escritos"]`) para servir de `texto_conhecido` no ciclo seguinte; hoje `linha_de_base.andamentos_texto` só guarda o texto lido na migração e a detecção de edição manual ficaria cega depois do primeiro ciclo.
2. `Aviso` ganha o campo aditivo `codigo` (ex.: `edicao_manual`, `fecho_acrescentado`, `revisao_no_trecho`) para os testes e a tela de revisão não dependerem do texto da mensagem.
3. Em "Regra de ouro" (PLANO 3.3 e CONTRATOS 5), nomear as exceções mecânicas (data-base, momento atual, último andamento, data do fecho), ou o teste de aceite "só acrescenta" fica ambíguo.
4. Opções do `gravar` do `.docx`: `fecho_apos_novidade`, `renovar_fecho_dos_demais`, `textos_conhecidos`, `sobrescrever_destino` (já implementadas).

**Dependências novas:** `lxml` (já vem junto com o python-docx, mas não está no `requirements.txt`) para atualizar; `python-docx` só para criar o esqueleto no `gerar` do protótipo e para os testes (se o modelo padrão virar arquivo, sai da gravação). Nenhuma das duas está em `requirements.txt` hoje; o `pypdf` já está.

## 7. O que o usuário deve conferir à mão (com uma exportação real)

Eu **não** abri nada no Word nem no Google Docs. Só python-docx, lxml e LibreOffice. Lista de conferência, em ordem de risco:

1. **Rodar `ler_estrutura` numa exportação real** (de preferência uma cópia sanitizada) e conferir: reconheceu a data-base, o quadro-resumo, todos os blocos e todos os campos? Os rótulos reais batem com os que supus (seção 4)? O título tem `[ MOMENTO ]` com colchetes? O fecho tem exatamente a redação "Em DD/MM/AAAA, sem atualizações."? O resumo escreve vários números do mesmo processo em parágrafos, quebras de linha ou separados por barra?
2. **Abrir o arquivo atualizado no Word** (Mac e/ou Windows): abre sem a mensagem "conteúdo ilegível, deseja recuperar"? Datas novas em negrito, fonte e tamanho iguais aos vizinhos, sem sublinhado nem marca-texto herdados?
3. **Enviar o atualizado ao Google Drive e abrir como Google Doc**: larguras de coluna, mesclagens, parágrafos vazios entre as tabelas, negrito. Depois **exportar de novo para `.docx` e rodar um segundo ciclo** (a ida e volta é o uso real e nunca foi testada).
4. **Processo novo**: o bloco clonado tem o mesmo aspecto dos outros? A linha do resumo entrou na ordem certa (o protótipo sempre acrescenta no fim; talvez o escritório ordene por outro critério)?
5. **Comentários e sugestões** do Google Doc: criar um comentário e uma sugestão num parágrafo de andamentos e rodar a atualização: o aviso apareceu e nada foi apagado?
6. **Edição à mão**: escrever uma frase no fim do texto de um processo, rodar com o `texto_conhecido` do ciclo anterior e conferir o aviso `edicao_manual`.
7. **Andamentos escritos de outro jeito** (sem "Em DD/MM/AAAA") no histórico real: avaliar quantos há, pois a checagem de duplicata não os enxerga.
8. **Cabeçalho, rodapé, logotipo e imagens**: continuam iguais?
9. **Aparência**: comparar o PDF antes e depois lado a lado (quebras de página, bloco partido entre páginas).

## 8. Próximos passos sugeridos

1. Usuário responde a pergunta do fecho (seção 4) e fornece uma exportação real **sanitizada** (ou diz os rótulos exatos).
2. WS-6 parte deste protótipo: mover para `src/escritores/docx_a.py`, trocar o `texto_do_evento` pelo uso de `relatorio.linha`, criar `modelos/docx_a/` e o `gerar` por clonagem do modelo.
3. WS-2 reaproveita `ler_estrutura` no leitor `docx_a`.
4. Calibrar os limiares de duplicata e de edição manual com textos reais no piloto M5.
