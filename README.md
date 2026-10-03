# Relatório de Andamentos

Atualiza as planilhas mensais de relatório aos clientes a partir dos autos
eletrônicos. A ferramenta entra no jus.br e no PJe dos TRTs com o seu
certificado digital, encontra os andamentos e documentos novos de cada
processo (inclusive os que ainda não saíram no Diário), tira print, resume o
teor com uma inteligência artificial que roda **no seu próprio computador** e
deixa tudo numa fila de revisão. Só o que você aprova entra na planilha.

Nenhum documento de cliente é enviado para a internet. A senha do certificado
e o segredo do autenticador ficam no cofre do próprio sistema operacional.

Cada relatório (um grupo de clientes ou um cliente só) é independente e tem a
sua aba no painel.

---

## 1. O que você precisa ter antes

| Item | Observação |
| --- | --- |
| Mac (macOS) ou Windows 10/11 | No Mac, a ferramenta foi testada em uso real. No Windows, a instalação e o login estão preparados, **mas ainda não foram testados** (veja a seção 9). |
| Certificado digital A1 instalado no **PJe Office Pro** | O mesmo que você usa para peticionar. O PJe Office precisa estar aberto quando a ferramenta for ao jus.br. |
| Autenticador do jus.br configurado no celular | E o **segredo** dele (veja abaixo). É o que permite à ferramenta gerar o código de 6 dígitos sozinha. |
| Cerca de 6 GB livres e internet na instalação | Para o modelo de IA (2 a 3,5 GB) e o navegador de automação. |

### Como obter o segredo do autenticador

O segredo é o código de letras e números (16 a 32 caracteres) que o jus.br
mostra quando você cadastra um aplicativo autenticador. Na tela de cadastro
com o QR Code, a opção **"Não foi possível ler o QR Code?"** exibe esse código
em texto.

- Se você ainda vai cadastrar o autenticador: copie esse código antes de
  concluir o cadastro e use o mesmo código no app do celular e na ferramenta.
- Se o autenticador já está cadastrado e você não tem o código: refaça o
  cadastro do autenticador na sua conta e, desta vez, copie o código.

Trate esse código como uma senha: quem o tiver gera os seus códigos de acesso.
A ferramenta o guarda no cofre do sistema e nunca o mostra de volta.

## 2. Instalação no Mac

1. Descompacte o arquivo `relatorio-andamentos.zip` (por exemplo, em Documentos).
2. Dois cliques em **`Instalar (Mac).command`**.
   - Se o Mac avisar que o arquivo é de um desenvolvedor não identificado:
     clique com o botão direito no arquivo, escolha **Abrir** e confirme.
3. Responda às perguntas na janela do Terminal (`s` para sim). O instalador
   pergunta antes de cada download: Homebrew (se faltar; pede a senha do Mac),
   Python, leitura de documentos digitalizados (OCR), o motor de IA (Ollama) e
   o modelo de IA. Para o uso completo, responda `s` a todas.
   - Nas perguntas do próprio Homebrew, responda `y` (ele não aceita `s`).
4. No fim, o painel abre no navegador. Siga para a seção 4.

## 3. Instalação no Windows

1. Descompacte o arquivo `relatorio-andamentos.zip` (por exemplo, em Documentos).
2. Dois cliques em **`Instalar (Windows).bat`**.
   - Se o Windows mostrar "O Windows protegeu o computador": clique em
     **Mais informações** e depois em **Executar assim mesmo**.
3. Responda às perguntas (`s` para sim). O instalador usa o `winget` (que já
   vem no Windows 10/11) para instalar o Python e o Ollama, se faltarem, e
   baixa o modelo de IA.
4. No fim, o painel abre no navegador. Siga para a seção 4.

No Windows, documentos digitalizados (imagem, sem texto) não são lidos
automaticamente: entram na revisão com alerta, para leitura no próprio PDF.

## 4. Primeiro uso (cerca de 10 minutos)

O painel fica em **http://127.0.0.1:5072**. Para abri-lo de novo depois: dois
cliques em **`Abrir painel.command`** (Mac) ou **`Abrir painel.bat`**
(Windows). Deixe a janela do Terminal (Mac) ou do Prompt (Windows) aberta
enquanto usa o painel.

1. **Acesso e escritório** (link no canto superior direito):
   - senha (PIN) do certificado, a mesma que você digita no PJe Office;
   - segredo do autenticador. Depois de salvar, o painel mostra o código de 6
     dígitos daquele momento: confira se é igual ao do app no celular;
   - quem assina pelo escritório: um por linha, o nome completo e o número da
     OAB (ex.: `Fulano de Tal` e `12.345`). É assim que a ferramenta escreve
     "apresentamos" nas petições do escritório e "a parte contrária
     apresentou" nas demais;
   - clique em **Salvar** e depois em **Testar acesso** (com o PJe Office
     aberto). Deve aparecer "ACESSO OK".
