import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class RedisManager:
    def __init__(self, redis_url: str = None):
        # 🔥 SEM REDIS - SÓ MEMÓRIA
        self.redis = None
        self._memory_cache = {}
        self._user_states = {}
        logger.info("⚠️ Usando APENAS cache em memória (sem Redis)")
    
    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Rate limiting em memória"""
        current_time = time.time()
        
        if key not in self._memory_cache:
            self._memory_cache[key] = []
        
        # Remover entradas antigas
        self._memory_cache[key] = [
            t for t in self._memory_cache[key] 
            if current_time - t < window_seconds
        ]
        
        if len(self._memory_cache[key]) >= limit:
            return False
        
        self._memory_cache[key].append(current_time)
        return True
    
    def set_user_state(self, user_id: int, state: str, ttl: int = 3600):
        """Salvar estado em memória"""
        self._user_states[user_id] = {
            'state': state,
            'timestamp': time.time()
        }
        logger.info(f"📝 Estado salvo (memória): {user_id} → {state}")
    
    def get_user_state(self, user_id: int) -> str:
        """Recuperar estado da memória"""
        if user_id in self._user_states:
            user_data = self._user_states[user_id]
            # Verificar se expirou (1 hora)
            if time.time() - user_data['timestamp'] < 3600:
                return user_data['state']
            else:
                # Expirado
                del self._user_states[user_id]
        
        return "normal"
    
    def cleanup_old_data(self):
        """Limpeza de dados antigos"""
        current_time = time.time()
        
        # Limpar rate limiting
        keys_to_remove = []
        for key, timestamps in self._memory_cache.items():
            self._memory_cache[key] = [
                t for t in timestamps if current_time - t < 3600
            ]
            if not self._memory_cache[key]:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._memory_cache[key]
        
        # Limpar estados expirados
        expired_users = [
            user_id for user_id, data in self._user_states.items()
            if current_time - data['timestamp'] > 3600
        ]
        
        for user_id in expired_users:
            del self._user_states[user_id]

# Instância global
redis_manager = RedisManager()
