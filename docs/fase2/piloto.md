# Roteiro do piloto (no seu Mac)

Objetivo: provar, com casos reais e em ordem, que o programa monta e atualiza relatórios completos. O acesso ao jus.br e aos TRTs já foi validado por você; aqui o foco é o que o programa **produz**. Anote tudo na planilha de registro (fim deste arquivo). Dados reais ficam só no seu computador: **não envie a pasta `projetos/` a ninguém**.

## 0. Antes de começar

1. Instale a versão nova do programa e abra o painel (`Abrir painel.command`).
2. Em **Acesso e escritório**, confirme que o acesso continua "OK".
3. Escolha **um cliente pequeno** (10 a 20 processos) que já tenha relatório em texto e em planilha, para comparar com o que o programa gerar.
4. Se for usar o DataJud (uso não comercial, liberado): coloque a chave pública do CNJ em `config.json` (`fontes_externas` → `datajud` → `chave`) ou na variável `DATAJUD_CHAVE`. Sem a chave, o programa segue sem ele.
5. Exporte o relatório em texto do Google Docs como `.docx` e guarde a planilha mais recente (`.xlsx`).

## 1. Marco M5: um cliente pequeno

### 1.1 Importar relatórios existentes
- No painel: **Assistente → Importar relatórios existentes**. Arraste o `.docx` e o `.xlsx`.
- Confira a tela de conferência: quantos processos foram lidos, números inválidos, duplicados, vinculados, clientes sem nome padronizado, colunas sem destino.
- **Anote**: o que o programa entendeu errado (rótulos, momento atual, datas, valores). Isso calibra os leitores.

### 1.2 Atualizar de verdade
- **Assistente → Atualizar relatório**, com o `.docx` e o `.xlsx` enviados. Escolha o modo **imediato** (cliente pequeno) e leia o aviso de duração.
- Revise pela **Triagem**: aprove os verdes em lote, olhe os amarelos e vermelhos.
- Gere as entregas e abra:
  - o `.docx` no **Word** e no **Google Docs** (siga `conferencia-docx.md`);
  - a `.xlsx` no **Excel** e no **Google Planilhas** (siga `conferencia-xlsx.md`; se aparecer `#NOME?`, anote a célula);
  - o `.html` no navegador, sem internet, arrastando a planilha.
- Compare com o relatório anterior: nada sumiu, nada duplicou, o que você escreveu à mão continua lá.
- **Anote**: tempo por processo, quantos itens ficaram em "conferir manualmente", cobertura por tribunal.

### 1.3 Relatório inicial
- Com 3 a 5 processos novos do mesmo cliente: **Elaborar relatório inicial**, nas três profundidades (rápido, padrão, completo).
- **Anote**: qual profundidade entrega o suficiente; tempo de cada uma; se o momento atual e o resumo fazem sentido.

### 1.4 Migrar de modelo
- Pegue uma planilha de outro cliente, fora do padrão, e use **Migrar de modelo**. Confira a tela de mapeamento e a aba "Campos não migrados".

### 1.5 IA e pedidos das iniciais
- Teste o resumo com o modelo local. Se tiver um modelo maior, anote o nome e a diferença.
- Se for usar IA externa: cadastre o provedor em **IA**, marque o consentimento só para esse cliente e confira o selo e o registro de envios.
- **Pedidos das iniciais**: pegue 2 ou 3 petições, siga `docs/pedidos-iniciais.md` na IA que você escolher, cole o resultado e veja os achados do validador. O prompt é a versão 1.0.0 e **não foi validado com petição real**: anote o que a IA errou.

### 1.6 Sugestão de julgamento
- Nos processos que você já classificou à mão (probabilidade, resultado, valor estimado, economizado), veja a concordância com a sugestão do programa. Anote as divergências: elas calibram as regras.
- Lembrete: probabilidade é a do **resultado** (se somos autores, "provável" é vencer); economia só de encerrado e sem os casos com ressalva. Escreva em **Observações** os marcadores `[acordo pago por terceiro]` e `[exclusão da lide]`.

### Critério para seguir ao M6
- Os arquivos abrem sem aviso de reparo no Word, Excel e Google.
- Nenhum andamento duplicado e nenhum texto seu apagado.
- O momento atual e o último andamento batem em pelo menos 90% dos processos conferidos (ajuste esse número se preferir).
- O tempo por processo e a cobertura por tribunal são aceitáveis.

## 2. Marco M6: carteira grande (cerca de 200 processos)

1. Importe os relatórios dos clientes (ou a lista de números). Confira a tela de migração.
2. Use o modo **contínuo** (janela à noite) em lotes de um cliente por vez; deixe o computador ligado e o PJe Office aberto.
3. No dia seguinte: veja o resumo da fila (coletados, manuais, erros), resolva os captchas pendentes e revise pela Triagem.
4. Gere as entregas, leia o relatório de qualidade da base e o "o que mudou".
5. **Anote**: horas de coleta, falhas por tipo, se a retomada funcionou depois de interrupção, quanto tempo de revisão humana cada lote exigiu.

## 3. Planilha de registro (copie para uma planilha sua)

| Data | Etapa | Cliente | Processos | O que fiz | Tempo | O que deu errado | Arquivo/tela | Gravidade (1 a 3) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Mande-me essa planilha **sem nomes de cliente nem números de processo** (use códigos como "Cliente A", "Proc 07"). Com ela calibro leitores, vocabulário, limiares e regras sem precisar de dados reais.

## 4. Correções da segunda leitura

- Acrescentada a observação sobre dados reais ficarem só no computador.
- O critério de 90% foi tornado ajustável.
- Incluído o lembrete dos marcadores de ressalva antes da sugestão de julgamento.
