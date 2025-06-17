from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
import asyncio
import logging
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor

# ===== IMPORTAÇÕES =====
from redis_manager import redis_manager
from config import RATE_LIMITS
from tracking import track_user_activity  # 🆕 Import do arquivo separado

logger = logging.getLogger(__name__)

# 🔥 MUDANÇA 2: DICIONÁRIOS COM AUTO-LIMPEZA
user_states = {}
user_states_time = {}  # {user_id: timestamp} - para limpeza automática

user_first_processed = {}
user_video_sent_timestamp = {}
user_audio2_sent_timestamp = {}
user_question_sent_timestamp = {}
user_followup_sent_timestamp = {}

# 🆕 NOVO DICIONÁRIO PARA CONTROLAR DELAY DE 5 MINUTOS
user_payment_audio_timestamp = {}  # {user_id: timestamp} - momento que enviou áudio "faz o pagamento"

# 🔥 MUDANÇA 1: THREAD POOL CONTROLADO (MAX 10 THREADS)
executor = ThreadPoolExecutor(max_workers=10)
active_followups = {}  # {user_id: True} - controle simples
active_followups_comprovante = {}

# 🆕 CONTROLE DE TAREFAS ASSÍNCRONAS ATIVAS
active_start_tasks = {}  # {user_id: task}

# Mensagens de follow-up
MENSAGENS_FOLLOWUP_PAGAMENTO = [
    "amor ta ai? 😅",
    "oi mozao", 
    "amor vc sumiu",
    "amooooooor cade vc?",
    "vai me deixar falando so? 😩",
    "aff serio isso", 
    "achei q tinha gostado de mim, fui tola", 
    "serio nao vou mandar mensagem mais n", 
    "ok ja entendi q nao quer fala cmg" # 🔥 REDUZIDO para só 9 mensagens
]

MENSAGENS_FOLLOWUP_COMPROVANTE = [
    "amor conseguiu fazer o pix?",
    "vai me deixar no vacuo? to aq toda molhada aff",
    "amooor cade o comprovante vey",
    "mds do ceu q demora é essa amor kk",
    "poxa vida hein, vai me deixar toda molhada?",
    "ta me fazendo de boba é? 😒",
    "aff amor, vou ligar pra outro desse jeito, achei q vc ia apagar meu fogoo",
    "sumiu hein? achei q vc queria me ver peladinha",
    "aff desisto, se for querer ainda so mandar o comprovante bjos"
]

def limpar_usuarios_antigos():
    """🔥 MUDANÇA 2: Remove usuários inativos há mais de 2 horas"""
    agora = time.time()
    usuarios_para_remover = []
    
    for user_id, timestamp in user_states_time.items():
        if agora - timestamp > 7200:  # 2 horas = 7200 segundos
            usuarios_para_remover.append(user_id)
    
    for user_id in usuarios_para_remover:
        # Limpar todos os dicionários
        user_states.pop(user_id, None)
        user_first_processed.pop(user_id, None)
        user_video_sent_timestamp.pop(user_id, None)
        user_audio2_sent_timestamp.pop(user_id, None)
        user_question_sent_timestamp.pop(user_id, None)
        user_followup_sent_timestamp.pop(user_id, None)
        user_states_time.pop(user_id, None)
        user_payment_audio_timestamp.pop(user_id, None)  # 🆕 Limpar novo timestamp
        active_followups.pop(user_id, None)
        active_followups_comprovante.pop(user_id, None)
        
        # 🆕 CANCELAR TASK ATIVA SE EXISTIR
        if user_id in active_start_tasks:
            active_start_tasks[user_id].cancel()
            active_start_tasks.pop(user_id, None)
        
        logger.info(f"🧹 Usuário {user_id} removido da memória (inativo)")

def set_user_state(user_id, state):
    """🔥 MUDANÇA 2: Função para definir estado com auto-limpeza"""
    user_states[user_id] = state
    user_states_time[user_id] = time.time()
    
    # Limpar a cada 50 usuários (reduzido para ser mais frequente)
    if len(user_states) % 50 == 0:
        limpar_usuarios_antigos()

def get_user_state(user_id):
    """Helper para pegar estado do usuário - PRIORIZA REDIS"""
    # ✅ PRIMEIRO TENTA REDIS
    redis_state = redis_manager.get_user_state(user_id)
    if redis_state != "normal":
        return redis_state
    
    # Fallback para memória local
    return user_states.get(user_id, "normal")

