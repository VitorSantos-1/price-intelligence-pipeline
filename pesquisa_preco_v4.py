import time
import re
import requests
import csv
import os
import json
import logging
import base64
import io
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import quote, quote_plus, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from colorama import Fore, Style, init
from tabulate import tabulate
from dotenv import load_dotenv
from openai import OpenAI
import pdfplumber
import tempfile
import urllib.request
import unicodedata
from difflib import SequenceMatcher


# ==========================================
# SAIDA SEGURA EM MODO --noconsole (PyInstaller)
# ==========================================
# Ao compilar com --noconsole, o PyInstaller define sys.stdout/sys.stderr como None.
# Como o motor usa print() em dezenas de pontos, o primeiro print() de qualquer
# raspagem lancava AttributeError, era engolido pelo except e a busca voltava vazia.
# Aqui garantimos um destino gravavel para stdout/stderr antes de qualquer print.
class _SaidaNula:
    def write(self, *_args, **_kwargs):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = _SaidaNula()
if sys.stderr is None:
    sys.stderr = _SaidaNula()

init(autoreset=True)

# ==========================================
# CONFIGURAÇÃO DE AMBIENTE & PLAYWRIGHT BROWSERS
# ==========================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "PesquisaPreco_v4")
os.makedirs(_USER_DATA_DIR, exist_ok=True)

def _resolver_ms_playwright() -> str:
    """
    Descobre onde estao os navegadores do Playwright.
    No .exe empacotado prioriza a copia embutida ao lado do app; caso contrario
    usa a pasta padrao do usuario (~/AppData/Local/ms-playwright).
    """
    candidatos = []
    base_bundle = getattr(sys, "_MEIPASS", None)
    if base_bundle:
        candidatos.append(os.path.join(base_bundle, "ms-playwright"))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidatos.append(os.path.join(exe_dir, "ms-playwright"))
        candidatos.append(os.path.join(exe_dir, "_internal", "ms-playwright"))
    candidatos.append(os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright"))
    for caminho in candidatos:
        if caminho and os.path.isdir(caminho):
            return caminho
    return candidatos[-1]


# Garante que o Playwright encontre o Chromium (embutido no .exe ou no AppData do usuario)
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _resolver_ms_playwright()


def lancar_navegador_seguro(pw):
    """
    Tenta abrir o Chromium do Playwright. Se nao encontrar rodando como script,
    instala o Chromium e tenta de novo. No .exe empacotado nao da para chamar
    'python -m playwright' (sys.executable seria o proprio app), entao erra claro.
    """
    try:
        return pw.chromium.launch(headless=True)
    except Exception as e:
        logger.warning("Chromium nao abriu na primeira tentativa: %s", e)
        if not getattr(sys, "frozen", False):
            print("   [Playwright] Baixando navegadores necessarios (primeiro uso)...")
            try:
                import subprocess
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True, check=False,
                )
            except Exception as e_inst:
                logger.error("Falha ao instalar Chromium: %s", e_inst)
            return pw.chromium.launch(headless=True)
        raise RuntimeError(
            "Navegador (Chromium) do Playwright nao encontrado. "
            "Reinstale o programa ou rode 'playwright install chromium'."
        ) from e

_LOG_DIR = os.path.join(_USER_DATA_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_log_filename = os.path.join(
    _LOG_DIR,
    datetime.now().strftime("pesquisa_%Y-%m-%d_%H-%M-%S.log")
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_filename, encoding="utf-8"),   # tudo em arquivo
        logging.StreamHandler(),                                 # WARNING+ no console
    ],
)
# Silencia o handler de console para DEBUG/INFO (o colorama cuida do console)
logging.getLogger().handlers[1].setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.info("Script iniciado. Log em: %s", _log_filename)


# ==========================================
# PASTA DE DESTINO PARA CSVs
# ==========================================
CSV_DIR = os.path.join(_USER_DATA_DIR, "resultados_csv")
os.makedirs(CSV_DIR, exist_ok=True)


# ==========================================
# VALIDADOR DE EAN & AUTO-APRENDIZADO (SELECTORS)
# ==========================================
ARQUIVO_SELETORES = os.path.join(_USER_DATA_DIR, "selectors.json")

# Regex para aspas em HTML (dupla ou simples) -- usa \x27 para aspa simples
RE_ASPAS = re.compile(r'["\x27]')


def validar_ean(ean_texto: str) -> bool:
    if not ean_texto or not ean_texto.isdigit():
        return False
    comprimento = len(ean_texto)
    if comprimento not in (8, 12, 13, 14):
        return False
    digitos = [int(c) for c in ean_texto]
    soma = 0
    peso = 3
    for idx in range(comprimento - 2, -1, -1):
        soma += digitos[idx] * peso
        peso = 1 if peso == 3 else 3
    return (10 - (soma % 10)) % 10 == digitos[-1]


def carregar_seletores_personalizados():
    if os.path.exists(ARQUIVO_SELETORES):
        try:
            with open(ARQUIVO_SELETORES, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Erro ao carregar selectors.json: %s", e)
    return {}


def salvar_seletor_personalizado(chave, cfg):
    dados = carregar_seletores_personalizados()
    dados[chave] = cfg
    try:
        with open(ARQUIVO_SELETORES, 'w', encoding='utf-8') as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
        print(f"   {Fore.GREEN}[Auto-Aprendizado] Seletor para '{chave}' salvo em selectors.json!{Style.RESET_ALL}")
        logger.info("Seletor para '%s' salvo.", chave)
    except Exception as e:
        logger.error("Erro ao salvar selectors.json: %s", e)


def tentar_auto_aprendizado(chave: str, corpo_html: str) -> dict:
    if not _existe_alguma_ia():
        return None
    print(f"   {Fore.MAGENTA}[Auto-Aprendizado] Tentando descobrir seletores usando IA para {chave}...{Style.RESET_ALL}")
    logger.info("[Auto-Aprendizado] Consultando IA para '%s'.", chave)
    linhas_html = corpo_html.split("\n")
    html_resumido = []
    for idx, linha in enumerate(linhas_html):
        if "R$" in linha or "product" in linha or "item" in linha:
            inicio = max(0, idx - 5)
            fim = min(len(linhas_html), idx + 5)
            html_resumido.extend(linhas_html[inicio:fim])
            if len(html_resumido) > 150:
                break
    trecho_html = "\n".join(html_resumido)
    instrucao = (
        f"Voce e um engenheiro de dados especialista em Web Scraping.\n"
        f"O seletor atual para '{chave}' falhou. Analise o HTML abaixo e identifique:\n"
        "1. seletor_card: container de cada produto\n"
        "2. seletor_titulo: titulo dentro do card\n"
        "3. seletor_preco: preco dentro do card\n"
        "4. seletor_link: link dentro do card\n"
        "Retorne APENAS JSON valido:\n"
        '{"seletor_card":"...","seletor_titulo":"...","seletor_preco":"...","seletor_link":"..."}\n\n'
        f"HTML:\n```html\n{trecho_html[:8000]}\n```"
    )
    resposta = ia_chat(
        [
            {"role": "system", "content": "Responda apenas com JSON valido."},
            {"role": "user", "content": instrucao}
        ],
        temperatura=0.0, max_tokens=200, force_json=True, ordem=_ORDEM_IA_PRECISA,
    )
    return _extrair_json(resposta)


# ==========================================
# CONFIGURACAO DA IA (OPENAI)
# FIX .env: carrega sempre o .env da pasta do proprio script,
# independente de onde o usuario executa o comando.
# ==========================================
load_dotenv(dotenv_path=os.path.join(_SCRIPT_DIR, ".env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    cliente_openai = OpenAI(api_key=OPENAI_API_KEY)
else:
    cliente_openai = None
    print(f"{Fore.RED}Aviso: OPENAI_API_KEY nao encontrada. IA sera desativada.{Style.RESET_ALL}")
    logger.warning("OPENAI_API_KEY ausente. IA desativada.")


# ==========================================
# CLIENTES IA ADICIONAIS: Gemini + Groq
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")

# -- Gemini (Vision) --
_modelo_gemini_vision = None
_gemini_disponivel = False
try:
    import google.generativeai as genai  # pip install google-generativeai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        _modelo_gemini_vision = genai.GenerativeModel("gemini-2.5-flash")
        _gemini_disponivel = True
        print(f"{Fore.GREEN}[IA] Gemini 2.5 Flash inicializado (texto + visao).{Style.RESET_ALL}")
        logger.info("Gemini 2.5 Flash inicializado.")
except ImportError:
    logger.warning("google-generativeai nao instalado. Instale: pip install google-generativeai")
except Exception as _e:
    logger.warning("Gemini nao disponivel: %s", _e)

# -- Groq (LLaMA rapido para tarefas simples) --
_cliente_groq = None
_groq_disponivel = False
try:
    from groq import Groq  # pip install groq
    if GROQ_API_KEY:
        _cliente_groq = Groq(api_key=GROQ_API_KEY)
        _groq_disponivel = True
        print(f"{Fore.GREEN}[IA] Groq (LLaMA) inicializado.{Style.RESET_ALL}")
        logger.info("Groq inicializado.")
except ImportError:
    logger.warning("groq nao instalado. Instale: pip install groq")
except Exception as _e:
    logger.warning("Groq nao disponivel: %s", _e)

# -- OpenRouter (endpoint OpenAI-compativel que agrega varios modelos) --
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
cliente_openrouter = None
if OPENROUTER_API_KEY:
    try:
        cliente_openrouter = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
        print(f"{Fore.GREEN}[IA] OpenRouter inicializado.{Style.RESET_ALL}")
        logger.info("OpenRouter inicializado.")
    except Exception as _e:
        logger.warning("OpenRouter nao disponivel: %s", _e)

# -- HuggingFace (router com endpoint OpenAI-compativel) --
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
cliente_huggingface = None
if HUGGINGFACE_API_KEY:
    try:
        cliente_huggingface = OpenAI(api_key=HUGGINGFACE_API_KEY, base_url="https://router.huggingface.co/v1")
        print(f"{Fore.GREEN}[IA] HuggingFace inicializado.{Style.RESET_ALL}")
        logger.info("HuggingFace inicializado.")
    except Exception as _e:
        logger.warning("HuggingFace nao disponivel: %s", _e)


# ==========================================
# CAMADA UNIFICADA MULTI-IA (fallback automatico entre provedores)
# ==========================================
# Modelos por provedor — constantes para trocar facil se algum for descontinuado.
_MODELO_GROQ        = "llama-3.1-8b-instant"
_MODELO_OPENAI      = "gpt-4o-mini"
_MODELO_OPENROUTER  = "meta-llama/llama-3.1-8b-instruct"
_MODELO_HF          = "meta-llama/Llama-3.1-8B-Instruct"

# Ordem para tarefas rapidas/simples (normalizar, alternativas, resumo).
_ORDEM_IA_RAPIDA  = ["groq", "gemini", "openai", "openrouter", "huggingface"]
# Ordem para tarefas que exigem precisao (ex.: adivinhar um EAN).
_ORDEM_IA_PRECISA = ["openai", "gemini", "groq", "openrouter", "huggingface"]


def ias_disponiveis() -> list:
    """Nomes dos provedores de IA prontos para uso (para o status na interface)."""
    disp = []
    if cliente_openai:      disp.append("openai")
    if _gemini_disponivel:  disp.append("gemini")
    if _groq_disponivel:    disp.append("groq")
    if cliente_openrouter:  disp.append("openrouter")
    if cliente_huggingface: disp.append("huggingface")
    return disp


def _existe_alguma_ia() -> bool:
    return bool(cliente_openai or _gemini_disponivel or _groq_disponivel
                or cliente_openrouter or cliente_huggingface)


def _chat_openai_compat(cliente, modelo, mensagens, temperatura, max_tokens, force_json):
    kwargs = dict(model=modelo, messages=mensagens, temperature=temperatura, max_tokens=max_tokens)
    if force_json:
        kwargs["response_format"] = {"type": "json_object"}
    resp = cliente.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def _chat_gemini(mensagens, temperatura, max_tokens):
    # Converte mensagens no estilo OpenAI em um unico prompt para o Gemini.
    partes = []
    for m in mensagens:
        prefixo = "Instrucoes: " if m.get("role") == "system" else ""
        partes.append(prefixo + str(m.get("content", "")))
    resp = _modelo_gemini_vision.generate_content(
        "\n\n".join(partes),
        generation_config={"temperature": temperatura, "max_output_tokens": max_tokens},
    )
    try:
        return (resp.text or "").strip()
    except Exception:
        # Alguns retornos nao expoem .text direto; monta o texto pelas partes do candidato
        try:
            cand = resp.candidates[0]
            return "".join(getattr(p, "text", "") for p in cand.content.parts).strip()
        except Exception:
            return ""


_NOME_IA_LEGIVEL = {
    "openai": "OpenAI GPT-4o", "gemini": "Gemini", "groq": "Groq LLaMA",
    "openrouter": "OpenRouter", "huggingface": "HuggingFace",
}


def _ia_ativa(nome: str) -> bool:
    return bool(
        (nome == "openai" and cliente_openai) or (nome == "gemini" and _gemini_disponivel)
        or (nome == "groq" and _groq_disponivel) or (nome == "openrouter" and cliente_openrouter)
        or (nome == "huggingface" and cliente_huggingface)
    )


def _fazer_chamada_ia(nome, mensagens, temperatura, max_tokens, force_json):
    """Executa a chamada num provedor especifico. Retorna None se indisponivel."""
    if nome == "openai" and cliente_openai:
        return _chat_openai_compat(cliente_openai, _MODELO_OPENAI, mensagens, temperatura, max_tokens, force_json)
    if nome == "groq" and _groq_disponivel:
        return _chat_openai_compat(_cliente_groq, _MODELO_GROQ, mensagens, temperatura, max_tokens, force_json)
    if nome == "gemini" and _gemini_disponivel:
        return _chat_gemini(mensagens, temperatura, max_tokens)
    if nome == "openrouter" and cliente_openrouter:
        return _chat_openai_compat(cliente_openrouter, _MODELO_OPENROUTER, mensagens, temperatura, max_tokens, force_json)
    if nome == "huggingface" and cliente_huggingface:
        return _chat_openai_compat(cliente_huggingface, _MODELO_HF, mensagens, temperatura, max_tokens, force_json)
    return None


def ia_chat(mensagens, temperatura=0.2, max_tokens=200, force_json=False, ordem=None):
    """
    Chama os provedores de IA na ordem indicada ate um responder com sucesso.
    Faz as IAs trabalharem em conjunto: se uma cai/limita/falha, a proxima assume.
    Retorna o texto da resposta, ou None se nenhum provedor respondeu.
    """
    ordem = ordem or _ORDEM_IA_RAPIDA
    for nome in ordem:
        try:
            texto = _fazer_chamada_ia(nome, mensagens, temperatura, max_tokens, force_json)
            if texto:
                logger.info("[IA] Resposta via %s.", nome)
                return texto
        except Exception as e:
            logger.warning("[IA] Provedor %s falhou: %s", nome, e)
    return None


def ia_consenso(mensagens, temperatura=0.3, max_tokens=200, force_json=False, ordem=None):
    """
    IAs EM CONJUNTO: consulta TODOS os provedores disponiveis EM PARALELO e
    reune as respostas. A latencia fica ~= a do provedor mais lento (nao a soma).
    Retorna {'respostas': {prov: texto}, 'participantes': [nomes], 'melhor': texto|None}.
    """
    ordem = ordem or ["openai", "gemini", "groq", "openrouter", "huggingface"]
    ativos = [n for n in ordem if _ia_ativa(n)]
    if not ativos:
        return {"respostas": {}, "participantes": [], "melhor": None}

    def _um(nome):
        try:
            return nome, _fazer_chamada_ia(nome, mensagens, temperatura, max_tokens, force_json)
        except Exception as e:
            logger.warning("[IA consenso] %s falhou: %s", nome, e)
            return nome, None

    respostas = {}
    with ThreadPoolExecutor(max_workers=len(ativos)) as ex:
        for nome, txt in ex.map(_um, ativos):
            if txt and txt.strip():
                respostas[nome] = txt.strip()
    participantes = list(respostas.keys())
    melhor = max(respostas.values(), key=len) if respostas else None
    return {"respostas": respostas, "participantes": participantes, "melhor": melhor}


def _extrair_json(texto: str):
    """Extrai o primeiro objeto JSON de um texto (robusto a provedores sem modo JSON)."""
    if not texto:
        return None
    try:
        return json.loads(texto)
    except Exception:
        pass
    oc = re.search(r'\{[\s\S]*\}', texto)
    if oc:
        try:
            return json.loads(oc.group())
        except Exception:
            return None
    return None


# ==========================================
# CACHE DE EAN EM MEMÓRIA  (Melhoria #8)
# ==========================================
_cache_ean: dict[str, tuple[str, str]] = {}


# ==========================================
# IA ASSISTIDA NA PESQUISA  (novo)
# ==========================================
def ia_normalizar_entrada(texto_usuario: str) -> str:
    """
    Usa a IA para normalizar o que o usuario digitou:
    - Corrige erros de digitacao
    - Padroniza formato (ex: '1L', '1 litro', '1l' -> '1L')
    - Remove ambiguidades obvias
    Retorna o texto normalizado, ou o original se a IA estiver indisponivel.
    """
    if not _existe_alguma_ia():
        return texto_usuario
    normalizado = ia_chat(
        [
            {
                "role": "system",
                "content": (
                    "Voce e um assistente especializado em pesquisa de precos em supermercados brasileiros.\n"
                    "Sua unica funcao e normalizar o nome do produto digitado pelo usuario.\n"
                    "Regras:\n"
                    "- Corrija erros de digitacao (ex: 'leiti' -> 'leite')\n"
                    "- Padronize unidades (ex: '1 litro', '1l', '1L' -> '1L'; '500g', '500 gramas' -> '500g')\n"
                    "- Mantenha marca se mencionada\n"
                    "- Nao adicione informacoes que o usuario nao disse\n"
                    "- Responda APENAS com o nome normalizado, sem explicacoes"
                )
            },
            {"role": "user", "content": f"Normalize: {texto_usuario}"}
        ],
        temperatura=0.0, max_tokens=40, ordem=_ORDEM_IA_RAPIDA,
    )
    if normalizado:
        normalizado = normalizado.strip().strip('"').strip()
        if normalizado and len(normalizado) < 120:
            return normalizado
    return texto_usuario


def ia_termos_alternativos(produto: str) -> list[str]:
    """
    Quando a busca nao retorna resultados, a IA sugere ate 3 termos
    alternativos para tentar novamente (sinonimos, variacoes de marca, etc.).
    Retorna lista de strings (pode ser vazia se IA indisponivel).
    """
    if not _existe_alguma_ia():
        return []
    resposta = ia_chat(
        [
            {
                "role": "system",
                "content": (
                    "Voce conhece produtos de supermercados brasileiros.\n"
                    "Dado um produto que nao foi encontrado na busca, sugira ate 3 termos alternativos\n"
                    "que o usuario poderia usar para encontrar o mesmo produto ou similar.\n"
                    "Exemplos de variacoes uteis: nome generico, marca diferente, abreviacao, nome popular.\n"
                    "Responda APENAS um JSON: {\"termos\": [\"termo1\", \"termo2\", \"termo3\"]}\n"
                    "Se nao tiver sugestoes uteis, retorne: {\"termos\": []}"
                )
            },
            {"role": "user", "content": f"Produto sem resultado: '{produto}'"}
        ],
        temperatura=0.3, max_tokens=80, force_json=True, ordem=_ORDEM_IA_RAPIDA,
    )
    dados = _extrair_json(resposta) or {}
    termos = dados.get("termos", [])
    return [t for t in termos if isinstance(t, str) and t.strip() and t.strip().lower() != produto.lower()][:3]


def ia_resumir_resultados(produto_buscado: str, resultados: list) -> str:
    """
    Gera um resumo em linguagem natural dos resultados encontrados:
    - Qual loja esta mais barata
    - Variacao de preco
    - Observacoes relevantes (oferta, EAN disponivel, etc.)
    Retorna string com o resumo, ou vazia se IA indisponivel.
    """
    if not _existe_alguma_ia() or not resultados:
        return ""
    # Prepara um resumo compacto dos dados para enviar a IA
    linhas_resumo = []
    for r in resultados[:8]:  # limita para nao estourar tokens
        loja = r.get("supermercado", "—")
        nome = r.get("produto_encontrado", "—")[:50]
        preco = r.get("preco_normal", "—")
        oferta = r.get("preco_oferta", "—")
        ean = r.get("ean", "—")
        linha = f"- {loja}: {nome} | Normal: {preco}"
        if oferta and oferta != "—":
            linha += f" | Oferta: {oferta}"
        if ean and ean != "—":
            linha += f" | EAN: {ean}"
        linhas_resumo.append(linha)
    dados_str = "\n".join(linhas_resumo)
    mensagens = [
        {
            "role": "system",
            "content": (
                "Voce e um assistente de compras que analisa precos em supermercados brasileiros.\n"
                "Faca um resumo CURTO (3-5 linhas) dos resultados de pesquisa de preco, destacando:\n"
                "1. Qual loja tem o menor preco e qual o valor\n"
                "2. A diferenca percentual entre o mais barato e o mais caro (se houver mais de uma loja)\n"
                "3. Se algum produto esta em oferta, mencione\n"
                "Seja direto e use linguagem informal brasileira. Nao repita todos os dados da tabela."
            )
        },
        {
            "role": "user",
            "content": f"Produto buscado: '{produto_buscado}'\n\nResultados:\n{dados_str}"
        }
    ]
    # IAs EM CONJUNTO: cada provedor disponivel analisa em paralelo; depois
    # uma sintese final une as analises numa unica resposta.
    consenso = ia_consenso(mensagens, temperatura=0.4, max_tokens=160)
    respostas = consenso["respostas"]
    participantes = consenso["participantes"]
    if not respostas:
        return ""
    if len(respostas) > 1:
        combinado = "\n\n".join(f"[{_NOME_IA_LEGIVEL.get(p, p)}] {t}" for p, t in respostas.items())
        sintese = ia_chat(
            [
                {"role": "system", "content": (
                    "Voce recebe analises de VARIAS IAs sobre a MESMA pesquisa de preco.\n"
                    "Una tudo em UMA sintese curta (3-5 linhas), sem repetir, em portugues informal brasileiro."
                )},
                {"role": "user", "content": combinado},
            ],
            temperatura=0.3, max_tokens=180,
        )
        resumo = (sintese or consenso["melhor"] or "").strip()
    else:
        resumo = (consenso["melhor"] or "").strip()
    if resumo and participantes:
        nomes = ", ".join(_NOME_IA_LEGIVEL.get(p, p) for p in participantes)
        resumo += f"\n\n🤝 IAs em conjunto: {nomes}"
    return resumo


# ==========================================
# IA VISION: Screenshot + OCR via GPT-4o e Gemini
# ==========================================
def ia_ler_screenshot_gpt4v(screenshot_bytes: bytes, produto_buscado: str, loja: str) -> list:
    """
    Envia screenshot da pagina para o GPT-4o Vision e extrai
    lista de produtos com nome, preco e EAN encontrados na imagem.
    """
    if not cliente_openai:
        return []
    b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
    prompt = (
        f"Esta e uma pagina de busca do supermercado '{loja}'.\n"
        f"Produto que estamos procurando: '{produto_buscado}'.\n"
        "Extraia TODOS os produtos visiveis na imagem.\n"
        "Para cada produto, retorne: nome completo, preco normal (R$), preco oferta (R$ se houver ou '-'), "
        "EAN/codigo de barras (se visivel ou '-').\n"
        "Retorne APENAS JSON valido:\n"
        '{"produtos": [{"nome": "...", "preco_normal": "R$ X,XX", "preco_oferta": "-", "ean": "-"}]}'
    )
    try:
        resp = cliente_openai.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                        "detail": "high"
                    }}
                ]
            }],
            temperature=0.0,
            max_tokens=1200,
            response_format={"type": "json_object"}
        )
        dados = json.loads(resp.choices[0].message.content or "{}")
        return dados.get("produtos", [])
    except Exception as e:
        logger.debug("ia_ler_screenshot_gpt4v: %s", e)
    return []


