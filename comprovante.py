import logging
import sys
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.helpers import escape_markdown  # ← NOVA IMPORTAÇÃO

logger = logging.getLogger(__name__)

try:
    from config import CANAL_ADMIN_ID, LINK_CHAMADA, MENSAGENS
except ImportError:
    print("❌ ERRO: Arquivo config.py não encontrado!")
    sys.exit(1)

pagamentos_pendentes = {}

async def handle_comprovante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 🛡️ ESCAPAR CARACTERES ESPECIAIS DO MARKDOWN
    safe_name = escape_markdown(user.full_name, version=2) if user.full_name else "Não informado"
    safe_username = escape_markdown(user.username, version=2) if user.username else "Não informado"
    
    user_info = f"""👤 **NOVO COMPROVANTE RECEBIDO**

📋 **Dados do Usuário:**
• Nome: {safe_name}
• Username: @{safe_username}
• ID: `{user.id}`
• Chat ID: `{chat_id}`

⏰ **Data/Hora:** {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}
📱 **Tipo:** {'Foto' if update.message.photo else 'Documento'}

💰 **Status:** Aguardando aprovação"""
    
    keyboard = [[
        InlineKeyboardButton("✅ Aprovar Pagamento", callback_data=f"aprovar_{user.id}"),
        InlineKeyboardButton("❌ Rejeitar Pagamento", callback_data=f"rejeitar_{user.id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        pagamentos_pendentes[user.id] = {
            'user_name': user.full_name,
            'username': user.username,
            'chat_id': chat_id,
            'timestamp': datetime.now().strftime('%d/%m/%Y às %H:%M:%S')
        }
        
        if update.message.photo:
            await context.bot.send_photo(
                chat_id=CANAL_ADMIN_ID, 
                photo=update.message.photo[-1].file_id, 
                caption=user_info, 
                reply_markup=reply_markup, 
                parse_mode='MarkdownV2'  # ← MUDOU PARA V2
            )
        elif update.message.document:
            await context.bot.send_document(
                chat_id=CANAL_ADMIN_ID, 
                document=update.message.document.file_id, 
                caption=user_info, 
                reply_markup=reply_markup, 
                parse_mode='MarkdownV2'  # ← MUDOU PARA V2
            )
        
        # 🔥 SÓ ENVIAR MENSAGEM SE NÃO ESTIVER VAZIA
        comprovante_msg = MENSAGENS["comprovante_recebido"]
        if comprovante_msg.strip():  # Se não estiver vazia
            await update.message.reply_text(comprovante_msg)
        
        logger.info(f"Comprovante recebido de {user.full_name} (ID: {user.id})")
        
    except Exception as e:
        logger.error(f"Erro ao encaminhar comprovante: {e}")
        
        # 🆕 FALLBACK: Enviar sem formatação se Markdown falhar
        try:
            simple_info = f"NOVO COMPROVANTE RECEBIDO\n\nNome: {user.full_name}\nUsername: @{user.username if user.username else 'N/A'}\nID: {user.id}\nData: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            
            if update.message.photo:
                await context.bot.send_photo(
                    chat_id=CANAL_ADMIN_ID, 
                    photo=update.message.photo[-1].file_id, 
                    caption=simple_info, 
                    reply_markup=reply_markup
                )
            elif update.message.document:
                await context.bot.send_document(
                    chat_id=CANAL_ADMIN_ID, 
                    document=update.message.document.file_id, 
                    caption=simple_info, 
                    reply_markup=reply_markup
                )
            
            logger.info(f"Comprovante enviado sem formatação para {user.full_name}")
            
        except Exception as fallback_error:
            logger.error(f"Erro crítico no comprovante: {fallback_error}")
            await update.message.reply_text("❌ Erro ao processar comprovante.\nTente novamente em alguns minutos.")

async def handle_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    action, user_id = query.data.split('_')
    user_id = int(user_id)
    
    if user_id not in pagamentos_pendentes:
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n⚠️ ERRO: Dados do pagamento não encontrados!"
        )
        return
    
    user_data = pagamentos_pendentes[user_id]
    admin_name = query.from_user.full_name
    
    try:
        if action == "aprovar":
            # 🔥 ENVIAR LINK SEM FORMATAÇÃO MARKDOWN (mais seguro)
            aprovado_msg = MENSAGENS["pagamento_aprovado"].format(link_chamada=LINK_CHAMADA)
            if aprovado_msg.strip():  # Se não estiver vazio
                await context.bot.send_message(
                    chat_id=user_data['chat_id'], 
                    text=aprovado_msg
                    # ← SEM parse_mode! Evita problemas com caracteres especiais
                )
            
            # Atualizar caption SEM formatação markdown
            new_caption = query.message.caption + f"\n\n✅ APROVADO por {admin_name}\n🔗 Link enviado ao usuário!"
            await query.edit_message_caption(caption=new_caption)
            
            logger.info(f"Pagamento aprovado para usuário {user_id} por {admin_name}")
            
        elif action == "rejeitar":
            # 🔥 ENVIAR REJEIÇÃO SEM FORMATAÇÃO MARKDOWN
            rejeitado_msg = MENSAGENS["pagamento_rejeitado"]
            if rejeitado_msg.strip():  # Se não estiver vazio
                await context.bot.send_message(
                    chat_id=user_data['chat_id'], 
                    text=rejeitado_msg
                    # ← SEM parse_mode!
                )
            
            # Atualizar caption SEM formatação markdown
            new_caption = query.message.caption + f"\n\n❌ REJEITADO por {admin_name}"
            await query.edit_message_caption(caption=new_caption)
            
            logger.info(f"Pagamento rejeitado para usuário {user_id} por {admin_name}")
            
    except Exception as e:
        logger.error(f"Erro ao processar pagamento: {e}")
        
        # Fallback simples
        try:
            simple_update = f"\n\nERRO ao processar: {str(e)}"
            await query.edit_message_caption(caption=query.message.caption + simple_update)
        except Exception as final_error:
            logger.error(f"Erro crítico no callback: {final_error}")
    
    if user_id in pagamentos_pendentes:
        del pagamentos_pendentes[user_id]

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    instrucoes_msg = MENSAGENS["instrucoes"]
    if instrucoes_msg.strip():  # Se não estiver vazio
        await update.message.reply_text(instrucoes_msg)

def setup_payment_handlers(application):
    if not CANAL_ADMIN_ID or CANAL_ADMIN_ID == "-100XXXXXXXXX":
        print("❌ ERRO: Configure o CANAL_ADMIN_ID no arquivo config.py!")
        return False
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_comprovante))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_comprovante))
    application.add_handler(CallbackQueryHandler(handle_button_callback))
    return True