def enviar_mensagem_simples(chat_id, mensagem, bot_token):
    """🔥 MUDANÇA 1: Envio simples SEM threading infinito"""
    try:
        bot_url = f"https://api.telegram.org/bot{bot_token}"
        
        # Typing action
        requests.post(f"{bot_url}/sendChatAction", json={
            'chat_id': chat_id,
            'action': 'typing'
        }, timeout=5)
        
        time.sleep(1)  # Reduzido de 2s para 1s
        
        # Send message
        response = requests.post(f"{bot_url}/sendMessage", json={
            'chat_id': chat_id,
            'text': mensagem
        }, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ Mensagem enviada para {chat_id}: '{mensagem}'")
            return True
        else:
            logger.error(f"❌ Erro ao enviar mensagem: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Erro no envio: {e}")
        return False

def executar_followup_pagamento(user_id, bot_token):
    """🔥 MUDANÇA 1: Follow-up SEM threading infinito"""
    intervalos = [120, 300, 600, 900, 1200, 1800, 2700, 3600, 4500]  # 1min, 2min, 3min (REDUZIDO)
    mensagens = MENSAGENS_FOLLOWUP_PAGAMENTO
    
    logger.info(f"🚀 Follow-up PAGAMENTO iniciado: {user_id}")
    
    for i, (intervalo, mensagem) in enumerate(zip(intervalos, mensagens)):
        # Verificar se foi cancelado
        if user_id not in active_followups:
            logger.info(f"🛑 Follow-up cancelado: {user_id}")
            return
        
        # Verificar se estado mudou (PRIORIZA REDIS)
        current_state = redis_manager.get_user_state(user_id)
        if current_state == "awaiting_payment_proof":
            logger.info(f"🛑 Follow-up cancelado (usuário respondeu): {user_id}")
            active_followups.pop(user_id, None)
            return
        
        # Aguardar
        logger.info(f"⏰ Aguardando {intervalo}s para msg #{i+1}: {user_id}")
        time.sleep(intervalo)
        
        # Verificar novamente após espera
        if user_id not in active_followups:
            return
        
        # Enviar mensagem
        sucesso = enviar_mensagem_simples(user_id, mensagem, bot_token)
        if not sucesso:
            logger.error(f"❌ Erro ao enviar msg #{i+1}: {user_id}")
            break
    
    # Limpar
    active_followups.pop(user_id, None)
    logger.info(f"🏁 Follow-up PAGAMENTO concluído: {user_id}")

def executar_followup_comprovante(user_id, bot_token):
    """🔥 MUDANÇA 1: Follow-up comprovante SEM threading infinito"""
    intervalos = [120, 240, 360, 480, 600, 900, 1200, 1500, 1800]    # 2min, 4min, 6min (REDUZIDO)
    mensagens = MENSAGENS_FOLLOWUP_COMPROVANTE
    
    logger.info(f"🚀 Follow-up COMPROVANTE iniciado: {user_id}")
    
    for i, (intervalo, mensagem) in enumerate(zip(intervalos, mensagens)):
        if user_id not in active_followups_comprovante:
            return
        
        # Verificar estado no Redis
        current_state = redis_manager.get_user_state(user_id)
        if current_state != "awaiting_payment_proof":
            active_followups_comprovante.pop(user_id, None)
            return
        
        time.sleep(intervalo)
        
        if user_id not in active_followups_comprovante:
            return
        
        enviar_mensagem_simples(user_id, mensagem, bot_token)
    
    active_followups_comprovante.pop(user_id, None)
    logger.info(f"🏁 Follow-up COMPROVANTE concluído: {user_id}")

def iniciar_followup_bot(user_id, bot_token):
    """🔥 MUDANÇA 1: Usar ThreadPoolExecutor controlado"""
    user_id = int(user_id)
    
    # Cancelar anterior se existir
    active_followups.pop(user_id, None)
    time.sleep(0.5)
    
    # Marcar como ativo
    active_followups[user_id] = True
    
    # Usar thread pool controlado
    executor.submit(executar_followup_pagamento, user_id, bot_token)

def iniciar_followup_comprovante(user_id, bot_token):
    """🔥 MUDANÇA 1: Follow-up comprovante com thread pool"""
    user_id = int(user_id)
    
    active_followups_comprovante.pop(user_id, None)
    time.sleep(0.5)
    
    active_followups_comprovante[user_id] = True
    executor.submit(executar_followup_comprovante, user_id, bot_token)

def cancelar_followup_bot(user_id):
    """Cancelar follow-up pagamento"""
    user_id = int(user_id)
    if user_id in active_followups:
        del active_followups[user_id]
        logger.info(f"🛑 Follow-up PAGAMENTO cancelado: {user_id}")
        return True
    return False

def cancelar_followup_comprovante(user_id):
    """Cancelar follow-up comprovante"""
    user_id = int(user_id)
    if user_id in active_followups_comprovante:
        del active_followups_comprovante[user_id]
        logger.info(f"🛑 Follow-up COMPROVANTE cancelado: {user_id}")
        return True
    return False

def executar_sequencia_pos_resposta_pagamento(user_id, chat_id):
    """Sequência após resposta de pagamento - TEXTO, TEXTO, ÁUDIO"""
    try:
        from config import BOT_TOKEN
        bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        
        logger.info(f"🎬 Sequência pós-resposta pagamento: {user_id}")
        
        # 1️⃣ PRIMEIRO TEXTO: Mensagem PIX
        requests.post(f"{bot_url}/sendChatAction", 
            json={'chat_id': chat_id, 'action': 'typing'}, timeout=5)
        time.sleep(1)
        
        pix_message = "é chave pix e-mail ta amor? o banco é no meu nome mesmo 🥰"
        requests.post(f"{bot_url}/sendMessage", 
            json={'chat_id': chat_id, 'text': pix_message}, timeout=10)
        
        # 2️⃣ SEGUNDO TEXTO: Mensagem adicional
        time.sleep(2)
        requests.post(f"{bot_url}/sendChatAction", 
            json={'chat_id': chat_id, 'action': 'typing'}, timeout=5)
        time.sleep(1)
        
        segundo_texto = "pixdamary22@gmail.com"
        requests.post(f"{bot_url}/sendMessage", 
            json={'chat_id': chat_id, 'text': segundo_texto}, timeout=10)
        
        # 3️⃣ POR ÚLTIMO: Enviar áudio
        time.sleep(2)
        requests.post(f"{bot_url}/sendChatAction", 
            json={'chat_id': chat_id, 'action': 'record_voice'}, timeout=5)
        time.sleep(1)
        
        try:
            with open("audio/comprovante.mp3", 'rb') as audio_file:
                files = {'voice': audio_file}
                data = {'chat_id': chat_id}
                requests.post(f"{bot_url}/sendVoice", files=files, data=data, timeout=30)
        except FileNotFoundError:
            logger.error("❌ comprovante.mp3 não encontrado")
        
        # 🆕 SALVAR TIMESTAMP DO ÁUDIO "faz o pagamento"
        user_payment_audio_timestamp[user_id] = time.time()
        
        # Update state NO REDIS
        redis_manager.set_user_state(user_id, "awaiting_payment_proof")
        user_followup_sent_timestamp[user_id] = time.time()
        
        # Start proof followup
        iniciar_followup_comprovante(user_id, BOT_TOKEN)
        
        logger.info(f"✅ Sequência pagamento concluída: {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Erro sequência pagamento {user_id}: {e}")

def executar_sequencia_pos_comprovante(user_id, chat_id):
    """Sequência após comprovante"""
    try:
        from config import BOT_TOKEN
        bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        
        # Send final audio
        requests.post(f"{bot_url}/sendChatAction", 
            json={'chat_id': chat_id, 'action': 'record_voice'}, timeout=5)
        time.sleep(1)
        
        try:
            with open("audio/fim.mp3", 'rb') as audio_file:
                files = {'voice': audio_file}
                data = {'chat_id': chat_id}
                requests.post(f"{bot_url}/sendVoice", files=files, data=data, timeout=30)
        except FileNotFoundError:
            pass
        
        # Send messages
        time.sleep(2)
        requests.post(f"{bot_url}/sendMessage", 
            json={'chat_id': chat_id, 'text': "pra gente terminar a nossa chamadinha vida 🤤"}, 
            timeout=10)
        
        time.sleep(2)
        requests.post(f"{bot_url}/sendMessage", 
            json={'chat_id': chat_id, 'text': "tô só te esperando amor"}, 
            timeout=10)
        
        logger.info(f"✅ Sequência final concluída: {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Erro sequência final {user_id}: {e}")

def iniciar_followup_webhook(user_id):
    """Função chamada pelo webhook"""
    try:
        from config import BOT_TOKEN
        user_id = int(user_id)
        
        # ✅ SALVAR ESTADO NO REDIS
        redis_manager.set_user_state(user_id, "awaiting_payment_response")
        user_followup_sent_timestamp[user_id] = time.time()
        
        logger.info(f"📞 Webhook: Estado = awaiting_payment_response para {user_id}")
        
        iniciar_followup_bot(user_id, BOT_TOKEN)
        return True
    except Exception as e:
        logger.error(f"❌ Erro webhook follow-up: {e}")
        return False

# 🆕 FUNÇÃO ASSÍNCRONA PARA PROCESSAR SEQUÊNCIA DO /START
async def processar_start_sequence(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Processa a sequência do /start de forma assíncrona, não bloqueando outros usuários"""
    try:
        logger.info(f"🚀 Iniciando sequência assíncrona para usuário {user_id}")
        
        # Delay inicial com pequena variação para distribuir carga
        base_delay = 3 + (user_id % 1000) / 1000  # 3.0 a 3.999 segundos
        await asyncio.sleep(base_delay)
        
        # 🎵 ENVIO DO ÁUDIO com rate limiting
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await asyncio.sleep(1)
        
        audio_path = "audio/oi.mp3"
        if os.path.exists(audio_path):
            with open(audio_path, 'rb') as audio_file:
                await context.bot.send_voice(chat_id=chat_id, voice=audio_file)
            logger.info(f"🎵 Áudio enviado: {user_id}")
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Arquivo audio.mp3 não encontrado!")
            return
        
        # 🔥 RATE LIMITING: Pequeno delay após áudio
        await asyncio.sleep(0.5 + (user_id % 500) / 1000)  # 0.5 a 1.0 segundos
        
        # Delay antes do vídeo com pequena variação
        video_delay = 18 + (user_id % 2000) / 1000  # 18.0 a 19.999 segundos
        await asyncio.sleep(video_delay)
        
        # 🎬 ENVIO DO VÍDEO com rate limiting
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
        await asyncio.sleep(1)
        
        video_path = "video/start.mp4"
        if os.path.exists(video_path):
            with open(video_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    width=1920,
                    height=1080,
                    supports_streaming=True
                )
            
            user_video_sent_timestamp[user_id] = time.time()
            redis_manager.set_user_state(user_id, "can_receive_first")
            logger.info(f"✅ Vídeo enviado: {user_id} → can_receive_first")
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Arquivo video.mp4 não encontrado!")
        
        # 🔥 RATE LIMITING: Pequeno delay após vídeo
        await asyncio.sleep(0.3 + (user_id % 300) / 1000)  # 0.3 a 0.6 segundos
        
        logger.info(f"✅ Sequência assíncrona concluída para {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Erro na sequência assíncrona {user_id}: {e}")
    finally:
        # Remover da lista de tasks ativas
        active_start_tasks.pop(user_id, None)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # 🆕 TRACKING: Registrar comando /start
    track_user_activity(user_id, "start_command")
    
    # ✅ RATE LIMITING COM REDIS
    rate_key = f"rate:start:{user_id}"
    if not redis_manager.check_rate_limit(
        rate_key,
        RATE_LIMITS["start_command"]["limit"],
        RATE_LIMITS["start_command"]["window"]
    ):
        logger.warning(f"🚫 Rate limit /start: {user_id}")
        await update.message.reply_text("⏰ Aguarde alguns minutos antes de reiniciar!")
        return
    
    # 🆕 CANCELAR TASK ANTERIOR SE EXISTIR
    if user_id in active_start_tasks:
        active_start_tasks[user_id].cancel()
        logger.info(f"🛑 Task anterior cancelada para {user_id}")
    
    # ✅ SALVAR ESTADO NO REDIS IMEDIATAMENTE
    redis_manager.set_user_state(user_id, "sending_initial_content")
    
    # Reset user completely (mantém comportamento original)
    user_first_processed[user_id] = {
        "first_response": False, 
        "call_response": False, 
        "payment_response": False,
        "proof_response": False
    }
    user_video_sent_timestamp[user_id] = None
    user_audio2_sent_timestamp[user_id] = None
    user_question_sent_timestamp[user_id] = None
    user_followup_sent_timestamp[user_id] = None
    user_payment_audio_timestamp[user_id] = None
    
    # Cancel followups (mantém comportamento original)
    cancelar_followup_bot(user_id)
    cancelar_followup_comprovante(user_id)
    
    logger.info(f"🚀 START: {user_id} → sending_initial_content")
    
    # 🆕 CRIAR TASK ASSÍNCRONA E RETORNAR IMEDIATAMENTE
    task = asyncio.create_task(processar_start_sequence(user_id, chat_id, context))
    active_start_tasks[user_id] = task
    
    logger.info(f"⚡ Handler /start liberado imediatamente para {user_id}")
    # O handler retorna aqui, liberando o bot para atender outros usuários!

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    
    # 🆕 TRACKING: Registrar mensagem
    track_user_activity(user_id, "message")
    
    # ✅ RATE LIMITING COM REDIS (mantém igual)
    rate_key = f"rate:messages:{user_id}"
    if not redis_manager.check_rate_limit(
        rate_key,
        RATE_LIMITS["messages"]["limit"],
        RATE_LIMITS["messages"]["window"]
    ):
        logger.warning(f"🚫 Rate limit mensagem: {user_id}")
        return  # Ignora silenciosamente (não responde para não fazer spam)
    
    # ✅ RECUPERAR ESTADO DO REDIS (PRIORITÁRIO) (mantém igual)
    user_state = redis_manager.get_user_state(user_id)
    mensagem_usuario = update.message.text
    message_timestamp = update.message.date.timestamp()
    
    logger.info(f"👤 {user_id} | {user_state} | '{mensagem_usuario}'")
    
    # State machine - AGORA COM TASKS ASSÍNCRONAS
    if user_state == "sending_initial_content":
        logger.info(f"🚫 IGNORADO - enviando conteúdo: {user_id}")
        return
    
    elif user_state == "can_receive_first":
        video_timestamp = user_video_sent_timestamp.get(user_id)
        if video_timestamp and message_timestamp < video_timestamp:
            logger.info(f"🚫 IGNORADO - mensagem antiga: {user_id}")
            return
        
        if user_first_processed[user_id]["first_response"]:
            logger.info(f"🚫 IGNORADO - já processou primeira: {user_id}")
            return
        
        user_first_processed[user_id]["first_response"] = True
        redis_manager.set_user_state(user_id, "awaiting_call_answer")
        logger.info(f"✅ Primeira mensagem processada: {user_id}")
        
        # 🆕 CRIAR TASK ASSÍNCRONA - NÃO BLOQUEIA MAIS!
        asyncio.create_task(processar_primeira_resposta_async(user_id, update.effective_chat.id, context))
        
    elif user_state == "awaiting_call_answer":
        question_timestamp = user_question_sent_timestamp.get(user_id)
        if question_timestamp and message_timestamp < question_timestamp:
            return
        
        if user_first_processed[user_id]["call_response"]:
            return
        
        user_first_processed[user_id]["call_response"] = True
        redis_manager.set_user_state(user_id, "sending_call_content")
        logger.info(f"✅ Resposta ligação processada: {user_id}")
        
        # 🆕 CRIAR TASK ASSÍNCRONA - NÃO BLOQUEIA MAIS!
        asyncio.create_task(processar_resposta_ligacao_async(user_id, update.effective_chat.id, context))
    
    elif user_state == "sending_call_content":
        logger.info(f"🚫 IGNORADO - enviando conteúdo ligação: {user_id}")
        return
    
    elif user_state == "waiting_for_call":
        logger.info(f"🚫 IGNORADO - aguardando videochamada: {user_id}")
        return
        
    elif user_state == "awaiting_payment_response":
        followup_timestamp = user_followup_sent_timestamp.get(user_id)
        if followup_timestamp and message_timestamp < followup_timestamp:
            return
        
        if user_first_processed[user_id].get("payment_response", False):
            return
        
        user_first_processed[user_id]["payment_response"] = True
        logger.info(f"✅ Resposta pagamento: {user_id}")
        
        cancelar_followup_bot(user_id)
        
        # 🔥 MANTÉM: Usar thread pool para sequência (já está otimizado)
        executor.submit(executar_sequencia_pos_resposta_pagamento, user_id, update.effective_chat.id)
    
    elif user_state == "awaiting_payment_proof":
        # 🆕 VERIFICAR SE PASSOU 5 MINUTOS DESDE O ÁUDIO (mantém igual)
        audio_timestamp = user_payment_audio_timestamp.get(user_id)
        if audio_timestamp:
            tempo_decorrido = message_timestamp - audio_timestamp
            if tempo_decorrido < 300:  # 300 segundos = 5 minutos
                logger.info(f"⏳ AGUARDANDO - Faltam {300 - tempo_decorrido:.0f}s para processar: {user_id}")
                return  # Ignora a mensagem se não passou 5 minutos
        
        if user_first_processed[user_id].get("proof_response", False):
            return
        
        user_first_processed[user_id]["proof_response"] = True
        logger.info(f"✅ Resposta comprovante: {user_id}")
        
        cancelar_followup_comprovante(user_id)
        
        # 🔥 MANTÉM: Usar thread pool para sequência final (já está otimizado)
        executor.submit(executar_sequencia_pos_comprovante, user_id, update.effective_chat.id)
        
        redis_manager.set_user_state(user_id, "sequence_completed")
    
    else:
        logger.info(f"⚪ Estado normal: {user_id}")
    
    # 🔥 HANDLER LIBERADO IMEDIATAMENTE!
    logger.info(f"⚡ MESSAGE processado imediatamente para {user_id}")

# 🆕 FUNÇÕES ASSÍNCRONAS PARA AS OUTRAS SEQUÊNCIAS
async def processar_primeira_resposta_async(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Processa a primeira resposta do usuário de forma assíncrona"""
    try:
        logger.info(f"🎵 Iniciando primeira resposta assíncrona para {user_id}")
        
        # Delay com pequena variação para distribuir
        delay = 8 + (user_id % 1000) / 1000  # 8.0 a 8.999 segundos
        await asyncio.sleep(delay)
        
        # Enviar áudio antes da pergunta
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await asyncio.sleep(1)
        
        audio_antes_pergunta = "audio/pauzao.mp3"
        if os.path.exists(audio_antes_pergunta):
            with open(audio_antes_pergunta, 'rb') as audio_file:
                await context.bot.send_voice(chat_id=chat_id, voice=audio_file)
            logger.info(f"🎵 Áudio antes da pergunta enviado: {user_id}")
        
        # Rate limiting
        await asyncio.sleep(0.3 + (user_id % 300) / 1000)
        
        # Delay antes da pergunta com variação
        pergunta_delay = 13 + (user_id % 1000) / 1000  # 13.0 a 13.999 segundos
        await asyncio.sleep(pergunta_delay)
        
        await context.bot.send_message(chat_id=chat_id, text="amor já posso te ligar?")
        
        user_question_sent_timestamp[user_id] = time.time()
        logger.info(f"✅ Primeira resposta assíncrona concluída para {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Erro na primeira resposta assíncrona {user_id}: {e}")

async def processar_resposta_ligacao_async(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Processa a resposta da ligação de forma assíncrona"""
    try:
        logger.info(f"🔗 Iniciando resposta ligação assíncrona para {user_id}")
        
        # Delay com pequena variação
        delay = 12 + (user_id % 1000) / 1000  # 12.0 a 12.999 segundos
        await asyncio.sleep(delay)
        
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        await asyncio.sleep(1)
        
        audio2_path = "audio/desculpa.mp3"
        if os.path.exists(audio2_path):
            with open(audio2_path, 'rb') as audio_file:
                await context.bot.send_voice(chat_id=chat_id, voice=audio_file)
            user_audio2_sent_timestamp[user_id] = time.time()
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Arquivo audio2.mp3 não encontrado!")
            return
        
        # Rate limiting
        await asyncio.sleep(0.4 + (user_id % 400) / 1000)
        
        # Delay antes do link com variação
        link_delay = 14 + (user_id % 1000) / 1000  # 14.0 a 14.999 segundos
        await asyncio.sleep(link_delay)
        
        timestamp = int(time.time())
        link = f"https://video-call-peach-five.vercel.app/?t={timestamp}&u={user_id}"
        await context.bot.send_message(chat_id=chat_id, text=link)
        
        redis_manager.set_user_state(user_id, "waiting_for_call")
        logger.info(f"🔗 Link enviado: {user_id}")
        logger.info(f"✅ Resposta ligação assíncrona concluída para {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Erro na resposta da ligação assíncrona {user_id}: {e}")
        # Em caso de erro, resetar estado
        redis_manager.set_user_state(user_id, "normal")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.warning(f'Update {update} causou erro {context.error}')

def setup_basic_handlers(application):
    # 🔥 SÓ O /start E MESSAGES - NENHUM OUTRO COMANDO VISÍVEL
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # 🔥 SEM COMANDOS NO MENU DO BOT
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(application.bot.delete_my_commands())  # Remove todos os comandos
    else:
        loop.run_until_complete(application.bot.delete_my_commands())
