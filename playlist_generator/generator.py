"""Geração automática de playlist aleatória sem repetir artista/álbum em sequência."""

from __future__ import annotations

import random
from typing import Optional, Sequence

from .scanner import Track


def generate_playlist(
    tracks: Sequence[Track],
    count: int = 0,
    rng: Optional[random.Random] = None,
) -> list[Track]:
    """Gera uma playlist aleatória.

    - `count` <= 0 (ou maior que o total) usa todas as faixas.
    - Primeiro sorteia quais faixas entram; depois as ordena evitando o mesmo
      artista duas vezes seguidas. Isso é garantido sempre que matematicamente
      possível (nenhum artista com mais da metade das faixas, arredondada p/ cima).
    - Quando possível, também evita o mesmo álbum em sequência (preferência).
    - Faixas sem artista nas tags não sofrem restrição de artista.
    - Se a restrição for impossível (ex.: só existe um artista), repete mesmo assim.
    """
    rng = rng or random.Random()
    pool = list(tracks)
    if not pool:
        return []

    target = len(pool) if count <= 0 else min(count, len(pool))
    chosen = rng.sample(pool, target)
    return _arrange(chosen, rng)


def _arrange(tracks: list[Track], rng: random.Random) -> list[Track]:
    # Agrupa por artista. Faixas sem artista ficam cada uma no seu próprio grupo.
    buckets: dict[str, list[Track]] = {}
    for index, track in enumerate(tracks):
        key = track.artist_key or f"\0unknown-{index}"
        buckets.setdefault(key, []).append(track)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    result: list[Track] = []
    last_key: Optional[str] = None
    last_album = ""
    remaining = len(tracks)

    while remaining:
        # Um artista com mais da metade do que resta (arredondada p/ cima) precisa
        # ser colocado agora, senão não haverá como separá-lo depois.
        urgent = [k for k, b in buckets.items() if k != last_key and len(b) * 2 > remaining]
        candidates = urgent or [k for k in buckets if k != last_key]
        if not candidates:  # só sobrou o artista anterior: repetição inevitável
            candidates = list(buckets)

        # Preferência: sorteio ponderado pelo nº de faixas restantes
        # (método de Efraimidis-Spirakis).
        ordered = sorted(
            candidates,
            key=lambda k: rng.random() ** (1.0 / len(buckets[k])),
            reverse=True,
        )

        chosen_key = ordered[0]
        chosen_index = 0
        for key in ordered:
            index = _pick_different_album(buckets[key], last_album)
            if index is not None:
                chosen_key, chosen_index = key, index
                break

        track = buckets[chosen_key].pop(chosen_index)
        if not buckets[chosen_key]:
            del buckets[chosen_key]
        result.append(track)
        last_key = chosen_key
        last_album = track.album_key
        remaining -= 1
    return result


def _pick_different_album(bucket: list[Track], last_album: str) -> Optional[int]:
    """Índice da primeira faixa cujo álbum difere do anterior (ou None)."""
    if not last_album:
        return 0
    for index, track in enumerate(bucket):
        if track.album_key != last_album:
            return index
    return None
