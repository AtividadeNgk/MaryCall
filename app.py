import asyncio
import logging
import sys
import platform
import threading
import time
import os
import aiohttp
import aiofiles
from telegram import Update
from telegram.ext import Application
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
from collections import defaultdict
import json

# ===== IMPORTAÇÕES =====
from redis_manager import redis_manager
from config import RATE_LIMITS
from tracking import user_stats, track_user_activity, cleanup_online_users  # 🆕 Import do arquivo separado

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from config import BOT_TOKEN
    from bot import setup_basic_handlers
    from comprovante import setup_payment_handlers
except ImportError as e:
    print(f"❌ ERRO: {e}")
    sys.exit(1) 

# Criar Flask app para webhook
webhook_app = Flask(__name__)
CORS(webhook_app)

# Proteção contra spam - rastrear chamadas recentes
recent_calls = {}  # {user_id: timestamp}

# 🔥 FOLLOW-UP SIMPLIFICADO INTEGRADO
active_followups = {}  # {user_id: thread_info}

# Mensagens de follow-up
MENSAGENS_FOLLOWUP = [
    "amor ta ai? 😅",
    "oi mozao", 
    "amor vc sumiu",
    "amooooooor cade vc?",
    "vai me deixar falando so? 😩",
    "aff serio isso",
    "achei q tinha gostado de mim, fui tola",
    "serio nao vou mandar mensagem mais n",
    "ok ja entendi q nao quer fala cmg"
]

