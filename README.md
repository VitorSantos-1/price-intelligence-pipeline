# 🛒 Price Intelligence Pipeline — Inteligência de Preços da Concorrência

Pipeline em **Python assíncrono** que coleta preços de vários supermercados concorrentes,
consolida os resultados e gera um **resumo comparativo automático usando IA** (múltiplos provedores de LLM).
Evoluído por várias versões até o app desktop **Falcons Data**, com **interface gráfica** e empacotamento em executável.

> ⚠️ **Aviso sobre os dados**
> Todos os dados presentes neste repositório (planilhas, seeds, exemplos) são **fictícios** e foram
> **gerados aleatoriamente apenas para demonstração**. Os dados reais da operação em que o projeto
> foi utilizado são **confidenciais e estão protegidos** — nenhum dado real, credencial ou informação
> de terceiros foi incluído aqui.

## 🎯 O que faz
- Coleta preços de **+11 redes concorrentes** via APIs de catálogo (VTEX), seletores CSS por loja
  e **navegação completa por categoria** (paginação até o fim, sem limite artificial de páginas).
- Executa as buscas de forma **assíncrona** (`asyncio`) para paralelizar as consultas.
- **Auto-aprendizado de seletores:** quando um layout muda, o pipeline aprende o novo seletor CSS e o
  guarda em um `selectors.json` (cache gerado em tempo de execução, fora do repositório).
- **Monitor de preços:** watchlist de produtos com histórico persistido em **SQLite** para acompanhar variação.
- **Sites customizados:** o próprio usuário cadastra novas lojas (URL de busca) para entrarem na coleta.
- **Casamento por catálogo:** compara um catálogo próprio (CSV) com os produtos das redes, casando por
  **EAN** e por similaridade de nome, com **confirmação por IA** quando o match é ambíguo.
- Envia os resultados para **4 provedores de LLM** (Gemini, Groq/Llama, GPT-4o-mini via OpenRouter e HuggingFace)
  e gera um resumo curto: loja mais barata, diferença %, ofertas.
- Exporta os resultados em **CSV** e registra tudo em **logs estruturados**.
- Possui **GUI** (`app_gui.py` — app desktop *Falcons Data*) e script de empacotamento em `.exe` (`gerar_executavel.py`).

## 🏗️ Arquitetura
```
Entrada (lista de produtos)
      │
      ▼
Coleta assíncrona ──► APIs de catálogo (VTEX) + seletores CSS (auto-aprendizado)
      │
      ▼
Normalização (produto, loja, preço, oferta)
      │
      ├──► Exportação CSV (resultados_csv/)
      ├──► Resumo por IA (Gemini / Groq / OpenRouter / HuggingFace)
      └──► Banco relacional (sql/schema.sql): dim_produto · dim_loja · fato_preco
```

## 🗄️ Banco de dados
O arquivo [`sql/schema.sql`](sql/schema.sql) traz um **modelo relacional normalizado (3FN)** que representa a
saída do pipeline — permite carregar os CSVs de `resultados_csv/` em um banco para análise histórica:
- `dim_produto` (nome, EAN validado) · `dim_loja` (própria/concorrente) · `fato_preco` (grão: produto × loja × dia).
- View `vw_comparativo_precos`: para cada produto/dia, calcula o **menor preço do dia** entre as lojas.

## 🧑‍💻 Stack
`Python` · `asyncio` · `Web Scraping` · `APIs REST/JSON` · `LLM/IA` · `SQL/Modelagem (3FN)` · `Tkinter (GUI)` · `PyInstaller` · `logging`

## ▶️ Como rodar
```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env      # preencha suas chaves de API
python pesquisa_preco_v4.py
```
Interface gráfica: `python app_gui.py`

## 📁 Estrutura
```
pesquisa_preco_v4.py      # pipeline principal (assíncrono)
app_gui.py                # interface gráfica
gerar_executavel.py       # empacotamento em .exe
sql/schema.sql            # modelo relacional (3FN) da saída do pipeline
resultados_csv/           # saídas (exemplo fictício incluído)
.env.example              # modelo de variáveis de ambiente
```
> `selectors.json` e o banco local **não** são versionados: o primeiro é um cache gerado em runtime; o segundo
> é criado a partir de `sql/schema.sql` no seu ambiente.

---

### 🧰 Competências demonstradas
`Python assíncrono` · `Integração com múltiplos LLMs` · `Web Scraping` · `ETL` · `Modelagem de dados (3FN)` · `Empacotamento de aplicações`

### 👤 Autor
**José Vitor Santos Pinheiro** — Analista de Dados / BI / Ciência de Dados
· vytorsantt@gmail.com