def ia_ler_screenshot_gemini(screenshot_bytes: bytes, produto_buscado: str, loja: str) -> list:
    """
    Fallback de Vision: usa Gemini 1.5 Flash para ler a imagem.
    """
    if not _gemini_disponivel:
        return []
    try:
        import PIL.Image  # pip install Pillow
        img = PIL.Image.open(io.BytesIO(screenshot_bytes))
        prompt = (
            f"Pagina do supermercado '{loja}'. Produto buscado: '{produto_buscado}'.\n"
            "Extraia todos os produtos visiveis: nome, preco normal, preco oferta (ou '-'), EAN (ou '-').\n"
            'Responda APENAS JSON: {"produtos": [{"nome": "...", "preco_normal": "R$ X,XX", "preco_oferta": "-", "ean": "-"}]}'
        )
        resp = _modelo_gemini_vision.generate_content([prompt, img])
        texto = (resp.text or "").strip()
        m = re.search(r'\{[\s\S]+\}', texto)
        if m:
            dados = json.loads(m.group())
            return dados.get("produtos", [])
    except ImportError:
        logger.warning("Pillow nao instalado. Instale: pip install Pillow")
    except Exception as e:
        logger.debug("ia_ler_screenshot_gemini: %s", e)
    return []


def ia_ler_screenshot_pagina(pagina, produto_buscado: str, loja: str) -> list:
    """
    Orquestrador de Vision: tira screenshot full-page e tenta
    GPT-4o primeiro, Gemini como fallback. Retorna lista de resultados
    no mesmo formato que raspar_concorrente.
    """
    print(f"   {Fore.MAGENTA}[IA Vision] Capturando screenshot para leitura visual...{Style.RESET_ALL}")
    logger.info("[IA Vision] Screenshot em '%s' para '%s'.", loja, produto_buscado)
    try:
        screenshot_bytes = pagina.screenshot(full_page=True)
    except Exception as e:
        logger.warning("[IA Vision] Falha no screenshot: %s", e)
        return []

    produtos_lidos = []
    fonte = ""

    if cliente_openai:
        produtos_lidos = ia_ler_screenshot_gpt4v(screenshot_bytes, produto_buscado, loja)
        fonte = "GPT-4o Vision"

    if not produtos_lidos and _gemini_disponivel:
        print(f"   {Fore.MAGENTA}[IA Vision] GPT-4o sem resultado, tentando Gemini...{Style.RESET_ALL}")
        produtos_lidos = ia_ler_screenshot_gemini(screenshot_bytes, produto_buscado, loja)
        fonte = "Gemini 1.5 Flash Vision"

    if not produtos_lidos:
        print(f"   {Fore.YELLOW}[IA Vision] Nenhum produto extraido da imagem.{Style.RESET_ALL}")
        return []

    print(f"   {Fore.GREEN}[IA Vision] {len(produtos_lidos)} produto(s) lido(s) via {fonte}.{Style.RESET_ALL}")
    resultados = []
    for p in produtos_lidos:
        nome = (p.get("nome") or "").strip()
        preco_normal = p.get("preco_normal", "—") or "—"
        preco_oferta = p.get("preco_oferta", "—") or "—"
        ean_v = (p.get("ean") or "-").strip()
        ean_v = ean_v if (ean_v not in ("-", "") and validar_ean(ean_v)) else "—"
        if not nome or preco_normal in ("—", "-", ""):
            continue
        resultados.append({
            "supermercado": loja,
            "produto_encontrado": nome,
            "preco_normal": preco_normal,
            "preco_oferta": preco_oferta if preco_oferta not in ("-", "") else "—",
            "ean": ean_v,
            "metodo_ean": f"IA Vision ({fonte})" if ean_v != "—" else "—",
            "url": pagina.url,
        })
    return resultados


# ==========================================
# BUSCA DIRETA NA BARRA DO GOOGLE POR LOJA
# ==========================================
def buscar_produto_google_simples(produto: str, nome_loja: str, dominio_loja: str, pagina) -> list:
    """
    Pesquisa no Google usando URL direta codificada.
    Bula popups de consentimento e coleta links do dominio da loja.
    """
    query = f"{produto} {nome_loja}"
    encoded = quote_plus(query)
    url_g = f"https://www.google.com.br/search?q={encoded}"
    print(f"   {Fore.CYAN}[Google] Pesquisando: \"{query}\"...{Style.RESET_ALL}", end="", flush=True)
    links = []
    try:
        try:
            pagina.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except Exception:
            pass
        pagina.goto(url_g, timeout=20000, wait_until="domcontentloaded")
        pagina.wait_for_timeout(1500)
        
        # Bula modal de consentimento do Google se aparecer
        try:
            btn_consent = pagina.locator("button:has-text('Aceitar'), button:has-text('Concordo'), button:has-text('Accept all')").first
            if btn_consent.count() > 0:
                btn_consent.click(timeout=1500)
                pagina.wait_for_timeout(1000)
        except Exception:
            pass

        hrefs = pagina.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        for href in hrefs:
            if (
                href and (dominio_loja in href if dominio_loja else True)
                and "javascript" not in href
                and href not in links
                and "/search?" not in href
                and "google.com" not in href
                and "google.com.br" not in href
            ):
                links.append(href)
                if len(links) >= 6:
                    break
        print(f" {len(links)} link(s) do dominio encontrado(s).")
        logger.info("[Google] '%s': %d link(s).", query, len(links))
    except Exception as e:
        print(f" {Fore.RED}Erro: {str(e)[:50]}{Style.RESET_ALL}")
        logger.warning("buscar_produto_google_simples '%s': %s", query, e)
    return links


# ==========================================
# RETRY COM BACKOFF EXPONENCIAL  (Melhoria #12)
# ==========================================
def _get_com_retry(url: str, headers: dict, timeout: int = 8, tentativas: int = 3) -> requests.Response | None:
    """
    Faz GET com retry e backoff exponencial.
    Retrata em erros de rede e HTTP 429/5xx.
    """
    for tentativa in range(tentativas):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                espera = 2 ** tentativa
                logger.warning("HTTP 429 em %s. Aguardando %ds...", url[:60], espera)
                time.sleep(espera)
                continue
            if resp.status_code >= 500:
                espera = 2 ** tentativa
                logger.warning("HTTP %d em %s. Aguardando %ds...", resp.status_code, url[:60], espera)
                time.sleep(espera)
                continue
            return resp
        except requests.RequestException as e:
            espera = 2 ** tentativa
            logger.warning("Erro de rede em %s (tentativa %d): %s. Aguardando %ds...", url[:60], tentativa + 1, e, espera)
            time.sleep(espera)
    logger.error("Todas as tentativas falharam para %s", url[:60])
    return None


# ==========================================
# FONTES REAIS DE EAN POR NOME DE PRODUTO
# ==========================================

def buscar_ean_mercado_livre(nome_produto):
    try:
        url_api = f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(nome_produto)}&limit=3"
        resp = _get_com_retry(url_api, headers=CABECALHOS_REQUISICAO)
        if resp and resp.status_code in (200, 206):
            for item in resp.json().get("results", []):
                id_item = item.get("id", "")
                if not id_item:
                    continue
                resp2 = _get_com_retry(f"https://api.mercadolibre.com/items/{id_item}", headers=CABECALHOS_REQUISICAO)
                if resp2 and resp2.status_code in (200, 206):
                    detalhes = resp2.json()
                    for attr in (detalhes.get("attributes") or []):
                        if attr.get("id") in ("GTIN", "EAN", "BARCODE"):
                            v = str(attr.get("value_name", "") or "").strip()
                            if validar_ean(v):
                                return v, "Nivel 6A (Mercado Livre API)"
                    for attr in (detalhes.get("attributes") or []):
                        v = str(attr.get("value_name", "") or "").strip()
                        if validar_ean(v):
                            return v, "Nivel 6A (Mercado Livre API)"
    except Exception as e:
        logger.debug("buscar_ean_mercado_livre: %s", e)
    return None, None


def buscar_ean_buscape(nome_produto):
    try:
        url = f"https://www.buscape.com.br/search?q={quote_plus(nome_produto)}"
        resp = _get_com_retry(url, headers={**CABECALHOS_REQUISICAO, 'Referer': 'https://www.buscape.com.br/'})
        if resp and resp.status_code in (200, 206):
            # Usa aspas duplas no padrao para evitar conflito com delimitador da string
            ocorrencias = re.findall(r'(?i)(?:"gtin"|"ean"|"barcode")\s*:\s*["\x27]?(\d{8,14})["\x27]?', resp.text)
            for oc in ocorrencias:
                if validar_ean(oc):
                    return oc, "Nivel 6B (Buscape)"
            ocorrencias2 = re.findall(r'(?i)(?:EAN|GTIN|codigo de barras)[^\d]{0,20}(\d{8,14})', resp.text)
            for oc in ocorrencias2:
                if validar_ean(oc):
                    return oc, "Nivel 6B (Buscape)"
    except Exception as e:
        logger.debug("buscar_ean_buscape: %s", e)
    return None, None


