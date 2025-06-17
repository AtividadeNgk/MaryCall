# 🆕 CRIAR ARQUIVO: tracking.py

import logging
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)

# 📊 SISTEMA DE TRACKING SIMPLES
user_stats = {
    'online_now': set(),           # Usuários ativos últimos 5 minutos
    'daily_users': set(),          # Usuários únicos hoje
    'weekly_users': set(),         # Usuários únicos esta semana  
    'interactions_today': 0,       # Total interações hoje
    'interactions_week': 0,        # Total interações esta semana
    'last_reset_day': datetime.now().date(),
    'last_reset_week': datetime.now().isocalendar()[1],
    'user_activity': {},           # {user_id: last_activity_timestamp}
    'hourly_stats': defaultdict(int), # Estatísticas por hora
    'commands_count': defaultdict(int), # Contador de comandos
}

def track_user_activity(user_id, action="message"):
    """Registra atividade do usuário"""
    now = datetime.now()
    current_date = now.date()
    current_week = now.isocalendar()[1]
    current_hour = now.hour
    
    # Reset diário
    if user_stats['last_reset_day'] != current_date:
        user_stats['daily_users'].clear()
        user_stats['interactions_today'] = 0
        user_stats['last_reset_day'] = current_date
        user_stats['hourly_stats'].clear()
        logger.info("📅 Reset estatísticas diárias")
    
    # Reset semanal  
    if user_stats['last_reset_week'] != current_week:
        user_stats['weekly_users'].clear()
        user_stats['interactions_week'] = 0
        user_stats['last_reset_week'] = current_week
        logger.info("📅 Reset estatísticas semanais")
    
    # Registrar atividade
    user_stats['user_activity'][user_id] = now.timestamp()
    user_stats['online_now'].add(user_id)
    user_stats['daily_users'].add(user_id)
    user_stats['weekly_users'].add(user_id)
    user_stats['interactions_today'] += 1
    user_stats['interactions_week'] += 1
    user_stats['hourly_stats'][current_hour] += 1
    user_stats['commands_count'][action] += 1

def cleanup_online_users():
    """Remove usuários inativos (5+ minutos)"""
    now = datetime.now().timestamp()
    cutoff = now - 300  # 5 minutos
    
    inactive_users = [
        user_id for user_id, last_activity in user_stats['user_activity'].items()
        if last_activity < cutoff
    ]
    
    for user_id in inactive_users:
        user_stats['online_now'].discard(user_id)
        del user_stats['user_activity'][user_id]