def enviar_mensagem_followup(user_id, mensagem):
    """Envia uma mensagem de follow-up"""
    try:
        bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        
        # Mostrar "digitando..."
        requests.post(f"{bot_url}/sendChatAction", json={
            'chat_id': user_id,
            'action': 'typing'
        }, timeout=10)
        
        time.sleep(2)
        
        # Enviar mensagem
        response = requests.post(f"{bot_url}/sendMessage", json={
            'chat_id': user_id,
            'text': mensagem
        }, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ Follow-up enviado para {user_id}: '{mensagem}'")
            return True
        else:
            logger.error(f"❌ Erro ao enviar follow-up: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Erro no follow-up: {e}")
        return False

def iniciar_followup_simples(user_id):
    """Inicia follow-up simplificado"""
    
    def executar_followup():
        intervalos = [60, 180, 300, 420, 600, 900, 1200, 1500, 1800]  # 1min, 3min, 5min, etc.
        
        logger.info(f"🚀 FOLLOW-UP INICIADO para usuário {user_id}")
        
        for i, intervalo in enumerate(intervalos):
            # Verificar se foi cancelado
            if user_id not in active_followups:
                logger.info(f"🛑 Follow-up cancelado para {user_id}")
                return
            
            # Aguardar intervalo
            logger.info(f"⏰ Aguardando {intervalo}s para enviar mensagem #{i+1} para {user_id}")
            time.sleep(intervalo)
            
            # Verificar novamente após a espera
            if user_id not in active_followups:
                logger.info(f"🛑 Follow-up cancelado durante espera para {user_id}")
                return
            
            # Escolher mensagem
            if i < len(MENSAGENS_FOLLOWUP):
                mensagem = MENSAGENS_FOLLOWUP[i]
            else:
                mensagem = "amor me responde por favor"
            
            # Enviar mensagem
            sucesso = enviar_mensagem_followup(user_id, mensagem)
            
            if not sucesso:
                logger.error(f"❌ Erro ao enviar follow-up #{i+1} para {user_id}")
                break
        
        # Limpar após terminar
        if user_id in active_followups:
            del active_followups[user_id]
        
        logger.info(f"🏁 Follow-up concluído para usuário {user_id}")
    
    # Cancelar follow-up anterior se existir
    if user_id in active_followups:
        del active_followups[user_id]
        time.sleep(1)  # Aguardar thread anterior terminar
    
    # Marcar como ativo
    active_followups[user_id] = True
    
    # Iniciar em thread separada
    thread = threading.Thread(target=executar_followup, daemon=True)
    thread.start()

def cancelar_followup(user_id):
    """Cancela follow-up de um usuário"""
    if user_id in active_followups:
        del active_followups[user_id]
        logger.info(f"❌ Follow-up cancelado para usuário {user_id}")

async def send_media_sequence_async(user_id, duration):
    """Envia sequência completa pós-chamada ASSÍNCRONA"""
    try:
        bot_url_base = f"https://api.telegram.org/bot{BOT_TOKEN}"
        
        logger.info(f"🎬 INICIANDO SEQUÊNCIA assíncrona pós-chamada para {user_id}")
        
        # Session HTTP assíncrona (reutilizar conexão)
        async with aiohttp.ClientSession() as session:
            
            # 1. STATUS "GRAVANDO ÁUDIO" + ÁUDIO 
            logger.info(f"🎵 Enviando áudio de encerramento para {user_id}")
            
            # Mostrar "gravando áudio..."
            await session.post(f"{bot_url_base}/sendChatAction", json={
                'chat_id': user_id,
                'action': 'record_voice'
            })
            await asyncio.sleep(2)  # Não bloqueia outros webhooks!
            
            audio_path = "audio/caiu.mp3"
            if os.path.exists(audio_path):
                async with aiofiles.open(audio_path, 'rb') as audio_file:
                    audio_data = await audio_file.read()
                    
                data = aiohttp.FormData()
                data.add_field('chat_id', str(user_id))
                data.add_field('voice', audio_data, filename='caiu.mp3')
                
                response = await session.post(f"{bot_url_base}/sendVoice", data=data)
                
                if response.status == 200:
                    logger.info(f"✅ Áudio de encerramento enviado para {user_id}")
                else:
                    logger.error(f"❌ Erro ao enviar áudio: {await response.text()}")
                    return
            else:
                logger.error(f"❌ Arquivo caiu.mp3 não encontrado")
                return
            
            # 2. AGUARDAR + VÍDEO (assíncrono)
            await asyncio.sleep(20)  # Não bloqueia outros webhooks!
            logger.info(f"🎬 Enviando vídeo pós-chamada para {user_id}")
            
            # Mostrar "enviando vídeo..."
            await session.post(f"{bot_url_base}/sendChatAction", json={
                'chat_id': user_id,
                'action': 'upload_video'
            })
            await asyncio.sleep(2)
            
            video_path = "video/final.mp4"
            if os.path.exists(video_path):
                async with aiofiles.open(video_path, 'rb') as video_file:
                    video_data = await video_file.read()
                    
                data = aiohttp.FormData()
                data.add_field('chat_id', str(user_id))
                data.add_field('video', video_data, filename='final.mp4')
                
                response = await session.post(f"{bot_url_base}/sendVideo", data=data)
                
                if response.status == 200:
                    logger.info(f"✅ Vídeo pós-chamada enviado para {user_id}")
                else:
                    logger.error(f"❌ Erro ao enviar vídeo: {await response.text()}")
                    return
            else:
                logger.error(f"❌ Arquivo final.mp4 não encontrado")
                return
            
            # 3. AGUARDAR + SEGUNDO ÁUDIO
            await asyncio.sleep(12)  # Não bloqueia!
            logger.info(f"🎵 Enviando segundo áudio para {user_id}")
            
            # Mostrar "gravando áudio..." novamente
            await session.post(f"{bot_url_base}/sendChatAction", json={
                'chat_id': user_id,
                'action': 'record_voice'
            })
            await asyncio.sleep(2)
            
            audio2_path = "audio/pix.mp3"
            if os.path.exists(audio2_path):
                async with aiofiles.open(audio2_path, 'rb') as audio_file:
                    audio_data = await audio_file.read()
                    
                data = aiohttp.FormData()
                data.add_field('chat_id', str(user_id))
                data.add_field('voice', audio_data, filename='pix.mp3')
                
                response = await session.post(f"{bot_url_base}/sendVoice", data=data)
                
                if response.status == 200:
                    logger.info(f"✅ Segundo áudio enviado para {user_id}")
                else:
                    logger.error(f"❌ Erro ao enviar segundo áudio: {await response.text()}")
                    return
            else:
                logger.error(f"❌ Arquivo pix.mp3 não encontrado")
                return
            
            # 4. AGUARDAR + TEXTO "Pode ser?"
            await asyncio.sleep(10)  # Não bloqueia!
            logger.info(f"💬 Enviando 'Pode ser?' para {user_id}")
            
            # Mostrar "digitando..."
            await session.post(f"{bot_url_base}/sendChatAction", json={
                'chat_id': user_id,
                'action': 'typing'
            })
            await asyncio.sleep(2)
            
            message = "pode ser meu bemm?"
            response = await session.post(f"{bot_url_base}/sendMessage", json={
                'chat_id': user_id,
                'text': message
            })
            
            if response.status == 200:
                logger.info(f"✅ 'Pode ser?' enviado para {user_id}")
                
                # 🔥 DEFINIR ESTADO E INICIAR FOLLOW-UP
                try:
                    redis_manager.set_user_state(user_id, "awaiting_payment_response")
                    logger.info(f"📝 Estado definido para {user_id}: awaiting_payment_response")
                    
                    # Iniciar follow-up
                    from bot import iniciar_followup_webhook
                    sucesso = iniciar_followup_webhook(user_id)
                    if sucesso:
                        logger.info(f"🚀 Follow-up iniciado via bot para usuário {user_id}")
                    else:
                        logger.error(f"❌ Erro ao iniciar follow-up via bot para {user_id}")
                except Exception as e:
                    logger.error(f"❌ Erro ao chamar follow-up do bot: {e}")
                
            else:
                logger.error(f"❌ Erro ao enviar 'Pode ser?': {await response.text()}")
                
    except Exception as e:
        logger.error(f"❌ Erro na sequência assíncrona para {user_id}: {str(e)}")

@webhook_app.route('/api/call-ended', methods=['POST'])
def call_ended():
    try:
        data = request.json
        user_id = data.get('userId')
        duration = data.get('duration', '01:27')
        
        # Validação básica
        if not user_id:
            logger.warning("❌ Webhook sem userId")
            return jsonify({'status': 'error', 'message': 'userId obrigatório'}), 400
        
        # ✅ RATE LIMITING COM REDIS
        rate_key = f"rate:webhook:{user_id}"
        if not redis_manager.check_rate_limit(
            rate_key, 
            RATE_LIMITS["webhook"]["limit"], 
            RATE_LIMITS["webhook"]["window"]
        ):
            logger.warning(f"🚫 Rate limit webhook: {user_id}")
            return jsonify({'status': 'rate_limited', 'message': 'Muitas chamadas'}), 429
        
        logger.info(f"📞 WEBHOOK RECEBIDO - Usuário: {user_id}, Duração: {duration}")
        
        # 🆕 EXECUTAR FUNÇÃO ASSÍNCRONA EM THREAD SEPARADA
        def run_async_sequence():
            """Executa sequência assíncrona em thread com seu próprio event loop"""
            try:
                # Criar novo event loop para esta thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Executar função assíncrona
                loop.run_until_complete(send_media_sequence_async(user_id, duration))
                
                # Fechar loop
                loop.close()
                
            except Exception as e:
                logger.error(f"❌ Erro na thread assíncrona: {e}")
        
        # Iniciar em thread separada (não bloqueia webhook)
        threading.Thread(target=run_async_sequence, daemon=True).start()
        
        return jsonify({'status': 'success', 'message': 'Sequência assíncrona iniciada'})
        
    except Exception as e:
        logger.error(f"❌ Erro no webhook: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Erro interno'}), 500

@webhook_app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'online', 
        'timestamp': datetime.now().isoformat(),
        'active_users': len(recent_calls),
        'redis_status': 'connected' if redis_manager.redis else 'fallback_memory'
    })

