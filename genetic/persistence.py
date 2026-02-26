"""Persistence layer for saving/loading generation state and crash recovery."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from genetic.config import POPULATION_SIZE, STATE_DIR
from genetic.genome import Genome

logger = logging.getLogger("evolution")


def ensure_state_dir():
    """Create state directory if it doesn't exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def save_generation_state(
    generation: int,
    genomes: list[Genome],
    fitness_scores: list[float],
    stats: dict,
):
    """Persist generation state for crash recovery and analysis."""
    ensure_state_dir()

    state = {
        "generation": generation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "genomes": [g.to_dict() for g in genomes],
        "fitness_scores": fitness_scores,
        "stats": stats,
    }
    path = STATE_DIR / f"gen_{generation:04d}.json"
    with open(path, "w") as f:
        json.dump(state, f, indent=2, default=str)

    # Update latest pointer
    with open(STATE_DIR / "latest.json", "w") as f:
        json.dump({"generation": generation, "file": str(path)}, f)

    logger.info(f"Saved generation {generation} state to {path}")


def save_checkpoint(generation: int, bots, tick_count: int):
    """Save a mid-generation checkpoint for crash recovery."""
    ensure_state_dir()

    checkpoint = {
        "generation": generation,
        "tick": tick_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "accounts": {},
    }

    for bot in bots:
        acct = bot.account
        checkpoint["accounts"][bot.bot_id] = {
            "genome_id": bot.genome.id,
            "cash": acct.cash,
            "total_trades": acct.total_trades,
            "n_settled": acct.n_settled,
            "n_open": acct.n_open,
            "realized_pnl": acct.realized_pnl,
            "roi_pct": acct.roi_pct,
        }

    path = STATE_DIR / f"checkpoint_gen{generation:04d}.json"
    with open(path, "w") as f:
        json.dump(checkpoint, f, indent=2, default=str)


def load_latest_state() -> tuple[int, list[Genome]] | None:
    """
    Load the latest saved generation for crash recovery.
    Returns (generation_number, genomes) or None if no state found.
    """
    pointer_path = STATE_DIR / "latest.json"
    if not pointer_path.exists():
        return None

    try:
        with open(pointer_path) as f:
            pointer = json.load(f)

        gen_path = Path(pointer["file"])
        if not gen_path.exists():
            return None

        with open(gen_path) as f:
            state = json.load(f)

        genomes = [Genome.from_dict(d) for d in state["genomes"]]
        gen_num = state["generation"]
        logger.info(f"Loaded generation {gen_num} with {len(genomes)} genomes")
        return gen_num, genomes

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"Failed to load state: {e}")
        return None


def save_hall_of_fame(generation: int, top_entries: list[dict]):
    """
    Update the hall of fame with top performers from this generation.
    Keeps the best genome ever seen, plus the top 10 from the latest generation.
    """
    ensure_state_dir()
    hof_path = STATE_DIR / "hall_of_fame.json"

    # Load existing hall of fame
    existing: list[dict] = []
    if hof_path.exists():
        try:
            with open(hof_path) as f:
                data = json.load(f)
                existing = data.get("entries", [])
        except (json.JSONDecodeError, TypeError):
            existing = []

    # Merge: keep all previous entries + new ones, dedupe by genome id
    seen_ids: set[str] = set()
    merged: list[dict] = []

    # Add new entries first (they have latest performance data)
    for entry in top_entries:
        gid = entry["genome"]["id"]
        if gid not in seen_ids:
            seen_ids.add(gid)
            merged.append(entry)

    # Add previous entries that aren't duplicates
    for entry in existing:
        gid = entry.get("genome", {}).get("id", "")
        if gid and gid not in seen_ids:
            seen_ids.add(gid)
            merged.append(entry)

    # Sort by fitness and keep top 20 all-time
    merged.sort(key=lambda x: x.get("fitness_roi_pct", -999), reverse=True)
    merged = merged[:20]

    hof = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "latest_generation": generation,
        "best_ever": merged[0] if merged else None,
        "entries": merged,
    }

    with open(hof_path, "w") as f:
        json.dump(hof, f, indent=2, default=str)

    if merged:
        best = merged[0]
        logger.info(
            f"Hall of Fame updated: best ever = {best['fitness_roi_pct']:.1f}% ROI "
            f"(gen {best['generation']}, {best['signal_type']})"
        )


def load_hall_of_fame() -> dict | None:
    """Load the hall of fame."""
    hof_path = STATE_DIR / "hall_of_fame.json"
    if not hof_path.exists():
        return None
    with open(hof_path) as f:
        return json.load(f)


def load_generation(generation: int) -> dict | None:
    """Load a specific generation's full state."""
    path = STATE_DIR / f"gen_{generation:04d}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)
