# 🛒 Price Intelligence Pipeline — Inteligência de Preços da Concorrência

Pipeline em **Python assíncrono** que coleta preços de vários supermercados concorrentes,
consolida os resultados e gera um **resumo comparativo automático usando IA** (múltiplos provedores de LLM).
Evoluído por 4 versões, com **interface gráfica** e empacotamento em executável.

> ⚠️ **Aviso sobre os dados**
> Todos os dados presentes neste repositório (planilhas, seeds, exemplos) são **fictícios** e foram
> **gerados aleatoriamente apenas para demonstração**. Os dados reais da operação em que o projeto
> foi utilizado são **confidenciais e estão protegidos** — nenhum dado real, credencial ou informação
> de terceiros foi incluído aqui.

## 🎯 O que faz
- Coleta preços de **+8 redes concorrentes** via APIs de catálogo (VTEX) e seletores CSS configuráveis por loja (`selectors.json`).
- Executa as buscas de forma **assíncrona** (`asyncio`) para paralelizar as consultas.
- Envia os resultados para **4 provedores de LLM** (Gemini, Groq/Llama, GPT-4o-mini via OpenRouter e HuggingFace) e gera um resumo curto: loja mais barata, diferença %, ofertas.
- Exporta os resultados em **CSV** e registra tudo em **logs estruturados**.
- Possui **GUI** (`app_gui.py`) e script de empacotamento em `.exe` (`gerar_executavel.py`).

## 🏗️ Arquitetura
```
Entrada (lista de produtos)
      │
      ▼
Coleta assíncrona ──► APIs de catálogo + seletores CSS (selectors.json)
      │
      ▼
Normalização (produto, loja, preço, oferta)
      │
      ├──► Exportação CSV (resultados_csv/)
      └──► Resumo por IA (Gemini / Groq / OpenRouter / HuggingFace)
```

## 🧑‍💻 Stack
`Python` · `asyncio` · `Web Scraping` · `APIs REST/JSON` · `LLM/IA` · `Tkinter (GUI)` · `PyInstaller` · `logging`

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
selectors.json            # seletores CSS por loja
resultados_csv/           # saídas (exemplo fictício incluído)
.env.example              # modelo de variáveis de ambiente
```

---

### 🧰 Competências demonstradas
`Python assíncrono` · `Integração com múltiplos LLMs` · `Web Scraping` · `ETL` · `Empacotamento de aplicações`

### 👤 Autor
**José Vitor Santos Pinheiro** — Analista de Dados / BI / Ciência de Dados
· vytorsantt@gmail.com
