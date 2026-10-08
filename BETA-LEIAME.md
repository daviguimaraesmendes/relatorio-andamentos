# Relatório de Andamentos — versão 2.0.0-beta2

Esta é a primeira versão de teste da **Fase 2**. Ela acrescenta, ao que você já usa, a montagem e a atualização de relatórios completos (texto, planilha e dashboard). O acesso ao jus.br e aos TRTs é o mesmo que já funciona; a aba **Atualizar** da versão anterior continua no painel, como plano B.

## 0. Novo no beta2: clientes em lote

Importar um relatório de dezenas de processos não pede mais o cliente processo a processo.
- Na **conferência da importação** há o bloco **"Quem é o cliente?"**: o programa lista as partes que mais se repetem (a empresa, ou várias empresas do mesmo grupo, já agrupando as grafias) e deixa **marcado** o candidato óbvio. Um clique em "Confirmar" define, em todos os processos, o **cliente**, o **polo** (autor ou réu) e a **parte contrária**. Há também um campo de **cliente padrão** para o que sobrar.
- Em **Clientes e processos**, quando houver processos sem cliente, aparecem dois botões: **"Identificar os clientes pelas partes dos processos"** (usa os clientes que você cadastrou, com as variações de nome) e **"Aplicar a todos os sem cliente"**.
- Correção: o cliente, o polo e a parte contrária editados à mão em **Clientes e processos** agora valem para os relatórios novos (antes, a edição podia ficar escondida atrás do valor importado).

## 1. O que há de novo

Na aba **Assistente**, quatro caminhos:

1. **Importar relatórios existentes**: você arrasta o relatório em texto (`.docx`) e/ou a planilha (`.xlsx`), ou uma lista de números de processo. O programa mostra o que entendeu (processos, vinculados, números inválidos, duplicados) e, se você confirmar, cria o relatório sem recoletar o histórico que já está escrito.
2. **Elaborar relatório inicial**: gera os três entregáveis (texto `.docx`, planilha `.xlsx` e dashboard `.html`), com profundidade rápida, padrão ou completa. Pode rodar na hora (com aviso de quanto deve demorar) ou nas horas que você escolher.
3. **Atualizar relatório**: você envia o `.docx` e/ou a planilha mais recente; o programa coleta só o que veio depois da data-base, leva à revisão e devolve arquivos novos (o `.html` se alimenta da planilha).
4. **Migrar de modelo**: converte um relatório que está em outro formato para os modelos do programa, mostrando antes o mapeamento das colunas e guardando em uma aba à parte o que não tem destino.

Também há: **Triagem** da revisão (aprovar em lote o que não tem alerta), **Pedidos** (kit para extrair os pedidos das iniciais com uma IA melhor), **IA** (escolha do motor e do consentimento por cliente), **Entregas** (baixar os arquivos e ver o que conferir) e **Perfil** do relatório.

## 2. Como instalar sobre a versão que você já tem (Mac)

Seus dados ficam na pasta `projetos/` e a sua configuração em `config.json`. O pacote **não** contém nenhum dos dois, então não há risco de sobrescrevê-los.

1. **Faça uma cópia de segurança** da pasta inteira do programa atual (botão direito → Duplicar). Isso é o seu caminho de volta.
2. Descompacte `relatorio-andamentos.zip` e copie o conteúdo **por cima** da pasta do programa, escolhendo "Substituir". (Se preferir, descompacte numa pasta nova e copie para ela a sua `projetos/` e o seu `config.json`.)
3. Dois cliques em **`Instalar (Mac).command`** e responda `s`. Ele reaproveita o que já está instalado e só acrescenta o que falta (por exemplo, a biblioteca de Word).
4. **Opcional, recomendado**: instale o LibreOffice. Com ele, as fórmulas da planilha saem já calculadas (sem ele, abrem calculadas no Excel, mas o dashboard embutido perde alguns indicadores).
5. Dois cliques em **`Abrir painel.command`**. No topo da tela deve aparecer "versão 2.0.0-beta1".

**DataJud (opcional)**: a fonte de capa do processo (vara, município, data de ajuizamento, classe) vem ligada, mas precisa da chave pública do CNJ, que está na página "Acesso" da wiki do DataJud. Cole-a em `config.json` (`fontes_externas` → `datajud` → `chave`) ou na variável `DATAJUD_CHAVE`. Sem a chave, o programa segue sem ela.

**Voltar à versão anterior**: feche o painel, apague a pasta nova e use a cópia de segurança.

## 3. Roteiro curto de teste (uns 40 minutos)

Use **um cliente pequeno** (10 a 20 processos) que já tenha relatório em texto e planilha. O roteiro completo, com o que anotar, está em `docs/fase2/piloto.md`. O mínimo:

1. **Assistente → Importar**: arraste o `.docx` e a `.xlsx` do cliente. Veja se a conferência bate com o que você sabe do relatório.
2. **Assistente → Atualizar**: envie os mesmos arquivos, modo **imediato**, e leia o aviso de duração. Revise pela **Triagem**.
3. **Entregas**: baixe os arquivos e abra o `.docx` no Word (ou no Google Docs), a planilha no Excel (ou no Google Planilhas) e o `.html` no navegador. Siga as listas `docs/fase2/conferencia-docx.md` e `docs/fase2/conferencia-xlsx.md`.
4. Confira se **nada sumiu, nada duplicou e o que você escreveu à mão continua lá**.
5. Anote o tempo por processo e tudo que parecer estranho.

## 4. O que ainda não foi testado com casos reais (é para isso que serve o beta)

- A coleta pela **fila** (a aba Atualizar antiga continua sendo o caminho já validado).
- Os arquivos gerados no Word, no Excel e no Google; a leitura de relatórios reais exportados do Google Docs.
- A qualidade do momento atual, do último andamento e das sugestões de julgamento com texto real.
- A IA externa (Claude ou outro serviço) e o prompt dos pedidos das iniciais.
- Windows.

## 5. Como me mandar o resultado do teste

Preencha a planilha de registro de `docs/fase2/piloto.md` e envie **sem nomes de cliente nem números de processo** (use "Cliente A", "Proc 07"). Prints de tela de erro: tape nomes e números. Quando algo falhar, anote a tela, o que você clicou e a mensagem exata.

**Segurança**: nada de cliente sai do seu computador, a menos que você ligue IA externa para aquele cliente na aba IA. Mantenha o disco criptografado (FileVault) e nunca envie a pasta `projetos/`.