def buscar_ean_google_shopping(nome_produto):
    tentativas_query = [
        f'{nome_produto} EAN site:mercadolivre.com.br',
        f'{nome_produto} "codigo de barras" EAN 13 digitos',
        f'{nome_produto} GTIN EAN supermercado',
    ]
    for texto_busca in tentativas_query:
        try:
            url = f"https://www.google.com/search?q={quote_plus(texto_busca)}&num=5&hl=pt-BR"
            resp = _get_com_retry(url, headers={**CABECALHOS_REQUISICAO, 'Accept-Encoding': 'gzip, deflate', 'Referer': 'https://www.google.com/'})
            if resp and resp.status_code in (200, 206):
                ocorrencias = re.findall(r'(?i)(?:EAN|GTIN|barcode|codigo)[^\d]{0,30}(\d{8,14})', resp.text)
                for oc in ocorrencias:
                    if validar_ean(oc):
                        return oc, "Nivel 6C (Google Shopping)"
                ocorrencias2 = re.findall(r'\b(7[0-9]{12})\b', resp.text)
                for oc in ocorrencias2:
                    if validar_ean(oc):
                        return oc, "Nivel 6C (Google - EAN BR)"
        except Exception as e:
            logger.debug("buscar_ean_google_shopping: %s", e)
    return None, None


def buscar_ean_open_food_facts(nome_produto):
    palavras = nome_produto.split()
    termos = [nome_produto]
    if len(palavras) >= 2:
        termos.append(" ".join(palavras[:3]))
    if len(palavras) >= 2:
        termos.append(" ".join(palavras[:2]))
    for url_base in ["https://br.openfoodfacts.org/cgi/search.pl", "https://world.openfoodfacts.org/cgi/search.pl"]:
        for termo in termos:
            try:
                url = f"{url_base}?search_terms={quote_plus(termo)}&search_simple=1&action=process&json=1&page_size=3"
                resp = _get_com_retry(url, headers=CABECALHOS_REQUISICAO, timeout=7)
                if resp and resp.status_code in (200, 206):
                    for prod in resp.json().get("products", []):
                        codigo = str(prod.get("code", "") or "")
                        if not validar_ean(codigo):
                            continue
                        nome_off = " ".join([prod.get("product_name", "") or "", prod.get("product_name_pt", "") or "", prod.get("brands", "") or ""]).lower()
                        palavras_chave = [w for w in nome_produto.lower().split() if len(w) > 3]
                        if any(p in nome_off for p in palavras_chave):
                            return codigo, "Nivel 6D (Open Food Facts)"
            except Exception as e:
                logger.debug("buscar_ean_open_food_facts: %s", e)
    return None, None


def buscar_ean_cosmos(nome_produto):
    # FIX #4: guard de token ausente restaurado
    token = os.getenv("COSMOS_TOKEN", "")
    if not token:
        logger.debug("COSMOS_TOKEN ausente. Pulando Cosmos/Bluesoft.")
        return None, None
    try:
        url = f"https://api.cosmos.bluesoft.com.br/gtins?q={quote_plus(nome_produto)}&page=1&per_page=5"
        resp = _get_com_retry(url, headers={**CABECALHOS_REQUISICAO, 'X-Cosmos-Token': token, 'Accept': 'application/json'})
        if resp and resp.status_code in (200, 206):
            for item in (resp.json().get("data") or []):
                gtin = str(item.get("gtin", "") or "")
                if not validar_ean(gtin):
                    continue
                desc = (item.get("description", "") or "").lower()
                palavras_chave = [w for w in nome_produto.lower().split() if len(w) > 3]
                if any(p in desc for p in palavras_chave):
                    return gtin, "Nivel 6E (Cosmos/Bluesoft)"
    except Exception as e:
        logger.debug("buscar_ean_cosmos: %s", e)
    return None, None


# ==========================================
# PIPELINE COMPLETO DE BUSCA DE EAN POR NOME
# ==========================================
def buscar_ean_por_nome(nome_produto):
    # FIX #8: cache em memória para evitar repetição de todas as APIs
    chave_cache = nome_produto.lower().strip()
    if chave_cache in _cache_ean:
        ean_c, metodo_c = _cache_ean[chave_cache]
        logger.debug("EAN retornado do cache para '%s': %s", nome_produto[:40], ean_c)
        return ean_c, metodo_c

    print(f"   {Fore.CYAN}[EAN] Buscando para: {nome_produto[:55]}{Style.RESET_ALL}")
    logger.info("[EAN] Iniciando pipeline para: %s", nome_produto[:55])
    for func in [
        buscar_ean_mercado_livre,
        buscar_ean_buscape,
        buscar_ean_google_shopping,
        buscar_ean_open_food_facts,
        buscar_ean_cosmos,
    ]:
        ean, metodo = func(nome_produto)
        if ean:
            print(f"   {Fore.GREEN}[EAN] Encontrado via {metodo}: {ean}{Style.RESET_ALL}")
            logger.info("[EAN] %s -> %s (%s)", nome_produto[:40], ean, metodo)
            _cache_ean[chave_cache] = (ean, metodo)
            return ean, metodo

    if _existe_alguma_ia():
        print(f"   {Fore.MAGENTA}[EAN] Consultando IA...{Style.RESET_ALL}")
        logger.info("[EAN] Consultando IA como ultimo recurso para '%s'.", nome_produto[:40])
        instrucao = (
            f"Produto: '{nome_produto}'\n\n"
            "Responda SOMENTE com o EAN/GTIN de 13 digitos se tiver CERTEZA TOTAL.\n"
            "Se tiver qualquer duvida, responda: FALHA\n"
            "NUNCA invente. Prefira FALHA a um codigo errado."
        )
        texto = ia_chat(
            [
                {"role": "system", "content": "Base de dados de EAN. Nunca invente. Se nao tiver certeza, responda FALHA."},
                {"role": "user", "content": instrucao}
            ],
            temperatura=0.0, max_tokens=20, ordem=_ORDEM_IA_PRECISA,
        )
        if texto and not texto.upper().startswith("FALHA"):
            oc = re.search(r'\b(\d{8,14})\b', texto)
            if oc and validar_ean(oc.group(1)):
                resultado = (oc.group(1), "Nivel 7 (IA - Ultimo Recurso)")
                _cache_ean[chave_cache] = resultado
                return resultado

    _cache_ean[chave_cache] = ("—", "Falha Total")
    return "—", "Falha Total"


# ==========================================
# COMPARADOR INTELIGENTE DE PRODUTOS (NLP)
# ==========================================
class ComparadorInteligenteProdutos:
    PALAVRAS_PARADA = {
        "de", "do", "da", "em", "para", "com", "sem", "no", "na", "o", "a", "os", "as",
        "um", "uma", "e", "para", "por", "dos", "das"
    }

    @staticmethod
    def remover_acentos(texto: str) -> str:
        if not texto:
            return ""
        nfkd = unicodedata.normalize('NFKD', texto)
        return "".join([c for c in nfkd if not unicodedata.combining(c)])

    @classmethod
    def normalizar(cls, texto: str) -> str:
        if not texto:
            return ""
        texto = cls.remover_acentos(texto.lower().strip())
        texto = re.sub(r'[\-/\\_]', ' ', texto)
        texto = re.sub(r'[^a-z0-9\s]', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto

    @classmethod
    def tokenizar(cls, texto: str) -> list:
        norm = cls.normalizar(texto)
        return [p for p in norm.split() if p not in cls.PALAVRAS_PARADA and (len(p) > 1 or p.isdigit())]

    @staticmethod
    def extrair_unidades(texto: str) -> list:
        texto_norm = texto.lower()
        padrao = r'\b(\d+(?:[.,]\d+)?)\s*(ml|l|kg|g|gr|lt|unid|un|und|pct|pacote)\b'
        resultados = []
        for valor_str, unidade in re.findall(padrao, texto_norm):
            try:
                valor = float(valor_str.replace(',', '.'))
                if unidade in ('l', 'lt'):
                    resultados.append({'valor_padrao': valor * 1000.0, 'unidade_padrao': 'ml'})
                elif unidade == 'ml':
                    resultados.append({'valor_padrao': valor, 'unidade_padrao': 'ml'})
                elif unidade == 'kg':
                    resultados.append({'valor_padrao': valor * 1000.0, 'unidade_padrao': 'g'})
                elif unidade in ('g', 'gr'):
                    resultados.append({'valor_padrao': valor, 'unidade_padrao': 'g'})
                else:
                    resultados.append({'valor_padrao': valor, 'unidade_padrao': 'un'})
            except ValueError:
                pass
        return resultados

    @classmethod
    def calcular_relevancia(cls, busca: str, nome_produto: str) -> float:
        if not busca or not nome_produto:
            return 0.0
        busca_norm = cls.normalizar(busca)
        prod_norm = cls.normalizar(nome_produto)

        unidades_busca = cls.extrair_unidades(busca)
        unidades_prod = cls.extrair_unidades(nome_produto)
        if unidades_busca and unidades_prod:
            ub = unidades_busca[0]
            compativel = any(
                ub['unidade_padrao'] == up['unidade_padrao'] and abs(ub['valor_padrao'] - up['valor_padrao']) < 0.1
                for up in unidades_prod
            )
            if not compativel:
                return 0.05

        especiais = ["zero", "diet", "light", "sem lactose", "lacfree", "sem acucar", "desnatado", "semidesnatado"]
        penalizar = False
        for termo in especiais:
            termo_norm = cls.remover_acentos(termo)
            na_busca = termo_norm in busca_norm
            no_prod = termo_norm in prod_norm
            if na_busca != no_prod:
                if na_busca:
                    return 0.10
                else:
                    penalizar = True

        if "integral" in busca_norm and ("desnatado" in prod_norm or "semidesnatado" in prod_norm):
            return 0.05
        if ("desnatado" in busca_norm or "semidesnatado" in busca_norm) and "integral" in prod_norm:
            return 0.05

        tokens_busca = cls.tokenizar(busca)
        tokens_prod = cls.tokenizar(nome_produto)
        if not tokens_busca:
            return 0.0

        conjunto_busca = set(tokens_busca)
        conjunto_prod = set(tokens_prod)
        intersecao = conjunto_busca.intersection(conjunto_prod)

        palavras_essenciais = [t for t in tokens_busca if len(t) > 2]
        for pe in palavras_essenciais:
            if pe.isdigit():
                continue
            if pe not in conjunto_prod:
                achei = any(pe in tp or tp in pe for tp in tokens_prod)
                if not achei:
                    return 0.15

        jaccard = len(intersecao) / len(conjunto_busca)
        sim_seq = SequenceMatcher(None, busca_norm, prod_norm).ratio()
        pontuacao = (jaccard * 0.6) + (sim_seq * 0.4)
        if penalizar:
            pontuacao *= 0.60
        return round(pontuacao, 4)


# FIX #7: limiar NLP unificado em uma única constante
NLP_LIMIAR_PADRAO = 0.25


def filtrar_e_ordenar_por_nlp(produto_busca: str, resultados: list, limite: float = NLP_LIMIAR_PADRAO) -> list:
    if not resultados:
        return []
    resultado_nlp = []
    for r in resultados:
        score = ComparadorInteligenteProdutos.calcular_relevancia(produto_busca, r.get("produto_encontrado", ""))
        r["nlp_score"] = score
        if score >= limite:
            resultado_nlp.append(r)
    resultado_nlp.sort(key=lambda x: x.get("nlp_score", 0.0), reverse=True)
    return resultado_nlp


# ==========================================
# CONCORRENTES E CABECALHOS
# ==========================================
CONCORRENTES = {
    "diniz": {
        "nome": "Diniz Supermercados",
        "url_busca": "https://www.dinizsupermercados.com.br/busca?termo={produto}",
        "codificador": quote,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "categorias": {
            "Mercearia":                  "https://www.dinizsupermercados.com.br/departamentos/mercearia",
            "Salgadinhos e Chocolates":   "https://www.dinizsupermercados.com.br/departamentos/salgadinhos-biscoitos-e-chocolates",
            "Matinais e Sobremesas":      "https://www.dinizsupermercados.com.br/departamentos/matinais-e-sobremesas",
            "Cereais e Farinaceos":       "https://www.dinizsupermercados.com.br/departamentos/cereais-e-farinaceos",
            "Carnes":                     "https://www.dinizsupermercados.com.br/departamentos/carnes",
            "Frios e Laticinios":         "https://www.dinizsupermercados.com.br/departamentos/frios-e-laticinios",
            "Hortifruti":                 "https://www.dinizsupermercados.com.br/departamentos/hortifruti",
            "Padaria":                    "https://www.dinizsupermercados.com.br/departamentos/padaria",
            "Congelados":                 "https://www.dinizsupermercados.com.br/departamentos/congelados",
            "Bebidas":                    "https://www.dinizsupermercados.com.br/departamentos/bebidas",
            "Perfumaria, Higiene e Bebe": "https://www.dinizsupermercados.com.br/departamentos/perfumaria-higiene-e-bebe",
            "Limpeza":                    "https://www.dinizsupermercados.com.br/departamentos/limpeza",
            "Bazar e Utilidades":         "https://www.dinizsupermercados.com.br/departamentos/bazar-e-utilidades",
            "Animais":                    "https://www.dinizsupermercados.com.br/departamentos/animais",
            "Fitness":                    "https://www.dinizsupermercados.com.br/departamentos/fitness",
        },
    },
    "saoluiz": {
        "nome": "loja oestes Sao Luiz",
        "url_busca": "https://loja oestessaoluiz.com.br/loja/369?search={produto}",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "clicar_no_produto": True,
        "seletor_link_produto": "a[href*='/produto/']",
        "url_encartes": "https://loja oestessaoluiz.com.br/loja/355",
        "categorias": {
            "Ofertas":            "https://loja oestessaoluiz.com.br/loja/355/ofertas",
            "Hortifruti":         "https://loja oestessaoluiz.com.br/loja/355/categoria/13778",
            "Acougue":            "https://loja oestessaoluiz.com.br/loja/355/categoria/13780",
            "Peixaria":           "https://loja oestessaoluiz.com.br/loja/355/categoria/13781",
            "Padaria":            "https://loja oestessaoluiz.com.br/loja/355/categoria/13782",
            "Congelados":         "https://loja oestessaoluiz.com.br/loja/355/categoria/13783",
            "Frios e Laticinios": "https://loja oestessaoluiz.com.br/loja/355/categoria/13784",
            "Mercearia":          "https://loja oestessaoluiz.com.br/loja/355/categoria/13785",
            "Doces e Biscoitos":  "https://loja oestessaoluiz.com.br/loja/355/categoria/13786",
            "Cereais":            "https://loja oestessaoluiz.com.br/loja/355/categoria/13787",
            "Massas":             "https://loja oestessaoluiz.com.br/loja/355/categoria/13788",
            "Bebidas":            "https://loja oestessaoluiz.com.br/loja/355/categoria/13789",
            "Limpeza":            "https://loja oestessaoluiz.com.br/loja/355/categoria/13790",
            "Higiene e Bebe":     "https://loja oestessaoluiz.com.br/loja/355/categoria/13791",
        },
    },
    "atacadao": {
        "nome": "Atacadao",
        "url_busca": "https://www.atacadao.com.br/s?q={produto}&sort=score_desc&page=0",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'(?:ean|gtin|barcode)[\/](\d{8,14})',
        "categorias": {},
    },
    # ── Expansao Ceara ──────────────────────────────────────────────────────
    "assai": {
        "nome": "Assai Atacadista",
        "url_busca": "https://www.assai.com.br/busca?q={produto}&sort=score_desc",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'(?:ean|gtin|barcode)[\/](\d{8,14})',
        "categorias": {},
        # Assai usa VTEX, tentar VTEX API diretamente
        "vtex_api": "https://www.assai.com.br/api/catalog_system/pub/products/search/{produto}?_from=0&_to=9",
    },
    "carrefour": {
        "nome": "Carrefour",
        "url_busca": "https://www.carrefour.com.br/s?q={produto}&sort=score_desc",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'(?:ean|gtin|barcode)[\/](\d{8,14})',
        "categorias": {},
        "vtex_api": "https://www.carrefour.com.br/api/catalog_system/pub/products/search/{produto}?_from=0&_to=9",
    },
    "cometa": {
        "nome": "Cometa Supermercados",
        "url_busca": "https://www.cometasupermercados.com.br/busca?q={produto}",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "categorias": {},
        "usar_google_search": True,  # fallback: busca na barra do Google
    },
    "bomprece": {
        "nome": "Bom Preco Supermercados",
        "url_busca": "https://www.bomprecoce.com.br/busca?q={produto}",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "categorias": {},
        "usar_google_search": True,
    },
    "mercantil": {
        "nome": "Mercantil Rodrigues",
        "url_busca": "https://www.mercantilrodrigues.com.br/busca?q={produto}",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "categorias": {},
        "usar_google_search": True,
    },
    "bigbompreco": {
        "nome": "Big Bompreco",
        "url_busca": "https://www.bigbompreco.com.br/busca?q={produto}",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "categorias": {},
        "usar_google_search": True,
    },
    "atakarejo": {
        "nome": "Atakarejo",
        "url_busca": "https://www.atakarejo.com.br/busca?q={produto}",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "categorias": {},
        "usar_google_search": True,
    },
    "pinheiro": {
        "nome": "Pinheiro Supermercados",
        "url_busca": "https://www.superpinheiro.com.br/busca?q={produto}",
        "codificador": quote_plus,
        "expressao_regular_ean_url": r'ean=(\d{8,14})',
        "categorias": {},
        "usar_google_search": True,
    },
}

CABECALHOS_REQUISICAO = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
}

