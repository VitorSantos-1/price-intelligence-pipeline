import os
import sys
import subprocess


def _achar_ms_playwright():
    """Pasta onde o Playwright guarda os navegadores nesta maquina."""
    caminho = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")
    return caminho if os.path.isdir(caminho) else None


def compilar():
    print("====================================================")
    print("   GERADOR DE EXECUTAVEL GUI - PESQUISA DE PRECO v4 ")
    print("====================================================")

    v4_dir = os.path.dirname(os.path.abspath(__file__))
    script_principal = os.path.join(v4_dir, "app_gui.py")
    env_file = os.path.join(v4_dir, ".env")

    print("\n[1/3] Preparando PyInstaller sem janela de terminal (--noconsole)...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--noconsole",                     # Esconde a janela preta do CMD!
        "--onedir",                        # Pasta portatil do aplicativo
        "--name=PesquisaPreco_v4",
        f"--add-data={env_file};.",
        "--collect-all=customtkinter",
        "--collect-all=playwright",
        "--collect-all=openai",
        "--collect-all=google.generativeai",
        "--collect-all=groq",
        "--collect-all=pdfplumber",
        "--collect-all=PIL",
    ]

    # Empacota o navegador Chromium do Playwright junto do app, para que a BUSCA
    # funcione tambem em computadores onde o Playwright nunca foi instalado.
    # (o app_gui/engine procuram por _internal/ms-playwright em tempo de execucao)
    ms_pw = _achar_ms_playwright()
    if ms_pw:
        cmd.append(f"--add-data={ms_pw};ms-playwright")
        print(f"[i] Empacotando navegador do Playwright de:\n    {ms_pw}")
        print("    (isso aumenta bastante o tamanho do app, mas garante a busca funcionando)")
    else:
        print("[!] ms-playwright NAO encontrado nesta maquina.")
        print("    Rode antes:  playwright install chromium")
        print("    Sem isso, a busca so vai funcionar em PCs que ja tenham o Chromium do Playwright.")

    cmd.append(script_principal)

    print("[2/3] Compilando interface grafica (aguarde)...")
    result = subprocess.run(cmd, cwd=v4_dir)

    if result.returncode == 0:
        print("\n====================================================")
        print("   COMPILACAO CONCLUIDA COM SUCESSO! ")
        print("====================================================")
        print("Aplicativo Desktop sem CMD gerado em:")
        print(f"  {os.path.join(v4_dir, 'dist', 'PesquisaPreco_v4')}")
        print("\nExecutavel principal:")
        print(f"  {os.path.join(v4_dir, 'dist', 'PesquisaPreco_v4', 'PesquisaPreco_v4.exe')}")
        print("\n[3/3] Agora gere o instalador compilando 'installer_config.iss' no Inno Setup.")
    else:
        print("\nErro durante a compilacao. Verifique os logs acima.")


if __name__ == "__main__":
    compilar()
