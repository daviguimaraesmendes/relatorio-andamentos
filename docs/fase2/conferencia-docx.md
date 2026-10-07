# Conferência do relatório em texto (`.docx`, modelo A): o que você precisa olhar à mão

O que foi testado aqui: `python-docx`, `lxml` e o LibreOffice, sempre com arquivos **fictícios**. O que **não** foi testado: o Word (Mac e Windows) e o Google Docs. Esta lista é para você fazer com uma exportação **real** do Google Doc de um cliente pequeno. Nada disso exige programar; os comandos estão prontos. Faça tudo numa **cópia** do arquivo (o programa nunca mexe no original, mas a cópia é a sua rede de segurança).

Tempo previsto: 30 a 40 minutos.

## Antes de começar

1. No Google Docs, abra o relatório de um cliente pequeno e use **Arquivo > Fazer download > Microsoft Word (.docx)**.
2. Guarde o arquivo numa pasta sua (fora do repositório; ele tem dados de cliente e **não** deve ir para o GitHub nem para a pasta do projeto).
3. Para ver o que o programa entendeu do arquivo:
   `python3 src/escritores/docx_a.py ler "caminho/do/relatorio.docx"`

## A. O programa entendeu o arquivo? (ordem de risco)

- [ ] **Data-base, cliente e quadro-resumo** aparecem na leitura? O número de processos lidos bate com o que você vê no documento?
- [ ] **Todos os campos de cada processo** foram lidos (assunto, autor, réu, ajuizamento, valor da causa, data de citação, juízo, área, matéria, andamentos)? Se algum campo vier vazio ou sumir, anote o **nome exato do rótulo** que está no documento (por exemplo, "Autor(es)" ou "Parte autora"): é o rótulo que o programa precisa conhecer.
- [ ] O título de cada processo tem **"[ MOMENTO ATUAL ]" entre colchetes**? E o momento com observação, tipo "(HONORÁRIOS SUSPENSOS)", aparece inteiro?
- [ ] Processos com **mais de um número** (agravo, apenso): a leitura mostra os números e o tipo certo?
- [ ] A frase **"Em DD/MM/AAAA, sem atualizações."** é exatamente essa? Se o escritório usa outra redação ("Sem novidades até ..."), o programa não a reconhece como fecho.
- [ ] No quadro-resumo, vários números do mesmo processo ficam em linhas separadas dentro da célula? (O programa grava assim.)

## B. O arquivo atualizado abre bem?

Enquanto o painel não estiver ligado ao escritor, use o **ciclo de ensaio**, que trabalha numa cópia: ele troca a Data-Base, acrescenta uma frase de teste ("ENSAIO") nos dois primeiros processos, renova a frase de fecho nos demais e cria um processo de mentira no fim:
`python3 src/escritores/docx_a.py ensaio "relatorio.docx" "relatorio-ensaio.docx" 07/10/2026`
(troque a data pela de hoje). O comando lista o que fez e os avisos. Depois, no arquivo `relatorio-ensaio.docx`:

- [ ] **Word** abre sem a mensagem "o conteúdo está ilegível, deseja recuperar"? (Mac e, se possível, Windows.)
- [ ] As **datas novas estão em negrito**, com a mesma fonte e tamanho do texto ao redor, sem sublinhado nem marca-texto herdados?
- [ ] O **texto que você escreveu à mão** continua lá, igualzinho (inclusive anotações em destaque)?
- [ ] Os dois primeiros processos (com a frase de teste) terminam na frase nova, sem "sem atualizações"? Os demais terminam em "Em [data-base], sem atualizações."? O processo de mentira no fim (número 0000000-00...) tem o mesmo aspecto dos outros?
- [ ] **Momento atual** igual no quadro-resumo e no título do bloco? **Último andamento** do quadro-resumo é a data certa?
- [ ] **Cabeçalho, rodapé, logotipo e imagens** continuam iguais?
- [ ] Compare o **PDF antes e depois**, lado a lado: algum bloco ficou partido entre duas páginas de um jeito feio?