DOMINIOS_CONCORRENTES = {
    "dinizsupermercados.com.br":    "diniz",
    "loja oestessaoluiz.com.br":    "saoluiz",
    "atacadao.com.br":              "atacadao",
    "assai.com.br":                 "assai",
    "carrefour.com.br":             "carrefour",
    "cometasupermercados.com.br":   "cometa",
    "bomprecoce.com.br":            "bomprece",
    "mercantilrodrigues.com.br":    "mercantil",
    "bigbompreco.com.br":           "bigbompreco",
    "atakarejo.com.br":             "atakarejo",
    "superpinheiro.com.br":         "pinheiro",
}

# Regexes pre-compiladas para evitar problemas de aspas em raw strings
RE_GTIN_META = re.compile(r'(?i)"(?:gtin13|gtin|sku|ean|bar_?code|ProductEan|codigo_barras|codigo)"\s*[:=]\s*["\x27]?(\d{8,14})["\x27]?')
RE_GTIN_JSON = re.compile(r'(?i)(?:gtin|ean|bar_?code|codigo_barras|codigo|sku)["\x27]?\s*[:=]\s*["\x27]?(\d{8,14})["\x27]?')
RE_GTIN_BUSCAPE = re.compile(r'(?i)(?:"gtin"|"ean"|"barcode")\s*:\s*["\x27]?(\d{8,14})["\x27]?')

# FIX #3: RE_EAN_HREF corrigida — captura a URL do href, não as aspas
RE_EAN_HREF = re.compile(r'href=["\x27]([^"\x27]+)["\x27]')

RE_HREF_PRODUTO = re.compile(r'href=["\x27](["\x27]*?/produto/[^"\x27]+)["\x27]')
RE_HREF_GERAL = re.compile(r'href=["\x27]([^"\x27]+)["\x27]')
RE_DATA_EAN = re.compile(r'data-(?:ean|sku|id)=["\x27](\d{8,14})["\x27]')
RE_ENCARTE_HREF = re.compile(r'href=["\x27]([^"\x27]*(?:encarte|oferta|flyer)[^"\x27]*)["\x27]', re.I)


# ==========================================
# DEDUPLICACAO DE RESULTADOS
# ==========================================
def _deduplicar_resultados(resultados: list) -> list:
    """
    Remove duplicatas da mesma loja, mantendo o de menor preco.
    Criterio: (supermercado, primeiras_palavras_do_nome)
    """
    vistos = {}
    for r in resultados:
        loja = r.get("supermercado", "")
        nome = r.get("produto_encontrado", "")
        # Chave: loja + nome COMPLETO normalizado. Assim variantes diferentes
        # (2L, 1L, lata, zero...) NAO sao colapsadas — so duplicatas identicas.
        chave = (loja, " ".join(nome.lower().split()))
        if chave not in vistos:
            vistos[chave] = r
        else:
            # Prefere o de menor preco
            def _preco_num(item):
                p = item.get("preco_oferta") or item.get("preco_normal") or "9999"
                nums = re.findall(r'[\d,.]+', str(p))
                if nums:
                    try:
                        return float(nums[0].replace(',', '.'))
                    except Exception:
                        return 9999.0
                return 9999.0
            if _preco_num(r) < _preco_num(vistos[chave]):
                vistos[chave] = r
    return list(vistos.values())


# ==========================================
# RASPAGEM EM PARALELO COM TIMEOUT POR LOJA
# ==========================================
def raspar_concorrente_com_timeout(
    produto: str,
    chave: str,
    configuracao: dict,
    parar_event: threading.Event | None = None,
    timeout_seg: int = 30,
    callback_status=None,
    coletor_erros: list | None = None,
    limite=None,
) -> list:
    """
    Executa raspar_concorrente com timeout por loja.
    Roda em thread separada com Playwright proprio.
    Erros vao para coletor_erros (para a GUI mostrar, em vez de sumirem).
    """
    if parar_event and parar_event.is_set():
        return []
    loja = configuracao.get("nome", chave)
    if callback_status:
        callback_status(f"🔍 Buscando {loja}...")
    resultados = []
    try:
        with sync_playwright() as pw:
            nav = lancar_navegador_seguro(pw)
            ctx = nav.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                ignore_https_errors=True,
                locale="pt-BR"
            )
            pag = ctx.new_page()
            try:
                pag.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            except Exception:
                pass
            pag.set_default_timeout(timeout_seg * 1000)
            tempo_nav = max(15, timeout_seg - 5)
            resultados = raspar_concorrente(produto, chave, configuracao, pag, ctx,
                                            limite=limite, callback_status=callback_status,
                                            tempo_max=tempo_nav)
            nav.close()
    except Exception as e:
        logger.warning("raspar_concorrente_com_timeout [%s]: %s", chave, e)
        if coletor_erros is not None:
            coletor_erros.append((loja, str(e)))
        if callback_status:
            callback_status(f"⚠️ {loja}: {str(e)[:60]}")
        return resultados
    if callback_status:
        callback_status(f"✅ {loja}: {len(resultados)} produto(s)")
    return resultados


def raspar_todos_paralelo(
    produto: str,
    lojas_selecionadas: list | None = None,
    parar_event: threading.Event | None = None,
    max_workers: int = 4,
    timeout_por_loja: int = 30,
    callback_status=None,
    limite_por_loja=None,
) -> list:
    """
    Busca em todas as lojas em paralelo usando ThreadPoolExecutor.
    Retorna lista de resultados deduplicados.
    """
    concorrentes = {
        k: v for k, v in CONCORRENTES.items()
        if not lojas_selecionadas or k in lojas_selecionadas
    }
    todos_resultados = []
    erros = []
    total = max(len(concorrentes), 1)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futuros = {
            executor.submit(
                raspar_concorrente_com_timeout,
                produto, chave, cfg,
                parar_event, timeout_por_loja, callback_status, erros, limite_por_loja
            ): chave
            for chave, cfg in concorrentes.items()
        }
        try:
            for fut in as_completed(futuros, timeout=timeout_por_loja * total + 30):
                if parar_event and parar_event.is_set():
                    break
                chave = futuros[fut]
                try:
                    res = fut.result(timeout=2)
                    todos_resultados.extend(res)
                except Exception as e:
                    logger.warning("Loja [%s] falhou no paralelo: %s", chave, e)
                    erros.append((chave, str(e)))
        except FuturesTimeout:
            logger.warning("Tempo total da busca esgotado; retornando o que ja veio.")

    resultados = _deduplicar_resultados(todos_resultados)
    # Se nada voltou e houve falha de navegador em todas as lojas, avisa a GUI de forma clara
    if not resultados and erros and not (parar_event and parar_event.is_set()):
        msg_browser = next(
            (m for _, m in erros
             if any(p in m.lower() for p in ("chromium", "navegador", "playwright", "executable", "browsertype"))),
            None,
        )
        if msg_browser:
            raise RuntimeError(msg_browser)
    return resultados


# ==========================================
# ENCARTES DE TODOS OS SUPERMERCADOS
# ==========================================
def buscar_encartes_todos(pagina, contexto, lojas_filtro=None) -> list:
    """
    Busca encartes de todas as redes via Google, alem do Sao Luiz que tem pagina propria.
    """
    todos = []
    lojas_encarte = [
        ("saoluiz",     "loja oestes Sao Luiz",  None),
        ("atacadao",    "Atacadao",               "atacadao.com.br"),
        ("assai",       "Assai Atacadista",        "assai.com.br"),
        ("carrefour",   "Carrefour",              "carrefour.com.br"),
        ("diniz",       "Diniz",                  "dinizsupermercados.com.br"),
        ("cometa",      "Cometa",                 "cometasupermercados.com.br"),
        ("bomprece",    "Bom Preco",              "bomprecoce.com.br"),
        ("mercantil",   "Mercantil Rodrigues",     "mercantilrodrigues.com.br"),
        ("bigbompreco", "Big Bompreco",            "bigbompreco.com.br"),
        ("atakarejo",   "Atakarejo",              "atakarejo.com.br"),
        ("pinheiro",    "Pinheiro",               "superpinheiro.com.br"),
    ]
    if lojas_filtro:
        lojas_encarte = [(c, n, d) for c, n, d in lojas_encarte if c in lojas_filtro]

    for chave, nome, dominio in lojas_encarte:
        print(f"\n{Fore.CYAN}[Encarte] Buscando encarte de {nome}...{Style.RESET_ALL}")
        # Sao Luiz: metodo proprio
        if chave == "saoluiz":
            res_sl = buscar_encartes_saoluiz(pagina, contexto)
            todos.extend(res_sl)
            continue
        # Outras: Google
        query = f"encarte {nome} Fortaleza Ceara preco"
        try:
            pagina.goto("https://www.google.com.br", timeout=15000)
            campo = pagina.locator('input[name="q"], textarea[name="q"]').first
            if campo.count() == 0:
                continue
            campo.fill(query)
            campo.press("Enter")
            pagina.wait_for_load_state("domcontentloaded", timeout=10000)
            pagina.wait_for_timeout(1000)
            hrefs = pagina.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            pdfs = [h for h in hrefs if h and ('.pdf' in h.lower() or ('encarte' in h.lower() and dominio and dominio in h))]
            if pdfs:
                for url_pdf in pdfs[:2]:
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                            urllib.request.urlretrieve(url_pdf, tf.name)
                            caminho = tf.name
                        with pdfplumber.open(caminho) as doc:
                            for pag_pdf in doc.pages:
                                for linha in (pag_pdf.extract_text() or "").split("\n"):
                                    oc = re.search(r'R\$\s*([\d.,]+)', linha)
                                    if oc and len(linha) > 8:
                                        nome_prod = re.sub(r'R\$[\d.,\s]+', '', linha).strip()
                                        if nome_prod and len(nome_prod) > 4:
                                            todos.append({
                                                "supermercado": f"{nome} (Encarte)",
                                                "produto_encontrado": nome_prod[:80],
                                                "preco_normal": f"R$ {oc.group(1)}",
                                                "preco_oferta": "—",
                                                "ean": "—",
                                                "metodo_ean": "Encarte PDF",
                                                "url": url_pdf
                                            })
                        os.unlink(caminho)
                    except Exception as e_pdf:
                        logger.warning("Encarte PDF %s: %s", url_pdf[:60], e_pdf)
            else:
                print(f"   {Fore.YELLOW}Nenhum PDF de encarte encontrado para {nome}.{Style.RESET_ALL}")
        except Exception as e:
            logger.warning("buscar_encartes_todos [%s]: %s", chave, e)
    print(f"\n{Fore.GREEN}[Encartes] Total: {len(todos)} produto(s) de encarte.{Style.RESET_ALL}")
    return todos


# ==========================================
# EXPORTACAO PARA CSV  (pasta configurável)
# ==========================================
def exportar_para_csv(resultados):
    if not resultados:
        return
    data_hora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome_arquivo = os.path.join(CSV_DIR, f"extracao_precos_{data_hora}.csv")
    colunas = ["Loja", "Produto Encontrado", "Preco Normal", "Oferta", "EAN", "Nivel de Extracao", "URL"]
    try:
        with open(nome_arquivo, mode='w', newline='', encoding='utf-8-sig') as f:
            escritor = csv.writer(f, delimiter=';')
            escritor.writerow(colunas)
            for r in resultados:
                escritor.writerow([
                    r.get("supermercado", "—"), r.get("produto_encontrado", "—"),
                    r.get("preco_normal", "—"), r.get("preco_oferta", "—"),
                    r.get("ean", "—"), r.get("metodo_ean", "—"), r.get("url", "—")
                ])
        print(f"\n{Fore.GREEN}CSV salvo: {nome_arquivo}{Style.RESET_ALL}")
        logger.info("CSV exportado: %s (%d linha(s))", nome_arquivo, len(resultados))
    except Exception as e:
        print(f"\n{Fore.RED}Erro ao salvar CSV: {e}{Style.RESET_ALL}")
        logger.error("Erro ao salvar CSV: %s", e)


# ==========================================
# MOTOR DE BUSCA DE EAN (NIVEIS 3, 4 E 5)
# ==========================================
def buscar_ean_profundo(url_produto, contexto_playwright):
    try:
        resp = _get_com_retry(url_produto, headers=CABECALHOS_REQUISICAO, timeout=6)
        if resp and resp.status_code in (200, 206):
            sopa = BeautifulSoup(resp.text, 'html.parser')
            for tag in [sopa.find('meta', property='product:retailer_item_id'), sopa.find('meta', itemprop='gtin13'), sopa.find('meta', itemprop='sku')]:
                if tag and tag.get('content'):
                    v = tag.get('content').strip()
                    if validar_ean(v):
                        return v, "Nivel 3 (Meta Tag)"
            for script in sopa.find_all('script'):
                if not script.string:
                    continue
                for oc in RE_GTIN_META.findall(script.string):
                    if validar_ean(oc):
                        return oc, "Nivel 4 (JSON-LD/Script)"
            for oc in re.findall(r'(?i)(?:EAN|C[ou]digo de barras|GTIN)[\s\S]{0,120}?(\d{8,14})', resp.text):
                if validar_ean(oc):
                    return oc, "Nivel 3.5 (Regex HTML)"
    except Exception as e:
        logger.debug("buscar_ean_profundo (requests): %s", e)

    pagina_prod = None
    url_analisada = urlparse(url_produto)
    id_prod = url_analisada.path.rstrip("/").split("/")[-1]
    id_num = re.search(r'/(\d{5,})', url_produto)
    id_num = id_num.group(1) if id_num else ""
    sniffer = []

    def interceptar(resp_rede):
        if "application/json" in resp_rede.headers.get("content-type", ""):
            try:
                texto = str(resp_rede.json())
                eans = {oc for oc in RE_GTIN_JSON.findall(texto) if validar_ean(oc)}
                if eans:
                    sniffer.append((eans, resp_rede.url))
            except Exception:
                pass

    try:
        pagina_prod = contexto_playwright.new_page()
        pagina_prod.on("response", interceptar)
        pagina_prod.goto(url_produto, timeout=15000, wait_until="networkidle")

        if sniffer:
            def pontuacao_url(u):
                p = 0
                if id_prod and id_prod in u: p += 10
                if id_num and id_num in u: p += 5
                for kw in ("/product/", "/produto/", "/item/", "/sku/", "/pdp/"):
                    if kw in u: p += 3
                return p

            resps_prod = [(e, u) for e, u in sniffer if len(e) == 1]
            resps_lista = [(e, u) for e, u in sniffer if len(e) > 1]
            ean_escolhido = None
            if resps_prod:
                melhor = max(resps_prod, key=lambda x: pontuacao_url(x[1]))
                ean_escolhido = next(iter(melhor[0]))
            if not ean_escolhido and resps_lista:
                melhor = max(resps_lista, key=lambda x: pontuacao_url(x[1]))
                ean_escolhido = next(iter(melhor[0]))
            if ean_escolhido:
                pagina_prod.close()
                return ean_escolhido, "Nivel 5.1 (Sniffer de API/Rede)"

        for oc in re.findall(r'(?i)(?:EAN|C[OoÓó]DIGO DE BARRAS)[\s\S]{0,50}?(\d{8,14})', pagina_prod.inner_text("body")):
            if validar_ean(oc):
                pagina_prod.close()
                return oc, "Nivel 5.2 (Texto visivel Playwright)"
        pagina_prod.close()
    except Exception as e:
        logger.debug("buscar_ean_profundo (playwright): %s", e)
        try:
            if pagina_prod:
                pagina_prod.close()
        except Exception:
            pass
    return "—", "Falha nos sites"