@webhook_app.route('/api/stats', methods=['GET'])
def stats():
    """Endpoint para ver estatísticas de uso"""
    now = time.time()
    active_users = {uid: now - ts for uid, ts in recent_calls.items() if now - ts < 3600}  # Última hora
    
    return jsonify({
        'total_users_tracked': len(recent_calls),
        'users_last_hour': len(active_users),
        'recent_calls': {uid: f"{duration:.0f}s ago" for uid, duration in active_users.items()},
        'active_followups': len(active_followups),
        'followup_users': list(active_followups.keys()),
        'redis_status': 'connected' if redis_manager.redis else 'fallback_memory'
    })

@webhook_app.route('/api/cancel-followup/<user_id>', methods=['POST'])
def cancel_followup_manual(user_id):
    """Endpoint para cancelar follow-up manualmente"""
    try:
        user_id = int(user_id)
        # Chamar função do bot para cancelar
        from bot import cancelar_followup_bot
        sucesso = cancelar_followup_bot(user_id)
        
        if sucesso:
            return jsonify({'status': 'success', 'message': f'Follow-up cancelado para usuário {user_id}'})
        else:
            return jsonify({'status': 'info', 'message': f'Usuário {user_id} não tinha follow-up ativo'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@webhook_app.route('/api/test-followup/<user_id>', methods=['POST'])
def test_followup_manual(user_id):
    """Endpoint para testar follow-up manualmente"""
    try:
        user_id = int(user_id)
        logger.info(f"🧪 TESTE: Iniciando follow-up manual para {user_id}")
        from bot import iniciar_followup_webhook
        sucesso = iniciar_followup_webhook(user_id)
        
        if sucesso:
            return jsonify({'status': 'success', 'message': f'Follow-up teste iniciado para usuário {user_id}'})
        else:
            return jsonify({'status': 'error', 'message': f'Erro ao iniciar follow-up para {user_id}'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@webhook_app.route('/dashboard')
def dashboard():
    """Dashboard HTML com gráfico corrigido"""
    
    # Limpar usuários offline
    cleanup_online_users()
    
    # Estatísticas atuais
    stats = {
        'online_now': len(user_stats['online_now']),
        'daily_users': len(user_stats['daily_users']),
        'weekly_users': len(user_stats['weekly_users']),
        'interactions_today': user_stats['interactions_today'],
        'interactions_week': user_stats['interactions_week'],
        'hourly_stats': dict(user_stats['hourly_stats']),
        'commands_count': dict(user_stats['commands_count']),
        'last_update': datetime.now().strftime('%H:%M:%S')
    }
    
    # 🔥 DEBUG: Log dos dados para verificar
    logger.info(f"📊 Dashboard - Dados horários: {stats['hourly_stats']}")
    
    return f'''
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>📊 Dashboard Bot - Amanda</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
                color: white;
            }}
            
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            
            .header {{
                text-align: center;
                margin-bottom: 30px;
            }}
            
            .header h1 {{
                font-size: 2.5rem;
                margin-bottom: 10px;
                text-shadow: 0 2px 4px rgba(0,0,0,0.3);
            }}
            
            .last-update {{
                background: rgba(255,255,255,0.2);
                padding: 8px 16px;
                border-radius: 20px;
                display: inline-block;
                backdrop-filter: blur(10px);
            }}
            
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }}
            
            .card {{
                background: rgba(255,255,255,0.15);
                border-radius: 15px;
                padding: 25px;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.2);
                transition: transform 0.3s ease, box-shadow 0.3s ease;
            }}
            
            .card:hover {{
                transform: translateY(-5px);
                box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            }}
            
            .card-icon {{
                font-size: 2.5rem;
                margin-bottom: 15px;
                display: block;
            }}
            
            .card-title {{
                font-size: 1.1rem;
                margin-bottom: 10px;
                opacity: 0.9;
            }}
            
            .card-value {{
                font-size: 2.5rem;
                font-weight: bold;
                margin-bottom: 10px;
                text-shadow: 0 2px 4px rgba(0,0,0,0.3);
            }}
            
            .card-subtitle {{
                font-size: 0.9rem;
                opacity: 0.7;
            }}
            
            .online {{ color: #4CAF50; }}
            .today {{ color: #2196F3; }}
            .week {{ color: #FF9800; }}
            .interactions {{ color: #E91E63; }}
            
            .charts {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                gap: 20px;
            }}
            
            .chart-card {{
                background: rgba(255,255,255,0.15);
                border-radius: 15px;
                padding: 25px;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255,255,255,0.2);
            }}
            
            .chart-title {{
                font-size: 1.3rem;
                margin-bottom: 20px;
                text-align: center;
            }}
            
            /* 🔥 GRÁFICO DE BARRAS CORRIGIDO */
            .bar-chart {{
                display: flex;
                align-items: end;
                height: 180px;
                gap: 4px;
                margin-top: 30px;
                padding: 0 10px;
                position: relative;
            }}
            
            .bar {{
                background: linear-gradient(to top, #4CAF50 0%, #81C784 100%);
                border-radius: 3px 3px 0 0;
                min-height: 2px;
                position: relative;
                transition: all 0.3s ease;
                display: flex;
                flex: 1;
                max-width: 25px;
            }}
            
            .bar:hover {{
                background: linear-gradient(to top, #66BB6A 0%, #A5D6A7 100%);
                transform: scaleY(1.05);
                box-shadow: 0 2px 8px rgba(76, 175, 80, 0.3);
            }}
            
            .bar-value {{
                position: absolute;
                top: -25px;
                left: 50%;
                transform: translateX(-50%);
                font-size: 0.7rem;
                font-weight: bold;
                color: white;
                text-shadow: 0 1px 2px rgba(0,0,0,0.5);
            }}
            
            .bar-label {{
                position: absolute;
                bottom: -25px;
                left: 50%;
                transform: translateX(-50%);
                font-size: 0.7rem;
                white-space: nowrap;
                color: rgba(255,255,255,0.8);
            }}
            
            .commands-list {{
                display: flex;
                flex-direction: column;
                gap: 10px;
            }}
            
            .command-item {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                background: rgba(255,255,255,0.1);
                padding: 12px 16px;
                border-radius: 8px;
                transition: background 0.3s ease;
            }}
            
            .command-item:hover {{
                background: rgba(255,255,255,0.2);
            }}
            
            .status-indicator {{
                display: inline-block;
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: #4CAF50;
                margin-left: 10px;
                animation: pulse 2s infinite;
            }}
            
            @keyframes pulse {{
                0% {{ opacity: 1; transform: scale(1); }}
                50% {{ opacity: 0.7; transform: scale(1.1); }}
                100% {{ opacity: 1; transform: scale(1); }}
            }}
            
            .refresh-btn {{
                position: fixed;
                bottom: 30px;
                right: 30px;
                background: rgba(255,255,255,0.2);
                border: none;
                border-radius: 50%;
                width: 60px;
                height: 60px;
                color: white;
                font-size: 1.5rem;
                cursor: pointer;
                backdrop-filter: blur(10px);
                transition: all 0.3s ease;
            }}
            
            .refresh-btn:hover {{
                background: rgba(255,255,255,0.3);
                transform: rotate(180deg);
            }}
            
            /* 🔥 ESTILO PARA GRÁFICO VAZIO */
            .empty-chart {{
                display: flex;
                align-items: center;
                justify-content: center;
                height: 180px;
                color: rgba(255,255,255,0.6);
                font-style: italic;
            }}
        </style>
        <script>
            // Auto-refresh a cada 30 segundos
            setInterval(() => {{
                location.reload();
            }}, 30000);
            
            function refreshNow() {{
                location.reload();
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 Dashboard Bot Amanda</h1>
                <div class="last-update">
                    Última atualização: {stats['last_update']} <span class="status-indicator"></span>
                </div>
            </div>
            
            <div class="grid">
                <div class="card">
                    <span class="card-icon">🟢</span>
                    <div class="card-title">Usuários Online</div>
                    <div class="card-value online">{stats['online_now']}</div>
                    <div class="card-subtitle">Ativos nos últimos 5 minutos</div>
                </div>
                
                <div class="card">
                    <span class="card-icon">📱</span>
                    <div class="card-title">Usuários Hoje</div>
                    <div class="card-value today">{stats['daily_users']}</div>
                    <div class="card-subtitle">Únicos nas últimas 24h</div>
                </div>
                
                <div class="card">
                    <span class="card-icon">📅</span>
                    <div class="card-title">Usuários Esta Semana</div>
                    <div class="card-value week">{stats['weekly_users']}</div>
                    <div class="card-subtitle">Únicos nos últimos 7 dias</div>
                </div>
                
                <div class="card">
                    <span class="card-icon">💬</span>
                    <div class="card-title">Interações Hoje</div>
                    <div class="card-value interactions">{stats['interactions_today']}</div>
                    <div class="card-subtitle">Total de mensagens</div>
                </div>
            </div>
            
            <div class="charts">
                <div class="chart-card">
                    <div class="chart-title">📊 Atividade por Hora (Hoje)</div>
                    {generate_hourly_chart(stats['hourly_stats'])}
                </div>
                
                <div class="chart-card">
                    <div class="chart-title">🎯 Comandos Mais Usados</div>
                    <div class="commands-list">
                        {generate_commands_list(stats['commands_count'])}
                    </div>
                </div>
            </div>
        </div>
        
        <button class="refresh-btn" onclick="refreshNow()" title="Atualizar agora">🔄</button>
    </body>
    </html>
    '''

def generate_hourly_chart(hourly_stats):
    """Gera gráfico de barras das horas - VERSÃO CORRIGIDA"""
    
    # Debug: Ver que dados estão chegando
    print(f"🔍 DEBUG hourly_stats: {hourly_stats}")
    
    # Se não houver dados, mostrar mensagem
    if not hourly_stats or sum(hourly_stats.values()) == 0:
        return '''
        <div style="display: flex; align-items: center; justify-content: center; height: 180px; color: rgba(255,255,255,0.6); font-style: italic;">
            📊 Nenhuma atividade registrada hoje
        </div>
        '''
    
    # Pegar o valor máximo para normalizar
    max_value = max(hourly_stats.values())
    
    html = '''
    <div style="display: flex; align-items: end; height: 180px; gap: 4px; margin-top: 30px; padding: 0 10px; position: relative;">
    '''
    
    for hour in range(24):
        value = hourly_stats.get(hour, 0)
        
        # Calcular altura (mínimo 5% se tiver valor)
        if value > 0:
            height = max(8, (value / max_value * 100))
        else:
            height = 3  # Altura mínima para mostrar a barra vazia
        
        # Cor diferente se houver atividade
        if value > 0:
            background = "linear-gradient(to top, #4CAF50 0%, #81C784 100%)"
            bar_value = f'<div style="position: absolute; top: -25px; left: 50%; transform: translateX(-50%); font-size: 0.7rem; font-weight: bold; color: white; text-shadow: 0 1px 2px rgba(0,0,0,0.5);">{value}</div>'
        else:
            background = "linear-gradient(to top, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.2) 100%)"
            bar_value = ""
        
        html += f'''
        <div style="
            background: {background};
            border-radius: 3px 3px 0 0;
            height: {height}%;
            position: relative;
            transition: all 0.3s ease;
            flex: 1;
            max-width: 25px;
            min-width: 15px;
        " title="{value} interações às {hour}h">
            {bar_value}
            <div style="
                position: absolute; 
                bottom: -25px; 
                left: 50%; 
                transform: translateX(-50%); 
                font-size: 0.7rem; 
                white-space: nowrap; 
                color: rgba(255,255,255,0.8);
            ">{hour}h</div>
        </div>
        '''
    
    html += '</div>'
    return html

def generate_commands_list(commands_count):
    """Gera lista de comandos mais usados"""
    if not commands_count:
        return '<div class="command-item">Nenhuma atividade registrada</div>'
    
    # Ordenar por quantidade (top 5)
    sorted_commands = sorted(commands_count.items(), key=lambda x: x[1], reverse=True)[:5]
    
    html = ""
    for command, count in sorted_commands:
        html += f'''
        <div class="command-item">
            <span>📍 {command}</span>
            <span><strong>{count}</strong></span>
        </div>
        '''
    
    return html

@webhook_app.route('/api/dashboard-data')
def dashboard_data():
    """API endpoint para dados do dashboard (JSON)"""
    cleanup_online_users()
    
    return jsonify({
        'online_now': len(user_stats['online_now']),
        'daily_users': len(user_stats['daily_users']),
        'weekly_users': len(user_stats['weekly_users']),
        'interactions_today': user_stats['interactions_today'],
        'interactions_week': user_stats['interactions_week'],
        'hourly_stats': dict(user_stats['hourly_stats']),
        'commands_count': dict(user_stats['commands_count']),
        'timestamp': datetime.now().isoformat()
    })

@webhook_app.route('/', methods=['GET'])
def home():
    redis_status = "✅ Redis conectado" if redis_manager.redis else "⚠️ Redis fallback (memória)"
    
    return f'''
    <h1>🤖 Bot + Webhook + Redis - Online</h1>
    <p>Sistema com Rate Limiting e Redis</p>
    <ul>
        <li><a href="/api/health">Health Check</a></li>
        <li><a href="/api/stats">Estatísticas Completas</a></li>
        <li><a href="/dashboard">📊 Dashboard Completo</a></li>
    </ul>
    <h3>🔥 Status:</h3>
    <ul>
        <li>{redis_status}</li>
        <li>✅ Rate limiting ativo</li>
        <li>✅ Follow-up automático</li>
        <li>✅ Logs detalhados</li>
        <li>✅ Dashboard em tempo real</li>
    </ul>
    '''

def run_webhook_server():
    """Roda o servidor Flask em thread separada"""
    port = int(os.getenv("PORT", 5000))
    webhook_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def main():
    if not BOT_TOKEN or BOT_TOKEN == "SEU_TOKEN_AQUI":
        print("❌ ERRO: Configure o BOT_TOKEN no arquivo config.py!")
        return
    
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Iniciar servidor webhook em thread separada
    print("🚀 Iniciando servidor webhook na porta 5000...")
    webhook_thread = threading.Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()
    
    # Dar tempo para o servidor iniciar
    time.sleep(2)
    
    # Iniciar bot do Telegram
    application = Application.builder().token(BOT_TOKEN).build()
    
    setup_basic_handlers(application)
    setup_payment_handlers(application)
    
    print("🤖 Bot rodando... Ctrl+C para parar")
    print("🔥 REDIS + RATE LIMITING ATIVO")
    print("📡 Webhook API: http://localhost:5000")
    print("📊 Dashboard: http://localhost:5000/dashboard")
    print("📈 Estatísticas: http://localhost:5000/api/stats")
    print("🧪 Teste follow-up: POST /api/test-followup/USER_ID")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n🛑 Sistema finalizado")
    except Exception as e:
        logger.error(f"Erro: {e}")

if __name__ == '__main__':
    main()
