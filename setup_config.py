#!/usr/bin/env python3
"""
genomics-mcp セットアップスクリプト

Python標準ライブラリのみで動作します。
uv の検出・自動インストール、APIキー設定、Claude Desktop設定ファイルの自動生成を行います。
"""

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def find_uv() -> str | None:
    """uv コマンドのパスを検出する"""
    # まず PATH 上を探す
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path

    # よくあるインストール先を探す
    home = Path.home()
    candidates = []
    if platform.system() == "Windows":
        candidates = [
            home / ".local" / "bin" / "uv.exe",
            home / ".cargo" / "bin" / "uv.exe",
        ]
    else:
        candidates = [
            home / ".local" / "bin" / "uv",
            home / ".cargo" / "bin" / "uv",
        ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def check_uv_version(uv_cmd: str) -> bool:
    """uv が正常に動作するか確認する"""
    try:
        result = subprocess.run(
            [uv_cmd, "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"  uv が見つかりました: {result.stdout.strip()}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return False


def install_uv() -> str | None:
    """uv を自動インストールする"""
    answer = input("\nuv が見つかりません。自動インストールしますか？ (Y/n): ").strip()
    if answer.lower() == "n":
        print("uv のインストールをスキップしました。")
        print("手動でインストールする場合:")
        if platform.system() == "Windows":
            print('  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"')
        else:
            print('  curl -LsSf https://astral.sh/uv/install.sh | sh')
        return None

    print("\nuv をインストールしています...")

    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["powershell", "-ExecutionPolicy", "ByPass", "-c",
                 "irm https://astral.sh/uv/install.ps1 | iex"],
                check=True, timeout=120
            )
        else:
            subprocess.run(
                ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
                check=True, timeout=120
            )
    except subprocess.CalledProcessError as e:
        print(f"uv のインストールに失敗しました: {e}")
        return None
    except subprocess.TimeoutExpired:
        print("uv のインストールがタイムアウトしました。")
        return None

    # インストール後に再検出
    uv_path = find_uv()
    if uv_path and check_uv_version(uv_path):
        return uv_path

    # PATH が通っていない場合の案内
    home = Path.home()
    if platform.system() == "Windows":
        expected = home / ".local" / "bin"
        print(f"\n⚠ uv はインストールされましたが、PATHに含まれていない可能性があります。")
        print(f"  ターミナルを再起動するか、以下をPATHに追加してください:")
        print(f"  {expected}")
        candidate = expected / "uv.exe"
    else:
        expected = home / ".local" / "bin"
        print(f"\n⚠ uv はインストールされましたが、PATHに含まれていない可能性があります。")
        print(f"  ターミナルを再起動するか、以下をPATHに追加してください:")
        print(f"  {expected}")
        candidate = expected / "uv"

    if candidate.exists():
        return str(candidate)

    return None


def setup_env(script_dir: Path) -> dict:
    """APIキーの対話的設定を行い、.env を作成・更新する"""
    env_file = script_dir / ".env"
    env_example = script_dir / ".env.example"
    current_values = {"NCBI_API_KEY": "", "ONCOKB_TOKEN": ""}

    # 既存の .env があれば読み込む
    if env_file.exists():
        print("\n既存の .env ファイルを検出しました。")
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key in current_values:
                        current_values[key] = value

        # 現在の値を表示
        for key, value in current_values.items():
            if value:
                masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "****"
                print(f"  {key}: {masked}")
            else:
                print(f"  {key}: (未設定)")

        answer = input("\nAPIキーを変更しますか？ (y/N): ").strip()
        if answer.lower() != "y":
            return current_values

    print("\n--- APIキーの設定 ---")

    ncbi_key = input(
        "NCBI API Keyを入力してください（なければEnterでスキップ）: "
    ).strip()
    if ncbi_key:
        current_values["NCBI_API_KEY"] = ncbi_key

    oncokb_token = input(
        "OncoKB Tokenを入力してください（なければEnterでスキップ）: "
    ).strip()
    if oncokb_token:
        current_values["ONCOKB_TOKEN"] = oncokb_token

    # .env ファイルを書き出し
    lines = []
    if env_example.exists():
        with open(env_example, "r", encoding="utf-8") as f:
            for line in f:
                written = False
                for key in current_values:
                    if line.strip().startswith(f"{key}="):
                        lines.append(f"{key}={current_values[key]}\n")
                        written = True
                        break
                if not written:
                    lines.append(line)
    else:
        for key, value in current_values.items():
            lines.append(f"{key}={value}\n")

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"  .env を保存しました: {env_file}")
    return current_values


def generate_config(script_dir: Path, env_values: dict):
    """claude_desktop_config.json を生成・マージする"""
    template_file = script_dir / "config_template.json"
    if not template_file.exists():
        print(f"エラー: config_template.json が見つかりません: {template_file}")
        sys.exit(1)

    with open(template_file, "r", encoding="utf-8") as f:
        template = f.read()

    # プレースホルダーを置換
    install_dir = str(script_dir).replace("\\", "\\\\")
    documents_dir = str(Path.home() / "Documents").replace("\\", "\\\\")
    template = template.replace("{{INSTALL_DIR}}", install_dir)
    template = template.replace("{{DOCUMENTS_DIR}}", documents_dir)
    template = template.replace("{{NCBI_API_KEY}}", env_values.get("NCBI_API_KEY", ""))
    template = template.replace("{{ONCOKB_TOKEN}}", env_values.get("ONCOKB_TOKEN", ""))

    new_config = json.loads(template)

    # Claude Desktop の設定ファイルパスを検出
    if platform.system() == "Windows":
        config_path = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"

    # 既存ファイルがある場合はマージ
    if config_path.exists():
        # バックアップ
        backup_path = config_path.with_suffix(".json.bak")
        shutil.copy2(config_path, backup_path)
        print(f"  既存設定のバックアップ: {backup_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            existing_config = json.load(f)

        # mcpServers をマージ（既存キーは上書き、他は保持）
        if "mcpServers" not in existing_config:
            existing_config["mcpServers"] = {}
        existing_config["mcpServers"].update(new_config["mcpServers"])
        final_config = existing_config
    else:
        # ディレクトリがなければ作成
        config_path.parent.mkdir(parents=True, exist_ok=True)
        final_config = new_config

    # 書き出し
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(final_config, f, indent=2, ensure_ascii=False)

    print(f"  設定ファイルを更新しました: {config_path}")
    return config_path


def main():
    print("=" * 60)
    print("  genomics-mcp セットアップ")
    print("=" * 60)

    script_dir = Path(__file__).resolve().parent

    # 1. uv の検出・自動インストール
    print("\n[1/3] uv の確認...")
    uv_path = find_uv()

    if uv_path and check_uv_version(uv_path):
        pass  # OK
    else:
        uv_path = install_uv()
        if not uv_path:
            print("\n⚠ uv が利用できません。手動でインストールしてください。")
            print("  セットアップは続行しますが、サーバー起動には uv が必要です。")

    # 2. APIキー設定
    print("\n[2/3] APIキーの設定...")
    env_values = setup_env(script_dir)

    # 3. claude_desktop_config.json の生成
    print("\n[3/3] Claude Desktop 設定ファイルの生成...")
    config_path = generate_config(script_dir, env_values)

    # 完了メッセージ
    servers = ["pubmed", "clinvar", "civic", "oncokb", "semantic_scholar", "clinicaltrials"]
    print("\n" + "=" * 60)
    print("  セットアップ完了！Claude Desktopを再起動してください。")
    print("=" * 60)
    print(f"\n  設定ファイル: {config_path}")
    print(f"  登録されたサーバー: {', '.join(servers)}")

    # filesystem サーバーの案内
    npx_path = shutil.which("npx")
    if npx_path:
        print(f"\n  ✅ Filesystemサーバーも登録済み（Node.js検出済み）")
        print(f"     Claudeがローカルファイルを読み書きできます")
    else:
        print(f"\n  💡 Filesystemサーバー: Node.jsをインストールすると使えるようになります")
        print(f"     （Node.js無しでも他の6サーバーは正常に動作します）")

    if not env_values.get("ONCOKB_TOKEN"):
        print("\n  ⚠ OncoKBサーバーはTokenを設定するまで動作しません。")
        print("    取得方法: https://www.oncokb.org/account/register")

    if not env_values.get("NCBI_API_KEY"):
        print("\n  💡 NCBI API Keyを設定するとPubMed検索のレートリミットが緩和されます。")
        print("    取得方法: https://www.ncbi.nlm.nih.gov/account/")

    print()


if __name__ == "__main__":
    main()
