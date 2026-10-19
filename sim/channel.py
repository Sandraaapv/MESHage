"""
wireless channel model with log-distance path loss and shadowing
"""
import math
import random
from typing import Optional


class WirelessChannel:
    def __init__(
        self,
        tx_power_dbm: float = 14.0,
        d0: float = 1.0,
        pl_d0: float = 40.0,
        n: float = 3.0,
        sigma: float = 4.0,
        sensitivity_dbm: float = -85.0,
    ):
        self.tx_power_dbm = tx_power_dbm
        self.d0 = d0
        self.pl_d0 = pl_d0
        self.n = n
        self.sigma = sigma
        self.sensitivity_dbm = sensitivity_dbm

    def path_loss(
        self,
        distance: float,
        shadowing: bool = True,
        rng: Optional[random.Random] = None,
    ) -> float:
        # clamp distance to reference distance
        d = max(distance, self.d0)
        # log-distance path loss
        pl = self.pl_d0 + 10.0 * self.n * math.log10(d / self.d0)
        if shadowing and self.sigma > 0:
            # gaussian shadowing with mean 0 and std sigma
            x = rng.gauss(0.0, self.sigma) if rng else random.gauss(0.0, self.sigma)
            pl += x
        return pl

    def received_power(
        self,
        distance: float,
        shadowing: bool = True,
        rng: Optional[random.Random] = None,
    ) -> float:
        # received power in dBm = tx power - path loss
        return self.tx_power_dbm - self.path_loss(distance, shadowing=shadowing, rng=rng)

    def success_probability(self, prx_dbm: float) -> float:
        # logistic function centered at receiver sensitivity
        diff = prx_dbm - self.sensitivity_dbm
        if diff > 20.0:
            return 1.0
        if diff < -20.0:
            return 0.0
        return 1.0 / (1.0 + math.exp(-0.5 * diff))

    def packet_success_from_distance(
        self,
        distance: float,
        shadowing: bool = False,
        rng: Optional[random.Random] = None,
    ) -> float:
        prx = self.received_power(distance, shadowing=shadowing, rng=rng)
        return self.success_probability(prx)

    def transmits_successfully(
        self,
        distance: float,
        rng: Optional[random.Random] = None,
    ) -> bool:
        # calculate instantaneous received power with shadowing
        prx = self.received_power(distance, shadowing=True, rng=rng)
        prob = self.success_probability(prx)
        roll = rng.random() if rng else random.random()
        return roll < prob