# ==========================================
# RASPAGEM ATACADÃO VIA API VTEX (e generica para outras lojas VTEX)
# ==========================================
def _raspar_vtex_generico(produto: str, chave: str, configuracao: dict) -> list:
    """
    Raspa lojas VTEX genericas (Assai, Carrefour, etc.) usando a URL
    vtex_api definida em CONCORRENTES. Reutiliza a mesma logica do Atacadao.
    """
    vtex_url_template = configuracao.get("vtex_api", "")
    if not vtex_url_template:
        return []
    loja = configuracao["nome"]
    resultados = []
    cabecalhos = {**CABECALHOS_REQUISICAO, 'Accept': 'application/json',
                  'Referer': f'https://{next((d for d, c in DOMINIOS_CONCORRENTES.items() if c == chave), "")}'}
    url = vtex_url_template.replace("{produto}", quote_plus(produto))
    try:
        resp = _get_com_retry(url, headers=cabecalhos, timeout=10)
        if resp and resp.status_code in (200, 206):
            dados = resp.json()
            if not isinstance(dados, list):
                return []
            for item in dados[:8]:
                nome = item.get("productName") or item.get("name") or "—"
                ean, metodo_ean = "—", "—"
                for campo in ["EAN", "ean", "gtin"]:
                    v = str(item.get(campo) or "").strip()
                    if validar_ean(v):
                        ean, metodo_ean = v, f"VTEX API ({loja})"
                        break
                if ean == "—":
                    for sku in item.get("items", []):
                        v = str(sku.get("ean") or sku.get("EAN") or "")
                        if validar_ean(v):
                            ean, metodo_ean = v, f"VTEX API SKU ({loja})"
                            break
                preco_normal, preco_oferta = "—", "—"
                try:
                    sellers = item.get("items", [{}])[0].get("sellers", [{}])
                    if sellers:
                        oferta = sellers[0].get("commertialOffer", {})
                        por = oferta.get("Price")
                        de = oferta.get("ListPrice")
                        if por:
                            preco_normal = f"R$ {por:.2f}".replace('.', ',')
                        if de and de != por:
                            preco_oferta = f"R$ {por:.2f}".replace('.', ',')
                            preco_normal = f"R$ {de:.2f}".replace('.', ',')
                except Exception:
                    pass
                if preco_normal == "—":
                    continue
                link_text = item.get("linkText", "")
                resultados.append({
                    "produto_encontrado": nome, "preco_normal": preco_normal,
                    "preco_oferta": preco_oferta,
                    "url": f"https://{next((d for d, c in DOMINIOS_CONCORRENTES.items() if c == chave), '')}/{link_text}/p",
                    "ean": ean, "metodo_ean": metodo_ean, "supermercado": loja,
                })
    except Exception as e:
        logger.debug("_raspar_vtex_generico %s: %s", loja, e)
    return resultados


def _parse_item_vtex_atacadao(item: dict):
    """Converte um item da VTEX API do Atacadao no formato interno (ou None)."""
    nome = item.get("productName") or item.get("name") or "—"
    ean, metodo_ean = "—", "—"
    for campo in ["EAN", "ean", "gtin"]:
        v = str(item.get(campo) or "").strip()
        if validar_ean(v):
            ean, metodo_ean = v, "Nivel 5.4 (VTEX API)"
            break
    if ean == "—":
        for sku in item.get("items", []):
            v = str(sku.get("ean") or sku.get("EAN") or "")
            if validar_ean(v):
                ean, metodo_ean = v, "Nivel 5.4 (VTEX API SKU)"
                break
    preco_normal, preco_oferta = "—", "—"
    try:
        sellers = item.get("items", [{}])[0].get("sellers", [{}])
        if sellers:
            oferta = sellers[0].get("commertialOffer", {})
            por = oferta.get("Price")
            de = oferta.get("ListPrice")
            if por:
                preco_normal = f"R$ {por:.2f}".replace('.', ',')
            if de and de != por:
                preco_oferta = f"R$ {por:.2f}".replace('.', ',')
                preco_normal = f"R$ {de:.2f}".replace('.', ',')
    except Exception:
        pass
    if preco_normal == "—":
        return None
    return {
        "produto_encontrado": nome, "preco_normal": preco_normal,
        "preco_oferta": preco_oferta, "url": f"https://www.atacadao.com.br/{item.get('linkText', '')}/p",
        "ean": ean, "metodo_ean": metodo_ean, "supermercado": "Atacadao",
    }


