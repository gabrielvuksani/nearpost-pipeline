"""Dixon-Coles (1997) with exponential time decay, on numpy and scipy only.

Goals are Poisson with home rate exp(attack_h + defence_a + home) and away rate
exp(attack_a + defence_h), plus the Dixon-Coles low-score correction rho. Parameters are
the weighted maximum-likelihood estimate. penaltyblog serves as the test oracle
(tests/test_dixon_coles_oracle.py) but is not a runtime dependency, which keeps its ~80
transitive packages out of the process that holds production secrets.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson

from nearpost.domain import MatchResult
from nearpost.forecast import Forecast
from nearpost.models.errors import ModelInputError

MODEL_ID = "dixon-coles-v1"
DEFAULT_XI = 0.0018  # per-day decay: a match a year old counts about half
MAX_GOALS = 15
_TAU_FLOOR = 1e-10


def time_weights(dates: Sequence[date], xi: float, base_date: date) -> np.ndarray:
    return np.exp(-xi * np.array([(base_date - d).days for d in dates], dtype=float))


def _tau(home_goals, away_goals, lam, mu, rho):
    """Dixon-Coles correction for the 0-0, 1-0, 0-1 and 1-1 scorelines."""
    tau = np.ones_like(lam)
    tau = np.where((home_goals == 0) & (away_goals == 0), 1 - lam * mu * rho, tau)
    tau = np.where((home_goals == 0) & (away_goals == 1), 1 + lam * rho, tau)
    tau = np.where((home_goals == 1) & (away_goals == 0), 1 + mu * rho, tau)
    return np.where((home_goals == 1) & (away_goals == 1), 1 - rho, tau)


def likelihood(history: Sequence[MatchResult], *, as_of: date, xi: float):
    """Weighted negative log-likelihood and its analytic gradient over free parameters.

    Free parameters: attack for all but the last team (whose attack is minus the sum, pinning
    the mean at zero, since attack is only identified up to a shift against defence), every
    team's defence, home advantage, rho. Returns (nll, gradient, size, team_index, unpack).
    """
    names = sorted({r.home for r in history} | {r.away for r in history})
    index = {name: i for i, name in enumerate(names)}
    n = len(names)
    hi = np.array([index[r.home] for r in history])
    ai = np.array([index[r.away] for r in history])
    hg = np.array([r.home_goals for r in history], dtype=float)
    ag = np.array([r.away_goals for r in history], dtype=float)
    w = time_weights([r.played_on for r in history], xi, as_of)
    constant = gammaln(hg + 1) + gammaln(ag + 1)
    s00, s01 = (hg == 0) & (ag == 0), (hg == 0) & (ag == 1)
    s10, s11 = (hg == 1) & (ag == 0), (hg == 1) & (ag == 1)

    def unpack(free: np.ndarray):
        attack = np.append(free[: n - 1], -free[: n - 1].sum())
        return attack, free[n - 1 : 2 * n - 1], free[-2], free[-1]

    def rates(free: np.ndarray):
        attack, defence, home, rho = unpack(free)
        lam = np.exp(attack[hi] + defence[ai] + home)
        mu = np.exp(attack[ai] + defence[hi])
        return lam, mu, rho, _tau(hg, ag, lam, mu, rho)

    def nll(free: np.ndarray) -> float:
        lam, mu, _, tau = rates(free)
        log_lik = np.log(np.maximum(tau, _TAU_FLOOR)) + hg * np.log(lam) - lam + ag * np.log(mu) - mu - constant
        return -float(np.dot(w, log_lik))

    def gradient(free: np.ndarray) -> np.ndarray:
        lam, mu, rho, tau = rates(free)
        live = tau > _TAU_FLOOR  # where tau is floored, it no longer depends on the parameters
        safe = np.where(live, tau, 1.0)
        dtau_dlam = np.where(s00, -mu * rho, 0.0) + np.where(s01, rho, 0.0)
        dtau_dmu = np.where(s00, -lam * rho, 0.0) + np.where(s10, rho, 0.0)
        dtau_drho = np.where(s00, -lam * mu, 0.0) + np.where(s01, lam, 0.0) + np.where(s10, mu, 0.0)
        dtau_drho = dtau_drho - np.where(s11, 1.0, 0.0)
        g_lam = w * (hg - lam + np.where(live, lam * dtau_dlam / safe, 0.0))  # d logL / d log(lam)
        g_mu = w * (ag - mu + np.where(live, mu * dtau_dmu / safe, 0.0))
        g_attack = np.bincount(hi, g_lam, n) + np.bincount(ai, g_mu, n)
        g_defence = np.bincount(ai, g_lam, n) + np.bincount(hi, g_mu, n)
        g_rho = float(np.sum(w * np.where(live, dtau_drho / safe, 0.0)))
        grad = np.concatenate([g_attack[:-1] - g_attack[-1], g_defence, [g_lam.sum(), g_rho]])
        return -grad

    return nll, gradient, 2 * n + 1, index, unpack


@dataclass(frozen=True)
class DixonColesModel:
    team_index: dict[str, int]
    attack: tuple[float, ...]
    defence: tuple[float, ...]
    home_advantage: float
    rho: float
    xi: float
    n_matches: int

    @property
    def teams(self) -> frozenset[str]:
        return frozenset(self.team_index)

    @classmethod
    def fit(cls, history: Sequence[MatchResult], *, as_of: date, xi: float = DEFAULT_XI) -> DixonColesModel:
        # Same-day rows are allowed: football-data rows are only used from earlier days, so a
        # same-day row is an FPL result that training_set confirmed finished before the forecast.
        late = [r for r in history if r.played_on > as_of]
        if late:
            raise ModelInputError(f"{len(late)} training results fall after {as_of}; that would leak")
        if not history:
            raise ModelInputError("dixon-coles needs at least one training result")

        nll, gradient, size, index, unpack = likelihood(history, as_of=as_of, xi=xi)
        n = len(index)
        start = np.concatenate([np.zeros(size - 2), [0.25, -0.1]])
        bounds = [(-3.0, 3.0)] * (2 * n - 1) + [(0.0, 2.0), (-1.0, 1.0)]
        options = {"maxiter": 5000, "ftol": 1e-13, "gtol": 1e-8}
        result = minimize(nll, start, jac=gradient, method="L-BFGS-B", bounds=bounds, options=options)
        if not result.success:
            raise ModelInputError(f"dixon-coles did not converge: {result.message}")
        attack, defence, home, rho = unpack(result.x)
        return cls(
            team_index=index,
            attack=tuple(float(a) for a in attack),
            defence=tuple(float(d) for d in defence),
            home_advantage=float(home),
            rho=float(rho),
            xi=xi,
            n_matches=len(history),
        )

    def score_grid(self, home: str, away: str) -> np.ndarray:
        """P(home goals = i, away goals = j) for i, j in 0..MAX_GOALS, normalised."""
        for team in (home, away):
            if team not in self.team_index:
                raise ModelInputError(f"dixon-coles has no history for {team!r}")
        h, a = self.team_index[home], self.team_index[away]
        lam = np.exp(self.attack[h] + self.defence[a] + self.home_advantage)
        mu = np.exp(self.attack[a] + self.defence[h])
        goals = np.arange(MAX_GOALS + 1)
        grid = np.outer(poisson.pmf(goals, lam), poisson.pmf(goals, mu))
        i, j = np.meshgrid(goals, goals, indexing="ij")
        grid = grid * _tau(i, j, np.full(grid.shape, lam), np.full(grid.shape, mu), self.rho)
        if (grid < 0).any():
            raise ModelInputError(f"dixon-coles produced negative scoreline probabilities for {home} v {away}")
        return grid / grid.sum()

    def predict(self, home: str, away: str) -> Forecast:
        grid = self.score_grid(home, away)
        i, j = np.indices(grid.shape)
        return Forecast(
            probs=(float(grid[i > j].sum()), float(grid[i == j].sum()), float(grid[i < j].sum())),
            over_2_5=float(grid[i + j > 2].sum()),
            btts=float(grid[(i > 0) & (j > 0)].sum()),
        )
