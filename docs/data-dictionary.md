# Dicionario de Dados

## Fonte: ` ATESTADOS GERAL` / `Tabela324`

| Campo original | Campo JSON | Tipo | Regra |
| --- | --- | --- | --- |
| Chapa | chapa | texto | Sempre tratado como texto, pois pode ser numerico ou alfanumerico. |
| Nome | nome | texto | Nome do colaborador conforme informado no Excel. |
| Funcao | funcao | texto | Funcao operacional. Atualmente `Motorista` ou `Cobrador`. |
| Periodo | periodo | texto | Periodo original do atestado. O asterisco indica quebra entre meses. |
| Data Inicial | dataInicial | data ISO | Data inicial normalizada para `YYYY-MM-DD`. |
| Data Final | dataFinal | data ISO | Data final normalizada para `YYYY-MM-DD`. |
| Total no mes | totalNoMes | numero | Dias considerados dentro do mes. |
| Ano | ano | numero | Convertido do numero serial do Excel para ano calendario. |
| Atestados | atestados | numero | Valor 1/0 usado para evitar dupla contagem em atestados quebrados entre meses. O Excel original pode trazer este cabecalho com espaco inicial. |
| Mes | mes | texto | Mes em portugues calculado pela planilha. |
| Medico | medico | texto | Profissional informado no atestado. |
| Capitulo CID | capituloCid | texto | Capitulo CID conforme planilha. |
| Subcategoria do CID | subcategoriaCid | texto | CID/subcategoria conforme planilha. |

Campos adicionados pelo importador:

| Campo JSON | Tipo | Regra |
| --- | --- | --- |
| origem | texto | `operacao`. |
| origemLabel | texto | `Operação`. |
| sourceSheet | texto | Aba de origem do registro. |
| dataRecebimento | data ISO | Vazio nesta fonte. |
| crmMedico | texto | Vazio nesta fonte. |
| afastamentoInss | texto | Vazio nesta fonte. |
| tipoDuracao | texto | `dias`. |

## Fonte: `Planilha Monitoramento dos Atestados Médicos .xlsx` / abas mensais de 2025 e 2026

Esta fonte nao possui tabelas formais do Excel. O importador identifica as abas mensais pelo cabecalho na linha 2 e importa somente o historico de 2025 e 2026. Motoristas e cobradores desta planilha sao ignorados, pois a fonte oficial dessas funcoes e a planilha `ATESTADOS OPERAÇÃO 2026 cópia.xlsx`. O ano/mes usado nos filtros da Empresa vem da aba mensal, para evitar que datas digitadas incorretamente no historico poluam os indicadores.

| Campo original | Campo JSON | Tipo | Regra |
| --- | --- | --- | --- |
| Data recebimento do atestado | dataRecebimento | data ISO | Data em que o atestado foi recebido. Se estiver fora do intervalo esperado, o mes/ano da aba e usado para filtros. |
| Chapa | chapa | texto | Sempre tratado como texto. |
| NOME | nome | texto | Nome do colaborador conforme informado no Excel. |
| FUNÇÃO | funcao | texto | Funcao do colaborador. |
| DATA DO INÍCIO DO AFASTAMENTO | periodo, dataInicial, dataFinal | texto/data ISO | Pode vir como data serial ou intervalo textual. Erros como ano `20023` sao normalizados para `2023`. |
| DIAS DE AFASTAMENTO | totalNoMes, diasAfastamentoOriginal, tipoDuracao | numero/texto | Numeros viram dias; `HORAS` vira `tipoDuracao = horas` e `totalNoMes = 0`; outros valores ficam como `indefinido`. |
| MEDICO | medico | texto | Profissional ou unidade informada no atestado. |
| CRM Médico | crmMedico | texto | CRM conforme planilha. |
| Afastamento INSS (Sim /Não) | afastamentoInss | texto | Indicador original da planilha. |
| CID/DESCRIÇÃO | subcategoriaCid, capituloCid | texto | A descricao original e preservada; o capitulo CID e inferido pelo codigo quando possivel. |
| OBSERVAÇÃO DOS GESTORES | observacaoGestores | texto | Observacao original. |
| OBSERVAÇÃO/TRATATIVA SEGURANÇA DO TRABALHO | tratativaSeguranca | texto | Tratativa original. |
| TRATATIVAS DIRETORIA | tratativaDiretoria | texto | Tratativa original. |
| TRATATIVA JONILTON | tratativaJonilton | texto | Tratativa original. |

## Fonte: `AFASTADOS` / `Tabela328`

| Campo original | Campo JSON | Tipo | Regra |
| --- | --- | --- | --- |
| Colaboradores | colaborador | texto | Nome + chapa conforme Excel. |
| Chapa | chapa | texto | Sempre tratado como texto. |
| Funcao | funcao | texto | Funcao operacional. |
| Periodo | periodo | texto | Periodo original do afastamento. |
| Total | total | numero | Total de dias do afastamento. |
| Mes | mes | texto | Mes de referencia. |
| Medico | medico | texto | Profissional informado. |
| Capitulo CID | capituloCid | texto | Capitulo CID conforme planilha. |
| Subcategoria CID | subcategoriaCid | texto | CID/subcategoria conforme planilha. |

## Indicadores principais

- `dias`: soma de `totalNoMes` nos atestados ou `total` nos afastados.
- `atestados`: soma do campo `atestados`, nao contagem direta de linhas.
- `registros`: quantidade de linhas importadas.
- `chapasUnicas`: quantidade de chapas distintas.
- `colaboradoresUnicos`: quantidade de nomes/colaboradores distintos.

## Observacoes de qualidade

- A linha total da `Tabela324` e excluida dos registros e usada apenas para validacao.
- A visao `Consolidado` combina Operacao e Empresa. Motoristas e cobradores ficam exclusivamente na Operacao; a remocao de sobreposicoes por `chapa + dataInicial + dataFinal` permanece como protecao adicional.
- Linhas da planilha geral com `HORAS` sao contadas como atestado, mas nao somam dias de afastamento.
- Alguns capitulos CID aparecem com grafias diferentes; por enquanto o dashboard preserva o texto original.
- Dados medicos e CID sao sensiveis. A versao final deve ter autenticacao, autorizacao e trilha de auditoria.
