"""Prepare an independent, verified starting state for simulation experiments."""

from collections import deque
from dataclasses import dataclass
from typing import Callable

from engine import Controls, Twin


QUALITY_TOLERANCE = 0.005
INVENTORY_TOLERANCE_M3 = 1.0
STABILITY_WINDOW_S = 3600
VERIFICATION_S = 24 * 3600
MAX_WARMUP_HOURS = 90 * 24
SOLIDS_LOAD_TOLERANCE = 0.01


class WarmupNotConverged(RuntimeError):
    """No alarm-free starting state passed the verification window."""


@dataclass(frozen=True)
class WarmupSample:
    time_s: float
    nh4_mg_l: float | None
    cod_mg_l: float | None
    inventory_m3: float
    rejected_m3: float
    alarms: tuple[str, ...]
    permeate_tss_mg_l: float | None = None
    membrane_tss_mg_l: tuple[float, ...] = ()
    in_process_tss_kg: float = 0.
    admitted_tss_kg: float = 0.


@dataclass(frozen=True)
class WarmStart:
    candidate: WarmupSample
    verified: WarmupSample
    samples: tuple[WarmupSample, ...]
    _volume: dict[str, float]
    _mass: dict[str, dict[str, float]]
    _part: dict[str, dict[str, float]]

    def new_twin(self, twin_type: type[Twin] = Twin) -> Twin:
        """Copy physical state while starting a new experiment clock and totals."""
        twin = twin_type()
        twin.volume = self._volume.copy()
        twin.mass = {key: mass.copy() for key, mass in self._mass.items()}
        twin.part = {key: mass.copy() for key, mass in self._part.items()}
        return twin


def _stable(samples, *, require_solids_stability=False):
    if any(s.alarms or s.nh4_mg_l is None or s.cod_mg_l is None for s in samples):
        return False
    first, last = samples[0], samples[-1]
    if abs(last.inventory_m3 - first.inventory_m3) >= INVENTORY_TOLERANCE_M3:
        return False
    if last.rejected_m3 != first.rejected_m3:
        return False
    series = [[s.nh4_mg_l for s in samples], [s.cod_mg_l for s in samples]]
    if require_solids_stability:
        if any(s.permeate_tss_mg_l is None or len(s.membrane_tss_mg_l) != 4 for s in samples):
            return False
        series.append([s.permeate_tss_mg_l for s in samples])
        series.extend([s.membrane_tss_mg_l[i] for s in samples] for i in range(4))
    for values in series:
        spread = max(values) - min(values)
        if spread and spread >= QUALITY_TOLERANCE * values[0]:
            return False
    return True


def _solids_inventory_closed(first: WarmupSample, last: WarmupSample) -> bool:
    admitted = last.admitted_tss_kg - first.admitted_tss_kg
    change = abs(last.in_process_tss_kg - first.in_process_tss_kg)
    if admitted == 0.:
        return change < 1e-9
    return change < SOLIDS_LOAD_TOLERANCE * admitted


def prepare_initial_state(
    controls: Controls, *, max_hours: int = MAX_WARMUP_HOURS, require_solids_stability: bool = True,
    twin_factory: Callable[[], Twin] | None = None,
) -> WarmStart:
    """Warm up and verify 24 h of stability, or raise if the deadline is reached."""
    dt = controls.dt_s
    if not 0 < dt <= STABILITY_WINDOW_S or STABILITY_WINDOW_S % dt:
        raise ValueError('Warm-up step must divide 3600 seconds')
    if max_hours <= 24:
        raise ValueError('Warm-up deadline must allow a full 24-hour verification')

    twin = Twin() if twin_factory is None else twin_factory()
    samples = []
    window = deque(maxlen=int(STABILITY_WINDOW_S / dt) + 1)
    candidate = None
    admitted_tss_kg = 0.
    for _ in range(int(max_hours * 3600 / dt)):
        snapshot = twin.step(controls)
        admitted_tss_kg += twin._flows['inlet'] * controls.inlet_tss * .001
        sample = WarmupSample(
            time_s=twin.elapsed,
            nh4_mg_l=snapshot['effluent_quality']['nh4'],
            cod_mg_l=snapshot['effluent_quality']['cod'],
            inventory_m3=sum(twin.volume.values()),
            rejected_m3=twin.rejected,
            alarms=tuple(snapshot['alerts']),
            permeate_tss_mg_l=snapshot['permeate_tss_mg_l'],
            membrane_tss_mg_l=tuple(twin.concentration(f'mbr{i}', 'tss') for i in range(1, 5)),
            in_process_tss_kg=sum(mass['tss'] for key, mass in twin.mass.items() if key != 'outlet'),
            admitted_tss_kg=admitted_tss_kg,
        )
        samples.append(sample)
        window.append(sample)
        stable_window = len(window) == window.maxlen and _stable(window, require_solids_stability=require_solids_stability)
        if candidate is not None:
            if not stable_window or not _stable((candidate, sample), require_solids_stability=require_solids_stability):
                candidate = None
            elif sample.time_s - candidate.time_s >= VERIFICATION_S:
                if not require_solids_stability or _solids_inventory_closed(candidate, sample):
                    return WarmStart(candidate, sample, tuple(samples), twin.volume.copy(),
                                     {key: mass.copy() for key, mass in twin.mass.items()},
                                     {key: mass.copy() for key, mass in twin.part.items()})
                candidate = None
        if candidate is None and stable_window:
            candidate = sample
    raise WarmupNotConverged(f'No verified warm-start state within {max_hours} simulated hours')
