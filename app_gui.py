"""
app_gui.py — Interface Grafica Premium v5.0
SuperPreco Ceara — Inteligencia de Mercado
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
C = {
    "bg":          "#0a0e1a",
    "sidebar":     "#0d1224",
    "card":        "#111827",
    "card_hover":  "#1a2235",
    "tile":        "#0f1729",
    "border":      "#1e2d45",
    "accent":      "#4f8ef7",
    "accent_hi":   "#3a7af5",
    "accent2":     "#1ed99e",
    "accent3":     "#f7934f",
    "danger":      "#f75f4f",
    "text":        "#e8eaf6",
    "text_dim":    "#7b8ab0",
    "preco":       "#1ed99e",
    "melhor_bg":   "#0c3a2a",
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
    "diniz":    "Diniz",
    "saoluiz":  "Sao Luiz",
    "atacadao": "Atacadao",
    "assai":    "Assai (encarte)",
}


class AppPesquisaPreco(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SuperPreco Ceara v5.0 — Inteligencia de Mercado")
        self.geometry("1280x820")
        self.minsize(1024, 640)
        self.configure(fg_color=C["bg"])
        self._estados = {
            "busca":    {"resultados": [], "buscando": False, "cancelar": threading.Event()},
            "encartes": {"resultados": [], "buscando": False, "cancelar": threading.Event()},
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
        self._tab_busca    = self._tabview.add("  Busca Unificada")
        self._tab_encartes = self._tabview.add("  Encartes")
        self._tab_config   = self._tabview.add("  Configuracoes")
        self._build_tab_busca()
        self._build_tab_encartes()
        self._build_tab_config()

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, fg_color=C["sidebar"], corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(9, weight=1)

        ctk.CTkLabel(sb, text="SUPERPRECO", font=ctk.CTkFont("Segoe UI", 22, "bold"),
                     text_color=C["accent"]).grid(row=0, column=0, pady=(24, 2))
        ctk.CTkLabel(sb, text="CEARA v5.0", font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["accent2"]).grid(row=1, column=0, pady=(0, 16))
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
        ctk.CTkLabel(sb, text="© 2025 Ceara Edition", font=ctk.CTkFont("Segoe UI",9),
                     text_color=C["text_dim"]).grid(row=13, column=0, pady=(8,16))

    def _build_header(self):
        hdr = ctk.CTkFrame(self._main_frame, fg_color="transparent", height=56)
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(12,8))
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_propagate(False)
        ctk.CTkLabel(hdr, text="SuperPreco Ceara — Central de Inteligencia de Mercado",
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
        
        frame_grid_lojas = ctk.CTkFrame(pl, fg_color="transparent")
        frame_grid_lojas.grid(row=1, column=0, sticky="ew", padx=12, pady=(0,8))
        
        self._check_vars = {}
        items = list(LOJAS_CONFIG.items())
        cols_per_row = 6
        for idx, (chave, nome) in enumerate(items):
            r = idx // cols_per_row
            c = idx % cols_per_row
            var = tk.BooleanVar(value=True)
            self._check_vars[chave] = var
            ctk.CTkCheckBox(
                frame_grid_lojas, text=nome, variable=var,
                font=ctk.CTkFont("Segoe UI",11), fg_color=C["accent"],
                hover_color="#3a7af5", text_color=C["text"], checkmark_color="white",
                border_color=C["border"], width=130
            ).grid(row=r, column=c, padx=6, pady=4, sticky="w")
            
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
        ctk.CTkLabel(pe, text="Varredura de Encartes PDF de todas as redes do Ceara",
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
        self._set_resumo("Buscando precos em paralelo nas redes do Ceara...")
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
