# Pedidos das petições iniciais: passo a passo

Este guia mostra como pedir a uma IA (por exemplo, o Claude no navegador) que leia as petições iniciais e devolva os pedidos de cada processo, e como colar o resultado no programa. Não precisa saber programar.

> **Aviso de confidencialidade.** Quando você anexa uma petição numa IA que funciona na internet, o conteúdo dela (nomes das partes, números de processo, valores) **sai do seu computador** e passa a ser tratado pelo serviço dessa IA. Use somente uma IA que o escritório e o cliente autorizaram, de preferência uma conta com a opção de **não usar suas conversas para treinar o modelo**. O programa nunca envia nada sozinho: quem anexa e envia é você.

> **Situação do prompt.** O texto que o programa fornece (versão 1.0.0) foi escrito e testado **só com dados inventados**. A qualidade dele com petições reais ainda **não foi validada**; isso se confirma no piloto. Por isso o programa mostra tudo para você conferir antes de gravar, e você deve **conferir os valores contra a petição** nas primeiras vezes.

## O que o programa faz e o que a IA faz

| Quem | O quê |
| --- | --- |
| Programa | Separa os PDFs das iniciais e o texto do pedido (prompt), recebe a resposta, confere, mostra os problemas e só grava depois da sua confirmação |
| IA | Lê cada petição e escreve, para cada processo, o cadastro (partes, vara, valor da causa...) e a lista de pedidos com o valor que o reclamante atribuiu |
| Você | Escolhe os processos, anexa os PDFs na IA, cola a resposta de volta e confere os avisos |

## Passo a passo

### 1. Abra a tela "Pedidos"

No programa, abra a tela **Pedidos** (endereço `http://127.0.0.1:5072/pedidos`). Ela lista os processos do relatório, mostra quais já têm pedidos extraídos e quais têm a petição inicial localizada.

Se a inicial de um processo aparece como **"Inicial não localizada"**, coloque o PDF na pasta `iniciais` da pasta de dados do relatório (o caminho aparece na própria tela), com o **número do processo no nome** do arquivo. Depois recarregue a página.

### 2. Baixe o pacote

Deixe marcados os processos que você quer enviar (os que já têm pedidos vêm desmarcados) e clique em **Baixar pacote**. Se forem muitos, escolha **lotes** de 5 PDFs: a maioria das IAs aceita poucos anexos por conversa.

O arquivo `.zip` traz os PDFs (um por processo, com o número no nome), o `prompt.md` e um `LEIA-ME.txt`. Descompacte numa pasta.

### 3. Abra a IA e anexe os PDFs

Abra a IA autorizada (conversa nova). Anexe os PDFs **de um lote**. Se o arquivo for muito grande e a IA reclamar, envie menos arquivos por vez.

### 4. Cole o prompt e envie

Abra o `prompt.md` (pode ser no Bloco de Notas ou TextEdit), selecione tudo, copie e cole na conversa, junto com os anexos. Envie.

### 5. Copie a resposta

A IA deve responder **somente com um JSON** (um texto cheio de chaves e aspas). Copie a resposta **inteira**, do primeiro `{` ao último `}`. Se a resposta vier com texto antes ou depois, tudo bem, o programa tenta achar o JSON; mas se vier **cortada** no meio, escreva "continue" para a IA ou envie menos processos por vez.

### 6. Cole no programa e confira

Volte à tela **Pedidos**, cole no campo **"Cole aqui a resposta inteira da IA"** e clique em **Conferir**. Nada é gravado nesse momento. O programa mostra:

- **Erros** (em vermelho): o processo com erro **não será gravado**. Exemplos: número com dígito errado, processo que não está no relatório, processo repetido, valor que não é número, pedido "atribuído" sem valor.
- **Atenção** (em laranja): você decide. Exemplos: matéria que não existe no vocabulário (entra como "Outros", com sugestões das mais parecidas), soma dos pedidos diferente do valor da causa (o aviso diz os valores e a diferença), situação do valor incoerente, processo que já tinha pedidos (serão substituídos).
- **Observações**: informações de rotina.
- Para cada processo aceito: o cadastro lido, a lista de pedidos e os **achados da IA** (valor da causa estranho, página ilegível, pedido ambíguo...). **Leia os achados**: são o que a IA não teve certeza.

Se houver erro, volte à IA, explique o problema e peça para refazer só aquele processo; cole de novo e confira.

### 7. Grave

Marque **"Li os achados e avisos acima e confirmo a gravação"** e clique em **Gravar**. O programa guarda os pedidos no arquivo `pedidos.json` do relatório.

Duas opções, desmarcadas por padrão:

- **Preencher também a ficha de cada processo**: copia o cadastro da inicial (reclamante, vara, município, UF, ajuizamento, valor da causa, empresas) para a ficha, **só onde estiver vazio**, marcando como confirmado por você. A tela mostra antes uma tabela "hoje x na inicial".
- **Substituir também os valores diferentes que já estão na ficha**: só use se tiver certeza de que a inicial está certa e a ficha está errada.

### 8. Planilha

O botão **Baixar planilha dos pedidos já gravados** gera um `.xlsx` novo com as abas Cadastro, Pedidos, Resumo e Parâmetros por matéria. Essa planilha é provisória: a gravação nas abas da planilha de pedidos já existente do cliente ainda será ligada ao escritor de planilhas.

## Como as regras de leitura funcionam

- **Valor atribuído** é exatamente o que o reclamante colocou na petição; o programa e a IA não corrigem nem somam por conta própria.
- **Reflexos** ficam agrupados na matéria principal (horas extras e reflexos é uma linha só).
- **Multas dos arts. 467 e 477 da CLT** são matéria própria.
- **Situação do valor**: "atribuído", "sem valor atribuído", "fora do valor da causa" ou "encargos embutidos na causa". Só os atribuídos entram na soma; os encargos embutidos são somados à parte porque fazem parte do valor da causa.
- **Soma x valor da causa**: o programa avisa quando a diferença passa de R$ 1,00. Se o reclamante declarou outro critério (valor arbitrado, alçada), o aviso é só informativo.
- **Matéria**: só as do vocabulário do relatório. Fora dele, vai para "Outros" e a IA sugere o nome.

## Quando algo dá errado

| O que aconteceu | O que fazer |
| --- | --- |
| "O texto colado não é um JSON válido" | A resposta veio cortada ou misturada com conversa. Peça à IA: "responda de novo somente com o JSON, completo". |
| "Número do processo recusado" | A IA errou um dígito ou não achou o número. Confira no PDF e peça para corrigir. |
| "Este processo não está na carteira" | Você anexou o PDF de outro processo, ou o processo não está cadastrado no relatório. |
| Soma diferente do valor da causa | Abra a petição, veja a tabela de liquidação e confira. Pode ser erro da IA ou a própria petição estar inconsistente (a IA costuma registrar isso nos achados). |
| Matéria "fora do vocabulário" | O pedido foi para "Outros". Se for um tipo de pedido que aparece muito, peça ao responsável pelo programa para incluir a matéria no vocabulário. |
| Inicial "não localizada" | Coloque o PDF na pasta `iniciais` do relatório, com o número do processo no nome. |
| A IA não conseguiu ler uma página | Ela deve registrar um achado "página ilegível". Procure uma versão melhor do PDF e refaça aquele processo. |

## Observação sobre o envio direto

O botão **Enviar pelo provedor** aparece como "indisponível" até existir um provedor de IA externo cadastrado **e** autorizado (consentimento) para o relatório. Enquanto isso, o caminho é o do pacote e do "colar resultado".
