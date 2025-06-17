import os

# 🔥 PRODUÇÃO: Usar variáveis de ambiente
BOT_TOKEN = os.getenv("BOT_TOKEN", "7564123816:AAEuQudLmTFJMMLM9dF7zOsoL5ZVmxICYmY")
CANAL_ADMIN_ID = os.getenv("CANAL_ADMIN_ID", "-1002313875940")
LINK_CHAMADA = os.getenv("LINK_CHAMADA", "https://pixel-video-call.vercel.app/purchase.html")

# 🔥 REDIS: Railway vai dar URL automática
REDIS_URL = None  # Desabilitado temporariamente

# MENSAGENS (igual)
MENSAGENS = {
    "comprovante_recebido": "",
    "pagamento_aprovado": "{link_chamada}",
    "pagamento_rejeitado": "",
    "instrucoes": (
        "💰 **Sistema de Comprovantes**\n\n"
        "📸 Para enviar seu comprovante de pagamento:\n"
        "• Envie uma **foto** do comprovante\n"
        "• Ou envie um **documento** (PDF, imagem, etc.)\n\n"
        "⏳ Após o envio, aguarde a verificação.\n"
        "✅ Você receberá o link da chamada quando aprovado!"
    )
}

# Rate Limiting (igual)
RATE_LIMITS = {
    "start_command": {"limit": 3, "window": 300},
    "webhook": {"limit": 5, "window": 3600},
    "messages": {"limit": 10, "window": 60}
}
