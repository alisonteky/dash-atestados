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
- Alguns capitulos CID aparecem com grafias diferentes; por enquanto o dashboard preserva o texto original.
- Dados medicos e CID sao sensiveis. A versao final deve ter autenticacao, autorizacao e trilha de auditoria.
