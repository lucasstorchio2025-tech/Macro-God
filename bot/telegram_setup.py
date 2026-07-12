"""
Telegram Setup — Wealth Engine
================================
Configura as notificações do bot no Telegram.

COMO USAR:
  1. Abra o Telegram, procure por @BotFather
  2. Envie /newbot e siga as instruções
  3. Guarde o token que o BotFather te der (ex: 123456:ABC-DEF1234...)
  4. Envie uma mensagem qualquer pro seu bot (ex: "Oi")
  5. Rode este script:
       python bot/telegram_setup.py

O script vai:
  - Perguntar seu token
  - Descobrir seu chat_id automaticamente
  - Salvar as credenciais no .env do projeto
  - Testar enviando uma mensagem
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

def get_updates(token: str) -> list:
    """Pega as últimas mensagens recebidas pelo bot."""
    import requests
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            timeout=15,
        )
        data = r.json()
        if not data.get("ok"):
            print(f"  ERRO: {data.get('description', 'resposta inválida')}")
            return []
        return data.get("result", [])
    except Exception as e:
        print(f"  ERRO ao conectar: {e}")
        return []

def send_test(token: str, chat_id: str) -> bool:
    """Envia mensagem de teste."""
    import requests
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/sendMessage",
            params={"chat_id": chat_id, "text": "🤖 Wealth Engine — Teste de notificação OK!"},
            timeout=15,
        )
        data = r.json()
        if data.get("ok"):
            return True
        print(f"  ERRO: {data.get('description', 'resposta inválida')}")
        return False
    except Exception as e:
        print(f"  ERRO ao enviar: {e}")
        return False


def main():
    print("=" * 60)
    print("  Wealth Engine — Configuração de Telegram")
    print("=" * 60)
    print()
    print("Antes de continuar, você PRECISA:")
    print("  1. Ir no Telegram, procurar @BotFather")
    print("  2. Enviar /newbot, escolher um nome (ex: Wealth Engine Alerts)")
    print("  3. Escolher um username (ex: WealthEngineBot)")
    print("  4. Guardar o TOKEN que o BotFather te der")
    print("  5. Enviar UMA mensagem pro seu bot (qualquer coisa)")
    print()

    token = input("Cole o TOKEN do seu bot (ex: 123456:ABC-DEF...): ").strip()
    if not token or len(token) < 20:
        print("  Token inválido. Deve ser algo como 123456:ABC-DEF...")
        sys.exit(1)

    print("\n  Procurando seu chat_id...")
    updates = get_updates(token)

    if not updates:
        print()
        print("  Nenhuma mensagem encontrada.")
        print("  Passo a passo:")
        print("    1. Abra o Telegram no seu celular/PC")
        print("    2. Procure pelo username do seu bot (ex: @WealthEngineBot)")
        print("    3. Envie uma mensagem qualquer (ex: 'Oi')")
        print("    4. Rode este script novamente")
        sys.exit(1)

    # Pega o chat_id da última mensagem
    last = updates[-1]
    message = last.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))

    from_user = chat.get("first_name", "?")
    username = chat.get("username", "?")
    print(f"  Chat encontrado: {from_user} (@{username}) — ID: {chat_id}")

    # Testa envio
    print("\n  Enviando mensagem de teste...")
    if send_test(token, chat_id):
        print(f"  ✅ Mensagem enviada! Verifique o Telegram.")
    else:
        print("  ❌ Falha ao enviar. Verifique o token.")
        sys.exit(1)

    # Salva no .env
    print(f"\n  Salvando credenciais em: {ENV_PATH}")
    
    # Lê .env existente se houver
    env_lines = []
    if ENV_PATH.exists():
        env_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    
    # Remove linhas existentes de TELEGRAM
    env_lines = [l for l in env_lines 
                 if not l.strip().startswith("TELEGRAM_BOT_TOKEN=") 
                 and not l.strip().startswith("TELEGRAM_CHAT_ID=")]
    
    # Adiciona as novas
    env_lines.append(f"TELEGRAM_BOT_TOKEN={token}")
    env_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
    
    ENV_PATH.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    
    print("  ✅ Credenciais salvas!")
    print()
    print("=" * 60)
    print("  Configuração concluída!")
    print(f"  Token:    {token[:12]}...{token[-4:]}")
    print(f"  Chat ID:  {chat_id}")
    print()
    print("  O bot já vai usar Telegram nas próximas notificações.")
    print("=" * 60)


if __name__ == "__main__":
    main()
