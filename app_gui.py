"""
app_gui.py — Interface Grafica
Falcons Data — Inteligencia de Mercado
"""

import os
import sys


# Modo --noconsole (PyInstaller) deixa stdout/stderr como None; garante destino gravavel
# antes de qualquer print/log do app ou do motor importado abaixo.
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

import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
from datetime import datetime

# ── Path Setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import pesquisa_preco_v4 as engine

# ── Tema CustomTkinter ────────────────────────────────────────────────────────
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ── Paleta de Cores Premium ───────────────────────────────────────────────────
# Paleta inspirada no print: charcoal escuro + coral/vermelho + branco/cinza.
C = {
    "bg":          "#232323",
    "sidebar":     "#1b1b1b",
    "card":        "#2b2b2b",
    "card_hover":  "#363636",
    "tile":        "#262626",
    "border":      "#3a3a3a",
    "accent":      "#f2645a",   # coral (destaque principal, como no print)
    "accent_hi":   "#e0483d",   # vermelho mais forte (hover / logo)
    "accent2":     "#4ecb71",   # verde (IA online / disponivel)
    "accent3":     "#f0a35a",   # laranja (ofertas)
    "danger":      "#e0483d",
    "text":        "#f2f2f2",
    "text_dim":    "#9a9a9a",
    "preco":       "#4ecb71",   # verde para o preco (legibilidade)
    "melhor_bg":   "#2f2320",   # destaque do menor preco (avermelhado escuro)
}

# Nomes amigaveis dos provedores de IA (para o painel de status na barra lateral)
IAS_LABELS = {
    "openai":      "OpenAI GPT-4o",
    "gemini":      "Gemini Flash",
    "groq":        "Groq LLaMA",
    "openrouter":  "OpenRouter",
    "huggingface": "HuggingFace",
}

LOJAS_CONFIG = {
    "aurora":    "Aurora",
    "vizinho":  "Vizinho",
    "atacauno": "Atacado Uno",
    "atacadois":    "Atacado Dois (encarte)",
}


