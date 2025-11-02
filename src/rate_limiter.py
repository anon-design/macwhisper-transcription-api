#!/usr/bin/env python3
"""
Rate limiting por IP
"""
import time
from collections import defaultdict
from typing import Dict, Tuple
from src import config


class RateLimiter:
    """Rate limiter simple basado en sliding window"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Estructura: {ip: [timestamp1, timestamp2, ...]}
        self.requests: Dict[str, list] = defaultdict(list)

        # Límites configurables
        self.limit_per_minute = config.RATE_LIMIT_PER_MINUTE
        self.window_seconds = 60

        self._initialized = True

        print(f"🚦 Rate Limiter inicializado: {self.limit_per_minute} req/min por IP")

    def _cleanup_old_requests(self, ip: str) -> None:
        """Elimina requests fuera de la ventana de tiempo"""
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        # Filtrar solo requests dentro de la ventana
        self.requests[ip] = [
            ts for ts in self.requests[ip]
            if ts > cutoff_time
        ]

    def is_allowed(self, ip: str) -> Tuple[bool, int]:
        """
        Verifica si una IP puede hacer una request

        Returns:
            Tuple[bool, int]: (permitido, requests_restantes)
        """
        current_time = time.time()

        # Limpiar requests antiguos
        self._cleanup_old_requests(ip)

        # Contar requests en ventana actual
        request_count = len(self.requests[ip])

        # Verificar límite
        if request_count >= self.limit_per_minute:
            remaining = 0
            return False, remaining

        # Registrar request actual
        self.requests[ip].append(current_time)

        remaining = self.limit_per_minute - (request_count + 1)
        return True, remaining

    def get_retry_after(self, ip: str) -> float:
        """
        Obtiene el tiempo en segundos hasta que se puede reintentar

        Returns:
            float: Segundos hasta que expire el request más antiguo
        """
        if not self.requests[ip]:
            return 0.0

        oldest_request = min(self.requests[ip])
        current_time = time.time()

        retry_after = oldest_request + self.window_seconds - current_time

        return max(0.0, retry_after)

    def get_stats(self, ip: str) -> Dict:
        """Obtiene estadísticas de rate limiting para una IP"""
        self._cleanup_old_requests(ip)

        request_count = len(self.requests[ip])
        remaining = max(0, self.limit_per_minute - request_count)

        return {
            "limit": self.limit_per_minute,
            "remaining": remaining,
            "used": request_count,
            "window_seconds": self.window_seconds
        }

    def reset(self, ip: str) -> None:
        """Resetea el contador para una IP (para testing)"""
        if ip in self.requests:
            del self.requests[ip]

    def cleanup_all(self) -> None:
        """Limpia todas las IPs (ejecutar periódicamente)"""
        ips_to_cleanup = list(self.requests.keys())

        for ip in ips_to_cleanup:
            self._cleanup_old_requests(ip)

            # Eliminar IP si no tiene requests activos
            if not self.requests[ip]:
                del self.requests[ip]