2. **+ Novo relatório**: dê um nome (ex.: "Grupo Exemplo").
3. **Clientes e processos**:
   - cadastre os clientes com a razão social exatamente como aparece nos
     processos e, em "variações", siglas e nomes fantasia;
   - em "Importar processos", cole os números (de uma lista, de um e-mail) ou
     envie uma planilha, escolha o cliente e o polo, e importe. Números com
     erro de digitação são recusados e listados;
   - "Completar pelo DJEN" preenche a parte contrária dos processos que têm
     publicação.
4. **Configuração**: indique a planilha do último relatório enviado (o
   arquivo `.xlsx`) e a data dele.
5. **Atualizar**: na primeira vez, informe a data do último relatório; a
   ferramenta só traz o que veio depois dela. O navegador trabalha minimizado
   no canto da tela; acompanhe pelo painel.
6. **Revisar**: confira cada linha com o print, o documento e o trecho em que
   o resumo se baseia. Aprove, corrija ou descarte.
7. **Planilha**: gere a planilha do mês. Ela é uma cópia da anterior com os
   andamentos aprovados acrescentados na coluna **Andamentos** da aba
   **Processos**; gráficos, tabelas dinâmicas e demais abas ficam iguais. A
   planilha nova vira a referência do mês seguinte.

## 5. Dia a dia

| Quando | O que fazer |
| --- | --- |
| Para atualizar um relatório | Abrir o painel, escolher a aba do relatório, **Atualizar**, depois **Revisar**. |
| No fechamento do mês | **Planilha**: gerar e conferir antes de enviar ao cliente. |
| Uma vez por semana (opcional) | **Atualizar > Conferência**: separa, por responsável, o que entrou nos autos e ainda não foi para relatório, com PDFs e prints. |
| Processo novo do cliente | **Clientes e processos**: importar o número, ou "Descoberta no DJEN" para achar os que ficaram de fora. |

Nada roda sozinho: a ferramenta só trabalha quando alguém clica.

### Justiça do Trabalho (TRTs)

Processos trabalhistas (com `.5.` no número) são lidos na consulta processual
do próprio TRT, depois do login no jus.br. **O TRT costuma pedir um captcha
(letras numa imagem) na primeira consulta**: a janela aparece na frente, toca
um aviso e espera você digitar. Depois disso, a ferramenta segue sozinha.

## 6. Como a ferramenta escreve

Exemplos de linhas geradas, no estilo das planilhas do escritório:

> Em 18/08/2026 foi proferido despacho determinando que o processo volte a tramitar normalmente, após a suspensão anterior. Audiência: 06/10/2026 11:40.
>
> Em 17/08/2026 foi cancelada a audiência una de 28/10/2026 09:15.

- **Quem fez e o quê** sai por regra fixa: tradução dos andamentos
  (`movimentos.json`) e autoria pela assinatura do documento.
- **O conteúdo** é resumido pela IA local, do ponto de vista do cliente (ela
  sabe quem é o cliente, o polo e a parte contrária) e precisa citar o trecho
  do documento em que se baseou.
- **Ruído descartado automaticamente**, com o motivo visível na ferramenta: a
  mesma informação repetida no mesmo dia ou em dias seguidos, documento
  repetido, andamento que só anuncia uma decisão já resumida, intimações e
  certidões de rotina.
- Processo com recurso: o 1º e o 2º grau são lidos, e o texto diz "no 2º grau"
  quando o andamento é do recurso.

### Alertas na revisão (por regra, não pela IA)

| Alerta | Quando |
| --- | --- |
| Trecho não encontrado | O trecho que a IA citou não existe no documento. |
| Prazo ou data | Número informado pela IA que não aparece no documento. |
| Data de audiência | A data informada não aparece junto da palavra "audiência" (ou é a data da certidão ou da assinatura). |
| Desfavorável | A IA classificou o resultado como desfavorável ao cliente: avalie contato pessoal antes de enviar. |
| Nome ausente | O nome do cliente não aparece no documento. |
| Polo não informado | Sem o polo, o ponto de vista do resumo não é confiável. |
| Texto do print | O documento não baixou; o resumo saiu da parte visível na tela. |
| Autoria não identificada | Petição sem assinatura reconhecível. |
| Andamento sem tradução | Texto de andamento ainda não cadastrado em `movimentos.json`. |

**A revisão humana é obrigatória.** O modelo de IA é pequeno (roda no
notebook) e às vezes erra o sentido do documento; o trecho de origem fica logo
abaixo de cada resumo para a conferência.

