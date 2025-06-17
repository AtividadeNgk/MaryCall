import redis
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class RedisManager:
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        try:
            self.redis = redis.from_url(redis_url, decode_responses=True)
            # Testar conexão
            self.redis.ping()
            logger.info("✅ Redis conectado com sucesso!")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar Redis: {e}")
            # Fallback para dicionário em memória (desenvolvimento)
            self.redis = None
            self._memory_cache = {}
            logger.warning("⚠️ Usando cache em memória (fallback)")
    
    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
        """
        Verifica rate limiting
        Retorna True se permitido, False se excedeu limite
        """
        try:
            if self.redis is None:
                # Fallback para memória
                return self._check_rate_limit_memory(key, limit, window_seconds)
            
            current_time = int(time.time())
            pipe = self.redis.pipeline()
            
            # Usar sliding window com Redis
            pipe.zremrangebyscore(key, 0, current_time - window_seconds)
            pipe.zcard(key)
            pipe.zadd(key, {str(current_time): current_time})
            pipe.expire(key, window_seconds)
            
            results = pipe.execute()
            current_count = results[1]
            
            if current_count >= limit:
                logger.warning(f"🚫 Rate limit excedido: {key} ({current_count}/{limit})")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro no rate limiting: {e}")
            return True  # Em caso de erro, permitir (fail-safe)
    
    def _check_rate_limit_memory(self, key: str, limit: int, window_seconds: int) -> bool:
        """Fallback rate limiting em memória"""
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
        """Salvar estado do usuário no Redis"""
        try:
            if self.redis is None:
                self._memory_cache[f"state:{user_id}"] = state
                return
            
            self.redis.setex(f"state:{user_id}", ttl, state)
            logger.info(f"📝 Estado salvo: {user_id} → {state}")
        except Exception as e:
            logger.error(f"❌ Erro ao salvar estado: {e}")
    
    def get_user_state(self, user_id: int) -> str:
        """Recuperar estado do usuário do Redis"""
        try:
            if self.redis is None:
                return self._memory_cache.get(f"state:{user_id}", "normal")
            
            state = self.redis.get(f"state:{user_id}")
            return state if state else "normal"
        except Exception as e:
            logger.error(f"❌ Erro ao recuperar estado: {e}")
            return "normal"
    
    def cleanup_old_data(self):
        """Limpeza automática de dados antigos"""
        try:
            if self.redis is None:
                # Limpar cache em memória
                current_time = time.time()
                keys_to_remove = []
                for key, value in self._memory_cache.items():
                    if isinstance(value, list):
                        # Rate limiting data
                        self._memory_cache[key] = [
                            t for t in value if current_time - t < 3600
                        ]
                        if not self._memory_cache[key]:
                            keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    del self._memory_cache[key]
                return
            
            # Limpar dados antigos do Redis
            current_time = int(time.time())
            one_hour_ago = current_time - 3600
            
            # Buscar todas as chaves de rate limiting
            rate_limit_keys = self.redis.keys("rate:*")
            for key in rate_limit_keys:
                self.redis.zremrangebyscore(key, 0, one_hour_ago)
                # Remover chave se vazia
                if self.redis.zcard(key) == 0:
                    self.redis.delete(key)
            
            logger.info(f"🧹 Limpeza automática: {len(rate_limit_keys)} chaves processadas")
            
        except Exception as e:
            logger.error(f"❌ Erro na limpeza: {e}")

# Instância global
redis_manager = RedisManager()