class AppPesquisaPreco(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Falcons Data")
        self.geometry("1280x820")
        self.minsize(1024, 640)
        self.configure(fg_color=C["bg"])
        self._estados = {
            "busca":    {"resultados": [], "buscando": False, "cancelar": threading.Event()},
            "encartes": {"resultados": [], "buscando": False, "cancelar": threading.Event()},
            "monitor":  {"rodando": False, "parar": threading.Event()},
            "confronto": {"itens": [], "linhas": [], "rodando": False, "cancelar": threading.Event()},
        }
        self._build_layout()
        self._apply_ttk_style()

    def _build_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self._build_sidebar()
        self._main_frame = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        self._main_frame.grid(row=0, column=1, sticky="nsew")
        self._main_frame.grid_rowconfigure(1, weight=1)
        self._main_frame.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._tabview = ctk.CTkTabview(
            self._main_frame,
            fg_color=C["card"],
            segmented_button_fg_color=C["border"],
            segmented_button_selected_color=C["accent"],
            segmented_button_selected_hover_color="#3a7af5",
            segmented_button_unselected_color=C["border"],
            segmented_button_unselected_hover_color=C["card_hover"],
            text_color=C["text"],
            corner_radius=12,
        )
        self._tabview.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self._tabview._segmented_button.configure(font=ctk.CTkFont("Segoe UI", 13, "bold"))
        self._tab_busca     = self._tabview.add("  Busca Unificada")
        self._tab_confronto = self._tabview.add("  Confronto CSV")
        self._tab_monitor   = self._tabview.add("  Monitor")
        self._tab_encartes  = self._tabview.add("  Encartes")
        self._tab_config    = self._tabview.add("  Configuracoes")
        self._build_tab_busca()
        self._build_tab_confronto()
        self._build_tab_monitor()
        self._build_tab_encartes()
        self._build_tab_config()

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, fg_color=C["sidebar"], corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(9, weight=1)

        marca = ctk.CTkFrame(sb, fg_color="transparent")
        marca.grid(row=0, column=0, pady=(22, 2))
        badge = ctk.CTkFrame(marca, width=56, height=56, corner_radius=28, fg_color=C["accent_hi"])
        badge.pack(pady=(0, 8))
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text="F", font=ctk.CTkFont("Segoe UI", 27, "bold"),
                     text_color="#ffffff").pack(expand=True)
        ctk.CTkLabel(marca, text="F A L C O N S", font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["text_dim"]).pack()
        ctk.CTkLabel(marca, text="DATA", font=ctk.CTkFont("Segoe UI", 26, "bold"),
                     text_color=C["accent"]).pack()
        ctk.CTkLabel(sb, text="Inteligencia de Precos", font=ctk.CTkFont("Segoe UI", 10, slant="italic"),
                     text_color=C["text_dim"]).grid(row=1, column=0, pady=(2, 16))
        ctk.CTkFrame(sb, height=1, fg_color=C["border"]).grid(row=2, column=0, sticky="ew", padx=16, pady=(0,16))

        ctk.CTkLabel(sb, text="INTELIGENCIAS EM CONJUNTO", font=ctk.CTkFont("Segoe UI", 9, "bold"),
                     text_color=C["text_dim"]).grid(row=3, column=0, sticky="w", padx=16, pady=(0,8))
        self._ia_badges = {}
        for i, key in enumerate(["openai", "gemini", "groq", "openrouter", "huggingface"]):
            row_ia = ctk.CTkFrame(sb, fg_color="transparent")
            row_ia.grid(row=4+i, column=0, sticky="ew", padx=16, pady=2)
            row_ia.grid_columnconfigure(1, weight=1)
            dot = ctk.CTkLabel(row_ia, text="●", font=ctk.CTkFont("Segoe UI",11),
                               text_color=C["text_dim"], width=16)
            dot.grid(row=0, column=0)
            ctk.CTkLabel(row_ia, text=IAS_LABELS[key], font=ctk.CTkFont("Segoe UI",11),
                         text_color=C["text_dim"], anchor="w").grid(row=0, column=1, sticky="w", padx=4)
            self._ia_badges[key] = dot
        self.after(500, self._check_ias)

        ctk.CTkFrame(sb, height=1, fg_color=C["border"]).grid(row=10, column=0, sticky="ew", padx=16, pady=16)
        ctk.CTkButton(
            sb, text="Exportar CSV", fg_color=C["border"], hover_color=C["card_hover"],
            text_color=C["text"], font=ctk.CTkFont("Segoe UI",12), height=34, corner_radius=8,
            command=self._exportar_csv
        ).grid(row=12, column=0, sticky="ew", padx=16, pady=4)
        ctk.CTkLabel(sb, text="© Falcons Data", font=ctk.CTkFont("Segoe UI",9),
                     text_color=C["text_dim"]).grid(row=13, column=0, pady=(8,16))

    def _build_header(self):
        hdr = ctk.CTkFrame(self._main_frame, fg_color="transparent", height=56)
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(12,8))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_propagate(False)
        ctk.CTkLabel(hdr, text="Falcons Data — Central de Inteligencia de Mercado",
                     font=ctk.CTkFont("Segoe UI", 18, "bold"), text_color=C["text"]).grid(row=0, column=0, sticky="w")
        self._lbl_hora = ctk.CTkLabel(hdr, text="", font=ctk.CTkFont("Segoe UI",11), text_color=C["text_dim"])
        self._lbl_hora.grid(row=0, column=1, sticky="e")
        self._atualizar_hora()

    def _build_tab_busca(self):
        tab = self._tab_busca
        tab.configure(fg_color=C["card"])
        tab.grid_rowconfigure(4, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        # Painel busca
        pb = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        pb.grid(row=0, column=0, sticky="ew", padx=12, pady=(12,6))
        pb.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(pb, text="Produto:", font=ctk.CTkFont("Segoe UI",12,"bold"), text_color=C["text_dim"]).grid(row=0, column=0, padx=(16,8), pady=14)
        self._entry_busca = ctk.CTkEntry(
            pb, placeholder_text="Digite o produto (Ex: Coca 2L, Leite Italac, Arroz 5kg...)",
            font=ctk.CTkFont("Segoe UI",14), height=42, corner_radius=8,
            fg_color=C["border"], border_color=C["accent"], text_color=C["text"],
            placeholder_text_color=C["text_dim"]
        )
        self._entry_busca.grid(row=0, column=1, sticky="ew", padx=8, pady=14)
        self._entry_busca.bind("<Return>", lambda e: self._iniciar_busca())

        self._btn_buscar = ctk.CTkButton(
            pb, text="Buscar", font=ctk.CTkFont("Segoe UI",13,"bold"),
            fg_color=C["accent"], hover_color="#3a7af5", text_color="white",
            height=42, width=130, corner_radius=8, command=self._iniciar_busca
        )
        self._btn_buscar.grid(row=0, column=2, padx=(8,8), pady=14)

        self._btn_cancelar = ctk.CTkButton(
            pb, text="Cancelar", font=ctk.CTkFont("Segoe UI",13,"bold"),
            fg_color=C["danger"], hover_color="#c0392b", text_color="white",
            height=42, width=130, corner_radius=8, command=self._cancelar_busca, state="disabled"
        )
        self._btn_cancelar.grid(row=0, column=3, padx=(0,16), pady=14)

        # Lojas (GRID MULTI-LINHAS PARA NUNCA CORTAR!)
        pl = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        pl.grid(row=1, column=0, sticky="ew", padx=12, pady=(0,6))
        
        ctk.CTkLabel(pl, text="Lojas Monitoradas:", font=ctk.CTkFont("Segoe UI",11,"bold"), text_color=C["accent"]).grid(row=0, column=0, sticky="w", padx=12, pady=(8,4))
        
        self._frame_grid_lojas = ctk.CTkFrame(pl, fg_color="transparent")
        self._frame_grid_lojas.grid(row=1, column=0, sticky="ew", padx=12, pady=(0,8))
        self._check_vars = {}
        self._montar_checkboxes_lojas()

        # Botões de controle rápido
        btn_box = ctk.CTkFrame(pl, fg_color="transparent")
        btn_box.grid(row=2, column=0, sticky="w", padx=12, pady=(0,8))
        ctk.CTkButton(btn_box, text="Marcar Todas", width=100, height=26, fg_color=C["border"],
                      hover_color=C["card_hover"], text_color=C["text"],
                      font=ctk.CTkFont("Segoe UI",10,"bold"), corner_radius=6,
                      command=lambda: [v.set(True) for v in self._check_vars.values()]
                      ).pack(side="left", padx=(0,6))
        ctk.CTkButton(btn_box, text="Desmarcar Todas", width=110, height=26, fg_color=C["border"],
                      hover_color=C["card_hover"], text_color=C["text"],
                      font=ctk.CTkFont("Segoe UI",10,"bold"), corner_radius=6,
                      command=lambda: [v.set(False) for v in self._check_vars.values()]
                      ).pack(side="left")

        # Cartoes de resumo (stat tiles)
        tiles = ctk.CTkFrame(tab, fg_color="transparent")
        tiles.grid(row=2, column=0, sticky="ew", padx=12, pady=(0,6))
        for i in range(4):
            tiles.grid_columnconfigure(i, weight=1, uniform="tiles")
        self._tile_total   = self._criar_tile(tiles, 0, "Itens encontrados", C["accent"])
        self._tile_ofertas = self._criar_tile(tiles, 1, "Em oferta",         C["accent3"])
        self._tile_lojas   = self._criar_tile(tiles, 2, "Lojas",             C["text"])
        self._tile_menor   = self._criar_tile(tiles, 3, "Menor preco",       C["preco"])

        # Status
        ps = ctk.CTkFrame(tab, fg_color="transparent")
        ps.grid(row=3, column=0, sticky="ew", padx=12, pady=(0,4))
        ps.grid_columnconfigure(0, weight=1)
        self._lbl_status = ctk.CTkLabel(ps, text="Pronto para pesquisar...",
                                         font=ctk.CTkFont("Segoe UI",12), text_color=C["text_dim"], anchor="w")
        self._lbl_status.grid(row=0, column=0, sticky="w", padx=4)
        self._lbl_contagem = ctk.CTkLabel(ps, text="", font=ctk.CTkFont("Segoe UI",11,"bold"), text_color=C["accent2"])
        self._lbl_contagem.grid(row=0, column=1, sticky="e", padx=4)
        self._progress = ctk.CTkProgressBar(ps, fg_color=C["border"], progress_color=C["accent"], height=4, corner_radius=2)
        self._progress.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(2,0))
        self._progress.set(0)

        # Tabela
        ft = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        ft.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0,6))
        ft.grid_rowconfigure(0, weight=1)
        ft.grid_columnconfigure(0, weight=1)
        self._tree_busca = self._criar_tabela(ft, [
            ("#", 44), ("Loja", 180), ("Produto", 320), ("Preco Normal", 110),
            ("Preco Oferta", 110), ("EAN", 120), ("Metodo Extracao", 150)
        ])

        # Resumo IA
        self._txt_resumo = ctk.CTkTextbox(
            tab, height=75, fg_color=C["bg"], text_color=C["text_dim"],
            font=ctk.CTkFont("Segoe UI",11), corner_radius=8,
            border_color=C["border"], border_width=1
        )
        self._txt_resumo.grid(row=5, column=0, sticky="ew", padx=12, pady=(0,12))
        self._txt_resumo.insert("end", "O resumo executivo de IA aparecera aqui apos a busca...")
        self._txt_resumo.configure(state="disabled")

    def _lojas_disponiveis(self) -> dict:
        """Lojas fixas + sites cadastrados pelo usuario."""
        lojas = dict(LOJAS_CONFIG)
        try:
            for s in engine.carregar_sites_customizados():
                lojas[s["chave"]] = s.get("nome", s["chave"])
        except Exception:
            pass
        return lojas

    def _montar_checkboxes_lojas(self):
        """(Re)constroi os checkboxes de lojas (inclui sites cadastrados)."""
        for w in self._frame_grid_lojas.winfo_children():
            w.destroy()
        anteriores = {k: v.get() for k, v in self._check_vars.items()}
        self._check_vars = {}
        cols_per_row = 4
        for idx, (chave, nome) in enumerate(self._lojas_disponiveis().items()):
            var = tk.BooleanVar(value=anteriores.get(chave, True))
            self._check_vars[chave] = var
            ctk.CTkCheckBox(
                self._frame_grid_lojas, text=nome, variable=var,
                font=ctk.CTkFont("Segoe UI", 11), fg_color=C["accent"],
                hover_color=C["accent_hi"], text_color=C["text"], checkmark_color="white",
                border_color=C["border"], width=150
            ).grid(row=idx // cols_per_row, column=idx % cols_per_row, padx=6, pady=4, sticky="w")

    def _criar_tile(self, parent, col, titulo, cor):
        card = ctk.CTkFrame(parent, fg_color=C["tile"], corner_radius=10,
                            border_width=1, border_color=C["border"])
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0))
        card.grid_columnconfigure(0, weight=1)
        valor = ctk.CTkLabel(card, text="—", font=ctk.CTkFont("Segoe UI", 24, "bold"), text_color=cor)
        valor.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(card, text=titulo.upper(), font=ctk.CTkFont("Segoe UI", 9, "bold"),
                     text_color=C["text_dim"]).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        return valor

    def _build_tab_encartes(self):
        tab = self._tab_encartes
        tab.configure(fg_color=C["card"])
        tab.grid_rowconfigure(2, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        pe = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        pe.grid(row=0, column=0, sticky="ew", padx=12, pady=(12,6))
        pe.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(pe, text="Varredura de Encartes PDF de todas as redes do regiao",
                     font=ctk.CTkFont("Segoe UI",13,"bold"), text_color=C["text"]).grid(row=0, column=0, padx=16, pady=14, sticky="w")
        self._btn_encartes = ctk.CTkButton(
            pe, text="Buscar Encartes", font=ctk.CTkFont("Segoe UI",13,"bold"),
            fg_color=C["accent2"], hover_color="#17bf88", text_color=C["bg"],
            height=42, width=180, corner_radius=8, command=self._iniciar_encartes
        )
        self._btn_encartes.grid(row=0, column=1, padx=16, pady=14, sticky="e")
        self._btn_canc_enc = ctk.CTkButton(
            pe, text="Cancelar", font=ctk.CTkFont("Segoe UI",13,"bold"),
            fg_color=C["danger"], hover_color="#c0392b", text_color="white",
            height=42, width=120, corner_radius=8, command=self._cancelar_encartes, state="disabled"
        )
        self._btn_canc_enc.grid(row=0, column=2, padx=(0,16), pady=14)

        self._lbl_status_enc = ctk.CTkLabel(
            tab, text="Aguardando busca de encartes...",
            font=ctk.CTkFont("Segoe UI",11), text_color=C["text_dim"], anchor="w"
        )
        self._lbl_status_enc.grid(row=1, column=0, sticky="w", padx=16, pady=(0,4))

        fe = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        fe.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0,12))
        fe.grid_rowconfigure(0, weight=1)
        fe.grid_columnconfigure(0, weight=1)
        self._tree_enc = self._criar_tabela(fe, [
            ("#", 40), ("Loja", 180), ("Produto Encontrado", 380), ("Preco Encarte", 120)
        ])

    def _build_tab_config(self):
        tab = self._tab_config
        tab.configure(fg_color=C["card"])
        frame = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(frame, text="Configuracoes do Motor de Busca",
                     font=ctk.CTkFont("Segoe UI",15,"bold"), text_color=C["text"]).pack(anchor="w", padx=20, pady=(20,16))

        rw = ctk.CTkFrame(frame, fg_color="transparent")
        rw.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(rw, text="Lojas em paralelo (workers):", font=ctk.CTkFont("Segoe UI",12), text_color=C["text"]).pack(side="left")
        self._slider_workers = ctk.CTkSlider(rw, from_=1, to=8, number_of_steps=7,
                                              button_color=C["accent"], progress_color=C["accent"], width=180)
        self._slider_workers.set(4)
        self._slider_workers.pack(side="left", padx=16)
        self._lbl_workers = ctk.CTkLabel(rw, text="4", font=ctk.CTkFont("Segoe UI",12,"bold"), text_color=C["accent"])
        self._lbl_workers.pack(side="left")
        self._slider_workers.configure(command=lambda v: self._lbl_workers.configure(text=str(int(v))))

        rt = ctk.CTkFrame(frame, fg_color="transparent")
        rt.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(rt, text="Timeout por loja (segundos):", font=ctk.CTkFont("Segoe UI",12), text_color=C["text"]).pack(side="left")
        self._slider_timeout = ctk.CTkSlider(rt, from_=10, to=120, number_of_steps=11,
                                              button_color=C["accent"], progress_color=C["accent"], width=180)
        self._slider_timeout.set(45)
        self._slider_timeout.pack(side="left", padx=16)
        self._lbl_timeout = ctk.CTkLabel(rt, text="45s", font=ctk.CTkFont("Segoe UI",12,"bold"), text_color=C["accent"])
        self._lbl_timeout.pack(side="left")
        self._slider_timeout.configure(command=lambda v: self._lbl_timeout.configure(text=f"{int(v)}s"))

        # Limite de produtos por loja (vazio = trazer TUDO)
        rlim = ctk.CTkFrame(frame, fg_color="transparent")
        rlim.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(rlim, text="Maximo de produtos por loja:", font=ctk.CTkFont("Segoe UI",12), text_color=C["text"]).pack(side="left")
        self._entry_limite = ctk.CTkEntry(rlim, width=90, placeholder_text="tudo",
                                          fg_color=C["bg"], border_color=C["border"], text_color=C["text"])
        self._entry_limite.pack(side="left", padx=16)
        ctk.CTkLabel(rlim, text="(deixe em branco para trazer tudo)",
                     font=ctk.CTkFont("Segoe UI",11), text_color=C["text_dim"]).pack(side="left")

        ctk.CTkFrame(frame, height=1, fg_color=C["border"]).pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(
            frame,
            text=(
                "INFO: Busca paralela executa varredura de N redes simultaneamente.\n"
                "  Recomendado: 3-4 workers para maxima velocidade sem sobrecarregar.\n"
                "  O timeout encerra a busca de uma loja se ela demorar demais."
            ),
            font=ctk.CTkFont("Segoe UI",11), text_color=C["text_dim"], justify="left"
        ).pack(anchor="w", padx=20)

        # ── Sites personalizados (cadastro pelo usuario) ─────────────────────
        ctk.CTkFrame(frame, height=1, fg_color=C["border"]).pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(frame, text="Sites personalizados (entram na busca)",
                     font=ctk.CTkFont("Segoe UI",13,"bold"), text_color=C["accent"]).pack(anchor="w", padx=20, pady=(0,4))
        ctk.CTkLabel(frame, text="Cadastre outra loja: nome da empresa + link de busca (use {produto} onde vai o termo).\n"
                                 "A pagina sera lida pela IA para extrair os produtos.",
                     font=ctk.CTkFont("Segoe UI",10), text_color=C["text_dim"], justify="left").pack(anchor="w", padx=20)

        form = ctk.CTkFrame(frame, fg_color="transparent")
        form.pack(fill="x", padx=20, pady=8)
        self._entry_site_nome = ctk.CTkEntry(form, width=180, placeholder_text="Nome da empresa",
                                             fg_color=C["bg"], border_color=C["border"], text_color=C["text"])
        self._entry_site_nome.pack(side="left", padx=(0,8))
        self._entry_site_url = ctk.CTkEntry(form, width=380, placeholder_text="https://loja.com.br/busca?q={produto}",
                                            fg_color=C["bg"], border_color=C["border"], text_color=C["text"])
        self._entry_site_url.pack(side="left", padx=(0,8))
        ctk.CTkButton(form, text="Adicionar site", width=120, height=30, fg_color=C["accent"],
                      hover_color=C["accent_hi"], text_color="#ffffff", font=ctk.CTkFont("Segoe UI",11,"bold"),
                      corner_radius=8, command=self._adicionar_site).pack(side="left")

        self._frame_sites = ctk.CTkFrame(frame, fg_color="transparent")
        self._frame_sites.pack(fill="x", padx=20, pady=(4,12))
        self._montar_lista_sites()

    def _montar_lista_sites(self):
        for w in self._frame_sites.winfo_children():
            w.destroy()
        sites = engine.carregar_sites_customizados()
        if not sites:
            ctk.CTkLabel(self._frame_sites, text="Nenhum site cadastrado ainda.",
                         font=ctk.CTkFont("Segoe UI",10,slant="italic"), text_color=C["text_dim"]).pack(anchor="w")
            return
        for s in sites:
            row = ctk.CTkFrame(self._frame_sites, fg_color=C["tile"], corner_radius=6)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"  {s.get('nome','?')}", font=ctk.CTkFont("Segoe UI",11,"bold"),
                         text_color=C["text"], width=170, anchor="w").pack(side="left", padx=(4,8), pady=4)
            ctk.CTkLabel(row, text=s.get("url_busca","")[:70], font=ctk.CTkFont("Segoe UI",10),
                         text_color=C["text_dim"], anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="Remover", width=80, height=24, fg_color=C["border"],
                          hover_color=C["danger"], text_color=C["text"], font=ctk.CTkFont("Segoe UI",10),
                          corner_radius=6, command=lambda ch=s.get("chave"): self._remover_site(ch)).pack(side="right", padx=6)

    def _adicionar_site(self):
        nome = self._entry_site_nome.get().strip()
        url = self._entry_site_url.get().strip()
        if not nome or not url:
            messagebox.showwarning("Campos vazios", "Preencha o nome da empresa e o link de busca.")
            return
        site = engine.salvar_site_customizado(nome, url)
        if not site:
            messagebox.showwarning("Invalido", "Nao consegui cadastrar. Confira o link informado.")
            return
        self._entry_site_nome.delete(0, "end")
        self._entry_site_url.delete(0, "end")
        self._montar_lista_sites()
        self._montar_checkboxes_lojas()
        messagebox.showinfo("Site cadastrado",
                            f"'{nome}' entrou na busca. A pagina dele sera lida pela IA.")

    def _remover_site(self, chave):
        engine.remover_site_customizado(chave)
        self._montar_lista_sites()
        self._montar_checkboxes_lojas()

    # ── Monitor (Fase E) ────────────────────────────────────────────────────
    def _build_tab_monitor(self):
        tab = self._tab_monitor
        tab.configure(fg_color=C["card"])
        tab.grid_rowconfigure(3, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text="Produto:", font=ctk.CTkFont("Segoe UI",12,"bold"),
                     text_color=C["text"]).grid(row=0, column=0, padx=(14,8), pady=12)
        self._entry_monitor = ctk.CTkEntry(top, placeholder_text="Ex: coca cola 2l",
                                           fg_color=C["card"], border_color=C["border"], text_color=C["text"], height=36)
        self._entry_monitor.grid(row=0, column=1, sticky="ew", padx=8, pady=12)
        self._entry_monitor.bind("<Return>", lambda e: self._monitor_add())
        ctk.CTkButton(top, text="Adicionar", width=110, height=36, fg_color=C["accent"],
                      hover_color=C["accent_hi"], text_color="#ffffff", font=ctk.CTkFont("Segoe UI",12,"bold"),
                      corner_radius=8, command=self._monitor_add).grid(row=0, column=2, padx=(4,14), pady=12)

        self._frame_watch = ctk.CTkFrame(tab, fg_color="transparent")
        self._frame_watch.grid(row=1, column=0, sticky="ew", padx=12, pady=(0,6))

        ctr = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        ctr.grid(row=2, column=0, sticky="ew", padx=12, pady=(0,8))
        self._btn_monitor_agora = ctk.CTkButton(
            ctr, text="Rodar agora", width=130, height=34, fg_color=C["accent"],
            hover_color=C["accent_hi"], text_color="#ffffff", font=ctk.CTkFont("Segoe UI",12,"bold"),
            corner_radius=8, command=self._monitor_rodar_agora)
        self._btn_monitor_agora.pack(side="left", padx=(14,10), pady=12)
        ctk.CTkLabel(ctr, text="Intervalo (min):", font=ctk.CTkFont("Segoe UI",12),
                     text_color=C["text"]).pack(side="left")
        self._entry_intervalo = ctk.CTkEntry(ctr, width=70, placeholder_text="30",
                     fg_color=C["card"], border_color=C["border"], text_color=C["text"])
        self._entry_intervalo.pack(side="left", padx=10)
        self._btn_monitor_toggle = ctk.CTkButton(
            ctr, text="Iniciar monitor", width=150, height=34, fg_color=C["border"],
            hover_color=C["card_hover"], text_color=C["text"], font=ctk.CTkFont("Segoe UI",12,"bold"),
            corner_radius=8, command=self._monitor_toggle)
        self._btn_monitor_toggle.pack(side="left", padx=10)
        self._lbl_monitor_status = ctk.CTkLabel(ctr, text="parado", font=ctk.CTkFont("Segoe UI",11),
                     text_color=C["text_dim"])
        self._lbl_monitor_status.pack(side="left", padx=10)

        ft = ctk.CTkFrame(tab, fg_color=C["card"], corner_radius=10)
        ft.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0,12))
        ft.grid_rowconfigure(0, weight=1)
        ft.grid_columnconfigure(0, weight=1)
        self._tree_monitor = self._criar_tabela(ft, [
            ("Produto", 160), ("Loja", 150), ("Preco atual", 110),
            ("Anterior", 100), ("Variacao", 110), ("Atualizado", 150),
        ])
        self._monitor_montar_lista()
        self._monitor_atualizar_tabela()

    def _monitor_montar_lista(self):
        for w in self._frame_watch.winfo_children():
            w.destroy()
        termos = engine.carregar_watchlist()
        if not termos:
            ctk.CTkLabel(self._frame_watch, text="Nenhum produto no monitor. Adicione acima.",
                         font=ctk.CTkFont("Segoe UI",10,slant="italic"), text_color=C["text_dim"]).pack(anchor="w", padx=4)
            return
        for t in termos:
            chip = ctk.CTkFrame(self._frame_watch, fg_color=C["tile"], corner_radius=14)
            chip.pack(side="left", padx=4, pady=4)
            ctk.CTkLabel(chip, text=t, font=ctk.CTkFont("Segoe UI",11),
                         text_color=C["text"]).pack(side="left", padx=(10,4), pady=4)
            ctk.CTkButton(chip, text="✕", width=22, height=22, fg_color="transparent",
                          hover_color=C["danger"], text_color=C["text_dim"],
                          font=ctk.CTkFont("Segoe UI",11,"bold"), corner_radius=11,
                          command=lambda x=t: self._monitor_remove(x)).pack(side="left", padx=(0,4))

    def _monitor_add(self):
        termo = self._entry_monitor.get().strip()
        if not termo:
            return
        termos = engine.carregar_watchlist()
        if termo.lower() not in [x.lower() for x in termos]:
            termos.append(termo)
            engine.salvar_watchlist(termos)
        self._entry_monitor.delete(0, "end")
        self._monitor_montar_lista()

    def _monitor_remove(self, termo):
        engine.salvar_watchlist([x for x in engine.carregar_watchlist() if x != termo])
        self._monitor_montar_lista()

    def _monitor_atualizar_tabela(self):
        self._limpar_tabela(self._tree_monitor)
        for termo in engine.carregar_watchlist():
            try:
                variacoes = engine.monitor_variacao(termo)
            except Exception:
                variacoes = []
            for v in variacoes:
                atual = f"R$ {v['atual']:.2f}".replace('.', ',') if v['atual'] is not None else "—"
                ant = f"R$ {v['anterior']:.2f}".replace('.', ',') if v['anterior'] is not None else "—"
                if v['var'] is None:
                    varic = "—"
                elif v['var'] > 0.05:
                    varic = f"▲ {v['var']:+.1f}%"
                elif v['var'] < -0.05:
                    varic = f"▼ {v['var']:+.1f}%"
                else:
                    varic = "= 0%"
                self._tree_monitor.insert("", "end", values=(termo, v['loja'], atual, ant, varic, v['data']))

    def _monitor_rodar_agora(self):
        termos = engine.carregar_watchlist()
        if not termos:
            messagebox.showinfo("Monitor vazio", "Adicione ao menos um produto ao monitor.")
            return
        lojas = [k for k, val in self._check_vars.items() if val.get()]
        self._btn_monitor_agora.configure(state="disabled")
        self._lbl_monitor_status.configure(text="coletando...")

        def _run():
            for termo in termos:
                try:
                    res = engine.raspar_todos_paralelo(
                        produto=termo, lojas_selecionadas=lojas or None,
                        max_workers=int(self._slider_workers.get()),
                        timeout_por_loja=int(self._slider_timeout.get()),
                        limite_por_loja=5,
                    )
                    engine.monitor_registrar(termo, res)
                except Exception as e:
                    engine.logger.warning("monitor rodar %s: %s", termo, e)
            self.after(0, self._monitor_fim_coleta)

        threading.Thread(target=_run, daemon=True).start()

    def _monitor_fim_coleta(self):
        self._btn_monitor_agora.configure(state="normal")
        self._lbl_monitor_status.configure(text=f"atualizado {datetime.now().strftime('%H:%M:%S')}")
        self._monitor_atualizar_tabela()

    def _monitor_toggle(self):
        est = self._estados["monitor"]
        if est["rodando"]:
            est["parar"].set()
            est["rodando"] = False
            self._btn_monitor_toggle.configure(text="Iniciar monitor")
            self._lbl_monitor_status.configure(text="parado")
            return
        try:
            intervalo = max(1, int(self._entry_intervalo.get().strip() or "30"))
        except Exception:
            intervalo = 30
        est["parar"].clear()
        est["rodando"] = True
        self._btn_monitor_toggle.configure(text="Parar monitor")
        self._lbl_monitor_status.configure(text=f"monitorando a cada {intervalo} min")

        def _loop():
            while not est["parar"].is_set():
                termos = engine.carregar_watchlist()
                lojas = [k for k, val in self._check_vars.items() if val.get()]
                for termo in termos:
                    if est["parar"].is_set():
                        break
                    try:
                        res = engine.raspar_todos_paralelo(
                            produto=termo, lojas_selecionadas=lojas or None,
                            parar_event=est["parar"],
                            max_workers=int(self._slider_workers.get()),
                            timeout_por_loja=int(self._slider_timeout.get()),
                            limite_por_loja=5)
                        engine.monitor_registrar(termo, res)
                    except Exception as e:
                        engine.logger.warning("monitor loop %s: %s", termo, e)
                self.after(0, self._monitor_atualizar_tabela)
                est["parar"].wait(intervalo * 60)

        threading.Thread(target=_loop, daemon=True).start()

    def _criar_tabela(self, parent, colunas):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        tree = ttk.Treeview(frame, columns=[c[0] for c in colunas], show="headings", style="Premium.Treeview")
        for col_name, width in colunas:
            tree.heading(col_name, text=col_name)
            tree.column(col_name, width=width, minwidth=30, stretch=(col_name in ("Produto", "Produto Encontrado")))
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        tree.tag_configure("par",    background="#111827", foreground=C["text"])
        tree.tag_configure("impar",  background="#0d1224", foreground=C["text"])
        tree.tag_configure("preco",  background="#111827", foreground=C["preco"])
        tree.tag_configure("melhor", background=C["melhor_bg"], foreground=C["preco"])
        return tree

    def _apply_ttk_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Premium.Treeview", background=C["card"], foreground=C["text"],
                        fieldbackground=C["card"], rowheight=36, font=("Segoe UI", 11), borderwidth=0)
        style.configure("Premium.Treeview.Heading", background=C["border"], foreground=C["accent"],
                        font=("Segoe UI", 11, "bold"), relief="flat", padding=(6, 8))
        style.map("Premium.Treeview", background=[("selected", C["accent"])], foreground=[("selected", "white")])
        style.configure("Vertical.TScrollbar", background=C["border"], troughcolor=C["bg"], borderwidth=0, relief="flat")
        style.configure("Horizontal.TScrollbar", background=C["border"], troughcolor=C["bg"], borderwidth=0, relief="flat")

    def _check_ias(self):
        try:
            disponiveis = set(engine.ias_disponiveis())
        except Exception:
            disponiveis = set()
        for key, dot in self._ia_badges.items():
            dot.configure(text_color=C["accent2"] if key in disponiveis else C["danger"])

    def _atualizar_hora(self):
        self._lbl_hora.configure(text=datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))
        self.after(1000, self._atualizar_hora)

    # ── Busca ─────────────────────────────────────────────────────────────────
    def _iniciar_busca(self):
        estado = self._estados["busca"]
        if estado["buscando"]:
            return
        produto = self._entry_busca.get().strip()
        if not produto:
            messagebox.showwarning("Campo Vazio", "Digite o nome do produto antes de buscar.")
            return
        lojas = [k for k, v in self._check_vars.items() if v.get()]
        if not lojas:
            messagebox.showwarning("Sem Lojas", "Selecione ao menos uma loja para pesquisar.")
            return

        estado["buscando"] = True
        estado["cancelar"].clear()
        estado["resultados"] = []
        self._limpar_tabela(self._tree_busca)
        self._resetar_tiles()
        self._set_resumo("Buscando precos em paralelo nas redes do regiao...")
        self._lbl_status.configure(text=f"Buscando '{produto}' em {len(lojas)} loja(s)...")
        self._progress.configure(mode="indeterminate")
        self._progress.start()
        self._lbl_contagem.configure(text="")
        self._btn_buscar.configure(state="disabled")
        self._btn_cancelar.configure(state="normal")

        workers = int(self._slider_workers.get())
        timeout = int(self._slider_timeout.get())
        # Limite por loja: campo vazio (ou invalido) = trazer TUDO
        try:
            limite_txt = self._entry_limite.get().strip()
            limite_por_loja = int(limite_txt) if limite_txt else None
        except Exception:
            limite_por_loja = None

        def _thread():
            try:
                def cb_status(msg):
                    self.after(0, lambda m=msg: self._lbl_status.configure(text=m))
                resultados = engine.raspar_todos_paralelo(
                    produto=produto, lojas_selecionadas=lojas,
                    parar_event=estado["cancelar"],
                    max_workers=workers, timeout_por_loja=timeout, callback_status=cb_status,
                    limite_por_loja=limite_por_loja,
                )
                estado["resultados"] = resultados
                resumo = ""
                if resultados:
                    try:
                        resumo = engine.ia_resumir_resultados(produto, resultados)
                    except Exception:
                        lojas_unicas = len(set(r.get("supermercado","") for r in resultados))
                        resumo = f"{len(resultados)} resultado(s) em {lojas_unicas} loja(s)."
                self.after(0, self._finalizar_busca, resultados, resumo, produto)
            except Exception as e:
                self.after(0, self._erro_busca, str(e))

        threading.Thread(target=_thread, daemon=True).start()

    def _finalizar_busca(self, resultados, resumo, produto):
        estado = self._estados["busca"]
        estado["buscando"] = False
        self._progress.stop()
        self._progress.configure(mode="determinate")
        self._progress.set(1.0 if resultados else 0)
        self._btn_buscar.configure(state="normal")
        self._btn_cancelar.configure(state="disabled")
        if not resultados:
            self._resetar_tiles()
            self._lbl_status.configure(text=f"Nenhum resultado para '{produto}'.")
            self._set_resumo("Nenhum produto encontrado. Tente outros termos ou mais lojas.")
            return
        lojas_unicas = len(set(r.get("supermercado","") for r in resultados))
        self._lbl_status.configure(text=f"{len(resultados)} resultado(s) em {lojas_unicas} loja(s).")
        self._lbl_contagem.configure(text=f"{len(resultados)} itens")
        self._atualizar_tiles(resultados)
        self._popular_tabela(self._tree_busca, resultados)
        self._set_resumo(resumo or "Resumo nao disponivel.")

    def _erro_busca(self, msg):
        self._estados["busca"]["buscando"] = False
        self._progress.stop()
        self._progress.configure(mode="determinate")
        self._progress.set(0)
        self._btn_buscar.configure(state="normal")
        self._btn_cancelar.configure(state="disabled")
        self._lbl_status.configure(text=f"Erro: {msg[:80]}")

    def _cancelar_busca(self):
        self._estados["busca"]["cancelar"].set()
        self._lbl_status.configure(text="Cancelando...")
        self._btn_cancelar.configure(state="disabled")

    # ── Encartes ──────────────────────────────────────────────────────────────
    def _iniciar_encartes(self):
        estado = self._estados["encartes"]
        if estado["buscando"]:
            return
        estado["buscando"] = True
        estado["cancelar"].clear()
        estado["resultados"] = []
        self._limpar_tabela(self._tree_enc)
        self._lbl_status_enc.configure(text="Buscando encartes de todas as redes...")
        self._btn_encartes.configure(state="disabled")
        self._btn_canc_enc.configure(state="normal")

        def _thread():
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    nav = engine.lancar_navegador_seguro(pw)
                    ctx = nav.new_context()
                    pag = ctx.new_page()
                    resultados = engine.buscar_encartes_todos(pag, ctx)
                    nav.close()
                estado["resultados"] = resultados
                self.after(0, self._finalizar_encartes, resultados)
            except Exception as e:
                self.after(0, self._erro_encartes, str(e))

        threading.Thread(target=_thread, daemon=True).start()

    def _finalizar_encartes(self, resultados):
        estado = self._estados["encartes"]
        estado["buscando"] = False
        self._btn_encartes.configure(state="normal")
        self._btn_canc_enc.configure(state="disabled")
        if not resultados:
            self._lbl_status_enc.configure(text="Nenhum encarte encontrado.")
            return
        lojas_unicas = len(set(r.get("supermercado","") for r in resultados))
        self._lbl_status_enc.configure(text=f"{len(resultados)} produto(s) de encarte de {lojas_unicas} rede(s).")
        self._limpar_tabela(self._tree_enc)
        for i, r in enumerate(resultados):
            tag = "par" if i % 2 == 0 else "impar"
            self._tree_enc.insert("", "end", values=(i+1, r.get("supermercado","—"),
                                                      r.get("produto_encontrado","—"),
                                                      r.get("preco_normal","—")), tags=(tag,))

    def _erro_encartes(self, msg):
        self._estados["encartes"]["buscando"] = False
        self._btn_encartes.configure(state="normal")
        self._btn_canc_enc.configure(state="disabled")
        self._lbl_status_enc.configure(text=f"Erro: {msg[:80]}")

    def _cancelar_encartes(self):
        self._estados["encartes"]["cancelar"].set()
        self._lbl_status_enc.configure(text="Cancelando encartes...")
        self._btn_canc_enc.configure(state="disabled")

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _preco_para_float(texto):
        if not texto or str(texto).strip() in ("—", "-", ""):
            return None
        s = re.sub(r'[^\d.,]', '', str(texto))
        if not s:
            return None
        if '.' in s and ',' in s:
            s = s.replace('.', '').replace(',', '.')
        elif ',' in s:
            s = s.replace(',', '.')
        try:
            return float(s)
        except ValueError:
            return None

    def _preco_efetivo(self, r):
        v = self._preco_para_float(r.get("preco_oferta"))
        if v is None:
            v = self._preco_para_float(r.get("preco_normal"))
        return v

    def _indice_menor_preco(self, resultados):
        melhor_idx, melhor_val = -1, None
        for i, r in enumerate(resultados):
            v = self._preco_efetivo(r)
            if v is None:
                continue
            if melhor_val is None or v < melhor_val:
                melhor_val, melhor_idx = v, i
        return melhor_idx

    def _resetar_tiles(self):
        for lbl in (self._tile_total, self._tile_ofertas, self._tile_lojas, self._tile_menor):
            lbl.configure(text="—")

    def _atualizar_tiles(self, resultados):
        total = len(resultados)
        ofertas = sum(1 for r in resultados if r.get("preco_oferta") and r.get("preco_oferta") != "—")
        lojas = len(set(r.get("supermercado", "") for r in resultados))
        precos = [v for v in (self._preco_efetivo(r) for r in resultados) if v is not None]
        menor = min(precos) if precos else None
        self._tile_total.configure(text=str(total))
        self._tile_ofertas.configure(text=str(ofertas))
        self._tile_lojas.configure(text=str(lojas))
        self._tile_menor.configure(text=(f"R$ {menor:.2f}".replace('.', ',') if menor is not None else "—"))

    def _popular_tabela(self, tree, resultados):
        self._limpar_tabela(tree)
        idx_melhor = self._indice_menor_preco(resultados)
        for i, r in enumerate(resultados):
            preco_o = r.get("preco_oferta", "—")
            if i == idx_melhor:
                tag = "melhor"
            elif preco_o and preco_o != "—":
                tag = "preco"
            else:
                tag = "par" if i % 2 == 0 else "impar"
            nome = r.get("produto_encontrado", "—")
            if i == idx_melhor:
                nome = "★ " + nome
            tree.insert("", "end", values=(
                i+1,
                r.get("supermercado","—"),
                nome,
                r.get("preco_normal","—"),
                preco_o if preco_o != "—" else "—",
                r.get("ean","—"),
                r.get("metodo_ean","—"),
            ), tags=(tag,))

    def _limpar_tabela(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def _set_resumo(self, texto):
        self._txt_resumo.configure(state="normal")
        self._txt_resumo.delete("1.0", "end")
        self._txt_resumo.insert("end", texto)
        self._txt_resumo.configure(state="disabled")

    # ── Confronto de Catalogo (CSV) ─────────────────────────────────────────────
    def _build_tab_confronto(self):
        tab = self._tab_confronto
        tab.configure(fg_color=C["card"])
        tab.grid_rowconfigure(4, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        pa = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        pa.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        pa.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            pa, text="Importar CSV (nome;ean)", font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=C["accent"], hover_color="#3a7af5", text_color="white",
            height=42, width=200, corner_radius=8, command=self._confronto_importar
        ).grid(row=0, column=0, padx=(16, 8), pady=14)
        self._lbl_confronto_arquivo = ctk.CTkLabel(
            pa, text="Nenhum CSV carregado.", font=ctk.CTkFont("Segoe UI", 12),
            text_color=C["text_dim"], anchor="w")
        self._lbl_confronto_arquivo.grid(row=0, column=1, sticky="w", padx=8)
        self._chk_confronto_ia = ctk.CTkCheckBox(
            pa, text="IA confirma", font=ctk.CTkFont("Segoe UI", 11),
            fg_color=C["accent"], hover_color=C["accent_hi"], text_color=C["text"],
            checkmark_color="white", border_color=C["border"])
        self._chk_confronto_ia.select()
        self._chk_confronto_ia.grid(row=0, column=2, padx=8)
        self._btn_confronto = ctk.CTkButton(
            pa, text="Confrontar", font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=C["accent2"], hover_color="#17bf88", text_color=C["bg"],
            height=42, width=140, corner_radius=8, command=self._confronto_iniciar, state="disabled")
        self._btn_confronto.grid(row=0, column=3, padx=8, pady=14)
        self._btn_confronto_canc = ctk.CTkButton(
            pa, text="Cancelar", font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=C["danger"], hover_color="#c0392b", text_color="white",
            height=42, width=120, corner_radius=8, command=self._confronto_cancelar, state="disabled")
        self._btn_confronto_canc.grid(row=0, column=4, padx=(0, 16), pady=14)

        pl = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        pl.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        ctk.CTkLabel(pl, text="Lojas:", font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["accent"]).grid(row=0, column=0, sticky="w", padx=12, pady=8)
        self._confronto_check_vars = {}
        box = ctk.CTkFrame(pl, fg_color="transparent")
        box.grid(row=0, column=1, sticky="w")
        for idx, (chave, nome) in enumerate([("aurora", "Aurora"), ("vizinho", "Vizinho"), ("atacauno", "Atacado Uno")]):
            var = tk.BooleanVar(value=True)
            self._confronto_check_vars[chave] = var
            ctk.CTkCheckBox(box, text=nome, variable=var, font=ctk.CTkFont("Segoe UI", 11),
                            fg_color=C["accent"], hover_color=C["accent_hi"], text_color=C["text"],
                            checkmark_color="white", border_color=C["border"], width=120
                            ).grid(row=0, column=idx, padx=6, pady=6, sticky="w")

        ps = ctk.CTkFrame(tab, fg_color="transparent")
        ps.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))
        ps.grid_columnconfigure(0, weight=1)
        self._lbl_confronto_status = ctk.CTkLabel(
            ps, text="Importe um CSV com colunas nome;ean para comecar.",
            font=ctk.CTkFont("Segoe UI", 12), text_color=C["text_dim"], anchor="w")
        self._lbl_confronto_status.grid(row=0, column=0, sticky="w", padx=4)
        self._confronto_progress = ctk.CTkProgressBar(
            ps, fg_color=C["border"], progress_color=C["accent2"], height=4, corner_radius=2)
        self._confronto_progress.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 0))
        self._confronto_progress.set(0)

        leg = ctk.CTkFrame(tab, fg_color="transparent")
        leg.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 2))
        for cor, txt in [(C["accent2"], "Verde: EAN oficial"), ("#4ea3f2", "Azul: NLP/IA forte"),
                         (C["accent3"], "Amarelo: conferir"), (C["text_dim"], ">=75% = mesmo produto")]:
            ctk.CTkLabel(leg, text="  ● " + txt, font=ctk.CTkFont("Segoe UI", 10),
                         text_color=cor).pack(side="left", padx=4)

        ft = ctk.CTkFrame(tab, fg_color=C["bg"], corner_radius=10)
        ft.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 6))
        ft.grid_rowconfigure(0, weight=1)
        ft.grid_columnconfigure(0, weight=1)
        self._tree_confronto = self._criar_tabela(ft, [
            ("#", 40), ("Meu Produto", 200), ("Meu EAN", 120), ("Loja", 110),
            ("Produto Concorrente", 250), ("EAN", 120), ("Preco Normal", 100),
            ("Preco Oferta", 100), ("Sim%", 60), ("Faixa", 80)
        ])
        self._tree_confronto.tag_configure("verde",   foreground=C["accent2"])
        self._tree_confronto.tag_configure("azul",    foreground="#4ea3f2")
        self._tree_confronto.tag_configure("amarelo", foreground=C["accent3"])
        self._tree_confronto.tag_configure("naoenc",  foreground=C["text_dim"])

        pe = ctk.CTkFrame(tab, fg_color="transparent")
        pe.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 12))
        ctk.CTkButton(pe, text="Exportar TXT (EAN;PRECO)", font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      fg_color=C["accent"], hover_color="#3a7af5", text_color="white",
                      height=36, width=210, corner_radius=8, command=self._confronto_exportar_txt
                      ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(pe, text="Exportar CSV detalhado", font=ctk.CTkFont("Segoe UI", 12),
                      fg_color=C["border"], hover_color=C["card_hover"], text_color=C["text"],
                      height=36, width=190, corner_radius=8, command=self._confronto_exportar_csv
                      ).pack(side="left")

    def _confronto_importar(self):
        caminho = filedialog.askopenfilename(
            title="Selecione o CSV (nome;ean)",
            filetypes=[("CSV", "*.csv"), ("Texto", "*.txt"), ("Todos", "*.*")])
        if not caminho:
            return
        try:
            itens = engine.ler_catalogo_csv(caminho)
        except Exception as ex:
            messagebox.showerror("Erro ao ler CSV", str(ex))
            return
        if not itens:
            messagebox.showwarning("CSV vazio", "Nao encontrei itens. Esperado colunas nome;ean.")
            return
        self._estados["confronto"]["itens"] = itens
        com_ean = sum(1 for it in itens if it.get("ean"))
        self._lbl_confronto_arquivo.configure(
            text=f"{os.path.basename(caminho)}  —  {len(itens)} itens ({com_ean} com EAN)")
        self._lbl_confronto_status.configure(text="Pronto. Clique em Confrontar.")
        self._btn_confronto.configure(state="normal")

    def _confronto_iniciar(self):
        estado = self._estados["confronto"]
        if estado["rodando"]:
            return
        itens = estado["itens"]
        if not itens:
            messagebox.showwarning("Sem catalogo", "Importe um CSV primeiro.")
            return
        lojas = [k for k, v in self._confronto_check_vars.items() if v.get()]
        if not lojas:
            messagebox.showwarning("Sem lojas", "Selecione ao menos uma loja.")
            return
        usar_ia = bool(self._chk_confronto_ia.get())
        estado["rodando"] = True
        estado["cancelar"].clear()
        estado["linhas"] = []
        self._limpar_tabela(self._tree_confronto)
        self._btn_confronto.configure(state="disabled")
        self._btn_confronto_canc.configure(state="normal")
        self._confronto_progress.set(0)
        workers = int(self._slider_workers.get()) if hasattr(self, "_slider_workers") else 4
        timeout = int(self._slider_timeout.get()) if hasattr(self, "_slider_timeout") else 45

        def _prog(i, tot, nome):
            frac = i / max(tot, 1)
            self.after(0, lambda: self._confronto_progress.set(frac))
            self.after(0, lambda: self._lbl_confronto_status.configure(
                text=f"[{i+1}/{tot}] Confrontando: {nome[:45]}"))

        def _thread():
            try:
                linhas = engine.confrontar_catalogo(
                    itens, lojas=lojas, parar_event=estado["cancelar"],
                    max_workers=workers, timeout_por_loja=timeout,
                    usar_ia=usar_ia, callback_progresso=_prog)
                estado["linhas"] = linhas
                self.after(0, self._confronto_finalizar, linhas)
            except Exception as ex:
                self.after(0, self._confronto_erro, str(ex))

        threading.Thread(target=_thread, daemon=True).start()

    def _confronto_finalizar(self, linhas):
        estado = self._estados["confronto"]
        estado["rodando"] = False
        self._btn_confronto.configure(state="normal")
        self._btn_confronto_canc.configure(state="disabled")
        self._confronto_progress.set(1.0 if linhas else 0)
        if not linhas:
            self._lbl_confronto_status.configure(text="Nenhum match encontrado.")
            return
        cont = {}
        for l in linhas:
            cont[l.get("faixa", "")] = cont.get(l.get("faixa", ""), 0) + 1
        nenc = cont.get("Nao encontrado", 0)
        matches = len(linhas) - nenc
        self._lbl_confronto_status.configure(
            text=(f"{len(linhas)} linha(s) — {matches} match(es):  "
                  f"Verde {cont.get('Verde',0)} | Azul {cont.get('Azul',0)} | "
                  f"Amarelo {cont.get('Amarelo',0)} | Nao encontrado {nenc}"))
        self._confronto_popular(linhas)

    def _confronto_popular(self, linhas):
        self._limpar_tabela(self._tree_confronto)
        tag_por_faixa = {"Verde": "verde", "Azul": "azul", "Amarelo": "amarelo", "Nao encontrado": "naoenc"}
        for i, l in enumerate(linhas):
            tag = tag_por_faixa.get(l.get("faixa", ""), "impar")
            self._tree_confronto.insert("", "end", values=(
                i + 1, l.get("meu_nome", ""), l.get("meu_ean", "") or "—", l.get("loja", ""),
                l.get("produto_concorrente", ""), l.get("ean_concorrente", "") or "—",
                l.get("preco_normal", "—"), l.get("preco_oferta", "—"),
                l.get("similaridade", 0), l.get("faixa", "")
            ), tags=(tag,))

    def _confronto_erro(self, msg):
        estado = self._estados["confronto"]
        estado["rodando"] = False
        self._btn_confronto.configure(state="normal")
        self._btn_confronto_canc.configure(state="disabled")
        self._lbl_confronto_status.configure(text=f"Erro: {msg[:80]}")

    def _confronto_cancelar(self):
        self._estados["confronto"]["cancelar"].set()
        self._lbl_confronto_status.configure(text="Cancelando...")
        self._btn_confronto_canc.configure(state="disabled")

    def _confronto_exportar_txt(self):
        linhas = self._estados["confronto"]["linhas"]
        if not linhas:
            messagebox.showinfo("Exportar", "Rode um confronto primeiro.")
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Texto", "*.txt"), ("Todos", "*.*")],
            initialfile=f"confronto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if caminho:
            engine.exportar_confronto_txt(linhas, caminho)
            messagebox.showinfo("Exportado", f"TXT (EAN;PRECO) salvo!\n{caminho}")

    def _confronto_exportar_csv(self):
        linhas = self._estados["confronto"]["linhas"]
        if not linhas:
            messagebox.showinfo("Exportar", "Rode um confronto primeiro.")
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
            initialfile=f"confronto_detalhado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        if caminho:
            engine.exportar_confronto_csv(linhas, caminho)
            messagebox.showinfo("Exportado", f"CSV detalhado salvo!\n{caminho}")

    def _exportar_csv(self):
        tab = self._tabview.get()
        resultados = self._estados["busca"]["resultados"] if "Busca" in tab else self._estados["encartes"]["resultados"]
        if not resultados:
            messagebox.showinfo("Exportar", "Nenhum resultado para exportar.")
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV","*.csv"),("Todos","*.*")],
            initialfile=f"superpreco_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if caminho:
            engine.exportar_para_csv(resultados)
            messagebox.showinfo("Exportado", f"CSV salvo!\n{caminho}")


if __name__ == "__main__":
    app = AppPesquisaPreco()
    app.mainloop()
