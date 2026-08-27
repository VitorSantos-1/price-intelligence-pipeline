# Price Intelligence Pipeline — Inteligencia de Precos da Concorrencia

Pipeline em Python assincrono que coleta, valida e compara os precos praticados por redes
varejistas concorrentes e entrega um resumo comparativo automatico — loja mais barata, diferenca
percentual e ofertas do dia — apoiado por multiplos modelos de linguagem (LLM). O projeto nasceu de
uma necessidade real de uma rede de supermercados e evoluiu ate um aplicativo desktop com interface
grafica e empacotamento em executavel, permitindo que o time comercial o utilize sem conhecimento
tecnico.

> **Nota de confidencialidade:** todos os dados presentes neste repositorio (planilhas, seeds,
> exemplos) sao ficticios, gerados aleatoriamente apenas para demonstracao. Os dados reais da
> operacao em que o projeto foi utilizado sao confidenciais e estao protegidos — nenhum dado real,
> credencial ou informacao de terceiros foi incluido aqui.

---

## Visao Geral

A solucao automatiza um trabalho que, feito a mao, consome horas e desatualiza no dia seguinte:
levantar o preco da concorrencia produto a produto. Ela coleta os precos de mais de uma dezena de
redes (via APIs de catalogo e navegacao por categoria), casa cada item com o catalogo proprio pelo
codigo de barras, persiste o historico em banco e gera um comparativo pronto para decisao. O
resultado deixa de ser uma planilha manual e passa a ser uma esteira repetivel de inteligencia de
precos.

## Contexto de Negocio

No varejo alimentar, o preco e uma das alavancas mais sensiveis de margem e de competitividade: uma
diferenca de poucos centavos em itens de alto giro muda a percepcao de "caro ou barato" da loja
inteira e desloca volume entre concorrentes. O problema e que a informacao de preco do mercado
envelhece rapido e esta espalhada em dezenas de sites e encartes. Quando a area de compras descobre
que ficou cara, a venda ja migrou; quando descobre que esta barata demais, a margem ja foi deixada
na mesa. Este pipeline ataca essa defasagem, transformando a coleta de precos em um processo
automatico e diario.

## O Problema que Resolve

- **Auditoria manual de precos** da concorrencia: lenta, cara e desatualizada assim que termina.
- **Falta de base para precificar:** decisoes de preco tomadas por percepcao, nao por posicao real
  de mercado.
- **Cobertura limitada:** acompanhar poucas lojas e poucos itens por falta de braco operacional.
- **Casamento de produtos nao confiavel:** comparar itens diferentes por nome parecido gera decisao
  errada.

## Publico e Decisoes Apoiadas

- **Compras e Comercial:** identificam onde estao caros ou baratos frente ao mercado e reagem antes
  de perder venda ou margem.
- **Precificacao:** ajusta preco com base em dado observado, priorizando itens de maior impacto.
- **Diretoria:** acompanha o posicionamento de preco da rede frente aos concorrentes ao longo do tempo.

## Impacto e Valor Gerado

- Substitui a auditoria manual de precos (de horas por semana para minutos de execucao).
- Da visibilidade diaria dos desvios de preco frente a concorrencia, protegendo a margem comercial.
- Amplia a cobertura de monitoramento (mais lojas e mais itens) sem aumentar o esforco humano.
- Reduz o risco de decisao errada ao validar o casamento de produtos por codigo de barras e IA.

---

## Arquitetura e Abordagem Tecnica

```text
Entrada (catalogo proprio + lista de produtos)
      |
      v
Coleta assincrona (asyncio)  -->  APIs de catalogo (VTEX) + seletores CSS por loja
      |                                   (auto-aprendizado de seletores)
      v
Normalizacao (produto, loja, preco, oferta)
      |
      +--> Casamento por EAN + similaridade de nome (confirmacao por IA quando ambiguo)
      +--> Exportacao CSV (resultados_csv/)
      +--> Resumo por IA (Gemini / Groq-Llama / OpenRouter / HuggingFace)
      +--> Banco relacional (sql/schema.sql): dim_produto - dim_loja - fato_preco
```

### Coleta e resiliencia
- **Execucao assincrona** (`asyncio`) para paralelizar consultas a varias redes e reduzir o tempo total.
- **Auto-aprendizado de seletores:** quando o layout de um site muda, o pipeline reaprende o seletor
  CSS e o guarda em um cache (`selectors.json`, gerado em runtime, fora do versionamento), reduzindo
  a manutencao manual tipica de scrapers.
- **Sites customizados:** o proprio usuario cadastra novas lojas (URL de busca) para entrarem na coleta.

### Qualidade do dado
- **Validacao de EAN/GTIN** por checksum GS1, evitando casar produtos diferentes.
- **Casamento por catalogo:** compara o catalogo proprio (CSV) com os itens das redes por EAN e por
  similaridade textual, com **confirmacao por IA** nos casos ambiguos.

### Inteligencia e entrega
- **Camada multi-LLM** (Gemini, Groq/Llama, GPT-4o-mini via OpenRouter e HuggingFace) que gera um
  resumo curto e acionavel: loja mais barata, diferenca percentual e ofertas.
- **Exportacao em CSV** e **logs estruturados** para rastreabilidade.
- **Aplicativo desktop** (`app_gui.py`) e script de empacotamento em `.exe` (`gerar_executavel.py`),
  permitindo uso pelo time de negocio sem ambiente de desenvolvimento.

### Modelagem de dados (banco relacional)
O arquivo `sql/schema.sql` traz um modelo relacional normalizado (3FN) que representa a saida do
pipeline e permite carregar os CSVs em um banco para analise historica:
- `dim_produto` (nome, EAN validado), `dim_loja` (propria/concorrente) e `fato_preco`
  (grao: produto x loja x dia).
- View `vw_comparativo_precos`: calcula, para cada produto e dia, o menor preco entre as lojas.

## Stack

Python - asyncio - Web Scraping - APIs REST/JSON - Integracao multi-LLM - SQL e modelagem (3FN) -
Interface grafica (Tkinter) - PyInstaller - logging.

## Como Rodar

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env      # preencha as chaves de API
python pesquisa_preco_v4.py
```

Interface grafica: `python app_gui.py`. O painel de resultados e apresentado em `index.html`.

## Estrutura do Projeto

```text
pesquisa_preco_v4.py   -> Pipeline principal (coleta assincrona, casamento, resumo por IA)
app_gui.py             -> Interface grafica (aplicativo desktop)
gerar_executavel.py    -> Empacotamento em .exe (PyInstaller)
index.html             -> Painel de apresentacao dos resultados
sql/schema.sql         -> Modelo relacional (3FN) da saida do pipeline
resultados_csv/        -> Saidas em CSV (exemplo ficticio incluido)
.env.example           -> Modelo de variaveis de ambiente (sem segredos)
```

> `selectors.json` e o banco local nao sao versionados: o primeiro e um cache gerado em runtime; o
> segundo e criado a partir de `sql/schema.sql` no seu ambiente.

## Autor

Jose Vitor Santos Pinheiro — Analise de Dados e Inteligencia Comercial (Varejo e Supply Chain).
Contato: vytorsantt@gmail.com