## 7. Segurança

- **Só leitura.** A ferramenta lê, tira print e baixa. Nenhum clique de
  protocolo, assinatura ou peticionamento.
- **Segredos no cofre do sistema** (Keychain no Mac, Gerenciador de
  Credenciais no Windows). Não ficam em arquivo, não aparecem em tela nem em
  registro de diagnóstico.
- **Dados de clientes ficam no computador**, na pasta `projetos/`. Mantenha a
  criptografia do disco ligada (FileVault no Mac, BitLocker no Windows) e
  **nunca envie a pasta `projetos/`** a outra pessoa.
- **IA local.** O resumo é feito pelo Ollama no próprio computador; nada é
  enviado a serviço de IA externo.
- **Painel só local.** Atende apenas em 127.0.0.1 (este computador), com token
  nos formulários.
- **O que vai para a internet:** o login no jus.br e nos TRTs, as consultas aos
  autos e, se você usar "Descoberta no DJEN", o nome do cliente para a busca
  pública do CNJ.
- **Captcha e telas desconhecidas** param a tarefa e pedem ação humana; nada é
  contornado.
- **Termos de uso.** O gov.br e o jus.br proíbem acesso automatizado nos seus
  Termos de Uso. O uso desta ferramenta é um risco assumido por quem a usa, em
  ritmo humano (pausas entre processos, um processo por vez).

## 8. Problemas comuns

| Situação | O que fazer |
| --- | --- |
| "Testar acesso" não conclui | Confira se o PJe Office está aberto e com o certificado. Se aparecer uma janela pedindo ação (captcha, confirmação), conclua nela. |
| O código do painel é diferente do celular | O segredo foi digitado errado ou é de outro cadastro: salve de novo em **Acesso e escritório**. |
| O navegador diz que não consegue acessar 127.0.0.1:5072 | O painel não está aberto: dois cliques em `Abrir painel`. |
| "Processo em segredo de justiça" (TRT) | A consulta processual não mostra esses autos; o processo fica como "conferir manualmente". |
| "Processo não encontrado na consulta do jus.br" | Confira o número; se estiver certo, o processo fica para conferência manual. |
| Mac: "desenvolvedor não identificado" | Botão direito no arquivo > **Abrir** > confirmar. |
| Windows: o login para no diálogo do PJe Office | No Windows o preenchimento automático desse diálogo ainda não foi testado. Digite a senha na janela do PJe Office; a ferramenta segue depois. Avise quem mantém a ferramenta. |

## 9. Para quem mantém

| Parte | Situação (03/10/2026) |
| --- | --- |
| Mac: instalação, login (certificado + autenticador), jus.br, TRT7, resumo, revisão, planilha | Testado em uso real |
| Windows: instalador (`instalar.ps1`), preenchimento do diálogo do PJe Office (pywinauto), atalhos `.bat` | Escrito, **não testado** em máquina Windows |
| OCR de documentos digitalizados | Mac com Homebrew; no Windows, não |
| Conferência semanal | jus.br; TRT ainda não (fica "conferir manualmente") |

```
relatorio-andamentos/
├── Instalar (Mac).command / Instalar (Windows).bat   instalação
├── Abrir painel.command / Abrir painel.bat           painel
├── instalar.sh / instalar.ps1                        o que os instaladores rodam
├── rodar.sh / conferir.sh                            o mesmo que os botões, pelo Terminal do Mac
├── empacotar.sh                                      gera o .zip sem dados de clientes
├── config.json                                       porta, modelo de IA, quem assina (preenchido pelo painel)
├── movimentos.json                                   tradução dos andamentos (editável)
├── src/                                              código (Python)
├── tests/                                            testes automáticos (não tocam em dados reais)
└── projetos/<relatório>/                             dados de cada relatório (fica fora do pacote)
```

Pelo terminal, de dentro de `src/`, com o Python do ambiente
(`../.venv/bin/python` no Mac, `..\.venv\Scripts\python.exe` no Windows):

```
python rodar.py --projeto <pasta> [--desde DD/MM/AAAA] [--processo N1,N2]   atualizar
python conferencia.py --projeto <pasta> [--dias 7]                         conferência
python coletor.py --testar-login                                           testar acesso
python coletor.py --explorar <número>        diagnóstico da tela dos autos (jus.br)
python trt.py --explorar <número>            diagnóstico da consulta do TRT
```

Testes: `.venv/bin/python -m unittest tests/test_pipeline.py tests/test_autos.py -v`

Para gerar o pacote: `./empacotar.sh` (recusa o pacote se encontrar nome de
cliente cadastrado ou número de processo real).