## C. A ida e volta com o Google (a mais importante)

- [ ] Envie o arquivo **atualizado** (o do ensaio) para o Google Drive e abra como Google Doc. Larguras de coluna, células mescladas, linhas em branco entre as tabelas e negrito estão iguais?
- [ ] **Exporte de novo** para `.docx` e rode um **segundo ensaio** em cima desse arquivo (com uma data-base mais nova). A frase de teste do primeiro ensaio continua lá uma vez só e a nova entra depois (nada repetido)?
- [ ] Rode o **mesmo** ensaio (mesma data) **duas vezes seguidas**, a segunda sobre o arquivo gerado pela primeira: o resultado é igual (nada duplica, nenhum fecho aparece de novo nos processos que receberam a frase de teste)?

## D. Casos especiais

- [ ] **Processo novo** (que não estava no relatório): o bloco novo tem o mesmo aspecto dos outros? A linha nova do quadro-resumo entrou no fim da lista; o escritório prefere outra ordem (por número, por momento)?
- [ ] **Comentário e sugestão** do Google Docs: crie um comentário e uma sugestão no texto de andamentos de um processo e rode a atualização. O programa avisou ("controle de alterações/comentário") e **nada foi apagado**? (As edições do programa não aparecem como "sugestão": isso não é possível hoje.)
- [ ] **Você mexeu à mão** no momento atual, no último andamento ou na data da frase de fecho e rodou de novo: o programa trocou pelo valor dele **e avisou** ("edição manual sobrescrita")? Esses quatro campos (data-base, momento atual, último andamento, data do fecho) são os únicos que o programa reescreve; todo o resto do texto só recebe acréscimos.
- [ ] **Andamentos escritos de outro jeito** no histórico antigo ("No dia 18/06...", "Em 18/06", "18 de junho de 2026"): o programa reconhece estas formas. Mas formas como "18.06.2026" ou "dia 18" ele **não vê**, e pode repetir um andamento igual. Quantos há no seu histórico real? Se forem muitos, avise.
- [ ] **Texto de andamento que você acha repetido e o programa não repetiu** (ou o contrário): a regra de "já consta" é uma estimativa (parecido o bastante na mesma data). Se errar demais, os limites (`limiar_duplicata`, `limiar_parecido`) podem ser ajustados; anote os exemplos.

## E. O modelo de relatório novo (gerar do zero)

Os dois modelos prontos ficam em `src/modelos/docx_a/` (`modelo_a.docx` e `modelo_compacto.docx`). Gere um relatório **inicial** com cada um:

- [ ] Abre no Word e no Google Docs sem aviso? A aparência agrada? (O estilo "compacto" cabe mais processos por página.)
- [ ] O escritório quer logotipo, outra fonte ou outras cores? Pode editar o modelo no Word (mantendo os rótulos, o título "PROCESSO Nº ... [ MOMENTO ]" e o quadro de 4 colunas); o programa passa a usar a sua versão.

## Se algo der errado

Anote: **o que você fez, o que esperava e o que aconteceu**, e guarde o arquivo de antes e o de depois (fora do repositório). O programa **não** apaga nada do texto que você escreveu, e o arquivo original nunca é sobrescrito; no pior caso, descarte o arquivo gerado e use o original.

## Decisões que dependem de você

1. **Frase de fecho**: o padrão agora é só aparecer quando o processo **não** teve andamento novo (igual à planilha e ao modelo de referência). Se o escritório quiser a frase também depois da novidade, é uma opção (`fecho_apos_novidade`).
2. **Ordem do processo novo** no quadro-resumo e no documento (hoje: no fim).
3. **Estilo do texto no perfil** (`estilo_texto`): assumi `a` = layout do modelo de referência e `b` = "compacto". Confirme.