def raspar_atacadao_api(produto: str, limite=None) -> list:
    """VTEX API do Atacadao paginada em blocos de 10 (gentil, evita rate-limit)."""
    resultados = []
    cabecalhos = {**CABECALHOS_REQUISICAO, 'Accept': 'application/json', 'Referer': 'https://www.atacadao.com.br/'}
    q = quote_plus(produto)
    n_paginas = min(max(1, _limite_efetivo(limite) // 10), 20)
    for pagina_i in range(n_paginas):
        a = pagina_i * 10
        url = f"https://www.atacadao.com.br/api/catalog_system/pub/products/search/{q}?_from={a}&_to={a + 9}"
        try:
            resp = _get_com_retry(url, headers=cabecalhos, timeout=10)
        except Exception as e:
            logger.debug("raspar_atacadao_api: %s", e)
            break
        if not (resp and resp.status_code in (200, 206)):
            break
        try:
            dados = resp.json()
        except Exception:
            break
        if not isinstance(dados, list) or not dados:
            break
        for item in dados:
            parsed = _parse_item_vtex_atacadao(item)
            if parsed:
                resultados.append(parsed)
        if len(dados) < 10:
            break
        time.sleep(0.4)
    return resultados


# ==========================================
# RASPAGEM DINIZ VIA API JSON
# ==========================================
def raspar_diniz_api(produto: str, pagina, contexto) -> list:
    resultados_api = []
    loja = "Diniz Supermercados"
    url_busca = f"https://www.dinizsupermercados.com.br/busca?termo={quote(produto)}"

    def interceptar(resp_rede):
        if "application/json" not in resp_rede.headers.get("content-type", ""):
            return
        url_r = resp_rede.url
        if not any(kw in url_r.lower() for kw in ["busca", "search", "produto", "catalog", "product", "item"]):
            return
        try:
            dados = resp_rede.json()
            candidatos = []
            if isinstance(dados, list):
                candidatos = dados
            elif isinstance(dados, dict):
                for chave in ["products", "items", "data", "results", "produtos", "hits"]:
                    if isinstance(dados.get(chave), list):
                        candidatos = dados[chave]
                        break
                if not candidatos:
                    for v in dados.values():
                        if isinstance(v, dict):
                            for chave2 in ["products", "items", "data", "results", "hits"]:
                                if isinstance(v.get(chave2), list):
                                    candidatos = v[chave2]
                                    break
                        if candidatos:
                            break
            for item in candidatos[:10]:
                if not isinstance(item, dict):
                    continue
                nome = (item.get("name") or item.get("nome") or item.get("title") or item.get("productName") or item.get("description") or "").strip()
                if not nome or len(nome) < 3:
                    continue
                ean, metodo_ean = "—", "—"
                for campo in ["ean", "EAN", "gtin", "barcode", "codigo_barras", "sku", "referenceId"]:
                    val = str(item.get(campo) or "").strip()
                    if validar_ean(val):
                        ean, metodo_ean = val, "Nivel 5.5 (Diniz API JSON)"
                        break
                preco_normal, preco_oferta = "—", "—"
                for campo_preco in ["price", "preco", "valor", "Price", "salePrice", "listPrice"]:
                    val = item.get(campo_preco)
                    if val:
                        try:
                            preco_normal = f"R$ {float(val):.2f}".replace('.', ',')
                            break
                        except Exception:
                            pass
                if preco_normal == "—":
                    continue
                resultados_api.append({
                    "produto_encontrado": nome, "preco_normal": preco_normal,
                    "preco_oferta": preco_oferta, "url": item.get("url") or item.get("link") or url_busca,
                    "ean": ean, "metodo_ean": metodo_ean, "supermercado": loja,
                })
        except Exception as e:
            logger.debug("raspar_diniz_api interceptar: %s", e)

    pagina.on("response", interceptar)
    try:
        pagina.goto(url_busca, timeout=30000)
        pagina.wait_for_load_state("networkidle", timeout=12000)
    except PlaywrightTimeoutError:
        pass
    try:
        pagina.remove_listener("response", interceptar)
    except Exception:
        pass
    return resultados_api


# ==========================================
# EXTRATORES DOM POR PLATAFORMA  (lista COMPLETA de produtos)
# ==========================================
# Limite generoso por loja (o usuario quer "dezenas e centenas" de produtos).
CAP_POR_LOJA = 150

# Sao Luiz roda na plataforma Mercadapp: cada card e um div.card-product com
# .current-price-product (preco atual) e .offer-price (preco antigo riscado).
_JS_CARDS_SAOLUIZ = r"""
() => {
  const cards = Array.from(document.querySelectorAll('div.card-product'));
  return cards.map(c => {
    const d = c.querySelector('.product-description');
    if(!d) return null;
    const ps = Array.from(d.querySelectorAll('p'));
    let nome='';
    for(let i=ps.length-1;i>=0;i--){const p=ps[i];const cn=(p.className||'');if(cn.indexOf('price')===-1){nome=(p.innerText||'').trim();break;}}
    const cur=d.querySelector('.current-price-product');
    const off=d.querySelector('.offer-price');
    const link=c.querySelector('a[href]');
    return {nome,
            atual: cur?(cur.innerText||'').replace(/\s+/g,' ').trim():'',
            antigo: off?(off.innerText||'').replace(/\s+/g,' ').trim():'',
            url: link?(link.getAttribute('href')||''):''};
  }).filter(x=>x && x.nome && x.nome.length>2);
}
"""

# Diniz roda na plataforma VipCommerce (Angular): card .vip-card-produto,
# nome em [data-cy="produto-descricao"] e preco em <vip-produto-preco>.
_JS_CARDS_DINIZ = r"""
() => {
  const cards = Array.from(document.querySelectorAll('.vip-card-produto'));
  return cards.map(c => {
    const nameEl=c.querySelector('[data-cy="produto-descricao"]')||c.querySelector('a[title]');
    const nome=nameEl?((nameEl.innerText||nameEl.getAttribute('title')||'').trim()):'';
    const priceEl=c.querySelector('vip-produto-preco');
    const precoTxt=priceEl?(priceEl.innerText||'').replace(/\s+/g,' ').trim():'';
    const link=c.querySelector('a[href*="/produto/"]');
    return {nome, precoTxt, url: link?(link.getAttribute('href')||''):''};
  }).filter(x=>x && x.nome && x.nome.length>2);
}
"""


def _precos_do_texto(txt: str) -> list:
    """Extrai valores monetarios (formato brasileiro 1.234,56) -> lista de floats."""
    vals = []
    for a in re.findall(r'(\d{1,3}(?:\.\d{3})*,\d{2})', txt or ""):
        try:
            vals.append(float(a.replace('.', '').replace(',', '.')))
        except Exception:
            pass
    return vals


def _fmt_preco(v: float) -> str:
    return f"R$ {v:.2f}".replace('.', ',')


# Atacadao (pagina de busca VTEX IO): card em section[data-testid="store-product-card-content"],
# nome no h3[title], preco no texto do card.
_JS_CARDS_ATACADAO = r"""
() => {
  const cards = Array.from(document.querySelectorAll('[data-testid="store-product-card-content"], section[data-product-card-content="true"]'));
  return cards.map(c => {
    const h3 = c.querySelector('h3[title]') || c.querySelector('h3');
    const nome = h3 ? ((h3.getAttribute('title')||h3.innerText||'').trim()) : '';
    let a = c.closest('a[href*="/p"]');
    if(!a){ const cont = c.closest('article,li,div'); a = cont ? cont.querySelector('a[href*="/p"]') : null; }
    const url = a ? (a.getAttribute('href')||'') : '';
    return {nome, precoTxt: (c.innerText||'').replace(/\s+/g,' ').trim(), url};
  }).filter(x=>x && x.nome && x.nome.length>2);
}
"""


def _limite_efetivo(limite) -> int:
    """None/0/'' -> traz TUDO (teto interno alto de seguranca contra loop)."""
    try:
        v = int(limite)
    except (TypeError, ValueError):
        v = 0
    return v if v and v > 0 else 100000


def _navegar_e_coletar(pagina, js: str, seletor_espera: str, limite=None,
                       ver_mais_textos=None, tempo_max_seg: int = 60) -> list:
    """
    Navega como uma pessoa: espera os cards, ROLA DE VERDADE (mouse.wheel + End,
    que dispara o lazy-load por IntersectionObserver) e clica em "Ver Mais"/
    paginacao enquanto existir. Para quando atinge o limite, a contagem
    estabiliza (sem botao pra clicar) ou estoura o tempo.
    """
    alvo = _limite_efetivo(limite)
    try:
        pagina.wait_for_selector(seletor_espera, timeout=15000)
    except Exception:
        pass
    ver_mais_textos = ver_mais_textos or []
    inicio = time.time()
    itens, estavel = [], 0
    for _ in range(400):  # teto duro de iteracoes (anti-loop)
        try:
            itens = pagina.evaluate(js) or itens
        except Exception:
            pass
        n = len(itens)
        if n >= alvo or (time.time() - inicio) > tempo_max_seg:
            break
        # 1) clica "Ver Mais"/paginacao se existir, visivel e habilitado
        clicou = False
        for txt in ver_mais_textos:
            try:
                btn = pagina.locator(f"button:has-text('{txt}'), a:has-text('{txt}')").first
                if btn.count() and btn.is_visible() and btn.is_enabled():
                    btn.click(timeout=3000)
                    clicou = True
                    break
            except Exception:
                pass
        # 2) rolagem real e PACIENTE (dispara o lazy-load por IntersectionObserver).
        #    Varias rodadas pequenas cruzam o "sentinel" melhor que um pulo unico.
        try:
            for _ in range(3):
                pagina.mouse.wheel(0, 2500)
                pagina.wait_for_timeout(300)
            pagina.keyboard.press("End")
        except Exception:
            pass
        pagina.wait_for_timeout(1200)
        try:
            novo = len(pagina.evaluate(js) or [])
        except Exception:
            novo = n
        if novo <= n and not clicou:
            estavel += 1
            if estavel >= 4:
                break
        else:
            estavel = 0
    try:
        itens = pagina.evaluate(js) or itens
    except Exception:
        pass
    return itens[:alvo] if alvo < 100000 else itens


def raspar_saoluiz_dom(produto: str, pagina, url_busca: str, limite=None, tempo_max=55) -> list:
    """Lista completa do loja oestes Sao Luiz (Mercadapp), clicando 'Ver Mais'."""
    loja = "loja oestes Sao Luiz"
    try:
        pagina.goto(url_busca, timeout=40000, wait_until="domcontentloaded")
    except Exception as e:
        logger.debug("saoluiz goto: %s", e)
    resultados = []
    brutos = _navegar_e_coletar(pagina, _JS_CARDS_SAOLUIZ, "div.card-product",
                                limite, ver_mais_textos=["Ver Mais", "Ver mais"],
                                tempo_max_seg=tempo_max)
    for it in brutos:
        atual = _precos_do_texto(it.get("atual", ""))
        antigo = _precos_do_texto(it.get("antigo", ""))
        if not atual:
            continue
        if antigo:
            preco_normal, preco_oferta = _fmt_preco(antigo[0]), _fmt_preco(atual[0])
        else:
            preco_normal, preco_oferta = _fmt_preco(atual[0]), "—"
        url = it.get("url", "") or url_busca
        if url.startswith("/"):
            url = "https://loja oestessaoluiz.com.br" + url
        resultados.append({
            "produto_encontrado": it["nome"], "preco_normal": preco_normal,
            "preco_oferta": preco_oferta, "url": url,
            "ean": "—", "metodo_ean": "—", "supermercado": loja,
        })
    return resultados


def raspar_diniz_dom(produto: str, pagina, url_busca: str, limite=None, tempo_max=55) -> list:
    """Lista completa do Diniz (VipCommerce). Rola como pessoa para carregar as
    proximas paginas e INTERCEPTA a API JSON de busca (dados limpos + EAN)."""
    loja = "Diniz Supermercados"
    alvo = _limite_efetivo(limite)
    coletados = {}  # produto_id -> dict bruto (dedup por id)

    def on_resp(resp):
        try:
            if "buscas/produtos/termo" not in resp.url:
                return
            if "application/json" not in resp.headers.get("content-type", ""):
                return
            data = ((resp.json() or {}).get("data") or {})
            for p in data.get("produtos", []) or []:
                pid = p.get("produto_id") or p.get("id")
                if pid is not None:
                    coletados[pid] = p
        except Exception as e:
            logger.debug("diniz on_resp: %s", e)

    pagina.on("response", on_resp)
    try:
        pagina.goto(url_busca, timeout=40000, wait_until="domcontentloaded")
        pagina.wait_for_selector(".vip-card-produto", timeout=15000)
    except Exception as e:
        logger.debug("diniz goto: %s", e)
    # Rola de verdade (End + wheel) para o app buscar as proximas paginas.
    inicio, estavel, anterior = time.time(), 0, -1
    while (time.time() - inicio) < tempo_max:
        n = len(coletados)
        if n >= alvo:
            break
        if n == anterior:
            estavel += 1
            if estavel >= 4:
                break
        else:
            estavel = 0
        anterior = n
        try:
            pagina.keyboard.press("End")
            pagina.mouse.wheel(0, 3000)
        except Exception:
            pass
        pagina.wait_for_timeout(900)
    try:
        pagina.remove_listener("response", on_resp)
    except Exception:
        pass

    resultados = []
    for p in coletados.values():
        nome = (p.get("descricao") or "").strip()
        if not nome:
            continue
        try:
            preco = float(str(p.get("preco") or "0").replace(",", "."))
        except Exception:
            preco = 0.0
        if preco <= 0:
            continue
        preco_normal, preco_oferta = _fmt_preco(preco), "—"
        if p.get("em_oferta") and p.get("preco_original"):
            try:
                orig = float(str(p.get("preco_original")).replace(",", "."))
                if orig > preco:
                    preco_normal, preco_oferta = _fmt_preco(orig), _fmt_preco(preco)
            except Exception:
                pass
        ean = str(p.get("codigo_barras") or "").strip()
        ean_ok = ean if validar_ean(ean) else "—"
        slug = p.get("link") or ""
        url = (f"https://www.dinizsupermercados.com.br/produto/{p.get('produto_id')}/{slug}"
               if slug else url_busca)
        resultados.append({
            "produto_encontrado": nome, "preco_normal": preco_normal,
            "preco_oferta": preco_oferta, "url": url,
            "ean": ean_ok, "metodo_ean": ("VipCommerce API" if ean_ok != "—" else "—"),
            "supermercado": loja,
        })
    return resultados[:alvo] if alvo < 100000 else resultados


def raspar_atacadao_dom(produto: str, pagina, limite=None, tempo_max=55) -> list:
    """Fallback do Atacadao: navega a pagina de busca e le os cards do DOM
    (usado quando a API VTEX bloqueia/retorna 400/403)."""
    loja = "Atacadao"
    url = f"https://www.atacadao.com.br/s?q={quote_plus(produto)}&sort=score_desc&page=0"
    try:
        pagina.goto(url, timeout=40000, wait_until="domcontentloaded")
    except Exception as e:
        logger.debug("atacadao dom goto: %s", e)
    for txt in ("Aceitar", "Prosseguir", "Concordo"):
        try:
            b = pagina.locator(f"button:has-text('{txt}')").first
            if b.count() and b.is_visible():
                b.click(timeout=2000)
                break
        except Exception:
            pass
    resultados = []
    for it in _navegar_e_coletar(pagina, _JS_CARDS_ATACADAO,
                                 '[data-testid="store-product-card-content"]', limite,
                                 tempo_max_seg=tempo_max):
        precos = _precos_do_texto(it.get("precoTxt", ""))
        if not precos:
            continue
        if len(precos) >= 2:
            preco_normal, preco_oferta = _fmt_preco(max(precos)), _fmt_preco(min(precos))
        else:
            preco_normal, preco_oferta = _fmt_preco(precos[0]), "—"
        url_p = it.get("url", "") or url
        if url_p.startswith("/"):
            url_p = "https://www.atacadao.com.br" + url_p
        resultados.append({
            "produto_encontrado": it["nome"], "preco_normal": preco_normal,
            "preco_oferta": preco_oferta, "url": url_p,
            "ean": "—", "metodo_ean": "DOM (navegador)", "supermercado": loja,
        })
    return resultados


def ordenar_por_relevancia(produto_busca: str, resultados: list) -> list:
    """Ordena por relevancia NLP mantendo TODOS os itens (nao descarta nada)."""
    for r in resultados:
        r["nlp_score"] = ComparadorInteligenteProdutos.calcular_relevancia(
            produto_busca, r.get("produto_encontrado", ""))
    resultados.sort(key=lambda x: x.get("nlp_score", 0.0), reverse=True)
    return resultados


def _fallback_ia_extrair(pagina, produto: str, loja: str) -> list:
    """IA ATUANDO NA BUSCA: se a extracao por DOM falhar, a IA le o texto
    renderizado da pagina e extrai os produtos com preco."""
    if not _existe_alguma_ia():
        return []
    try:
        texto = (pagina.inner_text("body") or "")[:6000]
    except Exception:
        return []
    if "R$" not in texto:
        return []
    resp = ia_chat(
        [
            {"role": "system", "content": (
                "Voce extrai produtos de uma pagina de supermercado a partir do TEXTO dela.\n"
                "Responda APENAS JSON: {\"produtos\":[{\"nome\":\"...\",\"preco\":\"R$ 0,00\",\"oferta\":\"R$ 0,00 ou -\"}]}\n"
                "Inclua todos os produtos com preco visiveis. Nao invente precos."
            )},
            {"role": "user", "content": f"Produto buscado: {produto}\nLoja: {loja}\n\nTEXTO:\n{texto}"},
        ],
        temperatura=0.0, max_tokens=900, force_json=True,
        ordem=["groq", "openai", "gemini", "openrouter", "huggingface"],
    )
    dados = _extrair_json(resp) or {}
    out = []
    for p in dados.get("produtos", []):
        nome = (p.get("nome") or "").strip()
        preco = (p.get("preco") or "").strip()
        if not nome or not preco:
            continue
        oferta = (p.get("oferta") or "—").strip()
        if oferta in ("-", "", "R$ 0,00", "0"):
            oferta = "—"
        out.append({
            "produto_encontrado": nome, "preco_normal": preco, "preco_oferta": oferta,
            "url": "", "ean": "—", "metodo_ean": "IA (leitura da pagina)", "supermercado": loja,
        })
    return out


# ==========================================
# IDENTIFICADOR DE CONCORRENTE POR URL  (FIX #1/#2: definida UMA vez)
# ==========================================
def _identificar_concorrente_por_url(url: str):
    for dominio, chave in DOMINIOS_CONCORRENTES.items():
        if dominio in url:
            return chave
    return None


# ==========================================
# EXTRATOR DE PRECO POR PAGINA DE PRODUTO  (FIX #1/#2: definida UMA vez)
# ==========================================
def extrair_preco_pagina_produto(url: str, pagina, contexto):
    """Abre a URL do produto no site do concorrente e extrai nome + preco."""
    chave_conc = _identificar_concorrente_por_url(url)
    if not chave_conc:
        return None
    loja = CONCORRENTES[chave_conc]["nome"]
    sniffer_eans = []

    def interceptar_resp(resp):
        if "application/json" in resp.headers.get("content-type", ""):
            try:
                eans = [oc for oc in RE_GTIN_JSON.findall(str(resp.json())) if validar_ean(oc)]
                if eans:
                    sniffer_eans.extend(eans)
            except Exception:
                pass

    pagina_prod = None
    try:
        pagina_prod = contexto.new_page()
        pagina_prod.on("response", interceptar_resp)
        pagina_prod.goto(url, timeout=25000, wait_until="domcontentloaded")
        # FIX #5: substituído time.sleep(2) por wait_for_timeout do Playwright
        pagina_prod.wait_for_timeout(2000)

        # Extrai nome do produto
        nome = None
        for sel in ["h1", "[class*='product-name']", "[class*='titulo']",
                    "[class*='title']", "[itemprop='name']", "[class*='nome']"]:
            try:
                el = pagina_prod.locator(sel).first
                if el.count() > 0:
                    t = el.inner_text().strip()
                    if len(t) > 3:
                        nome = t
                        break
            except Exception:
                pass

        texto_body = pagina_prod.inner_text("body")

        # FIX #6: extração de preço mais precisa — busca preço próximo ao nome/h1,
        # ignorando preços de rodapé, frete e produtos relacionados.
        preco_normal, preco_oferta = "—", "—"
        precos_encontrados = re.findall(r'R\$\s*(\d+[.,]\d{2})', texto_body)
        if precos_encontrados:
            # Converte e filtra valores claramente absurdos (frete < R$5 ou >R$9999)
            valores_validos = []
            for p in precos_encontrados:
                try:
                    v = float(p.replace(',', '.'))
                    if 5.0 <= v <= 9999.0:
                        valores_validos.append(v)
                except ValueError:
                    pass
            valores_unicos = sorted(set(valores_validos))
            if len(valores_unicos) >= 2:
                # Assume: menor = preço com oferta, maior = preço normal/de
                preco_normal = f"R$ {max(valores_unicos):.2f}".replace('.', ',')
                preco_oferta = f"R$ {min(valores_unicos):.2f}".replace('.', ',')
            elif len(valores_unicos) == 1:
                preco_normal = f"R$ {valores_unicos[0]:.2f}".replace('.', ',')

        ean, metodo_ean = "—", "—"
        if sniffer_eans:
            ean, metodo_ean = sniffer_eans[0], "Nivel 5.1 (Sniffer)"
        else:
            for oc in re.findall(r'(?i)(?:EAN|GTIN|barcode)[^\d]{0,30}(\d{8,14})', texto_body):
                if validar_ean(oc):
                    ean, metodo_ean = oc, "Nivel 5.2 (Texto visivel)"
                    break

        pagina_prod.close()
        if preco_normal == "—":
            return None
        return {
            "supermercado": loja,
            "produto_encontrado": nome or url.split("/")[-1].replace("-", " ").title(),
            "preco_normal": preco_normal,
            "preco_oferta": preco_oferta,
            "url": url,
            "ean": ean,
            "metodo_ean": metodo_ean,
        }
    except Exception as e:
        logger.debug("extrair_preco_pagina_produto: %s", e)
        try:
            if pagina_prod:
                pagina_prod.close()
        except Exception:
            pass
        return None


# ==========================================
# BUSCA NO GOOGLE/DDG/BING + CONFRONTO DE PRECOS
# ==========================================
def _coletar_links_google(produto: str, pagina) -> list:
    """Tenta Google, DuckDuckGo e Bing para coletar links dos concorrentes."""
    dominios_str = " OR ".join(f"site:{d}" for d in DOMINIOS_CONCORRENTES.keys())
    query = f"{produto} ({dominios_str})"
    links = []

    motores = [
        ("Google",     f"https://www.google.com/search?q={quote_plus(query)}&num=20&hl=pt-BR"),
        ("DuckDuckGo", f"https://duckduckgo.com/?q={quote_plus(query)}&kl=br-pt"),
        ("Bing",       f"https://www.bing.com/search?q={quote_plus(query)}&mkt=pt-BR&count=20"),
    ]

    for nome_motor, url_busca in motores:
        print(f"   {Fore.CYAN}Tentando {nome_motor}...{Style.RESET_ALL}", end="", flush=True)
        try:
            pagina.goto(url_busca, timeout=25000)
            pagina.wait_for_load_state("domcontentloaded", timeout=10000)
            # FIX #5: substituído time.sleep(2) por wait_for_timeout do Playwright
            pagina.wait_for_timeout(2000)
            hrefs = pagina.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            encontrados = [
                h for h in hrefs
                if h and "google" not in h and "bing.com" not in h
                and "duckduckgo" not in h and "javascript" not in h
                and _identificar_concorrente_por_url(h) and h not in links
            ]
            links.extend(encontrados)
            print(f" {len(encontrados)} link(s)")
            logger.info("Motor %s: %d link(s) encontrado(s).", nome_motor, len(encontrados))
            if links:
                break  # Achou links, nao precisa tentar outros motores
        except Exception as e:
            print(f" {Fore.RED}Erro: {str(e)[:50]}{Style.RESET_ALL}")
            logger.warning("Motor %s falhou: %s", nome_motor, e)

    # Fallback: busca diretamente nos sites se nenhum motor funcionou
    if not links:
        print(f"   {Fore.YELLOW}Motores de busca bloquearam. Buscando diretamente nos sites...{Style.RESET_ALL}")
        urls_diretas = {
            "diniz":    f"https://www.dinizsupermercados.com.br/busca?termo={quote(produto)}",
            "saoluiz":  f"https://loja oestessaoluiz.com.br/loja/355?search={quote_plus(produto)}",
            "atacadao": f"https://www.atacadao.com.br/s?q={quote_plus(produto)}",
        }
        for url in urls_diretas.values():
            links.append(url)

    return links


def buscar_google_e_confrontar(produto: str, pagina, contexto) -> list:
    """
    Busca o produto em motores de busca (Google/DuckDuckGo/Bing) filtrando
    apenas links dos concorrentes, depois abre cada link e extrai o preco.
    Se os motores bloquearem, busca diretamente nos sites.
    """
    print(f"\n{Fore.CYAN}Pesquisando: '{produto}' nos concorrentes...{Style.RESET_ALL}")
    logger.info("buscar_google_e_confrontar: '%s'", produto)
    links = _coletar_links_google(produto, pagina)

    if not links:
        print(f"   {Fore.RED}Nao foi possivel encontrar links.{Style.RESET_ALL}")
        return []

    print(f"   {Fore.GREEN}{len(links)} link(s)/URL(s) para verificar.{Style.RESET_ALL}")
    resultados = []
    urls_visitadas = set()

    for idx, url_item in enumerate(links[:12]):
        if url_item in urls_visitadas:
            continue
        urls_visitadas.add(url_item)
        chave = _identificar_concorrente_por_url(url_item)
        loja_nome = CONCORRENTES.get(chave, {}).get("nome", "?") if chave else "?"

        # Se a URL e uma pagina de BUSCA (nao produto especifico), usa o raspador de catalogo
        eh_pagina_busca = any(kw in url_item for kw in ["busca?", "search=", "/s?q=", "searching"])

        if eh_pagina_busca:
            print(f"   {Fore.CYAN}[{idx+1}] {loja_nome}: raspando catalogo de busca...{Style.RESET_ALL}")
            cfg = CONCORRENTES.get(chave, {})
            res_cat = raspar_concorrente(produto, chave, cfg, pagina, contexto)
            for r in res_cat:
                score = ComparadorInteligenteProdutos.calcular_relevancia(produto, r.get("produto_encontrado", ""))
                # FIX #7: limiar unificado via constante NLP_LIMIAR_PADRAO
                if score >= NLP_LIMIAR_PADRAO:
                    r["nlp_score"] = score
                    resultados.append(r)
                    print(f"      {Fore.GREEN}OK: {r['produto_encontrado'][:50]} — {r['preco_normal']}{Style.RESET_ALL}")
        else:
            print(f"   {Fore.CYAN}[{idx+1}] {loja_nome}: {url_item[:65]}...{Style.RESET_ALL}")
            dados = extrair_preco_pagina_produto(url_item, pagina, contexto)
            if dados:
                score = ComparadorInteligenteProdutos.calcular_relevancia(produto, dados["produto_encontrado"])
                # FIX #7: limiar unificado via constante NLP_LIMIAR_PADRAO
                if score >= NLP_LIMIAR_PADRAO:
                    dados["nlp_score"] = score
                    resultados.append(dados)
                    print(f"      {Fore.GREEN}OK: {dados['produto_encontrado'][:50]} — {dados['preco_normal']}{Style.RESET_ALL}")
                else:
                    print(f"      {Fore.YELLOW}Score baixo ({score:.2f}): {dados['produto_encontrado'][:50]}{Style.RESET_ALL}")
            else:
                print(f"      {Fore.RED}Sem preco encontrado.{Style.RESET_ALL}")

    resultados.sort(key=lambda r: r.get("nlp_score", 0.0), reverse=True)
    return resultados


# ==========================================
# RASPAGEM PRINCIPAL (CATALOGO)
# ==========================================
def extrair_dados_card(texto_card: str, html_card: str, url_produto: str, configuracao: dict) -> dict:
    if configuracao.get("seletor_titulo") or configuracao.get("seletor_preco"):
        sopa = BeautifulSoup(html_card, 'html.parser')
        nome = None
        preco_normal = None
        preco_oferta = "—"
        ean, metodo_ean = None, "—"
        if configuracao.get("seletor_titulo"):
            el = sopa.select_one(configuracao["seletor_titulo"])
            if el:
                nome = el.get_text().strip()
        if configuracao.get("seletor_preco"):
            el = sopa.select_one(configuracao["seletor_preco"])
            if el:
                preco_normal = el.get_text().strip()
        if nome and preco_normal:
            if url_produto and configuracao.get("expressao_regular_ean_url"):
                oc = re.search(configuracao["expressao_regular_ean_url"], url_produto)
                if oc and validar_ean(oc.group(1)):
                    ean, metodo_ean = oc.group(1), "Nivel 1 (URL)"
            if not ean:
                oc = RE_DATA_EAN.search(html_card)
                if oc and validar_ean(oc.group(1)):
                    ean, metodo_ean = oc.group(1), "Nivel 2 (Atributo Card)"
            return {"produto_encontrado": nome, "preco_normal": preco_normal, "preco_oferta": preco_oferta, "url": url_produto, "ean": ean, "metodo_ean": metodo_ean}

    linhas = [l.strip() for l in texto_card.split('\n') if l.strip()]
    precos, candidatos_nome = [], []
    ean, metodo_ean = None, "—"
    IGNORADOS = {"adicionar", "comprar", "esgotado", "ver detalhes", "un", "/ cada", "/cada", "cada", "kg", "lt", "un.", "g"}
    for linha in linhas:
        oc = re.search(r'R\$\s*\d+[.,]\d{2}', linha, re.IGNORECASE)
        if oc:
            precos.append(oc.group())
            continue
        lm = linha.lower().strip()
        if lm in IGNORADOS:
            continue
        if re.fullmatch(r'[/\s]*(cada|un\.?|kg|g|lt?)[/\s]*', lm):
            continue
        if re.fullmatch(r'\d+\s*(g|kg|ml|l|lt|und)', lm):
            continue
        if len(linha) > 4 and "%" not in linha:
            candidatos_nome.append(linha)
    if not precos or not candidatos_nome:
        return None
    nome = candidatos_nome[0]
    if "oferta" in nome.lower() or "leve" in nome.lower():
        if len(candidatos_nome) > 1:
            nome = candidatos_nome[1]
    if len(precos) > 1:
        def cvt(p):
            try:
                return float(re.sub(r"[^\d,.]", "", p).replace(",", "."))
            except Exception:
                return 0.0
        v1, v2 = cvt(precos[0]), cvt(precos[1])
        preco_normal = precos[0] if v1 > v2 else precos[1]
        preco_oferta = precos[1] if v1 > v2 else precos[0]
    else:
        preco_normal, preco_oferta = precos[0], "—"
    if url_produto and configuracao.get("expressao_regular_ean_url"):
        oc = re.search(configuracao["expressao_regular_ean_url"], url_produto)
        if oc and validar_ean(oc.group(1)):
            ean, metodo_ean = oc.group(1), "Nivel 1 (URL)"
    if not ean:
        oc = RE_DATA_EAN.search(html_card)
        if oc and validar_ean(oc.group(1)):
            ean, metodo_ean = oc.group(1), "Nivel 2 (Atributo Card)"
    return {"produto_encontrado": nome, "preco_normal": preco_normal, "preco_oferta": preco_oferta, "url": url_produto, "ean": ean, "metodo_ean": metodo_ean}


def _extrair_url_produto_sao_luiz(pagina, locator_card, html_card, url_base):
    url_analisada = urlparse(url_base)
    base = f"{url_analisada.scheme}://{url_analisada.netloc}"
    oc = RE_HREF_PRODUTO.search(html_card)
    if oc:
        link = oc.group(1)
        return (base + link) if link.startswith("/") else link
    try:
        el = locator_card.locator("a[href*='/produto/']").first
        if el.count() > 0:
            link = el.get_attribute("href") or ""
            if link:
                return (base + link) if link.startswith("/") else link
    except Exception:
        pass
    return None


def raspar_concorrente(produto: str, chave: str, configuracao: dict, pagina, contexto,
                       limite=None, callback_status=None, tempo_max=55) -> list:
    loja = configuracao["nome"]
    url_base = configuracao["url_busca"].replace("{produto}", configuracao["codificador"](produto))
    usa_clique = configuracao.get("clicar_no_produto", False)
    print(f"\n{Fore.CYAN}Varrendo catalogo de {loja}...{Style.RESET_ALL}")
    logger.info("Raspando '%s' em %s.", produto, loja)

    # ── DISPATCH POR LOJA: navega como pessoa e traz a lista COMPLETA ────────
    if chave == "diniz":
        res = raspar_diniz_dom(produto, pagina, url_base, limite, tempo_max)
        if not res:
            print(f"   {Fore.YELLOW}Diniz: DOM vazio, tentando leitura por IA...{Style.RESET_ALL}")
            res = _fallback_ia_extrair(pagina, produto, loja)
        if res:
            res = ordenar_por_relevancia(produto, res)
            print(f"   {Fore.GREEN}Diniz: {len(res)} produto(s).{Style.RESET_ALL}")
            return res
        return []

    if chave == "saoluiz":
        res = raspar_saoluiz_dom(produto, pagina, url_base, limite, tempo_max)
        if not res:
            print(f"   {Fore.YELLOW}Sao Luiz: DOM vazio, tentando leitura por IA...{Style.RESET_ALL}")
            res = _fallback_ia_extrair(pagina, produto, loja)
        if res:
            res = ordenar_por_relevancia(produto, res)
            print(f"   {Fore.GREEN}Sao Luiz: {len(res)} produto(s).{Style.RESET_ALL}")
            return res
        return []

    if chave == "atacadao":
        # 1) API VTEX (rapida). 2) se bloquear/vier vazia, NAVEGA a pagina de
        # busca e le o DOM. 3) se ainda vazio, a IA le a pagina. Fim do
        # "as vezes vem, as vezes nao".
        res = raspar_atacadao_api(produto, limite)
        origem = "VTEX API"
        if not res:
            if callback_status:
                callback_status("🚫 Atacadao: API bloqueou — abrindo no navegador...")
            print(f"   {Fore.YELLOW}Atacadao: API vazia/bloqueada, indo pelo navegador...{Style.RESET_ALL}")
            res = raspar_atacadao_dom(produto, pagina, limite, tempo_max)
            origem = "navegador (DOM)"
        if not res:
            res = _fallback_ia_extrair(pagina, produto, loja)
            origem = "IA (leitura da pagina)"
        if res:
            res = ordenar_por_relevancia(produto, res)
            print(f"   {Fore.GREEN}Atacadao: {len(res)} produto(s) via {origem}.{Style.RESET_ALL}")
            return res
        if callback_status:
            callback_status("⚠️ Atacadao: bloqueado (sem resultado)")
        return []

    if chave == "assai":
        # Assai (atacadao) nao tem loja online com precos: dados apenas via
        # Encartes (PDF) na aba propria. A busca online fica vazia de proposito.
        logger.info("Assai: sem busca de produto online; use a aba Encartes.")
        return []

    # ── Carrefour e demais lojas VTEX: API generica ─────────────────────────
    if chave == "carrefour":
        res = _raspar_vtex_generico(produto, chave, configuracao)
        if res:
            filtrados = filtrar_e_ordenar_por_nlp(produto, res)
            if filtrados:
                print(f"   {Fore.GREEN}Extracao concluida via VTEX API ({loja}). {len(filtrados)} item(ns).{Style.RESET_ALL}")
                return filtrados[:CAP_POR_LOJA]

    # ── Lojas com Google Search como estrategia principal ───────────────────
    if configuracao.get("usar_google_search"):
        dominio = next((d for d, c in DOMINIOS_CONCORRENTES.items() if c == chave), "")
        if dominio:
            urls_google = buscar_produto_google_simples(produto, loja, dominio, pagina)
            if urls_google:
                resultados_google = []
                for url_g in urls_google[:4]:
                    dados_g = extrair_preco_pagina_produto(url_g, pagina, contexto)
                    if dados_g:
                        score = ComparadorInteligenteProdutos.calcular_relevancia(produto, dados_g["produto_encontrado"])
                        if score >= NLP_LIMIAR_PADRAO:
                            dados_g["nlp_score"] = score
                            resultados_google.append(dados_g)
                if resultados_google:
                    resultados_google.sort(key=lambda x: x.get("nlp_score", 0), reverse=True)
                    print(f"   {Fore.GREEN}Google Barra: {len(resultados_google)} produto(s) encontrado(s) em {loja}.{Style.RESET_ALL}")
                    return resultados_google[:6]

    # ── Sao Luiz e fallback: Playwright ─────────────────────────────────────
    resultados = []
    resultados_api_busca = []

    def interceptar_busca(resp_rede):
        if "items/search" in resp_rede.url and "application/json" in resp_rede.headers.get("content-type", ""):
            try:
                dados = resp_rede.json()
                for mix in dados.get("mixes", []):
                    for item in mix.get("items", []):
                        nome = item.get("description", "—").strip()
                        preco_n = item.get("price")
                        preco_o = "—"
                        if item.get("is_offer", False) and item.get("original_price") and item.get("price") != item.get("original_price"):
                            preco_o = f"R$ {item.get('price')}"
                            preco_n = f"R$ {item.get('original_price')}"
                        else:
                            preco_n = f"R$ {preco_n}" if preco_n else "—"
                        ean = str(item.get("bar_code") or item.get("market_system_code") or "—").strip()
                        metodo_ean = "—"
                        if ean != "—" and validar_ean(ean):
                            metodo_ean = "Nivel 5.3 (API JSON de Busca)"
                        else:
                            ean = "—"
                        slug = item.get("slug")
                        url_prod = f"https://loja oestessaoluiz.com.br/produto/{slug}" if slug else url_base
                        resultados_api_busca.append({
                            "produto_encontrado": nome, "preco_normal": preco_n, "preco_oferta": preco_o,
                            "url": url_prod, "ean": ean, "metodo_ean": metodo_ean, "supermercado": loja
                        })
            except Exception as e:
                logger.debug("interceptar_busca saoluiz: %s", e)

    if chave == "saoluiz":
        pagina.on("response", interceptar_busca)

    try:
        pagina.goto(url_base, timeout=30000, wait_until="domcontentloaded")
        pagina.wait_for_load_state("domcontentloaded", timeout=8000)
    except (PlaywrightTimeoutError, Exception):
        pass

    if chave == "saoluiz":
        try:
            pagina.remove_listener("response", interceptar_busca)
        except Exception:
            pass
        if resultados_api_busca:
            vistos = set()
            filtrados = []
            for item in resultados_api_busca:
                k = (item["produto_encontrado"], item["preco_normal"])
                if k not in vistos and len(item["produto_encontrado"]) > 4:
                    vistos.add(k)
                    filtrados.append(item)
            if filtrados:
                filtrados_nlp = filtrar_e_ordenar_por_nlp(produto, filtrados)
                print(f"   {Fore.GREEN}Extracao via API JSON. {len(filtrados_nlp[:6])} item(ns).{Style.RESET_ALL}")
                return filtrados_nlp[:6]

    # Scroll limitado a 2 paginas para evitar scroll infinito
    for _ in range(2):
        try:
            pagina.evaluate("window.scrollBy(0, 900);")
            pagina.wait_for_timeout(700)
        except Exception:
            break

    seletor_card = configuracao.get("seletor_card")
    if seletor_card:
        locators_cards = pagina.locator(seletor_card)
    else:
        locators_cards = pagina.locator(
            "xpath=//*[contains(text(), 'R$')]/ancestor::div[contains(@class, 'product') or contains(@class, 'item') or contains(@class, 'card')]"
            " | //*[contains(text(), 'R$')]/ancestor::li"
        )
    qtd = locators_cards.count()
    if qtd == 0 and not seletor_card:
        locators_cards = pagina.locator("xpath=//*[contains(text(), 'R$')]/..")
        qtd = locators_cards.count()

    if qtd == 0 and cliente_openai:
        cfg_aprendida = tentar_auto_aprendizado(chave, pagina.inner_html("body"))
        if cfg_aprendida:
            salvar_seletor_personalizado(chave, cfg_aprendida)
            configuracao.update(cfg_aprendida)
            seletor_card = cfg_aprendida.get("seletor_card")
            if seletor_card:
                locators_cards = pagina.locator(seletor_card)
                qtd = locators_cards.count()

    textos_vistos, urls_vistas, itens_profundos = set(), set(), []
    max_itens, inseridos = 6, 0

    for idx in range(qtd):
        if inseridos >= max_itens:
            break
        locator = locators_cards.nth(idx)
        try:
            texto = locator.inner_text(timeout=3000)
        except Exception:
            continue
        if not texto or texto in textos_vistos or "R$" not in texto:
            continue
        textos_vistos.add(texto)
        try:
            html_card = locator.inner_html(timeout=3000)
        except Exception:
            html_card = ""
        url_prod = None
        if usa_clique:
            url_prod = _extrair_url_produto_sao_luiz(pagina, locator, html_card, url_base)
        else:
            link_url = None
            sel_link = configuracao.get("seletor_link")
            if sel_link:
                try:
                    el = locator.locator(sel_link).first
                    link_url = el.get_attribute("href") if el.count() > 0 else None
                except Exception:
                    pass
            else:
                try:
                    el = locator.locator("a[href]").first
                    if el.count() > 0:
                        link_url = el.get_attribute("href")
                    else:
                        oc = RE_HREF_GERAL.search(html_card)
                        link_url = oc.group(1) if oc else None
                except Exception:
                    pass
            if link_url and len(link_url) > 2 and "javascript" not in link_url:
                if link_url.startswith("/"):
                    ua = urlparse(url_base)
                    url_prod = f"{ua.scheme}://{ua.netloc}{link_url}"
                elif "http" in link_url:
                    url_prod = link_url

        if url_prod in urls_vistas and url_prod:
            continue
        if url_prod:
            urls_vistas.add(url_prod)

        dados = extrair_dados_card(texto, html_card, url_prod, configuracao)
        if dados:
            dados["supermercado"] = loja
            resultados.append(dados)
            inseridos += 1
            if not dados["ean"] or dados["ean"] == "—":
                itens_profundos.append(dados)

    if itens_profundos:
        com_url = sum(1 for x in itens_profundos if x.get("url"))
        sem_url = len(itens_profundos) - com_url
        print(f"   {Fore.YELLOW}Busca profunda para {len(itens_profundos)} produto(s) ({com_url} com URL, {sem_url} sem)...{Style.RESET_ALL}")
        for item in itens_profundos:
            ean_e, metodo = "—", "Falha"
            if item.get("url"):
                ean_e, metodo = buscar_ean_profundo(item["url"], contexto)
            if ean_e == "—" or ean_e is None:
                ean_e, metodo = buscar_ean_por_nome(item["produto_encontrado"])
            item["ean"] = ean_e
            item["metodo_ean"] = metodo

    filtrados_nlp = filtrar_e_ordenar_por_nlp(produto, resultados)
    if filtrados_nlp:
        print(f"   {Fore.GREEN}Extracao concluida. {len(filtrados_nlp[:6])} item(ns).{Style.RESET_ALL}")
        return filtrados_nlp[:6]

    # ── Ultimo recurso: Google Barra + Screenshot OCR ────────────────────────
    # Se nao for loja com google_search (ja tentou acima) e nao for loja com API
    if not configuracao.get("usar_google_search") and chave not in ("atacadao", "assai", "carrefour"):
        dominio = next((d for d, c in DOMINIOS_CONCORRENTES.items() if c == chave), "")
        if dominio:
            print(f"   {Fore.YELLOW}Playwright sem resultado. Tentando Google Barra...{Style.RESET_ALL}")
            urls_google = buscar_produto_google_simples(produto, loja, dominio, pagina)
            for url_g in urls_google[:4]:
                dados_g = extrair_preco_pagina_produto(url_g, pagina, contexto)
                if dados_g:
                    score = ComparadorInteligenteProdutos.calcular_relevancia(produto, dados_g["produto_encontrado"])
                    if score >= NLP_LIMIAR_PADRAO:
                        dados_g["nlp_score"] = score
                        resultados.append(dados_g)

    # ── Visao por IA: screenshot se ainda vazio ──────────────────────────────
    if not resultados and (cliente_openai or _gemini_disponivel):
        # Volta para a pagina de busca da loja antes do screenshot
        try:
            pagina.goto(url_base, timeout=20000)
            pagina.wait_for_timeout(2000)
        except Exception:
            pass
        lidos = ia_ler_screenshot_pagina(pagina, produto, loja)
        if lidos:
            filtrados_vision = filtrar_e_ordenar_por_nlp(produto, lidos)
            if filtrados_vision:
                print(f"   {Fore.MAGENTA}[IA Vision] {len(filtrados_vision[:6])} produto(s) via leitura visual.{Style.RESET_ALL}")
                return filtrados_vision[:6]

    if resultados:
        filtrados_final = filtrar_e_ordenar_por_nlp(produto, resultados)
        print(f"   {Fore.GREEN}Extracao concluida (Google+Vision). {len(filtrados_final[:6])} item(ns).{Style.RESET_ALL}")
        return filtrados_final[:6]

    print(f"   {Fore.YELLOW}Nenhum produto encontrado em {loja} apos todos os metodos.{Style.RESET_ALL}")
    return []


# ==========================================
# RASPAGEM POR CATEGORIA
# ==========================================
def raspar_categoria(url_categoria: str, chave: str, configuracao: dict, pagina, contexto) -> list:
    loja = configuracao["nome"]
    print(f"\n{Fore.CYAN}Carregando categoria de {loja}...{Style.RESET_ALL}")
    resultados, urls_vistas = [], set()
    try:
        pagina.goto(url_categoria, timeout=30000)
        pagina.wait_for_load_state("networkidle", timeout=12000)
    except PlaywrightTimeoutError:
        pass
    numero_pag = 1
    MAX_PAGINAS = 20  # evita varredura infinita quando o botao "proxima" nunca desabilita
    while numero_pag <= MAX_PAGINAS:
        print(f"   {Fore.YELLOW}Pagina {numero_pag}...{Style.RESET_ALL}", end="", flush=True)
        for _ in range(6):
            pagina.evaluate("window.scrollBy(0, 900);")
            pagina.wait_for_timeout(600)
        locators = pagina.locator(
            "xpath=//*[contains(text(), 'R$')]/ancestor::div[contains(@class, 'product') or contains(@class, 'item') or contains(@class, 'card')]"
            " | //*[contains(text(), 'R$')]/ancestor::li"
        )
        qtd = locators.count()
        if qtd == 0:
            locators = pagina.locator("xpath=//*[contains(text(), 'R$')]/..")
            qtd = locators.count()
        novos, busca_prof = 0, []
        for idx in range(qtd):
            loc = locators.nth(idx)
            texto = loc.inner_text()
            if not texto or "R$" not in texto:
                continue
            html_card = loc.inner_html()
            url_prod = None
            if configuracao.get("clicar_no_produto"):
                url_prod = _extrair_url_produto_sao_luiz(pagina, loc, html_card, pagina.url)
            else:
                try:
                    el = loc.locator("a[href]").first
                    link = el.get_attribute("href") if el.count() > 0 else None
                    if not link:
                        oc = RE_HREF_GERAL.search(html_card)
                        link = oc.group(1) if oc else None
                    if link and "javascript" not in link:
                        ua = urlparse(pagina.url)
                        url_prod = (f"{ua.scheme}://{ua.netloc}{link}" if link.startswith("/") else link)
                except Exception:
                    pass
            if url_prod in urls_vistas and url_prod:
                continue
            if url_prod:
                urls_vistas.add(url_prod)
            dados = extrair_dados_card(texto, html_card, url_prod, configuracao)
            if dados:
                dados["supermercado"] = loja
                resultados.append(dados)
                novos += 1
                if not dados["ean"]:
                    busca_prof.append(dados)
        print(f" {novos} itens")
        # Se a pagina nao trouxe nenhum item novo, encerra (evita loop preso na mesma pagina)
        if novos == 0:
            break
        for item in busca_prof:
            ean, metodo = "—", "Falha"
            if item.get("url"):
                ean, metodo = buscar_ean_profundo(item["url"], contexto)
            if ean == "—" or ean is None:
                ean, metodo = buscar_ean_por_nome(item["produto_encontrado"])
            item["ean"] = ean
            item["metodo_ean"] = metodo
        try:
            btn = pagina.locator(
                "xpath=//a[contains(@aria-label,'prox') or contains(text(),'Proxima') or contains(@rel,'next')]"
                " | //button[contains(text(),'Proxima')]"
            )
            if btn.count() > 0 and btn.first.is_enabled():
                btn.first.click()
                pagina.wait_for_load_state("networkidle", timeout=10000)
                numero_pag += 1
            else:
                break
        except Exception:
            break
    print(f"   {Fore.GREEN}Categoria concluida. {len(resultados)} produto(s).{Style.RESET_ALL}")
    return resultados


# ==========================================
# ENCARTES PDF
# ==========================================
def buscar_encartes_saoluiz(pagina, contexto) -> list:
    print(f"\n{Fore.CYAN}Buscando encartes do loja oestes Sao Luiz...{Style.RESET_ALL}")
    resultados = []
    try:
        pagina.goto("https://loja oestessaoluiz.com.br/loja/355", timeout=30000)
        pagina.wait_for_load_state("networkidle", timeout=10000)
        btn = pagina.locator("text=Encartes").first
        if btn.count() == 0:
            print(f"   {Fore.RED}Link Encartes nao encontrado.{Style.RESET_ALL}")
            return []
        btn.click()
        pagina.wait_for_load_state("networkidle", timeout=10000)
        links_pdf = []
        for el in pagina.locator("a[href*='.pdf'], a[href*='encarte']").all():
            link = el.get_attribute("href") or ""
            if link and link not in links_pdf:
                links_pdf.append(link)
        if not links_pdf:
            html = pagina.content()
            links_pdf = list(set(RE_ENCARTE_HREF.findall(html)))
        if not links_pdf:
            print(f"   {Fore.RED}Nenhum PDF encontrado.{Style.RESET_ALL}")
            return []
        print(f"   {Fore.GREEN}{len(links_pdf)} encarte(s) encontrado(s).{Style.RESET_ALL}")
        for url_pdf in links_pdf[:3]:
            if not url_pdf.startswith("http"):
                url_pdf = "https://loja oestessaoluiz.com.br" + url_pdf
            print(f"   Baixando: {url_pdf[:80]}...")
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    urllib.request.urlretrieve(url_pdf, tf.name)
                    caminho = tf.name
                with pdfplumber.open(caminho) as doc:
                    for pag in doc.pages:
                        for linha in (pag.extract_text() or "").split("\n"):
                            oc = re.search(r'R\$\s*(\d+[.,]\d{2})', linha)
                            if oc and len(linha) > 8:
                                nome = re.sub(r'R\$[\d.,\s]+', '', linha).strip()
                                if nome and len(nome) > 4:
                                    resultados.append({
                                        "supermercado": "Sao Luiz (Encarte PDF)", "produto_encontrado": nome[:80],
                                        "preco_normal": f"R$ {oc.group(1)}", "preco_oferta": "—",
                                        "ean": "—", "metodo_ean": "Encarte PDF", "url": url_pdf
                                    })
                os.unlink(caminho)
            except Exception as e:
                print(f"   {Fore.RED}Erro no PDF: {str(e)[:60]}{Style.RESET_ALL}")
                logger.error("Erro ao processar PDF %s: %s", url_pdf[:60], e)
    except Exception as e:
        print(f"   {Fore.RED}Erro: {str(e)[:80]}{Style.RESET_ALL}")
        logger.error("buscar_encartes_saoluiz: %s", e)
    print(f"   {Fore.GREEN}{len(resultados)} produto(s) dos encartes.{Style.RESET_ALL}")
    return resultados


# ==========================================
# INICIALIZACAO E CLI
# ==========================================
def _exibir_e_exportar(resultados):
    if not resultados:
        print(f"\n{Fore.RED}Nenhum resultado encontrado.{Style.RESET_ALL}")
        return
    colunas = ["Loja", "Produto Encontrado", "Preco Normal", "Oferta", "EAN", "Nivel"]
    linhas = [
        [
            r.get("supermercado", "—"),
            (r.get("produto_encontrado", "—")[:45] + '...') if len(r.get("produto_encontrado", "")) > 45 else r.get("produto_encontrado", "—"),
            r.get("preco_normal", "—"), r.get("preco_oferta", "—"),
            r.get("ean", "—"), r.get("metodo_ean", "—")
        ] for r in resultados
    ]
    print("\n" + tabulate(linhas, headers=colunas, tablefmt="rounded_outline"))
    print(f"\n{Fore.CYAN}Exportar para CSV? (s/n): {Style.RESET_ALL}", end="")
    if input().strip().lower() == 's':
        exportar_para_csv(resultados)


def _menu_categorias(pagina, contexto):
    lojas_com_cat = {k: v for k, v in CONCORRENTES.items() if v.get("categorias")}
    nomes = list(lojas_com_cat.keys())
    print(f"\n{Fore.CYAN}Selecione a loja:{Style.RESET_ALL}")
    for i, k in enumerate(nomes, 1):
        print(f"  {i}. {CONCORRENTES[k]['nome']}")
    print("  0. Voltar")
    print("> ", end="")
    try:
        idx_loja = int(input().strip())
    except ValueError:
        return
    if idx_loja < 1 or idx_loja > len(nomes):
        return
    chave = nomes[idx_loja - 1]
    cfg = CONCORRENTES[chave]
    cats = cfg["categorias"]
    nomes_cats = list(cats.keys())
    print(f"\n{Fore.CYAN}Categorias de {cfg['nome']}:{Style.RESET_ALL}")
    for i, nome in enumerate(nomes_cats, 1):
        print(f"  {i:2}. {nome}")
    print("   0. Voltar")
    print("> ", end="")
    try:
        idx_cat = int(input().strip())
    except ValueError:
        return
    if idx_cat < 1 or idx_cat > len(nomes_cats):
        return
    nome_cat = nomes_cats[idx_cat - 1]
    resultados = raspar_categoria(cats[nome_cat], chave, cfg, pagina, contexto)
    _exibir_e_exportar(resultados)


def main():
    seletores = carregar_seletores_personalizados()
    for chave, val in seletores.items():
        if chave in CONCORRENTES:
            CONCORRENTES[chave].update(val)

    status_ia = f"{Fore.GREEN}ativa (Multi-IA: GPT-4o, Gemini 1.5, Groq){Style.RESET_ALL}" if cliente_openai else f"{Fore.RED}desativada (sem OPENAI_API_KEY){Style.RESET_ALL}"
    print(f"\n{Fore.YELLOW}===================================================={Style.RESET_ALL}")
    print(f"{Fore.YELLOW}   Extrator de Precos e EAN - v4.0 (Edicao Ceara)   {Style.RESET_ALL}")
    print(f"{Fore.YELLOW}   Diniz | Sao Luiz | Atacadao | Assai | Carrefour {Style.RESET_ALL}")
    print(f"{Fore.YELLOW}   Cometa | Bom Preco | Mercantil | Pinheiro | +3   {Style.RESET_ALL}")
    print(f"{Fore.YELLOW}===================================================={Style.RESET_ALL}")
    print(f"{Fore.CYAN}Assistente Multi-IA: {status_ia}")
    print(f"{Fore.CYAN}Logs salvos em: {_log_filename}{Style.RESET_ALL}\n")

    with sync_playwright() as pw:
        navegador = lancar_navegador_seguro(pw)
        ctx = navegador.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        pagina = ctx.new_page()
        try:
            while True:
                print(f"\n{Fore.YELLOW}O que deseja fazer?{Style.RESET_ALL}")
                print("  1. Pesquisar produto por nome (catalogo dos sites)")
                print("  2. Navegar por categoria/departamento")
                print("  3. Ver encartes (PDF) — Sao Luiz")
                print(f"  {Fore.GREEN}4. Buscar no Google e confrontar com concorrentes{Style.RESET_ALL}")
                print("  0. Sair")
                if cliente_openai:
                    print(f"   {Fore.MAGENTA}[IA] Normaliza sua busca, sugere alternativas e resume resultados automaticamente.{Style.RESET_ALL}")
                print("> ", end="")
                opcao = input().strip()

                if opcao == "0":
                    print(f"\n{Fore.CYAN}Encerrando. Ate logo.{Style.RESET_ALL}")
                    break

                elif opcao == "1":
                    print(f"\n{Fore.YELLOW}Produto para pesquisar (ou 0 para voltar): {Style.RESET_ALL}", end="")
                    entrada = input().strip()
                    if not entrada or entrada == "0":
                        continue

                    # ── IA: normaliza o que o usuario digitou ────────────────
                    produto_limpo = entrada.strip()
                    conc_esp = None
                    if " no " in entrada.lower():
                        partes = entrada.lower().split(" no ")
                        produto_limpo = partes[0].strip()
                        dest = partes[1].strip()
                        if "luiz" in dest:
                            conc_esp = "saoluiz"
                        elif "atacadao" in dest or "atacad\u00e3o" in dest:
                            conc_esp = "atacadao"
                        elif "diniz" in dest:
                            conc_esp = "diniz"

                    produto_normalizado = ia_normalizar_entrada(produto_limpo)
                    if produto_normalizado.lower() != produto_limpo.lower():
                        print(f"   {Fore.MAGENTA}[IA] Entendido como: \"{produto_normalizado}\"{Style.RESET_ALL}")
                        logger.info("[IA] Entrada normalizada: '%s' -> '%s'", produto_limpo, produto_normalizado)
                        produto_limpo = produto_normalizado

                    # ── Busca principal ──────────────────────────────────────
                    resultados = []
                    for chave, cfg in CONCORRENTES.items():
                        if conc_esp and chave != conc_esp:
                            continue
                        resultados.extend(raspar_concorrente(produto_limpo, chave, cfg, pagina, ctx))

                    # ── IA: se vazio, sugere termos alternativos ─────────────
                    if not resultados:
                        termos_alt = ia_termos_alternativos(produto_limpo)
                        if termos_alt:
                            print(f"\n   {Fore.MAGENTA}[IA] Sem resultados para \"{produto_limpo}\". Tentando alternativas:{Style.RESET_ALL}")
                            for termo in termos_alt:
                                print(f"   {Fore.MAGENTA}   -> \"{termo}\"{Style.RESET_ALL}")
                                logger.info("[IA] Tentando alternativa: '%s'", termo)
                                for chave, cfg in CONCORRENTES.items():
                                    if conc_esp and chave != conc_esp:
                                        continue
                                    resultados.extend(raspar_concorrente(termo, chave, cfg, pagina, ctx))
                                if resultados:
                                    print(f"   {Fore.GREEN}[IA] Encontrado com: \"{termo}\"{Style.RESET_ALL}")
                                    break

                    # ── IA: resume resultados em linguagem natural ───────────
                    _exibir_e_exportar(resultados)
                    if resultados:
                        resumo = ia_resumir_resultados(produto_limpo, resultados)
                        if resumo:
                            print(f"\n{Fore.MAGENTA}╔══ Resumo da IA ══════════════════════════════════╗{Style.RESET_ALL}")
                            for linha_resumo in resumo.split("\n"):
                                print(f"{Fore.MAGENTA}║  {linha_resumo}{Style.RESET_ALL}")
                            print(f"{Fore.MAGENTA}╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")

                elif opcao == "2":
                    _menu_categorias(pagina, ctx)

                elif opcao == "3":
                    resultados = buscar_encartes_saoluiz(pagina, ctx)
                    _exibir_e_exportar(resultados)

                elif opcao == "4":
                    print(f"\n{Fore.YELLOW}Produto para buscar no Google (ou 0 para voltar): {Style.RESET_ALL}", end="")
                    entrada = input().strip()
                    if not entrada or entrada == "0":
                        continue

                    # ── IA: normaliza entrada antes do Google ────────────────
                    produto_google = ia_normalizar_entrada(entrada.strip())
                    if produto_google.lower() != entrada.strip().lower():
                        print(f"   {Fore.MAGENTA}[IA] Entendido como: \"{produto_google}\"{Style.RESET_ALL}")

                    resultados = buscar_google_e_confrontar(produto_google, pagina, ctx)
                    _exibir_e_exportar(resultados)

                    # ── IA: resume resultados da busca Google ────────────────
                    if resultados:
                        resumo = ia_resumir_resultados(produto_google, resultados)
                        if resumo:
                            print(f"\n{Fore.MAGENTA}╔══ Resumo da IA ══════════════════════════════════╗{Style.RESET_ALL}")
                            for linha_resumo in resumo.split("\n"):
                                print(f"{Fore.MAGENTA}║  {linha_resumo}{Style.RESET_ALL}")
                            print(f"{Fore.MAGENTA}╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")

                else:
                    print(f"{Fore.RED}Opcao invalida.{Style.RESET_ALL}")
        finally:
            navegador.close()
            logger.info("Navegador encerrado.")


if __name__ == "__main__":
    main()