BOT_TOKEN = "7564123816:AAEuQudLmTFJMMLM9dF7zOsoL5ZVmxICYmY"  
CANAL_ADMIN_ID = "-1002313875940"  
LINK_CHAMADA = "https://pixel-video-call.vercel.app/purchase.html"  

# MENSAGENS PERSONALIZÁVEIS
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

# ===== NOVAS CONFIGURAÇÕES REDIS + RATE LIMITING =====

# Redis Configuration
REDIS_URL = "redis://localhost:6379/0"  # Para usar Redis local

# Rate Limiting Configuration
RATE_LIMITS = {
    "start_command": {
        "limit": 3,           # 3 comandos /start
        "window": 300         # em 5 minutos (300 segundos)
    },
    "webhook": {
        "limit": 5,           # 5 webhooks
        "window": 3600        # em 1 hora (3600 segundos)
    },
    "messages": {
        "limit": 10,          # 10 mensagens
        "window": 60          # em 1 minuto (60 segundos)
    }
}