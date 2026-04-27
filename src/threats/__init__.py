"""Adversarial-threat models: enemy drones with simple kinematics."""

from .enemy import EnemyDrone, ThreatManager, ThreatReport
from .interceptor import (
    Interceptor,
    InterceptorBattery,
    InterceptorManager,
    STATUS_INACTIVE,
    STATUS_BOOST,
    STATUS_COAST,
    STATUS_HIT,
    STATUS_MISS,
)

__all__ = [
    "EnemyDrone",
    "ThreatManager",
    "ThreatReport",
    "Interceptor",
    "InterceptorBattery",
    "InterceptorManager",
    "STATUS_INACTIVE",
    "STATUS_BOOST",
    "STATUS_COAST",
    "STATUS_HIT",
    "STATUS_MISS",
]
